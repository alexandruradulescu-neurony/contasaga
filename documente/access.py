from dataclasses import dataclass

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils.http import content_disposition_header

from .models import FisierDocument
from .storage import EroareStorage, get_document_storage

SALT_ACCES_LOCAL = "documente.acces-local.v1"


class EroareAccesFisier(Exception):
    pass


@dataclass(frozen=True)
class ContinutLocalSemnat:
    continut: bytes
    content_type: str
    content_disposition: str


def _dispozitie(*, descarcare: bool, nume: str) -> str:
    return content_disposition_header(descarcare, nume) or "attachment"


def url_acces_fisier(*, request, fisier: FisierDocument, descarcare: bool) -> str:
    if fisier.stare_procesare != FisierDocument.StareProcesare.PROCESAT:
        raise EroareAccesFisier("Fișierul nu este disponibil până la finalizarea procesării.")
    storage = get_document_storage()
    content_type = fisier.mime_type or "application/octet-stream"
    nume = fisier.nume_original or "document"
    content_disposition = _dispozitie(descarcare=descarcare, nume=nume)
    if not storage.is_local:
        return storage.presigned_get_url(
            fisier.storage_key,
            content_type=content_type,
            content_disposition=content_disposition,
        )

    token = signing.dumps(
        {
            "storage_key": fisier.storage_key,
            "content_type": content_type,
            "content_disposition": content_disposition,
        },
        salt=SALT_ACCES_LOCAL,
        compress=True,
    )
    cale = reverse("fisier_local_semnat")
    return request.build_absolute_uri(f"{cale}?token={token}")


def continut_local_semnat(*, token: str) -> ContinutLocalSemnat:
    storage = get_document_storage()
    if not storage.is_local:
        raise EroareAccesFisier("Endpoint-ul local nu este activ.")
    try:
        date = signing.loads(
            token,
            salt=SALT_ACCES_LOCAL,
            max_age=settings.DOCUMENT_DOWNLOAD_URL_TTL,
        )
        storage_key = date["storage_key"]
        content_type = date["content_type"]
        content_disposition = date["content_disposition"]
    except (KeyError, signing.BadSignature) as exc:
        raise EroareAccesFisier("Adresa fișierului este invalidă sau a expirat.") from exc
    try:
        continut = storage.read_bytes(storage_key)
    except EroareStorage as exc:
        raise EroareAccesFisier(str(exc)) from exc
    return ContinutLocalSemnat(
        continut=continut,
        content_type=content_type,
        content_disposition=content_disposition,
    )
