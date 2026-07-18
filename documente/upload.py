from dataclasses import dataclass
from pathlib import PurePosixPath

from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from conturi.models import Utilizator, UtilizatorFirma
from core.models import AuditLog
from firme.models import Firma
from perioade.models import PerioadaContabila

from .filetypes import TipFisierInvalid, tip_pentru_upload, tipuri_compatibile
from .models import Document, FisierDocument, IntentieUpload
from .processing import proceseaza_fisier
from .services import poate_incarca_documente
from .storage import EroareStorage, get_document_storage

SALT_UPLOAD_LOCAL = "documente.upload-local.v1"


class EroareUpload(Exception):
    pass


@dataclass(frozen=True)
class RezultatInitiere:
    intentie: IntentieUpload
    content_type: str
    upload_url: str
    headers: dict[str, str]


def poate_atasa_fisiere(utilizator, document) -> bool:
    if not poate_incarca_documente(utilizator):
        return False
    if document.stare == Document.Stare.DRAFT:
        return document.incarcat_de_id == utilizator.pk
    return bool(
        document.stare == Document.Stare.NECESITA_CLARIFICARI
        and utilizator.rol in {"client_admin", "client_operator"}
    )


def _utilizator_cu_acces_privilegiat(*, actor, document) -> Utilizator:
    """Revalidează rolul și accesul la tenant înaintea unei scrieri BYPASSRLS."""

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
    except Utilizator.DoesNotExist as exc:
        raise PermissionDenied from exc

    if utilizator.rol in {
        Utilizator.Rol.CONTABIL,
        Utilizator.Rol.CONTABIL_COORDONATOR,
    }:
        firma = Firma.objects.using("privileged").get(pk=document.firma_id)
        if utilizator.cabinet_id != firma.cabinet_id:
            raise PermissionDenied
        if utilizator.rol == Utilizator.Rol.CONTABIL and not (
            UtilizatorFirma.objects.using("privileged")
            .filter(
                utilizator_id=utilizator.pk,
                firma_id=document.firma_id,
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
            firma_id=document.firma_id,
            rol_in_firma=rol_alocare,
        )
        .exists()
    ):
        raise PermissionDenied
    return utilizator


def _nume_sigur(nume: str) -> str:
    nume = PurePosixPath((nume or "").replace("\\", "/")).name.strip()
    if not nume or len(nume) > 255:
        raise EroareUpload("Numele fișierului este invalid.")
    return nume


def _url_upload_local(*, request, intentie, content_type) -> str:
    token = signing.dumps(
        {"intentie_id": str(intentie.pk), "content_type": content_type},
        salt=SALT_UPLOAD_LOCAL,
    )
    cale = reverse("upload_local_put", kwargs={"intentie_id": intentie.pk})
    return request.build_absolute_uri(f"{cale}?token={token}")


def initiaza_upload(
    *,
    document_id,
    actor,
    nume_original: str,
    content_type: str | None,
    dimensiune_declarata: int,
    request,
    inlocuieste_fisier_id=None,
) -> RezultatInitiere:
    nume_original = _nume_sigur(nume_original)
    try:
        content_type = tip_pentru_upload(nume_original, content_type)
    except TipFisierInvalid as exc:
        raise EroareUpload(str(exc)) from exc
    if dimensiune_declarata < 1 or dimensiune_declarata > settings.DOCUMENT_UPLOAD_MAX_BYTES:
        raise EroareUpload("Fișierul trebuie să aibă cel mult 25 MB.")

    with transaction.atomic(using="default"):
        document = Document.objects.get(pk=document_id, sters_la__isnull=True)
        perioada = PerioadaContabila.objects.select_for_update().get(
            pk=document.perioada_contabila_id
        )
        document = Document.objects.select_for_update(of=("self",)).get(pk=document.pk)
        if perioada.stare == PerioadaContabila.Stare.INCHISA:
            raise EroareUpload("Perioada este închisă.")
        if not poate_atasa_fisiere(actor, document):
            raise PermissionDenied
        inlocuieste_fisier = None
        if inlocuieste_fisier_id:
            try:
                inlocuieste_fisier = FisierDocument.objects.get(
                    pk=inlocuieste_fisier_id,
                    document_id=document.pk,
                    activ=True,
                    sters_la__isnull=True,
                )
            except (FisierDocument.DoesNotExist, ValidationError) as exc:
                raise EroareUpload(
                    "Fișierul ales pentru înlocuire nu mai este versiunea activă."
                ) from exc
        intentie = IntentieUpload.objects.create(
            firma_id=document.firma_id,
            document_id=document.pk,
            inlocuieste_fisier=inlocuieste_fisier,
            utilizator_id=actor.pk,
            nume_original=nume_original,
        )

    storage = get_document_storage()
    if storage.is_local:
        upload_url = _url_upload_local(
            request=request,
            intentie=intentie,
            content_type=content_type,
        )
    else:
        upload_url = storage.presigned_put_url(intentie.storage_key, content_type)
    return RezultatInitiere(
        intentie=intentie,
        content_type=content_type,
        upload_url=upload_url,
        headers={"Content-Type": content_type},
    )


def valideaza_token_upload_local(*, token: str, intentie_id):
    try:
        date = signing.loads(
            token,
            salt=SALT_UPLOAD_LOCAL,
            max_age=settings.DOCUMENT_UPLOAD_URL_TTL,
        )
    except signing.BadSignature as exc:
        raise EroareUpload("Adresa de încărcare este invalidă sau a expirat.") from exc
    if date.get("intentie_id") != str(intentie_id):
        raise EroareUpload("Adresa nu corespunde intenției de încărcare.")
    return date["content_type"]


def primeste_upload_local(*, intentie_id, token: str, content_type: str, continut: bytes):
    storage = get_document_storage()
    if not storage.is_local:
        raise EroareUpload("Endpoint-ul local nu este activ.")
    tip_semnat = valideaza_token_upload_local(token=token, intentie_id=intentie_id)
    content_type = (content_type or "").split(";", maxsplit=1)[0].strip().lower()
    if content_type != tip_semnat:
        raise EroareUpload("Content-Type nu corespunde adresei semnate.")
    if not continut or len(continut) > settings.DOCUMENT_UPLOAD_MAX_BYTES:
        raise EroareUpload("Fișierul trebuie să aibă cel mult 25 MB.")
    with transaction.atomic(using="privileged"):
        intentie = (
            IntentieUpload.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=intentie_id)
        )
        if intentie.folosita_la or intentie.expira_la <= timezone.now():
            raise EroareUpload("Intenția de încărcare a expirat sau a fost deja folosită.")
        storage.put_bytes(intentie.storage_key, continut, tip_semnat)


def finalizeaza_upload(*, intentie_id, actor, context):
    intentie_vizibila = IntentieUpload.objects.get(pk=intentie_id)
    if intentie_vizibila.utilizator_id != actor.pk:
        raise PermissionDenied
    storage = get_document_storage()

    with transaction.atomic(using="privileged"):
        intentie = (
            IntentieUpload.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=intentie_id)
        )
        if intentie.utilizator_id != actor.pk:
            raise PermissionDenied
        if intentie.folosita_la:
            raise EroareUpload("Intenția a fost deja finalizată.")
        if intentie.expira_la <= timezone.now():
            raise EroareUpload("Intenția de încărcare a expirat.")
        document = Document.objects.using("privileged").get(
            pk=intentie.document_id,
            firma_id=intentie.firma_id,
            sters_la__isnull=True,
        )
        perioada = PerioadaContabila.objects.using("privileged").get(
            pk=document.perioada_contabila_id,
            firma_id=document.firma_id,
        )
        if perioada.stare == PerioadaContabila.Stare.INCHISA:
            raise EroareUpload("Perioada este închisă.")
        utilizator = _utilizator_cu_acces_privilegiat(actor=actor, document=document)
        if not poate_atasa_fisiere(utilizator, document):
            raise PermissionDenied

        inlocuieste_fisier = None
        if intentie.inlocuieste_fisier_id:
            try:
                inlocuieste_fisier = (
                    FisierDocument.objects.using("privileged")
                    .select_for_update(of=("self",))
                    .get(
                        pk=intentie.inlocuieste_fisier_id,
                        document_id=document.pk,
                        firma_id=document.firma_id,
                        activ=True,
                        sters_la__isnull=True,
                    )
                )
            except FisierDocument.DoesNotExist as exc:
                raise EroareUpload(
                    "Fișierul ales pentru înlocuire nu mai este versiunea activă."
                ) from exc

        try:
            metadata = storage.head(intentie.storage_key)
            tip_asteptat = tip_pentru_upload(
                intentie.nume_original or "",
                metadata.content_type,
            )
        except (EroareStorage, TipFisierInvalid) as exc:
            raise EroareUpload(str(exc)) from exc
        if metadata.dimensiune < 1 or metadata.dimensiune > settings.DOCUMENT_UPLOAD_MAX_BYTES:
            raise EroareUpload("Fișierul încărcat depășește limita de 25 MB.")
        if metadata.content_type and not tipuri_compatibile(tip_asteptat, metadata.content_type):
            raise EroareUpload("Tipul obiectului încărcat nu este cel autorizat.")

        if inlocuieste_fisier:
            ordine = inlocuieste_fisier.ordine
            versiune = (
                FisierDocument.objects.using("privileged")
                .filter(document_id=document.pk, ordine=ordine)
                .aggregate(maxim=Max("versiune"))["maxim"]
                or 0
            ) + 1
        else:
            ordine = (
                FisierDocument.objects.using("privileged")
                .filter(document_id=document.pk)
                .aggregate(maxim=Max("ordine"))["maxim"]
                or 0
            ) + 1
            versiune = 1
        fisier = FisierDocument.objects.using("privileged").create(
            document_id=document.pk,
            firma_id=document.firma_id,
            upload_intentie_id=intentie.pk,
            storage_key=intentie.storage_key,
            nume_original=intentie.nume_original,
            mime_type=tip_asteptat,
            dimensiune_bytes=metadata.dimensiune,
            ordine=ordine,
            versiune=versiune,
            inlocuieste_fisier_id=(inlocuieste_fisier.pk if inlocuieste_fisier else None),
            incarcat_de_id=utilizator.pk,
            activ=inlocuieste_fisier is None,
        )
        intentie.folosita_la = timezone.now()
        intentie.save(using="privileged", update_fields=["folosita_la"])
        AuditLog.objects.using("privileged").create(
            firma_id=document.firma_id,
            utilizator_id=utilizator.pk,
            entitate_tip="document",
            entitate_id=document.pk,
            actiune="fisier_incarcat",
            date_noi={
                "fisier_id": str(fisier.pk),
                "nume": fisier.nume_original,
                "dimensiune": fisier.dimensiune_bytes,
                "inlocuieste_fisier_id": (
                    str(inlocuieste_fisier.pk) if inlocuieste_fisier else None
                ),
            },
            ip_address=context.ip_address,
            user_agent=(context.user_agent or "")[:255] or None,
        )

    return proceseaza_fisier(fisier.pk)


def sterge_fisier(*, fisier_id, actor, context):
    fisier_vizibil = FisierDocument.objects.get(
        pk=fisier_id,
        activ=True,
        sters_la__isnull=True,
    )
    document_vizibil = Document.objects.get(pk=fisier_vizibil.document_id)
    if (
        document_vizibil.stare != Document.Stare.DRAFT
        or document_vizibil.incarcat_de_id != actor.pk
        or not actor.is_active
    ):
        raise PermissionDenied

    with transaction.atomic(using="privileged"):
        fisier = (
            FisierDocument.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=fisier_id, activ=True, sters_la__isnull=True)
        )
        document = Document.objects.using("privileged").get(
            pk=fisier.document_id,
            firma_id=fisier.firma_id,
            sters_la__isnull=True,
        )
        perioada = PerioadaContabila.objects.using("privileged").get(
            pk=document.perioada_contabila_id,
            firma_id=document.firma_id,
        )
        if perioada.stare == PerioadaContabila.Stare.INCHISA:
            raise EroareUpload("Perioada este închisă.")
        utilizator = _utilizator_cu_acces_privilegiat(actor=actor, document=document)
        if document.stare != Document.Stare.DRAFT or document.incarcat_de_id != utilizator.pk:
            raise PermissionDenied
        fisier.activ = False
        fisier.sters_la = timezone.now()
        fisier.sters_de_id = utilizator.pk
        fisier.save(
            using="privileged",
            update_fields=["activ", "sters_la", "sters_de"],
        )
        AuditLog.objects.using("privileged").create(
            firma_id=document.firma_id,
            utilizator_id=utilizator.pk,
            entitate_tip="document",
            entitate_id=document.pk,
            actiune="fisier_sters",
            date_noi={"fisier_id": str(fisier.pk)},
            ip_address=context.ip_address,
            user_agent=(context.user_agent or "")[:255] or None,
        )
    return fisier
