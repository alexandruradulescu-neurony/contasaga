from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header

from documente.storage import EroareStorage, get_document_storage

from .models import Export

SALT_EXPORT_LOCAL = "exporturi.acces-local.v1"


class EroareAccesExport(Exception):
    pass


@dataclass(frozen=True)
class ExportLocalSemnat:
    fisier: object
    content_disposition: str


def nume_export(export: Export) -> str:
    perioada = export.perioada_contabila
    cui = "".join(caracter for caracter in export.firma.cui if caracter.isalnum())
    return f"documente_{cui}_{perioada.an}_{perioada.luna:02d}.zip"


def url_descarcare_export(*, request, export: Export) -> str:
    if (
        export.status != Export.Status.FINALIZAT
        or not export.storage_key
        or not export.expira_la
        or export.expira_la <= timezone.now()
    ):
        raise EroareAccesExport("Exportul nu este disponibil sau a expirat.")
    storage = get_document_storage()
    dispozitie = content_disposition_header(True, nume_export(export)) or "attachment"
    if not storage.is_local:
        return storage.presigned_get_url(
            export.storage_key,
            content_type="application/zip",
            content_disposition=dispozitie,
        )

    token = signing.dumps(
        {
            "storage_key": export.storage_key,
            "content_disposition": dispozitie,
            "expira_la": export.expira_la.isoformat(),
        },
        salt=SALT_EXPORT_LOCAL,
        compress=True,
    )
    cale = reverse("export_local_semnat")
    return request.build_absolute_uri(f"{cale}?token={token}")


def deschide_export_local_semnat(*, token: str) -> ExportLocalSemnat:
    storage = get_document_storage()
    if not storage.is_local:
        raise EroareAccesExport("Endpoint-ul local nu este activ.")
    try:
        date = signing.loads(
            token,
            salt=SALT_EXPORT_LOCAL,
            max_age=settings.DOCUMENT_DOWNLOAD_URL_TTL,
        )
        expira_la = datetime.fromisoformat(date["expira_la"])
        if expira_la <= timezone.now():
            raise signing.BadSignature
        fisier = storage.open_binary(date["storage_key"])
        dispozitie = date["content_disposition"]
    except (KeyError, ValueError, signing.BadSignature, EroareStorage) as exc:
        raise EroareAccesExport("Adresa exportului este invalidă sau a expirat.") from exc
    return ExportLocalSemnat(fisier=fisier, content_disposition=dispozitie)
