from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from firme.models import ConfigurareDocumentFirma, ContFinanciar, TipDocument

from .ai import (
    ContextAnalizaDocument,
    EroareAnalizaAI,
    PaginaTextAnaliza,
    construieste_provider,
)
from .ai.contracts import ContFinanciarPermis, TipDocumentPermis
from .ai.providers import VERSIUNE_PROMPT
from .models import AnalizaFisierInbox, FisierInbox, PaginaFisierInbox
from .storage import EroareStorage, get_document_storage

LEASE_ANALIZA = timedelta(minutes=15)
MAX_INCERCARI_ANALIZA = 3


def asigura_analize_pentru_fisiere_disponibile(*, limit: int = 1000) -> int:
    ids_existente = AnalizaFisierInbox.objects.using("privileged").values("fisier_inbox_id")
    fisiere = list(
        FisierInbox.objects.using("privileged")
        .filter(status=FisierInbox.Status.DISPONIBIL)
        .exclude(pk__in=ids_existente)
        .order_by("creat_la")[:limit]
    )
    create = [
        AnalizaFisierInbox(
            fisier_inbox_id=fisier.pk,
            firma_id=fisier.firma_id,
            perioada_contabila_id=fisier.perioada_contabila_id,
        )
        for fisier in fisiere
    ]
    if create:
        AnalizaFisierInbox.objects.using("privileged").bulk_create(
            create,
            ignore_conflicts=True,
        )
    return len(create)


def _poate_fi_preluata(analiza, *, moment) -> bool:
    if analiza.status_revizuire != AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE:
        return False
    if analiza.incercari >= MAX_INCERCARI_ANALIZA:
        return False
    if analiza.status == AnalizaFisierInbox.Status.IN_LUCRU:
        return bool(
            analiza.procesare_inceputa_la
            and analiza.procesare_inceputa_la <= moment - LEASE_ANALIZA
        )
    return bool(
        analiza.status
        in {
            AnalizaFisierInbox.Status.IN_ASTEPTARE,
            AnalizaFisierInbox.Status.EROARE,
        }
        and analiza.reincearca_dupa <= moment
    )


def _context_analiza(analiza) -> ContextAnalizaDocument:
    fisier = analiza.fisier_inbox
    configurate = list(
        ConfigurareDocumentFirma.objects.using("privileged")
        .filter(firma_id=fisier.firma_id, activ=True, tip_document__activ=True)
        .select_related("tip_document")
        .order_by("tip_document__denumire")
    )
    if configurate:
        tipuri = [configurare.tip_document for configurare in configurate]
    else:
        tipuri = list(
            TipDocument.objects.using("privileged").filter(activ=True).order_by("denumire")
        )
    conturi = list(
        ContFinanciar.objects.using("privileged")
        .filter(firma_id=fisier.firma_id, activ=True)
        .order_by("denumire")
    )
    try:
        continut = get_document_storage().read_bytes(fisier.storage_key)
    except EroareStorage as exc:
        raise EroareAnalizaAI("Originalul din inbox nu mai este disponibil.") from exc
    return ContextAnalizaDocument(
        nume_fisier=fisier.nume_original,
        mime_type=fisier.mime_type,
        continut=continut,
        denumire_firma=fisier.firma.denumire,
        cui_firma=fisier.firma.cui,
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
        pagini_text=tuple(
            PaginaTextAnaliza(numar=pagina.numar_pagina, text=pagina.text_extras)
            for pagina in PaginaFisierInbox.objects.using("privileged")
            .filter(analiza_id=analiza.pk)
            .order_by("numar_pagina")
        ),
    )


def _segmente_ai_valide(
    *,
    segmente,
    numar_pagini: int,
    coduri_permibile: set[str],
    conturi_permibile: set[str],
):
    if not segmente:
        return None
    pagina_asteptata = 1
    normalizate = []
    for segment in segmente:
        start = segment.get("pagina_start")
        sfarsit = segment.get("pagina_sfarsit")
        cod = segment.get("cod_tip_document") or "necunoscut"
        cont_id = segment.get("cont_financiar_id")
        if (
            not isinstance(start, int)
            or not isinstance(sfarsit, int)
            or start != pagina_asteptata
            or not start <= sfarsit <= numar_pagini
            or cod not in coduri_permibile | {"necunoscut"}
        ):
            return None
        normalizat = dict(segment)
        if cont_id not in conturi_permibile:
            normalizat["cont_financiar_id"] = None
        if normalizat.get("directie") not in {"primit", "emis"}:
            normalizat["directie"] = None
        normalizate.append(normalizat)
        pagina_asteptata = sfarsit + 1
    return normalizate if pagina_asteptata == numar_pagini + 1 else None


def _salveaza_rezultat(*, analiza_id, incercare, provider, context, rezultat):
    with transaction.atomic(using="privileged"):
        analiza = (
            AnalizaFisierInbox.objects.using("privileged")
            .select_for_update(of=("self",))
            .select_related("fisier_inbox")
            .get(pk=analiza_id)
        )
        if (
            analiza.status != AnalizaFisierInbox.Status.IN_LUCRU
            or analiza.incercari != incercare
            or analiza.status_revizuire != AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE
        ):
            return analiza
        tipuri_dupa_cod = {tip.cod: tip for tip in context.tipuri_document}
        conturi_dupa_id = {cont.id: cont for cont in context.conturi_financiare}
        tip = tipuri_dupa_cod.get(rezultat.cod_tip_document or "")
        cont = conturi_dupa_id.get(rezultat.cont_financiar_id or "")
        if tip and cont:
            model_tip = TipDocument.objects.using("privileged").get(pk=tip.id)
            if not model_tip.necesita_cont_financiar:
                cont = None
            elif model_tip.tipuri_cont_compatibile and cont.tip not in (
                model_tip.tipuri_cont_compatibile
            ):
                cont = None
        elif not tip:
            cont = None

        segmente = _segmente_ai_valide(
            segmente=rezultat.segmente,
            numar_pagini=analiza.numar_pagini or 1,
            coduri_permibile=set(tipuri_dupa_cod),
            conturi_permibile=set(conturi_dupa_id),
        )

        analiza.status = AnalizaFisierInbox.Status.FINALIZATA
        analiza.provider = provider.nume
        analiza.model = provider.model
        analiza.versiune_prompt = VERSIUNE_PROMPT
        analiza.procesare_inceputa_la = None
        analiza.finalizata_la = timezone.now()
        analiza.eroare = None
        analiza.tip_document_sugerat_id = tip.id if tip else None
        analiza.cont_financiar_sugerat_id = cont.id if cont else None
        analiza.directie_sugerata = rezultat.directie
        analiza.incredere = Decimal(str(round(rezultat.incredere, 4)))
        analiza.rezumat = rezultat.rezumat or None
        analiza.text_extras = rezultat.text_extras or None
        analiza.campuri_extrase = rezultat.campuri_extrase
        analiza.avertismente_extragere = rezultat.avertismente_extragere
        analiza.dovezi = rezultat.dovezi
        analiza.raspuns_provider_id = rezultat.raspuns_provider_id
        analiza.tokeni_intrare = rezultat.tokeni_intrare
        analiza.tokeni_iesire = rezultat.tokeni_iesire
        if segmente:
            analiza.limite_sugerate = segmente
        analiza.save(
            using="privileged",
            update_fields=[
                "status",
                "provider",
                "model",
                "versiune_prompt",
                "procesare_inceputa_la",
                "finalizata_la",
                "eroare",
                "tip_document_sugerat",
                "cont_financiar_sugerat",
                "directie_sugerata",
                "incredere",
                "rezumat",
                "text_extras",
                "campuri_extrase",
                "avertismente_extragere",
                "dovezi",
                "raspuns_provider_id",
                "tokeni_intrare",
                "tokeni_iesire",
                "limite_sugerate",
            ],
        )
        return analiza


def _salveaza_eroare(*, analiza_id, incercare, provider, exc):
    with transaction.atomic(using="privileged"):
        analiza = (
            AnalizaFisierInbox.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=analiza_id)
        )
        if (
            analiza.status != AnalizaFisierInbox.Status.IN_LUCRU
            or analiza.incercari != incercare
            or analiza.status_revizuire != AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE
        ):
            return analiza
        analiza.status = AnalizaFisierInbox.Status.EROARE
        analiza.provider = provider.nume
        analiza.model = provider.model
        analiza.versiune_prompt = VERSIUNE_PROMPT
        analiza.procesare_inceputa_la = None
        analiza.eroare = str(exc)[:2000]
        analiza.reincearca_dupa = timezone.now() + timedelta(minutes=5**analiza.incercari)
        analiza.save(
            using="privileged",
            update_fields=[
                "status",
                "provider",
                "model",
                "versiune_prompt",
                "procesare_inceputa_la",
                "eroare",
                "reincearca_dupa",
            ],
        )
        return analiza


def proceseaza_analiza(analiza_id, *, provider=None):
    moment = timezone.now()
    with transaction.atomic(using="privileged"):
        analiza = (
            AnalizaFisierInbox.objects.using("privileged")
            .select_for_update(of=("self",))
            .select_related("fisier_inbox", "fisier_inbox__firma")
            .get(pk=analiza_id)
        )
        if (
            analiza.status == AnalizaFisierInbox.Status.IN_LUCRU
            and analiza.procesare_inceputa_la
            and analiza.procesare_inceputa_la <= moment - LEASE_ANALIZA
            and analiza.incercari >= MAX_INCERCARI_ANALIZA
        ):
            analiza.status = AnalizaFisierInbox.Status.EROARE
            analiza.procesare_inceputa_la = None
            analiza.eroare = "Procesarea ultimei încercări a fost întreruptă înainte de finalizare."
            analiza.save(
                using="privileged",
                update_fields=["status", "procesare_inceputa_la", "eroare"],
            )
            return analiza
        if analiza.fisier_inbox.status != FisierInbox.Status.DISPONIBIL:
            return analiza
        if analiza.status_citire != AnalizaFisierInbox.StatusCitire.FINALIZATA:
            return analiza
        if not _poate_fi_preluata(analiza, moment=moment):
            return analiza
        provider = provider or construieste_provider()
        analiza.status = AnalizaFisierInbox.Status.IN_LUCRU
        analiza.provider = provider.nume
        analiza.model = provider.model
        analiza.versiune_prompt = VERSIUNE_PROMPT
        analiza.incercari += 1
        analiza.procesare_inceputa_la = moment
        analiza.eroare = None
        analiza.save(
            using="privileged",
            update_fields=[
                "status",
                "provider",
                "model",
                "versiune_prompt",
                "incercari",
                "procesare_inceputa_la",
                "eroare",
            ],
        )
        incercare_curenta = analiza.incercari

    try:
        context = _context_analiza(analiza)
        rezultat = provider.analizeaza(context)
    except EroareAnalizaAI as exc:
        return _salveaza_eroare(
            analiza_id=analiza_id,
            incercare=incercare_curenta,
            provider=provider,
            exc=exc,
        )
    return _salveaza_rezultat(
        analiza_id=analiza_id,
        incercare=incercare_curenta,
        provider=provider,
        context=context,
        rezultat=rezultat,
    )


def ids_analize_de_procesat(*, limit: int) -> list:
    moment = timezone.now()
    limita_lease = moment - LEASE_ANALIZA
    return list(
        AnalizaFisierInbox.objects.using("privileged")
        .filter(
            status_revizuire=AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE,
            fisier_inbox__status=FisierInbox.Status.DISPONIBIL,
            status_citire=AnalizaFisierInbox.StatusCitire.FINALIZATA,
        )
        .filter(
            Q(
                status__in=(
                    AnalizaFisierInbox.Status.IN_ASTEPTARE,
                    AnalizaFisierInbox.Status.EROARE,
                ),
                reincearca_dupa__lte=moment,
                incercari__lt=MAX_INCERCARI_ANALIZA,
            )
            | Q(
                status=AnalizaFisierInbox.Status.IN_LUCRU,
                procesare_inceputa_la__lte=limita_lease,
            )
        )
        .order_by("reincearca_dupa", "creat_la")
        .values_list("pk", flat=True)[:limit]
    )


def proceseaza_coada_analize(*, limit: int = 20) -> tuple[int, int]:
    if not settings.DOCUMENT_AI_ENABLED:
        return 0, 0
    asigura_analize_pentru_fisiere_disponibile(limit=max(limit * 5, 100))
    provider = construieste_provider()
    finalizate = 0
    erori = 0
    for analiza_id in ids_analize_de_procesat(limit=limit):
        analiza = proceseaza_analiza(analiza_id, provider=provider)
        if analiza.status == AnalizaFisierInbox.Status.FINALIZATA:
            finalizate += 1
        elif analiza.status == AnalizaFisierInbox.Status.EROARE:
            erori += 1
    return finalizate, erori
