import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from conturi.models import Utilizator, UtilizatorFirma
from core.models import AuditLog
from firme.models import Firma
from perioade.models import PerioadaContabila

from .filetypes import TipFisierInvalid, detecteaza_tip, tip_pentru_upload, tipuri_compatibile
from .models import FisierInbox, LotIncarcare
from .services import poate_incarca_documente
from .storage import EroareStorage, get_document_storage
from .storage_keys import cheie_original_inbox

SALT_UPLOAD_INBOX_LOCAL = "documente.inbox-upload-local.v1"


class EroareInbox(Exception):
    pass


@dataclass(frozen=True)
class RezultatInitiereInbox:
    fisier: FisierInbox
    content_type: str
    upload_url: str
    headers: dict[str, str]


def _nume_sigur(nume: str) -> str:
    nume = PurePosixPath((nume or "").replace("\\", "/")).name.strip()
    if not nume or len(nume) > 255:
        raise EroareInbox("Numele fișierului este invalid.")
    return nume


def _audit(
    *,
    using: str,
    firma_id,
    actor_id,
    entitate_tip,
    entitate_id,
    actiune,
    context,
    date_noi,
):
    AuditLog.objects.using(using).create(
        firma_id=firma_id,
        utilizator_id=actor_id,
        entitate_tip=entitate_tip,
        entitate_id=entitate_id,
        actiune=actiune,
        date_noi=date_noi,
        ip_address=context.ip_address,
        user_agent=(context.user_agent or "")[:255] or None,
    )


def _utilizator_cu_acces_privilegiat(*, actor, firma_id) -> Utilizator:
    try:
        utilizator = Utilizator.objects.using("privileged").get(
            pk=actor.pk,
            is_active=True,
            rol__in=(
                Utilizator.Rol.CONTABIL,
                Utilizator.Rol.CONTABIL_COORDONATOR,
                Utilizator.Rol.CLIENT_ADMIN,
                Utilizator.Rol.CLIENT_OPERATOR,
            ),
        )
        firma = Firma.objects.using("privileged").get(pk=firma_id, activa=True)
    except (Utilizator.DoesNotExist, Firma.DoesNotExist) as exc:
        raise PermissionDenied from exc

    if utilizator.rol in {
        Utilizator.Rol.CONTABIL,
        Utilizator.Rol.CONTABIL_COORDONATOR,
    }:
        if utilizator.cabinet_id != firma.cabinet_id:
            raise PermissionDenied
        if utilizator.rol == Utilizator.Rol.CONTABIL and not (
            UtilizatorFirma.objects.using("privileged")
            .filter(
                utilizator_id=utilizator.pk,
                firma_id=firma.pk,
                rol_in_firma=UtilizatorFirma.Rol.CONTABIL_ALOCAT,
            )
            .exists()
        ):
            raise PermissionDenied
        return utilizator

    rol_alocare = (
        UtilizatorFirma.Rol.REPREZENTANT_CLIENT
        if utilizator.rol == Utilizator.Rol.CLIENT_ADMIN
        else UtilizatorFirma.Rol.OPERATOR_UPLOAD
    )
    if not (
        UtilizatorFirma.objects.using("privileged")
        .filter(
            utilizator_id=utilizator.pk,
            firma_id=firma.pk,
            rol_in_firma=rol_alocare,
        )
        .exists()
    ):
        raise PermissionDenied
    return utilizator


def creeaza_lot_incarcare(
    *,
    perioada_id,
    actor,
    numar_fisiere: int,
    dimensiune_totala: int,
    nota: str,
    context,
) -> LotIncarcare:
    if not poate_incarca_documente(actor):
        raise PermissionDenied
    if not 1 <= numar_fisiere <= settings.DOCUMENT_BATCH_MAX_FILES:
        raise EroareInbox(
            f"Un lot trebuie să conțină între 1 și {settings.DOCUMENT_BATCH_MAX_FILES} fișiere."
        )
    if not 1 <= dimensiune_totala <= settings.DOCUMENT_BATCH_MAX_TOTAL_BYTES:
        raise EroareInbox("Lotul poate avea cel mult 2 GB.")
    nota = (nota or "").strip()
    if len(nota) > 2000:
        raise EroareInbox("Nota lotului poate avea cel mult 2.000 de caractere.")

    with transaction.atomic(using="default"):
        perioada = PerioadaContabila.objects.select_for_update().get(pk=perioada_id)
        if perioada.stare in {
            PerioadaContabila.Stare.INCHIDERE_IN_CURS,
            PerioadaContabila.Stare.INCHISA,
        }:
            raise EroareInbox("Nu poți încărca într-o perioadă închisă.")
        lot = LotIncarcare.objects.create(
            firma_id=perioada.firma_id,
            perioada_contabila=perioada,
            creat_de_id=actor.pk,
            numar_fisiere_declarat=numar_fisiere,
            dimensiune_totala_declarata=dimensiune_totala,
            nota=nota or None,
        )
        _audit(
            using="default",
            firma_id=lot.firma_id,
            actor_id=actor.pk,
            entitate_tip="lot_incarcare",
            entitate_id=lot.pk,
            actiune="lot_incarcare_creat",
            context=context,
            date_noi={
                "perioada_id": str(perioada.pk),
                "numar_fisiere": numar_fisiere,
                "dimensiune_totala": dimensiune_totala,
            },
        )
    return lot


def _url_upload_local(*, request, fisier, content_type) -> str:
    token = signing.dumps(
        {"fisier_id": str(fisier.pk), "content_type": content_type},
        salt=SALT_UPLOAD_INBOX_LOCAL,
    )
    cale = reverse("inbox_upload_local_put", kwargs={"fisier_id": fisier.pk})
    return request.build_absolute_uri(f"{cale}?token={token}")


def initiaza_fisier_inbox(
    *,
    lot_id,
    actor,
    nume_original: str,
    content_type: str | None,
    dimensiune_declarata: int,
    request,
) -> RezultatInitiereInbox:
    nume_original = _nume_sigur(nume_original)
    try:
        content_type = tip_pentru_upload(nume_original, content_type)
    except TipFisierInvalid as exc:
        raise EroareInbox(str(exc)) from exc
    if not 1 <= dimensiune_declarata <= settings.DOCUMENT_UPLOAD_MAX_BYTES:
        raise EroareInbox("Fișierul trebuie să aibă cel mult 25 MB.")

    with transaction.atomic(using="default"):
        lot = LotIncarcare.objects.select_related("perioada_contabila").get(pk=lot_id)
        perioada = PerioadaContabila.objects.select_for_update().get(pk=lot.perioada_contabila_id)
        if lot.creat_de_id != actor.pk:
            raise PermissionDenied
        if lot.status != LotIncarcare.Status.IN_DESFASURARE:
            raise EroareInbox("Lotul nu mai acceptă fișiere.")
        if perioada.stare in {
            PerioadaContabila.Stare.INCHIDERE_IN_CURS,
            PerioadaContabila.Stare.INCHISA,
        }:
            raise EroareInbox("Perioada este închisă.")
        fisiere = FisierInbox.objects.filter(lot_id=lot.pk)
        if fisiere.count() >= lot.numar_fisiere_declarat:
            raise EroareInbox("Lotul conține deja toate pozițiile declarate.")
        dimensiune_existenta = fisiere.aggregate(total=Sum("dimensiune_declarata"))["total"] or 0
        if dimensiune_existenta + dimensiune_declarata > lot.dimensiune_totala_declarata:
            raise EroareInbox("Fișierele depășesc dimensiunea declarată a lotului.")
        fisier = FisierInbox.objects.create(
            lot=lot,
            firma_id=lot.firma_id,
            perioada_contabila_id=lot.perioada_contabila_id,
            incarcat_de_id=actor.pk,
            nume_original=nume_original,
            mime_type=content_type,
            dimensiune_declarata=dimensiune_declarata,
        )

    storage = get_document_storage()
    if storage.is_local:
        upload_url = _url_upload_local(
            request=request,
            fisier=fisier,
            content_type=content_type,
        )
    else:
        upload_url = storage.presigned_put_url(fisier.temp_storage_key, content_type)
    return RezultatInitiereInbox(
        fisier=fisier,
        content_type=content_type,
        upload_url=upload_url,
        headers={"Content-Type": content_type},
    )


def valideaza_token_upload_local(*, token: str, fisier_id) -> str:
    try:
        date = signing.loads(
            token,
            salt=SALT_UPLOAD_INBOX_LOCAL,
            max_age=settings.DOCUMENT_INBOX_UPLOAD_URL_TTL,
        )
    except signing.BadSignature as exc:
        raise EroareInbox("Adresa de încărcare este invalidă sau a expirat.") from exc
    if date.get("fisier_id") != str(fisier_id):
        raise EroareInbox("Adresa nu corespunde fișierului din inbox.")
    return date["content_type"]


def primeste_upload_local_inbox(*, fisier_id, token: str, content_type: str, continut: bytes):
    storage = get_document_storage()
    if not storage.is_local:
        raise EroareInbox("Endpoint-ul local nu este activ.")
    tip_semnat = valideaza_token_upload_local(token=token, fisier_id=fisier_id)
    content_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if content_type != tip_semnat:
        raise EroareInbox("Content-Type nu corespunde adresei semnate.")
    if not continut or len(continut) > settings.DOCUMENT_UPLOAD_MAX_BYTES:
        raise EroareInbox("Fișierul trebuie să aibă cel mult 25 MB.")

    with transaction.atomic(using="privileged"):
        fisier = (
            FisierInbox.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=fisier_id)
        )
        if fisier.status != FisierInbox.Status.IN_ASTEPTARE:
            raise EroareInbox("Fișierul nu mai acceptă conținut.")
        if fisier.expira_la <= timezone.now():
            raise EroareInbox("Adresa de încărcare a expirat.")
        if len(continut) != fisier.dimensiune_declarata:
            raise EroareInbox("Dimensiunea încărcată nu corespunde fișierului selectat.")
        storage.put_bytes(fisier.temp_storage_key, continut, tip_semnat)


def finalizeaza_fisier_inbox(*, fisier_id, actor, context) -> FisierInbox:
    fisier_vizibil = FisierInbox.objects.select_related("perioada_contabila").get(pk=fisier_id)
    if fisier_vizibil.incarcat_de_id != actor.pk:
        raise PermissionDenied
    if fisier_vizibil.status == FisierInbox.Status.DISPONIBIL:
        return fisier_vizibil
    if fisier_vizibil.status != FisierInbox.Status.IN_ASTEPTARE:
        raise EroareInbox("Fișierul nu mai poate fi finalizat.")

    storage = get_document_storage()
    try:
        continut = storage.read_bytes(fisier_vizibil.temp_storage_key)
        metadata = storage.head(fisier_vizibil.temp_storage_key)
    except EroareStorage as exc:
        raise EroareInbox("Fișierul nu a ajuns complet în spațiul temporar.") from exc
    if not continut or len(continut) > settings.DOCUMENT_UPLOAD_MAX_BYTES:
        raise EroareInbox("Fișierul trebuie să aibă cel mult 25 MB.")
    if len(continut) != fisier_vizibil.dimensiune_declarata:
        raise EroareInbox("Dimensiunea încărcată nu corespunde fișierului selectat.")
    try:
        tip_detectat = detecteaza_tip(continut)
        tip_asteptat = tip_pentru_upload(
            fisier_vizibil.nume_original,
            metadata.content_type,
        )
    except TipFisierInvalid as exc:
        raise EroareInbox(str(exc)) from exc
    if not tipuri_compatibile(tip_asteptat, tip_detectat):
        raise EroareInbox("Conținutul nu corespunde tipului și extensiei declarate.")

    perioada = fisier_vizibil.perioada_contabila
    cheie_finala = cheie_original_inbox(
        firma_id=fisier_vizibil.firma_id,
        an=perioada.an,
        luna=perioada.luna,
        lot_id=fisier_vizibil.lot_id,
        fisier_id=fisier_vizibil.pk,
    )
    checksum = hashlib.sha256(continut).hexdigest()
    destinatie_creata = False
    try:
        continut_existent = storage.read_bytes(cheie_finala)
    except EroareStorage:
        storage.put_bytes(cheie_finala, continut, tip_detectat)
        destinatie_creata = True
        try:
            continut_existent = storage.read_bytes(cheie_finala)
        except EroareStorage as exc:
            storage.delete(cheie_finala)
            raise EroareInbox("Fișierul nu a putut fi verificat după copiere.") from exc
        if hashlib.sha256(continut_existent).hexdigest() != checksum:
            storage.delete(cheie_finala)
            raise EroareInbox("Fișierul copiat nu corespunde sursei temporare.") from None
    else:
        if hashlib.sha256(continut_existent).hexdigest() != checksum:
            raise EroareInbox("Destinația inbox conține deja alt fișier.")

    try:
        with transaction.atomic(using="privileged"):
            fisier = (
                FisierInbox.objects.using("privileged")
                .select_for_update(of=("self",))
                .select_related("perioada_contabila")
                .get(pk=fisier_id)
            )
            lot = (
                LotIncarcare.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(pk=fisier.lot_id)
            )
            perioada = (
                PerioadaContabila.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(pk=fisier.perioada_contabila_id, firma_id=fisier.firma_id)
            )
            utilizator = _utilizator_cu_acces_privilegiat(actor=actor, firma_id=fisier.firma_id)
            if fisier.incarcat_de_id != utilizator.pk:
                raise PermissionDenied
            if fisier.status == FisierInbox.Status.DISPONIBIL:
                fisier_deja_finalizat = True
            else:
                fisier_deja_finalizat = False
                if fisier.status != FisierInbox.Status.IN_ASTEPTARE:
                    raise EroareInbox("Fișierul nu mai poate fi finalizat.")
                if lot.status != LotIncarcare.Status.IN_DESFASURARE:
                    raise EroareInbox("Lotul nu mai acceptă finalizări.")
                if perioada.stare in {
                    PerioadaContabila.Stare.INCHIDERE_IN_CURS,
                    PerioadaContabila.Stare.INCHISA,
                }:
                    raise EroareInbox("Perioada este închisă.")
                if fisier.expira_la <= timezone.now():
                    raise EroareInbox("Adresa de încărcare a expirat.")

                fisier.storage_key = cheie_finala
                fisier.mime_type = tip_detectat
                fisier.dimensiune_bytes = len(continut)
                fisier.checksum = checksum
                fisier.status = FisierInbox.Status.DISPONIBIL
                fisier.incarcat_la = timezone.now()
                fisier.save(
                    using="privileged",
                    update_fields=[
                        "storage_key",
                        "mime_type",
                        "dimensiune_bytes",
                        "checksum",
                        "status",
                        "incarcat_la",
                    ],
                )
                _audit(
                    using="privileged",
                    firma_id=fisier.firma_id,
                    actor_id=utilizator.pk,
                    entitate_tip="fisier_inbox",
                    entitate_id=fisier.pk,
                    actiune="fisier_inbox_finalizat",
                    context=context,
                    date_noi={
                        "lot_id": str(fisier.lot_id),
                        "storage_key": cheie_finala,
                        "checksum": checksum,
                        "dimensiune_bytes": len(continut),
                    },
                )
    except Exception:
        if destinatie_creata:
            storage.delete(cheie_finala)
        raise

    storage.delete(fisier_vizibil.temp_storage_key)
    if fisier_deja_finalizat:
        return fisier
    return fisier


def finalizeaza_lot_incarcare(*, lot_id, actor, context) -> LotIncarcare:
    get_lot = LotIncarcare.objects.get(pk=lot_id)
    if get_lot.creat_de_id != actor.pk:
        raise PermissionDenied

    with transaction.atomic(using="privileged"):
        lot = (
            LotIncarcare.objects.using("privileged").select_for_update(of=("self",)).get(pk=lot_id)
        )
        utilizator = _utilizator_cu_acces_privilegiat(actor=actor, firma_id=lot.firma_id)
        if lot.creat_de_id != utilizator.pk:
            raise PermissionDenied
        if lot.status != LotIncarcare.Status.IN_DESFASURARE:
            return lot

        fisiere = FisierInbox.objects.using("privileged").filter(lot_id=lot.pk)
        disponibile = fisiere.filter(status=FisierInbox.Status.DISPONIBIL).count()
        in_asteptare = fisiere.filter(status=FisierInbox.Status.IN_ASTEPTARE)
        in_asteptare.update(
            status=FisierInbox.Status.EROARE,
            eroare="Încărcarea nu a fost finalizată înainte de închiderea lotului.",
        )
        lot.status = (
            LotIncarcare.Status.FINALIZAT
            if disponibile == lot.numar_fisiere_declarat
            else LotIncarcare.Status.PARTIAL
        )
        lot.finalizat_la = timezone.now()
        lot.save(using="privileged", update_fields=["status", "finalizat_la"])
        _audit(
            using="privileged",
            firma_id=lot.firma_id,
            actor_id=utilizator.pk,
            entitate_tip="lot_incarcare",
            entitate_id=lot.pk,
            actiune="lot_incarcare_finalizat",
            context=context,
            date_noi={
                "status": lot.status,
                "fisiere_disponibile": disponibile,
                "fisiere_declarate": lot.numar_fisiere_declarat,
            },
        )
    return lot
