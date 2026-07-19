import hashlib
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import IstoricStare
from firme.models import ConfigurareDocumentFirma, ContFinanciar, Partener, TipDocument

from .ai import ContextAnalizaDocument, EroareAnalizaAI, PaginaTextAnaliza, construieste_provider
from .ai.contracts import ContFinanciarPermis, TipDocumentPermis
from .ai.providers import VERSIUNE_PROMPT
from .models import Document, ExtractieStructurataDocument, FisierDocument
from .reading import EroareCitireDocument, citeste_continut
from .storage import EroareStorage, get_document_storage

LEASE_EXTRAGERE = timedelta(minutes=15)
MAX_INCERCARI_EXTRAGERE = 3


class EroareRevizuireExtractie(Exception):
    pass


def _fisiere_active(document_id, *, using="privileged"):
    return list(
        FisierDocument.objects.using(using)
        .filter(
            document_id=document_id,
            activ=True,
            sters_la__isnull=True,
            stare_procesare=FisierDocument.StareProcesare.PROCESAT,
        )
        .order_by("ordine", "versiune", "incarcat_la")
    )


def _amprenta_fisiere(fisiere) -> str:
    digest = hashlib.sha256()
    for fisier in fisiere:
        digest.update(str(fisier.pk).encode())
        digest.update(b":")
        digest.update((fisier.checksum or "").encode())
        digest.update(b"\n")
    return digest.hexdigest()


def asigura_extrageri_pentru_documente(*, limit: int = 1000) -> int:
    if not settings.DOCUMENT_AI_ENABLED:
        return 0
    documente = list(
        Document.objects.using("privileged")
        .filter(stare=Document.Stare.IN_VERIFICARE, sters_la__isnull=True)
        .order_by("creat_la")[:limit]
    )
    create = []
    for document in documente:
        fisiere = _fisiere_active(document.pk)
        if not fisiere:
            continue
        amprenta = _amprenta_fisiere(fisiere)
        if (
            ExtractieStructurataDocument.objects.using("privileged")
            .filter(
                document_id=document.pk,
                checksum_sursa=amprenta,
            )
            .exists()
        ):
            continue
        create.append(
            ExtractieStructurataDocument(
                document_id=document.pk,
                fisier_document_id=fisiere[0].pk,
                firma_id=document.firma_id,
                perioada_contabila_id=document.perioada_contabila_id,
                checksum_sursa=amprenta,
                fisiere_sursa=[str(fisier.pk) for fisier in fisiere],
            )
        )
    if create:
        ExtractieStructurataDocument.objects.using("privileged").bulk_create(
            create,
            ignore_conflicts=True,
        )
    return len(create)


def creeaza_extractie_din_analiza(
    *,
    analiza,
    document,
    fisier_document,
    campuri: dict,
    avertismente: list[str],
    incredere,
):
    if not campuri:
        return None
    return ExtractieStructurataDocument.objects.using("privileged").create(
        document_id=document.pk,
        fisier_document_id=fisier_document.pk,
        firma_id=document.firma_id,
        perioada_contabila_id=document.perioada_contabila_id,
        status=ExtractieStructurataDocument.Status.FINALIZATA,
        provider=analiza.provider,
        model=analiza.model,
        versiune_prompt=analiza.versiune_prompt or VERSIUNE_PROMPT,
        finalizata_la=analiza.finalizata_la or timezone.now(),
        checksum_sursa=_amprenta_fisiere([fisier_document]),
        fisiere_sursa=[str(fisier_document.pk)],
        campuri_sugerate=campuri,
        avertismente=avertismente,
        incredere=incredere,
        raspuns_provider_id=analiza.raspuns_provider_id,
        tokeni_intrare=analiza.tokeni_intrare,
        tokeni_iesire=analiza.tokeni_iesire,
    )


def _context_extractie(extractie) -> ContextAnalizaDocument:
    document = extractie.document
    fisiere = _fisiere_active(document.pk)
    if (
        not fisiere
        or _amprenta_fisiere(fisiere) != extractie.checksum_sursa
        or [str(fisier.pk) for fisier in fisiere] != extractie.fisiere_sursa
    ):
        raise EroareAnalizaAI("Versiunea sursă a documentului s-a schimbat.")

    storage = get_document_storage()
    pagini = []
    continut_principal = None
    mime_principal = None
    nume = []
    numar_pagina = 1
    for fisier in fisiere:
        try:
            continut = storage.read_bytes(fisier.storage_key)
        except EroareStorage as exc:
            raise EroareAnalizaAI("Un fișier sursă nu mai este disponibil.") from exc
        if hashlib.sha256(continut).hexdigest() != fisier.checksum:
            raise EroareAnalizaAI("Un fișier sursă nu mai corespunde checksum-ului salvat.")
        if continut_principal is None:
            continut_principal = continut
            mime_principal = fisier.mime_type or "application/octet-stream"
        nume.append(fisier.nume_original or str(fisier.pk))
        try:
            citite = citeste_continut(
                continut=continut,
                mime_type=fisier.mime_type or "application/octet-stream",
            )
        except EroareCitireDocument as exc:
            raise EroareAnalizaAI(str(exc)) from exc
        for pagina in citite:
            pagini.append(PaginaTextAnaliza(numar=numar_pagina, text=pagina.text))
            numar_pagina += 1

    configurate = list(
        ConfigurareDocumentFirma.objects.using("privileged")
        .filter(firma_id=document.firma_id, activ=True, tip_document__activ=True)
        .select_related("tip_document")
        .order_by("tip_document__denumire")
    )
    tipuri = (
        [configurare.tip_document for configurare in configurate]
        if configurate
        else list(TipDocument.objects.using("privileged").filter(activ=True))
    )
    conturi = list(
        ContFinanciar.objects.using("privileged")
        .filter(firma_id=document.firma_id, activ=True)
        .order_by("denumire")
    )
    return ContextAnalizaDocument(
        nume_fisier=", ".join(nume)[:255],
        mime_type=mime_principal,
        continut=continut_principal,
        denumire_firma=document.firma.denumire,
        cui_firma=document.firma.cui,
        tipuri_document=tuple(
            TipDocumentPermis(
                id=str(tip.pk),
                cod=tip.cod,
                denumire=tip.denumire,
                necesita_cont_financiar=tip.necesita_cont_financiar,
            )
            for tip in tipuri
        ),
        conturi_financiare=tuple(
            ContFinanciarPermis(
                id=str(cont.pk),
                denumire=cont.denumire,
                tip=cont.tip,
                moneda=cont.moneda,
            )
            for cont in conturi
        ),
        pagini_text=tuple(pagini),
    )


def _poate_fi_preluata(extractie, *, moment) -> bool:
    if extractie.status_revizuire != ExtractieStructurataDocument.StatusRevizuire.IN_ASTEPTARE:
        return False
    if extractie.incercari >= MAX_INCERCARI_EXTRAGERE:
        return False
    if extractie.status == ExtractieStructurataDocument.Status.IN_LUCRU:
        return bool(
            extractie.procesare_inceputa_la
            and extractie.procesare_inceputa_la <= moment - LEASE_EXTRAGERE
        )
    return bool(
        extractie.status
        in {
            ExtractieStructurataDocument.Status.IN_ASTEPTARE,
            ExtractieStructurataDocument.Status.EROARE,
        }
        and extractie.reincearca_dupa <= moment
    )


def proceseaza_extractie(extractie_id, *, provider=None):
    moment = timezone.now()
    with transaction.atomic(using="privileged"):
        extractie = (
            ExtractieStructurataDocument.objects.using("privileged")
            .select_for_update(of=("self",))
            .select_related("document", "document__firma")
            .get(pk=extractie_id)
        )
        if (
            extractie.status == ExtractieStructurataDocument.Status.IN_LUCRU
            and extractie.procesare_inceputa_la
            and extractie.procesare_inceputa_la <= moment - LEASE_EXTRAGERE
            and extractie.incercari >= MAX_INCERCARI_EXTRAGERE
        ):
            extractie.status = ExtractieStructurataDocument.Status.EROARE
            extractie.procesare_inceputa_la = None
            extractie.eroare = (
                "Procesarea ultimei încercări a fost întreruptă înainte de finalizare."
            )
            extractie.save(
                using="privileged",
                update_fields=["status", "procesare_inceputa_la", "eroare"],
            )
            return extractie
        if not _poate_fi_preluata(extractie, moment=moment):
            return extractie
        if extractie.document.stare != Document.Stare.IN_VERIFICARE:
            tranzitie = (
                IstoricStare.objects.using("privileged")
                .filter(
                    entitate_tip="document",
                    entitate_id=extractie.document_id,
                    stare_noua=extractie.document.stare,
                )
                .order_by("-creat_la")
                .first()
            )
            extractie.status_revizuire = ExtractieStructurataDocument.StatusRevizuire.MANUALA
            extractie.revizuita_la = moment
            extractie.revizuita_de_id = (
                tranzitie.utilizator_id if tranzitie else extractie.document.incarcat_de_id
            )
            extractie.campuri_finale = _campuri_document(extractie.document)
            extractie.save(
                using="privileged",
                update_fields=[
                    "status_revizuire",
                    "revizuita_la",
                    "revizuita_de",
                    "campuri_finale",
                ],
            )
            return extractie
        extractie.status = ExtractieStructurataDocument.Status.IN_LUCRU
        extractie.incercari += 1
        extractie.procesare_inceputa_la = moment
        extractie.eroare = None
        extractie.save(
            using="privileged",
            update_fields=["status", "incercari", "procesare_inceputa_la", "eroare"],
        )
        incercare_curenta = extractie.incercari

    provider = provider or construieste_provider()
    try:
        context = _context_extractie(extractie)
        rezultat = provider.analizeaza(context)
    except (EroareAnalizaAI, EroareStorage) as exc:
        with transaction.atomic(using="privileged"):
            extractie = (
                ExtractieStructurataDocument.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(pk=extractie_id)
            )
            if (
                extractie.status != ExtractieStructurataDocument.Status.IN_LUCRU
                or extractie.incercari != incercare_curenta
                or extractie.status_revizuire
                != ExtractieStructurataDocument.StatusRevizuire.IN_ASTEPTARE
            ):
                return extractie
            extractie.status = ExtractieStructurataDocument.Status.EROARE
            extractie.procesare_inceputa_la = None
            extractie.eroare = str(exc)[:2000]
            extractie.reincearca_dupa = timezone.now() + timedelta(minutes=5**extractie.incercari)
            extractie.save(
                using="privileged",
                update_fields=[
                    "status",
                    "procesare_inceputa_la",
                    "eroare",
                    "reincearca_dupa",
                ],
            )
        return extractie

    with transaction.atomic(using="privileged"):
        extractie = (
            ExtractieStructurataDocument.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=extractie_id)
        )
        if (
            extractie.status != ExtractieStructurataDocument.Status.IN_LUCRU
            or extractie.incercari != incercare_curenta
            or extractie.status_revizuire
            != ExtractieStructurataDocument.StatusRevizuire.IN_ASTEPTARE
        ):
            return extractie
        extractie.status = ExtractieStructurataDocument.Status.FINALIZATA
        extractie.provider = provider.nume
        extractie.model = provider.model
        extractie.versiune_prompt = VERSIUNE_PROMPT
        extractie.procesare_inceputa_la = None
        extractie.finalizata_la = timezone.now()
        extractie.eroare = None
        extractie.campuri_sugerate = {
            **rezultat.campuri_extrase,
            "direction": rezultat.directie,
        }
        extractie.avertismente = rezultat.avertismente_extragere
        extractie.incredere = Decimal(str(round(rezultat.incredere, 4)))
        extractie.raspuns_provider_id = rezultat.raspuns_provider_id
        extractie.tokeni_intrare = rezultat.tokeni_intrare
        extractie.tokeni_iesire = rezultat.tokeni_iesire
        extractie.save(
            using="privileged",
            update_fields=[
                "status",
                "provider",
                "model",
                "versiune_prompt",
                "procesare_inceputa_la",
                "finalizata_la",
                "eroare",
                "campuri_sugerate",
                "avertismente",
                "incredere",
                "raspuns_provider_id",
                "tokeni_intrare",
                "tokeni_iesire",
            ],
        )
        return extractie


def proceseaza_coada_extrageri(*, limit: int = 20) -> tuple[int, int]:
    if not settings.DOCUMENT_AI_ENABLED:
        return 0, 0
    provider = construieste_provider()
    moment = timezone.now()
    candidate = list(
        ExtractieStructurataDocument.objects.using("privileged")
        .filter(
            status_revizuire=ExtractieStructurataDocument.StatusRevizuire.IN_ASTEPTARE,
        )
        .filter(
            Q(
                status__in=(
                    ExtractieStructurataDocument.Status.IN_ASTEPTARE,
                    ExtractieStructurataDocument.Status.EROARE,
                ),
                reincearca_dupa__lte=moment,
                incercari__lt=MAX_INCERCARI_EXTRAGERE,
            )
            | Q(
                status=ExtractieStructurataDocument.Status.IN_LUCRU,
                procesare_inceputa_la__lte=moment - LEASE_EXTRAGERE,
            )
        )
        .order_by("creat_la")
        .values_list("pk", flat=True)[:limit]
    )
    finalizate = erori = 0
    for extractie_id in candidate:
        extractie = proceseaza_extractie(extractie_id, provider=provider)
        if extractie.status == ExtractieStructurataDocument.Status.FINALIZATA:
            finalizate += 1
        elif extractie.status == ExtractieStructurataDocument.Status.EROARE:
            erori += 1
    return finalizate, erori


def _campuri_document(document) -> dict:
    return {
        "partner_id": str(document.partener_id) if document.partener_id else None,
        "direction": document.directie,
        "series": document.serie,
        "number": document.numar,
        "document_date": document.data_document.isoformat() if document.data_document else None,
        "due_date": document.data_scadenta.isoformat() if document.data_scadenta else None,
        "currency": document.moneda,
        "net_amount": str(document.valoare_fara_tva)
        if document.valoare_fara_tva is not None
        else None,
        "vat_amount": str(document.valoare_tva) if document.valoare_tva is not None else None,
        "total_amount": str(document.valoare_totala)
        if document.valoare_totala is not None
        else None,
    }


def sugestii_pentru_document(document) -> tuple[ExtractieStructurataDocument | None, dict]:
    extractie = (
        ExtractieStructurataDocument.objects.filter(document_id=document.pk)
        .order_by("-creat_la")
        .first()
    )
    fisiere = _fisiere_active(document.pk, using="default")
    if (
        not extractie
        or extractie.status != ExtractieStructurataDocument.Status.FINALIZATA
        or not fisiere
        or _amprenta_fisiere(fisiere) != extractie.checksum_sursa
    ):
        return extractie, {}
    campuri = extractie.campuri_sugerate or {}
    directie = document.directie or campuri.get("direction")
    if directie not in {Document.Directie.PRIMIT, Document.Directie.EMIS}:
        directie = None
    cui_partener = (
        campuri.get("issuer_tax_id")
        if directie == Document.Directie.PRIMIT
        else campuri.get("recipient_tax_id")
    )
    partener = None
    if cui_partener:
        partener = Partener.objects.filter(
            firma_id=document.firma_id,
            cui__iexact=cui_partener,
            activ=True,
        ).first()
    return extractie, {
        "partener": partener.pk if partener else None,
        "directie": directie,
        "serie": campuri.get("series"),
        "numar": campuri.get("number"),
        "data_document": campuri.get("document_date"),
        "data_scadenta": campuri.get("due_date"),
        "moneda": campuri.get("currency") or "RON",
        "valoare_fara_tva": campuri.get("net_amount"),
        "valoare_tva": campuri.get("vat_amount"),
        "valoare_totala": campuri.get("total_amount"),
    }


def revizuieste_extractie(*, document, actor):
    extractie = (
        ExtractieStructurataDocument.objects.select_for_update(of=("self",))
        .filter(document_id=document.pk)
        .order_by("-creat_la")
        .first()
    )
    if not extractie or extractie.status_revizuire != (
        ExtractieStructurataDocument.StatusRevizuire.IN_ASTEPTARE
    ):
        return extractie
    fisiere = _fisiere_active(document.pk, using="default")
    if (
        not settings.DOCUMENT_AI_ENABLED
        or not fisiere
        or _amprenta_fisiere(fisiere) != extractie.checksum_sursa
    ):
        extractie.status_revizuire = ExtractieStructurataDocument.StatusRevizuire.MANUALA
        extractie.revizuita_de_id = actor.pk
        extractie.revizuita_la = timezone.now()
        extractie.campuri_finale = _campuri_document(document)
        extractie.save(
            update_fields=[
                "status_revizuire",
                "revizuita_de",
                "revizuita_la",
                "campuri_finale",
            ]
        )
        return extractie
    if extractie.status in {
        ExtractieStructurataDocument.Status.IN_ASTEPTARE,
        ExtractieStructurataDocument.Status.IN_LUCRU,
    } or (
        extractie.status == ExtractieStructurataDocument.Status.EROARE
        and extractie.incercari < MAX_INCERCARI_EXTRAGERE
    ):
        raise EroareRevizuireExtractie(
            "Extragerea automată este încă în lucru. Revino după finalizare."
        )
    finale = _campuri_document(document)
    if extractie.status == ExtractieStructurataDocument.Status.FINALIZATA:
        _, sugerate = sugestii_pentru_document(document)
        comparabile = {
            "partner_id": str(sugerate.get("partener")) if sugerate.get("partener") else None,
            "direction": sugerate.get("directie"),
            "series": sugerate.get("serie"),
            "number": sugerate.get("numar"),
            "document_date": sugerate.get("data_document"),
            "due_date": sugerate.get("data_scadenta"),
            "currency": sugerate.get("moneda"),
            "net_amount": sugerate.get("valoare_fara_tva"),
            "vat_amount": sugerate.get("valoare_tva"),
            "total_amount": sugerate.get("valoare_totala"),
        }
        status = (
            ExtractieStructurataDocument.StatusRevizuire.CONFIRMATA
            if finale == comparabile
            else ExtractieStructurataDocument.StatusRevizuire.CORECTATA
        )
    else:
        status = ExtractieStructurataDocument.StatusRevizuire.MANUALA
    extractie.status_revizuire = status
    extractie.revizuita_de_id = actor.pk
    extractie.revizuita_la = timezone.now()
    extractie.campuri_finale = finale
    extractie.save(
        update_fields=[
            "status_revizuire",
            "revizuita_de",
            "revizuita_la",
            "campuri_finale",
        ]
    )
    return extractie
