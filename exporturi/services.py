import csv
import hashlib
import io
import logging
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.db.models import Prefetch
from django.utils import timezone

from conturi.models import Utilizator, UtilizatorFirma
from core.audit import ContextAudit
from core.models import AuditLog
from documente.models import Document, FisierDocument
from documente.storage import get_document_storage
from notificari.services import notifica_export_finalizat
from perioade.models import PerioadaContabila

from .models import Export

logger = logging.getLogger(__name__)
ROLURI_EXPORT = {Utilizator.Rol.CONTABIL, Utilizator.Rol.CONTABIL_COORDONATOR}
ZILE_VALABILITATE = 7


class EroareExport(Exception):
    pass


@dataclass(frozen=True)
class RezultatSolicitare:
    export: Export
    creat: bool


def poate_solicita_export(utilizator) -> bool:
    return bool(
        utilizator.is_authenticated and utilizator.is_active and utilizator.rol in ROLURI_EXPORT
    )


def _verifica_acces_privilegiat(*, actor, perioada) -> Utilizator:
    try:
        utilizator = Utilizator.objects.using("privileged").get(
            pk=actor.pk,
            is_active=True,
            rol__in=ROLURI_EXPORT,
        )
    except Utilizator.DoesNotExist as exc:
        raise PermissionDenied from exc
    if utilizator.cabinet_id != perioada.firma.cabinet_id:
        raise PermissionDenied
    if utilizator.rol == Utilizator.Rol.CONTABIL and not (
        UtilizatorFirma.objects.using("privileged")
        .filter(
            utilizator_id=utilizator.pk,
            firma_id=perioada.firma_id,
            rol_in_firma=UtilizatorFirma.Rol.CONTABIL_ALOCAT,
        )
        .exists()
    ):
        raise PermissionDenied
    return utilizator


def solicita_export(
    *,
    perioada_id,
    actor,
    context: ContextAudit,
) -> RezultatSolicitare:
    if not poate_solicita_export(actor):
        raise PermissionDenied
    with transaction.atomic(using="privileged"):
        perioada = (
            PerioadaContabila.objects.using("privileged")
            .select_for_update(of=("self",))
            .select_related("firma")
            .get(pk=perioada_id)
        )
        utilizator = _verifica_acces_privilegiat(actor=actor, perioada=perioada)
        if perioada.stare != PerioadaContabila.Stare.INCHISA:
            raise EroareExport("Exportul este disponibil numai pentru o perioadă închisă.")

        export = (
            Export.objects.using("privileged")
            .filter(
                perioada_contabila_id=perioada.pk,
                solicitat_de_id=utilizator.pk,
                status=Export.Status.IN_LUCRU,
            )
            .first()
        )
        if export:
            return RezultatSolicitare(export=export, creat=False)

        export = Export.objects.using("privileged").create(
            firma_id=perioada.firma_id,
            perioada_contabila_id=perioada.pk,
            solicitat_de_id=utilizator.pk,
        )
        AuditLog.objects.using("privileged").create(
            firma_id=perioada.firma_id,
            utilizator_id=utilizator.pk,
            entitate_tip="export",
            entitate_id=export.pk,
            actiune="export_solicitat",
            date_noi={"perioada_contabila_id": str(perioada.pk)},
            ip_address=context.ip_address,
            user_agent=(context.user_agent or "")[:255] or None,
        )
        return RezultatSolicitare(export=export, creat=True)


def _segment_sigur(valoare: str | None, *, fallback: str) -> str:
    normalizat = unicodedata.normalize("NFKD", valoare or "")
    ascii_text = normalizat.encode("ascii", "ignore").decode().lower()
    segment = re.sub(r"[^a-z0-9._-]+", "-", ascii_text).strip("-._")
    return segment[:80] or fallback


def _nume_original_sigur(valoare: str | None) -> str:
    nume = PurePosixPath((valoare or "document").replace("\\", "/")).name
    path = Path(nume)
    stem = _segment_sigur(path.stem, fallback="document")
    extensie = re.sub(r"[^a-zA-Z0-9.]", "", path.suffix.lower())[:12]
    return f"{stem}{extensie}"


def _scrie_in_zip(arhiva: ZipFile, cale: str, continut: bytes) -> None:
    informatie = ZipInfo(cale, date_time=(1980, 1, 1, 0, 0, 0))
    informatie.compress_type = ZIP_DEFLATED
    informatie.external_attr = 0o600 << 16
    arhiva.writestr(informatie, continut)


def _documente_export(perioada_id):
    fisiere = (
        FisierDocument.objects.using("privileged")
        .filter(
            activ=True,
            sters_la__isnull=True,
            stare_procesare=FisierDocument.StareProcesare.PROCESAT,
        )
        .order_by("ordine", "versiune", "pk")
    )
    return list(
        Document.objects.using("privileged")
        .filter(
            perioada_contabila_id=perioada_id,
            stare__in=(Document.Stare.PROCESAT, Document.Stare.ARHIVAT),
            sters_la__isnull=True,
            fisiere__activ=True,
            fisiere__sters_la__isnull=True,
            fisiere__stare_procesare=FisierDocument.StareProcesare.PROCESAT,
        )
        .select_related("tip_document", "cont_financiar", "partener")
        .prefetch_related(Prefetch("fisiere", queryset=fisiere, to_attr="fisiere_export"))
        .distinct()
        .order_by("tip_document__categorie", "tip_document__cod", "creat_la", "pk")
    )


def _construieste_zip(*, perioada_id, destinatie: Path) -> int:
    storage = get_document_storage()
    documente = _documente_export(perioada_id)
    manifest = io.StringIO(newline="")
    csv_writer = csv.writer(manifest, lineterminator="\n")
    csv_writer.writerow(
        (
            "cale_zip",
            "document_id",
            "categorie",
            "tip_document",
            "cont_financiar",
            "partener",
            "data_document",
            "serie",
            "numar",
            "directie",
            "moneda",
            "valoare_totala",
            "checksum_sha256",
        )
    )
    numar_fisiere = 0
    with ZipFile(destinatie, mode="w", compression=ZIP_DEFLATED, compresslevel=6) as arhiva:
        for index_document, document in enumerate(documente, start=1):
            categorie = _segment_sigur(
                document.tip_document.categorie,
                fallback="alte-documente",
            )
            tip = _segment_sigur(document.tip_document.cod, fallback="document")
            for index_fisier, fisier in enumerate(document.fisiere_export, start=1):
                nume = _nume_original_sigur(fisier.nume_original)
                cale_zip = f"{categorie}/{tip}/{index_document:04d}_{index_fisier:02d}_{nume}"
                continut = storage.read_bytes(fisier.storage_key)
                checksum = hashlib.sha256(continut).hexdigest()
                if fisier.checksum and checksum != fisier.checksum:
                    raise EroareExport(
                        f"Checksum invalid pentru fișierul {fisier.nume_original or fisier.pk}."
                    )
                _scrie_in_zip(arhiva, cale_zip, continut)
                csv_writer.writerow(
                    (
                        cale_zip,
                        document.pk,
                        document.tip_document.categorie,
                        document.tip_document.denumire,
                        document.cont_financiar.denumire if document.cont_financiar else "",
                        document.partener.denumire if document.partener else "",
                        document.data_document or "",
                        document.serie or "",
                        document.numar or "",
                        document.directie or "",
                        document.moneda,
                        document.valoare_totala if document.valoare_totala is not None else "",
                        checksum,
                    )
                )
                numar_fisiere += 1
        _scrie_in_zip(arhiva, "manifest.csv", manifest.getvalue().encode("utf-8-sig"))
    return numar_fisiere


def _incearca_blocare(export_id) -> bool:
    with connections["privileged"].cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            [str(export_id)],
        )
        return cursor.fetchone()[0]


def _elibereaza_blocare(export_id) -> None:
    with connections["privileged"].cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            [str(export_id)],
        )


def genereaza_export(export_id) -> Export | None:
    if not _incearca_blocare(export_id):
        return None
    storage = get_document_storage()
    storage_key = None
    try:
        export = (
            Export.objects.using("privileged")
            .select_related("perioada_contabila__firma", "solicitat_de")
            .get(pk=export_id)
        )
        if export.status != Export.Status.IN_LUCRU:
            return export
        if export.perioada_contabila.stare != PerioadaContabila.Stare.INCHISA:
            raise EroareExport("Perioada a fost redeschisă înainte de generarea exportului.")

        storage_key = f"exports/{export.firma_id}/{export.perioada_contabila_id}/{export.pk}.zip"
        with tempfile.TemporaryDirectory(prefix="conta-saga-export-") as folder:
            cale_zip = Path(folder) / "export.zip"
            numar_fisiere = _construieste_zip(
                perioada_id=export.perioada_contabila_id,
                destinatie=cale_zip,
            )
            storage.put_file(storage_key, cale_zip, "application/zip")

        with transaction.atomic(using="privileged"):
            export = (
                Export.objects.using("privileged")
                .select_for_update()
                .select_related("perioada_contabila__firma", "solicitat_de")
                .get(pk=export_id)
            )
            if export.status != Export.Status.IN_LUCRU:
                storage.delete(storage_key)
                return export
            if export.perioada_contabila.stare != PerioadaContabila.Stare.INCHISA:
                raise EroareExport("Perioada a fost redeschisă în timpul generării exportului.")
            export.status = Export.Status.FINALIZAT
            export.storage_key = storage_key
            export.expira_la = timezone.now() + timedelta(days=ZILE_VALABILITATE)
            export.eroare = None
            export.save(
                using="privileged",
                update_fields=["status", "storage_key", "expira_la", "eroare"],
            )
            AuditLog.objects.using("privileged").create(
                firma_id=export.firma_id,
                utilizator_id=export.solicitat_de_id,
                entitate_tip="export",
                entitate_id=export.pk,
                actiune="export_finalizat",
                date_noi={"numar_fisiere": numar_fisiere},
            )
            notifica_export_finalizat(export=export, numar_fisiere=numar_fisiere)
        return export
    except Exception as exc:
        logger.exception("Exportul %s nu a putut fi generat", export_id)
        if storage_key:
            try:
                storage.delete(storage_key)
            except Exception:
                logger.exception(
                    "Obiectul incomplet al exportului %s nu a putut fi șters",
                    export_id,
                )
        with transaction.atomic(using="privileged"):
            export = Export.objects.using("privileged").select_for_update().get(pk=export_id)
            if export.status == Export.Status.IN_LUCRU:
                export.status = Export.Status.EROARE
                export.storage_key = None
                export.expira_la = None
                export.eroare = str(exc)[:2000] or "Exportul nu a putut fi generat."
                export.save(
                    using="privileged",
                    update_fields=["status", "storage_key", "expira_la", "eroare"],
                )
        return export
    finally:
        _elibereaza_blocare(export_id)


def expira_export(export_id) -> Export:
    storage = get_document_storage()
    with transaction.atomic(using="privileged"):
        export = Export.objects.using("privileged").select_for_update().get(pk=export_id)
        if (
            export.status == Export.Status.FINALIZAT
            and export.expira_la
            and export.expira_la <= timezone.now()
        ):
            storage_key = export.storage_key
            if storage_key:
                storage.delete(storage_key)
            export.status = Export.Status.EXPIRAT
            export.storage_key = None
            export.eroare = None
            export.save(
                using="privileged",
                update_fields=["status", "storage_key", "eroare"],
            )
        return export
