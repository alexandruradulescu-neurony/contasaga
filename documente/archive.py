import csv
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from conturi.models import Utilizator
from core.audit import ContextAudit
from core.models import AuditLog, IstoricStare
from notificari.services import notifica_perioada_inchisa
from perioade.models import PerioadaContabila

from .models import (
    ArhivaLunara,
    Document,
    ExtractieStructurataDocument,
    FisierArhivaLunara,
    FisierDocument,
)
from .storage import EroareStorage, get_document_storage
from .storage_keys import prefix_arhiva_finala, prefix_arhiva_staging

LEASE_ARHIVA = timedelta(minutes=30)
MAX_INCERCARI_ARHIVA = 3


class EroareArhivaLunara(Exception):
    pass


@dataclass(frozen=True)
class FisierPregatit:
    ordine: int
    document_id: object
    fisier_document_id: object
    categorie: str
    cale_relativa: str
    storage_key_sursa: str
    storage_key_staging: str
    storage_key_final: str
    nume_original: str
    mime_type: str
    checksum: str
    dimensiune: int
    tip_document: str
    directie: str
    data_document: str
    partener: str
    serie: str
    numar: str


def _slug(valoare: str, *, fallback: str, limita: int) -> str:
    normalizat = unicodedata.normalize("NFKD", valoare or "").encode("ascii", "ignore").decode()
    normalizat = re.sub(r"[^A-Za-z0-9._-]+", "-", normalizat).strip("-._").lower()
    return (normalizat or fallback)[:limita]


def _nume_arhiva(*, document, fisier, ordine: int) -> str:
    extensie = _slug(Path(fisier.nume_original or "").suffix.lstrip("."), fallback="bin", limita=10)
    parti = []
    if document.data_document:
        parti.append(document.data_document.isoformat())
    if document.partener_id:
        parti.append(_slug(document.partener.denumire, fallback="partener", limita=60))
    identificator = "-".join(filter(None, (document.serie, document.numar)))
    if identificator:
        parti.append(_slug(identificator, fallback="document", limita=50))
    if not parti:
        parti.append(
            _slug(Path(fisier.nume_original or "document").stem, fallback="document", limita=120)
        )
    baza = "__".join(parti)[:190]
    return f"{ordine:04d}__{baza}__{str(fisier.pk)[:8]}.{extensie}"


def _categorie(document) -> str:
    directie = {
        Document.Directie.PRIMIT: "primite",
        Document.Directie.EMIS: "emise",
    }.get(document.directie, "fara-directie")
    tip = _slug(document.tip_document.cod, fallback="alte-documente", limita=80)
    return f"{directie}/{tip}"


def programeaza_arhiva_lunara(*, perioada, actor, context: ContextAudit) -> ArhivaLunara:
    try:
        with transaction.atomic(using="privileged"):
            existenta = (
                ArhivaLunara.objects.using("privileged")
                .select_for_update(of=("self",))
                .filter(
                    perioada_contabila_id=perioada.pk,
                    status__in=(
                        ArhivaLunara.Status.IN_ASTEPTARE,
                        ArhivaLunara.Status.IN_LUCRU,
                    ),
                )
                .first()
            )
            if existenta:
                return existenta
            ultima = (
                ArhivaLunara.objects.using("privileged")
                .filter(perioada_contabila_id=perioada.pk)
                .aggregate(maxima=Max("versiune"))["maxima"]
                or 0
            )
            versiune = ultima + 1
            return ArhivaLunara.objects.using("privileged").create(
                firma_id=perioada.firma_id,
                perioada_contabila_id=perioada.pk,
                versiune=versiune,
                prefix_staging=prefix_arhiva_staging(
                    firma_id=perioada.firma_id,
                    an=perioada.an,
                    luna=perioada.luna,
                    versiune=versiune,
                ),
                prefix_final=prefix_arhiva_finala(
                    firma_id=perioada.firma_id,
                    an=perioada.an,
                    luna=perioada.luna,
                    versiune=versiune,
                ),
                solicitata_de_id=actor.pk,
                audit_ip=context.ip_address,
                audit_user_agent=(context.user_agent or "")[:255] or None,
            )
    except IntegrityError as exc:
        raise EroareArhivaLunara("Există deja o arhivă activă pentru această perioadă.") from exc


def _poate_fi_preluata(arhiva, *, moment) -> bool:
    if arhiva.incercari >= MAX_INCERCARI_ARHIVA:
        return False
    if arhiva.status == ArhivaLunara.Status.IN_LUCRU:
        return bool(
            arhiva.procesare_inceputa_la and arhiva.procesare_inceputa_la <= moment - LEASE_ARHIVA
        )
    return bool(
        arhiva.status in {ArhivaLunara.Status.IN_ASTEPTARE, ArhivaLunara.Status.EROARE}
        and arhiva.reincearca_dupa <= moment
    )


def _plan_fisiere(arhiva) -> list[FisierPregatit]:
    documente = list(
        Document.objects.using("privileged")
        .filter(
            perioada_contabila_id=arhiva.perioada_contabila_id,
            stare__in=(Document.Stare.PROCESAT, Document.Stare.ARHIVAT),
            sters_la__isnull=True,
        )
        .select_related("tip_document", "partener")
        .order_by("tip_document__cod", "directie", "data_document", "id")
    )
    if (
        ExtractieStructurataDocument.objects.using("privileged")
        .filter(
            perioada_contabila_id=arhiva.perioada_contabila_id,
            document__in=documente,
            status_revizuire=ExtractieStructurataDocument.StatusRevizuire.IN_ASTEPTARE,
        )
        .exists()
    ):
        raise EroareArhivaLunara(
            "Există extrageri structurate care nu au fost revizuite de contabil."
        )
    pregatite = []
    ordine = 0
    for document in documente:
        fisiere = list(
            FisierDocument.objects.using("privileged")
            .filter(document_id=document.pk, activ=True, sters_la__isnull=True)
            .order_by("ordine", "versiune", "id")
        )
        if not fisiere:
            raise EroareArhivaLunara("Un document procesat nu are niciun fișier activ.")
        for fisier in fisiere:
            if (
                fisier.stare_procesare != FisierDocument.StareProcesare.PROCESAT
                or not fisier.checksum
                or fisier.dimensiune_bytes is None
            ):
                raise EroareArhivaLunara("Un fișier nu este procesat complet pentru arhivare.")
            ordine += 1
            categorie = _categorie(document)
            nume = _nume_arhiva(document=document, fisier=fisier, ordine=ordine)
            cale = f"{categorie}/{nume}"
            pregatite.append(
                FisierPregatit(
                    ordine=ordine,
                    document_id=document.pk,
                    fisier_document_id=fisier.pk,
                    categorie=categorie,
                    cale_relativa=cale,
                    storage_key_sursa=fisier.storage_key,
                    storage_key_staging=f"{arhiva.prefix_staging}/{cale}",
                    storage_key_final=f"{arhiva.prefix_final}/{cale}",
                    nume_original=fisier.nume_original or str(fisier.pk),
                    mime_type=fisier.mime_type or "application/octet-stream",
                    checksum=fisier.checksum,
                    dimensiune=fisier.dimensiune_bytes,
                    tip_document=document.tip_document.cod,
                    directie=document.directie or "",
                    data_document=(
                        document.data_document.isoformat() if document.data_document else ""
                    ),
                    partener=(document.partener.denumire if document.partener_id else ""),
                    serie=document.serie or "",
                    numar=document.numar or "",
                )
            )
    return pregatite


def _csv_sigur(valoare) -> str:
    text = str(valoare or "")
    potentiala_formula = text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
    return f"'{text}" if potentiala_formula else text


def _manifest(arhiva, fisiere: list[FisierPregatit]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "archive_version",
            "sequence",
            "document_id",
            "file_id",
            "category",
            "relative_path",
            "original_name",
            "document_type",
            "direction",
            "document_date",
            "partner",
            "series",
            "number",
            "mime_type",
            "size_bytes",
            "source_sha256",
            "archive_sha256",
        ]
    )
    for fisier in fisiere:
        writer.writerow(
            [
                arhiva.versiune,
                fisier.ordine,
                fisier.document_id,
                fisier.fisier_document_id,
                fisier.categorie,
                fisier.cale_relativa,
                _csv_sigur(fisier.nume_original),
                fisier.tip_document,
                fisier.directie,
                fisier.data_document,
                _csv_sigur(fisier.partener),
                _csv_sigur(fisier.serie),
                _csv_sigur(fisier.numar),
                fisier.mime_type,
                fisier.dimensiune,
                fisier.checksum,
                fisier.checksum,
            ]
        )
    return output.getvalue().encode("utf-8-sig")


def _sterge_chei(storage, chei):
    for cheie in dict.fromkeys(chei):
        try:
            storage.delete(cheie)
        except EroareStorage:
            pass


def _salveaza_eroare(*, arhiva_id, incercare, exc, chei_curatare):
    with transaction.atomic(using="privileged"):
        arhiva = (
            ArhivaLunara.objects.using("privileged")
            .select_for_update(of=("self",))
            .select_related("perioada_contabila")
            .get(pk=arhiva_id)
        )
        if arhiva.status != ArhivaLunara.Status.IN_LUCRU or arhiva.incercari != incercare:
            return arhiva
        arhiva.status = ArhivaLunara.Status.EROARE
        arhiva.procesare_inceputa_la = None
        arhiva.eroare = str(exc)[:2000]
        arhiva.reincearca_dupa = timezone.now() + timedelta(minutes=5**arhiva.incercari)
        arhiva.save(
            using="privileged",
            update_fields=[
                "status",
                "procesare_inceputa_la",
                "eroare",
                "reincearca_dupa",
            ],
        )
        if arhiva.incercari >= MAX_INCERCARI_ARHIVA:
            perioada = arhiva.perioada_contabila
            if perioada.stare == PerioadaContabila.Stare.INCHIDERE_IN_CURS:
                perioada.stare = PerioadaContabila.Stare.IN_LUCRU
                perioada.save(using="privileged", update_fields=["stare"])
                IstoricStare.objects.using("privileged").create(
                    firma_id=perioada.firma_id,
                    entitate_tip="perioada",
                    entitate_id=perioada.pk,
                    stare_veche=PerioadaContabila.Stare.INCHIDERE_IN_CURS,
                    stare_noua=PerioadaContabila.Stare.IN_LUCRU,
                    utilizator_id=arhiva.solicitata_de_id,
                    comentariu="Închiderea a fost anulată după eșecul arhivei lunare.",
                )
                AuditLog.objects.using("privileged").create(
                    firma_id=perioada.firma_id,
                    utilizator_id=arhiva.solicitata_de_id,
                    entitate_tip="perioada",
                    entitate_id=perioada.pk,
                    actiune="arhivare_lunara_esuata",
                    date_noi={
                        "arhiva_id": str(arhiva.pk),
                        "incercari": arhiva.incercari,
                        "eroare": str(exc)[:500],
                    },
                    ip_address=arhiva.audit_ip,
                    user_agent=arhiva.audit_user_agent,
                )
    storage = get_document_storage()
    _sterge_chei(storage, chei_curatare)
    for prefix in (arhiva.prefix_staging, arhiva.prefix_final):
        try:
            storage.delete_prefix(prefix)
        except EroareStorage:
            pass
    return arhiva


def proceseaza_arhiva_lunara(arhiva_id):
    moment = timezone.now()
    incercare_epuizata = None
    with transaction.atomic(using="privileged"):
        arhiva = (
            ArhivaLunara.objects.using("privileged")
            .select_for_update(of=("self",))
            .select_related("perioada_contabila", "perioada_contabila__firma")
            .get(pk=arhiva_id)
        )
        if (
            arhiva.status == ArhivaLunara.Status.IN_LUCRU
            and arhiva.procesare_inceputa_la
            and arhiva.procesare_inceputa_la <= moment - LEASE_ARHIVA
            and arhiva.incercari >= MAX_INCERCARI_ARHIVA
        ):
            incercare_epuizata = arhiva.incercari
        elif not _poate_fi_preluata(arhiva, moment=moment):
            return arhiva
        elif arhiva.perioada_contabila.stare != PerioadaContabila.Stare.INCHIDERE_IN_CURS:
            arhiva.status = ArhivaLunara.Status.ANULATA
            arhiva.eroare = "Perioada nu mai este în curs de închidere."
            arhiva.save(using="privileged", update_fields=["status", "eroare"])
            return arhiva
        else:
            arhiva.status = ArhivaLunara.Status.IN_LUCRU
            arhiva.incercari += 1
            arhiva.procesare_inceputa_la = moment
            arhiva.eroare = None
            arhiva.save(
                using="privileged",
                update_fields=["status", "incercari", "procesare_inceputa_la", "eroare"],
            )
            incercare_curenta = arhiva.incercari

    if incercare_epuizata is not None:
        return _salveaza_eroare(
            arhiva_id=arhiva_id,
            incercare=incercare_epuizata,
            exc=EroareArhivaLunara(
                "Procesarea ultimei încercări a fost întreruptă înainte de finalizare."
            ),
            chei_curatare=[],
        )

    storage = get_document_storage()
    chei_curatare = []
    try:
        fisiere = _plan_fisiere(arhiva)
        manifest = _manifest(arhiva, fisiere)
        manifest_checksum = hashlib.sha256(manifest).hexdigest()
        staging_manifest = f"{arhiva.prefix_staging}/.system/manifest.csv"
        final_manifest = f"{arhiva.prefix_final}/.system/manifest.csv"
        chei_curatare = [
            *(fisier.storage_key_staging for fisier in fisiere),
            staging_manifest,
            *(fisier.storage_key_final for fisier in fisiere),
            final_manifest,
        ]
        for fisier in fisiere:
            continut = storage.read_bytes(fisier.storage_key_sursa)
            if len(continut) != fisier.dimensiune or hashlib.sha256(continut).hexdigest() != (
                fisier.checksum
            ):
                raise EroareArhivaLunara("Checksum-ul unui fișier sursă nu mai corespunde.")
            storage.put_archive_bytes(fisier.storage_key_staging, continut, fisier.mime_type)
            verificare = storage.read_bytes(fisier.storage_key_staging)
            if hashlib.sha256(verificare).hexdigest() != fisier.checksum:
                raise EroareArhivaLunara("Verificarea copiei de staging a eșuat.")
        storage.put_archive_bytes(staging_manifest, manifest, "text/csv")
        if hashlib.sha256(storage.read_bytes(staging_manifest)).hexdigest() != manifest_checksum:
            raise EroareArhivaLunara("Manifestul de staging nu a trecut verificarea.")

        for fisier in fisiere:
            continut = storage.read_bytes(fisier.storage_key_staging)
            storage.put_archive_bytes(fisier.storage_key_final, continut, fisier.mime_type)
            if hashlib.sha256(storage.read_bytes(fisier.storage_key_final)).hexdigest() != (
                fisier.checksum
            ):
                raise EroareArhivaLunara("Verificarea copiei finale a eșuat.")
        storage.put_archive_bytes(final_manifest, manifest, "text/csv")
        if hashlib.sha256(storage.read_bytes(final_manifest)).hexdigest() != manifest_checksum:
            raise EroareArhivaLunara("Manifestul final nu a trecut verificarea.")

        with transaction.atomic(using="privileged"):
            arhiva = (
                ArhivaLunara.objects.using("privileged")
                .select_for_update(of=("self",))
                .select_related("perioada_contabila", "perioada_contabila__firma")
                .get(pk=arhiva_id)
            )
            if (
                arhiva.status != ArhivaLunara.Status.IN_LUCRU
                or arhiva.incercari != incercare_curenta
            ):
                return arhiva
            perioada = (
                PerioadaContabila.objects.using("privileged")
                .select_for_update(of=("self",))
                .select_related("firma")
                .get(pk=arhiva.perioada_contabila_id)
            )
            if perioada.stare != PerioadaContabila.Stare.INCHIDERE_IN_CURS:
                raise EroareArhivaLunara("Perioada nu mai poate fi finalizată.")
            FisierArhivaLunara.objects.using("privileged").bulk_create(
                [
                    FisierArhivaLunara(
                        arhiva_id=arhiva.pk,
                        document_id=fisier.document_id,
                        fisier_document_id=fisier.fisier_document_id,
                        firma_id=arhiva.firma_id,
                        perioada_contabila_id=arhiva.perioada_contabila_id,
                        ordine=fisier.ordine,
                        categorie=fisier.categorie,
                        cale_relativa=fisier.cale_relativa,
                        storage_key_sursa=fisier.storage_key_sursa,
                        storage_key_arhiva=fisier.storage_key_final,
                        nume_original=fisier.nume_original,
                        mime_type=fisier.mime_type,
                        checksum_sursa=fisier.checksum,
                        checksum_arhiva=fisier.checksum,
                        dimensiune_bytes=fisier.dimensiune,
                    )
                    for fisier in fisiere
                ]
            )
            documente = list(
                Document.objects.using("privileged")
                .select_for_update(of=("self",))
                .filter(
                    perioada_contabila_id=perioada.pk,
                    stare=Document.Stare.PROCESAT,
                    sters_la__isnull=True,
                )
            )
            for document in documente:
                document.stare = Document.Stare.ARHIVAT
                document.save(using="privileged", update_fields=["stare"])
                IstoricStare.objects.using("privileged").create(
                    firma_id=document.firma_id,
                    entitate_tip="document",
                    entitate_id=document.pk,
                    stare_veche=Document.Stare.PROCESAT,
                    stare_noua=Document.Stare.ARHIVAT,
                    utilizator_id=arhiva.solicitata_de_id,
                )
                AuditLog.objects.using("privileged").create(
                    firma_id=document.firma_id,
                    utilizator_id=arhiva.solicitata_de_id,
                    entitate_tip="document",
                    entitate_id=document.pk,
                    actiune="document_arhivat",
                    date_vechi={"stare": Document.Stare.PROCESAT},
                    date_noi={
                        "stare": Document.Stare.ARHIVAT,
                        "arhiva_id": str(arhiva.pk),
                        "versiune": arhiva.versiune,
                    },
                    ip_address=arhiva.audit_ip,
                    user_agent=arhiva.audit_user_agent,
                )
            ArhivaLunara.objects.using("privileged").filter(
                perioada_contabila_id=perioada.pk,
                status=ArhivaLunara.Status.FINALIZATA,
            ).exclude(pk=arhiva.pk).update(status=ArhivaLunara.Status.INLOCUITA)
            arhiva.status = ArhivaLunara.Status.FINALIZATA
            arhiva.procesare_inceputa_la = None
            arhiva.finalizata_la = timezone.now()
            arhiva.eroare = None
            arhiva.manifest_storage_key = final_manifest
            arhiva.manifest_checksum = manifest_checksum
            arhiva.numar_fisiere = len(fisiere)
            arhiva.dimensiune_totala = sum(fisier.dimensiune for fisier in fisiere)
            arhiva.save(
                using="privileged",
                update_fields=[
                    "status",
                    "procesare_inceputa_la",
                    "finalizata_la",
                    "eroare",
                    "manifest_storage_key",
                    "manifest_checksum",
                    "numar_fisiere",
                    "dimensiune_totala",
                ],
            )
            perioada.stare = PerioadaContabila.Stare.INCHISA
            perioada.inchisa_la = timezone.now()
            perioada.inchisa_de_id = arhiva.solicitata_de_id
            perioada.save(
                using="privileged",
                update_fields=["stare", "inchisa_la", "inchisa_de"],
            )
            istoric = IstoricStare.objects.using("privileged").create(
                firma_id=perioada.firma_id,
                entitate_tip="perioada",
                entitate_id=perioada.pk,
                stare_veche=PerioadaContabila.Stare.INCHIDERE_IN_CURS,
                stare_noua=PerioadaContabila.Stare.INCHISA,
                utilizator_id=arhiva.solicitata_de_id,
                comentariu=f"Arhiva lunară v{arhiva.versiune} verificată și publicată.",
            )
            AuditLog.objects.using("privileged").create(
                firma_id=perioada.firma_id,
                utilizator_id=arhiva.solicitata_de_id,
                entitate_tip="perioada",
                entitate_id=perioada.pk,
                actiune="perioada_inchisa",
                date_noi={
                    "stare": PerioadaContabila.Stare.INCHISA,
                    "arhiva_id": str(arhiva.pk),
                    "versiune": arhiva.versiune,
                    "manifest_checksum": manifest_checksum,
                },
                ip_address=arhiva.audit_ip,
                user_agent=arhiva.audit_user_agent,
            )
            actor = Utilizator.objects.using("privileged").get(pk=arhiva.solicitata_de_id)
            notifica_perioada_inchisa(
                perioada=perioada,
                actor=actor,
                eveniment_id=istoric.pk,
                using="privileged",
            )
        try:
            storage.delete_prefix(arhiva.prefix_staging)
        except EroareStorage:
            pass
        return arhiva
    except (EroareArhivaLunara, EroareStorage, DatabaseError, OSError, ValueError) as exc:
        return _salveaza_eroare(
            arhiva_id=arhiva_id,
            incercare=incercare_curenta,
            exc=exc,
            chei_curatare=chei_curatare,
        )


def proceseaza_coada_arhive(*, limit: int = 5) -> tuple[int, int]:
    moment = timezone.now()
    ids = list(
        ArhivaLunara.objects.using("privileged")
        .filter(
            Q(
                status__in=(ArhivaLunara.Status.IN_ASTEPTARE, ArhivaLunara.Status.EROARE),
                reincearca_dupa__lte=moment,
                incercari__lt=MAX_INCERCARI_ARHIVA,
            )
            | Q(
                status=ArhivaLunara.Status.IN_LUCRU,
                procesare_inceputa_la__lte=moment - LEASE_ARHIVA,
            )
        )
        .order_by("creat_la")
        .values_list("pk", flat=True)[:limit]
    )
    finalizate = erori = 0
    for arhiva_id in ids:
        arhiva = proceseaza_arhiva_lunara(arhiva_id)
        if arhiva.status == ArhivaLunara.Status.FINALIZATA:
            finalizate += 1
        elif arhiva.status == ArhivaLunara.Status.EROARE:
            erori += 1
    return finalizate, erori
