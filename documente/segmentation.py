import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import fitz
from django.db import transaction
from django.utils import timezone

from core.audit import ContextAudit
from core.models import IstoricStare
from firme.models import ContFinanciar, TipDocument
from perioade.models import PerioadaContabila

from .classification import (
    EroareClasificareInbox,
    _actualizeaza_checklist,
    _audit,
    _contabil_cu_acces,
    _valideaza_tip_si_cont,
)
from .extraction import creeaza_extractie_din_analiza
from .models import (
    AnalizaFisierInbox,
    DerivareFisierInbox,
    Document,
    FisierDocument,
    FisierInbox,
    IntentieUpload,
)
from .processing import proceseaza_fisier
from .storage import EroareStorage, get_document_storage


@dataclass(frozen=True)
class SegmentDocument:
    pagina_start: int
    pagina_sfarsit: int
    tip_document_id: object
    cont_financiar_id: object | None
    directie: str
    observatii: str = ""


def _valideaza_acoperire(*, segmente: list[SegmentDocument], numar_pagini: int) -> None:
    if not segmente:
        raise EroareClasificareInbox("Definește cel puțin un document rezultat.")
    pagina_asteptata = 1
    for segment in segmente:
        if segment.pagina_start != pagina_asteptata:
            raise EroareClasificareInbox(
                "Intervalele trebuie să acopere toate paginile în ordine, fără goluri."
            )
        if not segment.pagina_start <= segment.pagina_sfarsit <= numar_pagini:
            raise EroareClasificareInbox("Un interval de pagini este invalid.")
        pagina_asteptata = segment.pagina_sfarsit + 1
    if pagina_asteptata != numar_pagini + 1:
        raise EroareClasificareInbox(
            "Intervalele trebuie să acopere inclusiv ultima pagină a originalului."
        )


def _extrage_segment(
    *, continut: bytes, mime_type: str, pagina_start: int, pagina_sfarsit: int
) -> tuple[bytes, str, str]:
    if mime_type != "application/pdf":
        if pagina_start != 1 or pagina_sfarsit != 1:
            raise EroareClasificareInbox("O imagine poate deveni un singur document.")
        return continut, mime_type, DerivareFisierInbox.Metoda.COPIE_INTEGRALA
    numar_pagini = _numar_pagini_pdf(continut)
    if pagina_start == 1 and pagina_sfarsit == numar_pagini:
        return continut, mime_type, DerivareFisierInbox.Metoda.COPIE_INTEGRALA
    try:
        with fitz.open(stream=continut, filetype="pdf") as sursa:
            rezultat = fitz.open()
            try:
                rezultat.insert_pdf(
                    sursa,
                    from_page=pagina_start - 1,
                    to_page=pagina_sfarsit - 1,
                )
                derivat = rezultat.tobytes(garbage=4, deflate=True)
            finally:
                rezultat.close()
    except (fitz.FileDataError, RuntimeError, ValueError) as exc:
        raise EroareClasificareInbox("PDF-ul nu a putut fi separat în pagini.") from exc
    return derivat, "application/pdf", DerivareFisierInbox.Metoda.EXTRAGERE_PAGINI


def _numar_pagini_pdf(continut: bytes) -> int:
    try:
        with fitz.open(stream=continut, filetype="pdf") as document:
            return document.page_count
    except (fitz.FileDataError, RuntimeError, ValueError) as exc:
        raise EroareClasificareInbox("PDF-ul nu a putut fi deschis.") from exc


def _nume_derivat(*, nume_original: str, start: int, sfarsit: int, total: int) -> str:
    path = Path(nume_original)
    extensie = path.suffix if path.suffix else ".pdf"
    baza = re.sub(r"[^\w.-]+", "-", path.stem, flags=re.UNICODE).strip("-.") or "document"
    if start == 1 and sfarsit == total:
        return f"{baza[:220]}{extensie}"[:255]
    return f"{baza[:205]}-pag-{start:03d}-{sfarsit:03d}{extensie}"[:255]


def separa_fisier_inbox(
    *,
    fisier_id,
    actor,
    segmente: list[SegmentDocument],
    context: ContextAudit,
) -> list[Document]:
    fisier_vizibil = FisierInbox.objects.select_related("analiza").get(pk=fisier_id)
    analiza_vizibila = fisier_vizibil.analiza
    if fisier_vizibil.status != FisierInbox.Status.DISPONIBIL:
        raise EroareClasificareInbox("Fișierul nu mai așteaptă clasificarea.")
    if analiza_vizibila.status_citire != AnalizaFisierInbox.StatusCitire.FINALIZATA:
        raise EroareClasificareInbox("Așteaptă finalizarea citirii paginilor.")
    numar_pagini = analiza_vizibila.numar_pagini or 0
    _valideaza_acoperire(segmente=segmente, numar_pagini=numar_pagini)
    if len(segmente) > 100:
        raise EroareClasificareInbox("Un original poate fi separat în cel mult 100 documente.")

    storage = get_document_storage()
    try:
        continut = storage.read_bytes(fisier_vizibil.storage_key)
    except EroareStorage as exc:
        raise EroareClasificareInbox("Originalul din inbox nu mai este disponibil.") from exc
    checksum_sursa = hashlib.sha256(continut).hexdigest()
    if checksum_sursa != fisier_vizibil.checksum:
        raise EroareClasificareInbox(
            "Originalul nu mai corespunde checksum-ului înregistrat în inbox."
        )

    pregatite = []
    for segment in segmente:
        derivat, mime_type, metoda = _extrage_segment(
            continut=continut,
            mime_type=fisier_vizibil.mime_type,
            pagina_start=segment.pagina_start,
            pagina_sfarsit=segment.pagina_sfarsit,
        )
        pregatite.append(
            (
                segment,
                derivat,
                mime_type,
                metoda,
                hashlib.sha256(derivat).hexdigest(),
            )
        )

    chei_scrise = []
    fisiere_document = []
    documente = []
    try:
        with transaction.atomic(using="privileged"):
            fisier = (
                FisierInbox.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(pk=fisier_id)
            )
            perioada = (
                PerioadaContabila.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(pk=fisier.perioada_contabila_id, firma_id=fisier.firma_id)
            )
            utilizator = _contabil_cu_acces(actor=actor, firma_id=fisier.firma_id)
            if fisier.status != FisierInbox.Status.DISPONIBIL:
                raise EroareClasificareInbox("Fișierul nu mai așteaptă clasificarea.")
            if perioada.stare in {
                PerioadaContabila.Stare.INCHIDERE_IN_CURS,
                PerioadaContabila.Stare.INCHISA,
            }:
                raise EroareClasificareInbox("Perioada contabilă este închisă.")
            analiza = (
                AnalizaFisierInbox.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(fisier_inbox_id=fisier.pk)
            )
            if analiza.status_revizuire != AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE:
                raise EroareClasificareInbox("Fișierul a fost deja revizuit.")

            for segment, derivat, mime_type, metoda, checksum_derivat in pregatite:
                if segment.directie not in {valoare for valoare, _ in Document.Directie.choices}:
                    raise EroareClasificareInbox("Selectează direcția fiecărui document.")
                tip = TipDocument.objects.using("privileged").get(
                    pk=segment.tip_document_id,
                    activ=True,
                )
                cont = None
                if segment.cont_financiar_id:
                    cont = ContFinanciar.objects.using("privileged").get(
                        pk=segment.cont_financiar_id,
                        firma_id=fisier.firma_id,
                        activ=True,
                    )
                _valideaza_tip_si_cont(
                    tip_document=tip,
                    cont_financiar=cont,
                    firma_id=fisier.firma_id,
                )
                observatii = segment.observatii.strip()
                if len(observatii) > 2000:
                    raise EroareClasificareInbox(
                        "Observațiile unui document pot avea cel mult 2.000 de caractere."
                    )
                nume = _nume_derivat(
                    nume_original=fisier.nume_original,
                    start=segment.pagina_start,
                    sfarsit=segment.pagina_sfarsit,
                    total=numar_pagini,
                )
                document = Document.objects.using("privileged").create(
                    firma_id=fisier.firma_id,
                    perioada_contabila_id=perioada.pk,
                    tip_document_id=tip.pk,
                    cont_financiar_id=cont.pk if cont else None,
                    incarcat_de_id=fisier.incarcat_de_id,
                    directie=segment.directie,
                    stare=Document.Stare.IN_VERIFICARE,
                    incarcat_dupa_confirmare=perioada.confirmata_de_client_la is not None,
                    note=(
                        f"Derivat din {fisier.nume_original}, paginile "
                        f"{segment.pagina_start}-{segment.pagina_sfarsit}."
                        + (f"\n{observatii}" if observatii else "")
                    ),
                )
                IstoricStare.objects.using("privileged").bulk_create(
                    [
                        IstoricStare(
                            firma_id=fisier.firma_id,
                            entitate_tip="document",
                            entitate_id=document.pk,
                            stare_veche=None,
                            stare_noua=Document.Stare.DRAFT,
                            utilizator_id=utilizator.pk,
                            comentariu=(
                                "Creat prin separarea unui original din inbox: "
                                f"paginile {segment.pagina_start}-{segment.pagina_sfarsit}."
                            ),
                        ),
                        IstoricStare(
                            firma_id=fisier.firma_id,
                            entitate_tip="document",
                            entitate_id=document.pk,
                            stare_veche=Document.Stare.DRAFT,
                            stare_noua=Document.Stare.TRIMIS,
                            utilizator_id=utilizator.pk,
                        ),
                        IstoricStare(
                            firma_id=fisier.firma_id,
                            entitate_tip="document",
                            entitate_id=document.pk,
                            stare_veche=Document.Stare.TRIMIS,
                            stare_noua=Document.Stare.IN_VERIFICARE,
                            utilizator_id=utilizator.pk,
                        ),
                    ]
                )
                intentie = IntentieUpload.objects.using("privileged").create(
                    firma_id=fisier.firma_id,
                    document_id=document.pk,
                    utilizator_id=fisier.incarcat_de_id,
                    nume_original=nume,
                )
                storage.put_bytes(intentie.storage_key, derivat, mime_type)
                chei_scrise.append(intentie.storage_key)
                fisier_document = FisierDocument.objects.using("privileged").create(
                    document_id=document.pk,
                    firma_id=fisier.firma_id,
                    upload_intentie_id=intentie.pk,
                    storage_key=intentie.storage_key,
                    nume_original=nume,
                    mime_type=mime_type,
                    dimensiune_bytes=len(derivat),
                    checksum=checksum_derivat,
                    numar_pagini=segment.pagina_sfarsit - segment.pagina_start + 1,
                    ordine=1,
                    versiune=1,
                    incarcat_de_id=fisier.incarcat_de_id,
                    activ=True,
                )
                intentie.folosita_la = timezone.now()
                intentie.save(using="privileged", update_fields=["folosita_la"])
                DerivareFisierInbox.objects.using("privileged").create(
                    analiza_id=analiza.pk,
                    fisier_inbox_id=fisier.pk,
                    fisier_document_id=fisier_document.pk,
                    document_id=document.pk,
                    firma_id=fisier.firma_id,
                    perioada_contabila_id=perioada.pk,
                    pagina_start=segment.pagina_start,
                    pagina_sfarsit=segment.pagina_sfarsit,
                    metoda=metoda,
                    checksum_sursa=checksum_sursa,
                    checksum_derivat=checksum_derivat,
                    creat_de_id=utilizator.pk,
                )
                sugestie_segment = next(
                    (
                        limita
                        for limita in analiza.limite_sugerate
                        if limita.get("pagina_start") == segment.pagina_start
                        and limita.get("pagina_sfarsit") == segment.pagina_sfarsit
                    ),
                    {},
                )
                creeaza_extractie_din_analiza(
                    analiza=analiza,
                    document=document,
                    fisier_document=fisier_document,
                    campuri=sugestie_segment.get("campuri_extrase") or {},
                    avertismente=sugestie_segment.get("avertismente_extragere") or [],
                    incredere=sugestie_segment.get("incredere"),
                )
                _actualizeaza_checklist(
                    perioada=perioada,
                    document=document,
                    actor=utilizator,
                    context=context,
                )
                documente.append(document)
                fisiere_document.append(fisier_document)

            analiza.status_revizuire = AnalizaFisierInbox.StatusRevizuire.SEGMENTATA
            analiza.revizuita_de_id = utilizator.pk
            analiza.revizuita_la = timezone.now()
            analiza.observatii_revizuire = (
                f"Separare confirmată manual: {len(documente)} document(e)."
            )
            analiza.procesare_inceputa_la = None
            if analiza.status == AnalizaFisierInbox.Status.IN_LUCRU:
                analiza.status = AnalizaFisierInbox.Status.EROARE
                analiza.eroare = "Analiza a fost oprită după confirmarea separării."
            analiza.save(
                using="privileged",
                update_fields=[
                    "status",
                    "status_revizuire",
                    "revizuita_de",
                    "revizuita_la",
                    "observatii_revizuire",
                    "procesare_inceputa_la",
                    "eroare",
                ],
            )
            fisier.status = FisierInbox.Status.CLASIFICAT
            fisier.save(using="privileged", update_fields=["status"])
            _audit(
                using="privileged",
                fisier=fisier,
                actor=utilizator,
                actiune="fisier_inbox_segmentat",
                context=context,
                date_noi={
                    "analiza_id": str(analiza.pk),
                    "documente": [
                        {
                            "document_id": str(document.pk),
                            "pagina_start": segment.pagina_start,
                            "pagina_sfarsit": segment.pagina_sfarsit,
                        }
                        for document, segment in zip(documente, segmente, strict=True)
                    ],
                },
            )
    except Exception:
        for cheie in chei_scrise:
            storage.delete(cheie)
        raise

    for fisier_document in fisiere_document:
        proceseaza_fisier(fisier_document.pk, reincearca=True)
    return documente
