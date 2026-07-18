import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.audit import ContextAudit
from core.models import AuditLog
from firme.models import Firma

from .models import Invitatie, Utilizator, UtilizatorFirma

ROLURI_INTERNE = {"admin_cabinet", "contabil_coordonator", "contabil"}
ROLURI_CLIENT = {
    "client_admin": "reprezentant_client",
    "client_operator": "operator_upload",
}


class EroareInvitatie(Exception):
    pass


@dataclass(frozen=True)
class InvitatieCreata:
    id: object
    token: str


@dataclass(frozen=True)
class InvitatiePublica:
    id: object
    email: str
    rol: str
    rol_afisat: str
    destinatie: str
    cont_existent: bool


@dataclass(frozen=True)
class RezultatAcceptare:
    utilizator_id: object
    cont_creat: bool


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def poate_gestiona_invitatii(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated
        and utilizator.is_active
        and utilizator.rol in {"admin_cabinet", "client_admin"}
    )


def roluri_permise_pentru(utilizator) -> set[str]:
    if utilizator.rol == "admin_cabinet" and utilizator.cabinet_id:
        return ROLURI_INTERNE | set(ROLURI_CLIENT)
    if utilizator.rol == "client_admin":
        return {"client_operator"}
    return set()


def _client_admin_alocat(utilizator, firma: Firma) -> bool:
    return UtilizatorFirma.objects.filter(
        utilizator_id=utilizator.pk,
        firma_id=firma.pk,
        rol_in_firma="reprezentant_client",
    ).exists()


def _valideaza_tinta(*, utilizator, rol: str, firma: Firma | None) -> tuple[object, ...]:
    if rol not in roluri_permise_pentru(utilizator):
        raise PermissionDenied("Rolul nu poate fi invitat de acest utilizator.")

    if rol in ROLURI_INTERNE:
        if firma is not None or utilizator.rol != "admin_cabinet":
            raise EroareInvitatie("Invitațiile interne nu se leagă de o firmă clientă.")
        return utilizator.cabinet_id, None, None

    if firma is None:
        raise EroareInvitatie("Selectează firma clientă.")
    if utilizator.rol == "admin_cabinet":
        if firma.cabinet_id != utilizator.cabinet_id:
            raise PermissionDenied
    elif not _client_admin_alocat(utilizator, firma):
        raise PermissionDenied
    return None, firma.pk, ROLURI_CLIENT[rol]


def _scrie_audit_privilegiat(
    *,
    utilizator_id,
    invitatie_id,
    firma_id,
    actiune: str,
    context: ContextAudit,
    date_noi: dict | None = None,
) -> None:
    AuditLog.objects.using("privileged").create(
        firma_id=firma_id,
        utilizator_id=utilizator_id,
        entitate_tip="invitatie",
        entitate_id=invitatie_id,
        actiune=actiune,
        date_noi=date_noi,
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def creeaza_invitatie(
    *, utilizator, email: str, rol: str, firma: Firma | None, context: ContextAudit
) -> InvitatieCreata:
    if not poate_gestiona_invitatii(utilizator):
        raise PermissionDenied
    cabinet_id, firma_id, rol_in_firma = _valideaza_tinta(
        utilizator=utilizator, rol=rol, firma=firma
    )
    email = email.strip().lower()
    acum = timezone.now()

    with transaction.atomic(using="privileged"):
        existent = (
            Utilizator.objects.using("privileged")
            .filter(email__iexact=email)
            .values("id", "rol", "is_active")
            .first()
        )
        if existent and not existent["is_active"]:
            raise EroareInvitatie(
                "Contul existent este dezactivat și necesită intervenția platformei."
            )
        if existent and rol in ROLURI_INTERNE:
            raise EroareInvitatie("Există deja un cont cu această adresă de email.")
        if existent and existent["rol"] != rol:
            raise EroareInvitatie("Contul existent are un rol incompatibil cu invitația.")
        if (
            existent
            and firma_id
            and UtilizatorFirma.objects.using("privileged")
            .filter(utilizator_id=existent["id"], firma_id=firma_id)
            .exists()
        ):
            raise EroareInvitatie("Utilizatorul are deja acces la această firmă.")

        anterioare = Invitatie.objects.using("privileged").filter(
            email__iexact=email,
            cabinet_id=cabinet_id,
            firma_id=firma_id,
            rol=rol,
            acceptata_la__isnull=True,
            anulata_la__isnull=True,
        )
        invitatii_inlocuite = list(anterioare.values_list("id", "firma_id"))
        anterioare.update(anulata_la=acum)
        for invitatie_id, invitatie_firma_id in invitatii_inlocuite:
            _scrie_audit_privilegiat(
                utilizator_id=utilizator.pk,
                invitatie_id=invitatie_id,
                firma_id=invitatie_firma_id,
                actiune="invitatie_inlocuita",
                context=context,
            )

        token = secrets.token_urlsafe(32)
        invitatie = Invitatie.objects.using("privileged").create(
            cabinet_id=cabinet_id,
            firma_id=firma_id,
            email=email,
            rol=rol,
            rol_in_firma=rol_in_firma,
            token_hash=_hash_token(token),
            expira_la=acum + timedelta(days=7),
            creat_de_id=utilizator.pk,
        )
        _scrie_audit_privilegiat(
            utilizator_id=utilizator.pk,
            invitatie_id=invitatie.pk,
            firma_id=firma_id,
            actiune="invitatie_creata",
            context=context,
            date_noi={"email": email, "rol": rol, "firma_id": str(firma_id) if firma_id else None},
        )
    return InvitatieCreata(id=invitatie.pk, token=token)


def _invitatie_valida(token: str, *, blocare: bool = False) -> Invitatie:
    queryset = Invitatie.objects.using("privileged")
    if blocare:
        queryset = queryset.select_for_update()
    else:
        queryset = queryset.select_related("firma", "cabinet")
    invitatie = queryset.filter(token_hash=_hash_token(token)).first()
    if not invitatie:
        raise EroareInvitatie("Invitația nu există.")
    if invitatie.acceptata_la:
        raise EroareInvitatie("Invitația a fost deja acceptată.")
    if invitatie.anulata_la:
        raise EroareInvitatie("Invitația a fost anulată.")
    if invitatie.expira_la <= timezone.now():
        raise EroareInvitatie("Invitația a expirat.")
    return invitatie


def obtine_invitatie_publica(token: str) -> InvitatiePublica:
    invitatie = _invitatie_valida(token)
    cont_existent = (
        Utilizator.objects.using("privileged")
        .filter(email__iexact=invitatie.email, is_active=True)
        .exists()
    )
    destinatie = invitatie.firma.denumire if invitatie.firma_id else invitatie.cabinet.denumire
    return InvitatiePublica(
        id=invitatie.pk,
        email=invitatie.email,
        rol=invitatie.rol,
        rol_afisat=invitatie.get_rol_display(),
        destinatie=destinatie,
        cont_existent=cont_existent,
    )


def accepta_invitatie(
    *,
    token: str,
    utilizator_autentificat,
    nume: str | None,
    telefon: str | None,
    parola: str | None,
    context: ContextAudit,
) -> RezultatAcceptare:
    with transaction.atomic(using="privileged"):
        invitatie = _invitatie_valida(token, blocare=True)
        utilizator = (
            Utilizator.objects.using("privileged").filter(email__iexact=invitatie.email).first()
        )
        cont_creat = utilizator is None

        if utilizator:
            if not getattr(utilizator_autentificat, "is_authenticated", False):
                raise PermissionDenied("Autentificarea contului existent este obligatorie.")
            if utilizator_autentificat.pk != utilizator.pk:
                raise PermissionDenied("Invitația aparține altui cont.")
            if utilizator.rol != invitatie.rol:
                raise EroareInvitatie("Rolul contului nu corespunde invitației.")
        else:
            if not nume or not parola:
                raise EroareInvitatie("Numele și parola sunt obligatorii.")
            utilizator = Utilizator(
                email=invitatie.email,
                nume=nume.strip(),
                telefon=(telefon or "").strip() or None,
                rol=invitatie.rol,
                cabinet_id=invitatie.cabinet_id,
                is_active=True,
                is_staff=False,
                is_superuser=False,
            )
            utilizator.set_password(parola)
            try:
                utilizator.save(using="privileged")
            except IntegrityError as exc:
                raise EroareInvitatie(
                    "Contul a fost creat între timp. Autentifică-te și deschide din nou invitația."
                ) from exc

        if invitatie.firma_id:
            UtilizatorFirma.objects.using("privileged").get_or_create(
                utilizator_id=utilizator.pk,
                firma_id=invitatie.firma_id,
                defaults={
                    "rol_in_firma": invitatie.rol_in_firma,
                    "alocat_de_id": invitatie.creat_de_id,
                },
            )

        invitatie.acceptata_la = timezone.now()
        invitatie.save(using="privileged", update_fields=["acceptata_la"])
        _scrie_audit_privilegiat(
            utilizator_id=utilizator.pk,
            invitatie_id=invitatie.pk,
            firma_id=invitatie.firma_id,
            actiune="invitatie_acceptata",
            context=context,
            date_noi={"cont_creat": cont_creat, "rol": invitatie.rol},
        )
    return RezultatAcceptare(utilizator_id=utilizator.pk, cont_creat=cont_creat)


def anuleaza_invitatie(*, utilizator, invitatie: Invitatie, context: ContextAudit) -> None:
    if not poate_gestiona_invitatii(utilizator):
        raise PermissionDenied
    _valideaza_tinta(utilizator=utilizator, rol=invitatie.rol, firma=invitatie.firma)

    with transaction.atomic(using="privileged"):
        rand = Invitatie.objects.using("privileged").select_for_update().get(pk=invitatie.pk)
        if rand.acceptata_la:
            raise EroareInvitatie("Invitația a fost deja acceptată.")
        if rand.anulata_la:
            return
        rand.anulata_la = timezone.now()
        rand.save(using="privileged", update_fields=["anulata_la"])
        _scrie_audit_privilegiat(
            utilizator_id=utilizator.pk,
            invitatie_id=rand.pk,
            firma_id=rand.firma_id,
            actiune="invitatie_anulata",
            context=context,
        )
