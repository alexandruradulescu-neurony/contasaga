from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from conturi.models import Utilizator
from core.audit import context_audit_din_request
from firme.models import ContFinanciar, Firma, TipDocument

from .access import url_acces_pagina_inbox
from .classification import (
    EroareClasificareInbox,
    clasifica_fisier_inbox,
    ignora_fisier_inbox,
)
from .forms import ClasificareFisierInboxForm, SegmentDocumentInboxFormSet
from .models import AnalizaFisierInbox, FisierInbox, PaginaFisierInbox
from .segmentation import SegmentDocument, separa_fisier_inbox
from .services import poate_verifica_documente


def _fisiere_pentru_clasificare():
    return (
        FisierInbox.objects.filter(status=FisierInbox.Status.DISPONIBIL)
        .select_related(
            "firma",
            "perioada_contabila",
            "analiza",
            "analiza__tip_document_sugerat",
            "analiza__cont_financiar_sugerat",
        )
        .annotate(
            incarcat_de_nume=Subquery(
                Utilizator.objects.filter(pk=OuterRef("incarcat_de_id")).values("nume")[:1]
            )
        )
    )


@login_required
@require_GET
def coada_clasificare_inbox(request):
    if not poate_verifica_documente(request.user):
        raise PermissionDenied

    baza = _fisiere_pentru_clasificare()
    total = baza.count()
    fisiere = baza
    firme = list(Firma.objects.filter(activa=True).order_by("denumire"))
    firma_id = request.GET.get("firma", "")
    if firma_id and any(str(firma.pk) == firma_id for firma in firme):
        fisiere = fisiere.filter(firma_id=firma_id)
    else:
        firma_id = ""

    status_ai = request.GET.get("status_ai", "")
    statusuri_ai = {valoare for valoare, _ in AnalizaFisierInbox.Status.choices}
    if status_ai in statusuri_ai:
        fisiere = fisiere.filter(analiza__status=status_ai)
    else:
        status_ai = ""

    cautare = request.GET.get("q", "").strip()[:200]
    if cautare:
        fisiere = fisiere.filter(
            Q(nume_original__icontains=cautare) | Q(analiza__pagini__text_extras__icontains=cautare)
        ).distinct()

    fisiere = fisiere.order_by("creat_la")
    pagina = Paginator(fisiere, 25).get_page(request.GET.get("pagina"))
    for fisier in pagina:
        fisier.formular_clasificare = ClasificareFisierInboxForm(
            fisier=fisier,
            prefix=str(fisier.pk),
        )
    return render(
        request,
        "documente/coada_clasificare.html",
        {
            "fisiere": pagina,
            "total": total,
            "total_filtrat": pagina.paginator.count,
            "firme": firme,
            "firma_selectata": firma_id,
            "status_ai_selectat": status_ai,
            "statusuri_ai": AnalizaFisierInbox.Status.choices,
            "cautare": cautare,
        },
    )


@login_required
@require_POST
def clasifica_inbox(request, fisier_id):
    if not poate_verifica_documente(request.user):
        raise PermissionDenied
    fisier = get_object_or_404(
        FisierInbox.objects.select_related("analiza"),
        pk=fisier_id,
        status=FisierInbox.Status.DISPONIBIL,
    )
    formular = ClasificareFisierInboxForm(
        request.POST,
        fisier=fisier,
        prefix=str(fisier.pk),
    )
    if not formular.is_valid():
        messages.error(request, "Clasificarea este incompletă sau invalidă.")
        return redirect("coada_clasificare_inbox")
    try:
        document = clasifica_fisier_inbox(
            fisier_id=fisier.pk,
            actor=request.user,
            tip_document_id=formular.cleaned_data["tip_document"].pk,
            cont_financiar_id=(
                formular.cleaned_data["cont_financiar"].pk
                if formular.cleaned_data["cont_financiar"]
                else None
            ),
            directie=formular.cleaned_data["directie"],
            observatii=formular.cleaned_data["observatii"],
            context=context_audit_din_request(request),
        )
    except EroareClasificareInbox as exc:
        messages.error(request, str(exc))
        return redirect("coada_clasificare_inbox")
    messages.success(request, "Fișierul a fost clasificat și a intrat în verificare.")
    return redirect("document_detaliu", document_id=document.pk)


@login_required
@require_POST
def ignora_inbox(request, fisier_id):
    if not poate_verifica_documente(request.user):
        raise PermissionDenied
    get_object_or_404(
        FisierInbox,
        pk=fisier_id,
        status=FisierInbox.Status.DISPONIBIL,
    )
    try:
        ignora_fisier_inbox(
            fisier_id=fisier_id,
            actor=request.user,
            motiv=request.POST.get("motiv", ""),
            context=context_audit_din_request(request),
        )
    except EroareClasificareInbox as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Fișierul a fost marcat ca nerelevant și rămâne în audit.")
    return redirect("coada_clasificare_inbox")


def _initial_segmentare(fisier):
    analiza = fisier.analiza
    tipuri_dupa_cod = {
        tip.cod: tip.pk
        for tip in ClasificareFisierInboxForm(fisier=fisier).fields["tip_document"].queryset
    }
    limite = analiza.limite_sugerate or [
        {"pagina_start": 1, "pagina_sfarsit": analiza.numar_pagini or 1}
    ]
    initial = []
    for limita in limite:
        cod = limita.get("cod_tip_document")
        initial.append(
            {
                "pagina_start": limita.get("pagina_start"),
                "pagina_sfarsit": limita.get("pagina_sfarsit"),
                "tip_document": (
                    tipuri_dupa_cod.get(cod) if cod else analiza.tip_document_sugerat_id
                ),
                "cont_financiar": (
                    limita.get("cont_financiar_id") or analiza.cont_financiar_sugerat_id
                ),
                "directie": limita.get("directie") or analiza.directie_sugerata,
            }
        )
    return initial


@login_required
@require_http_methods(["GET", "POST"])
def separa_inbox(request, fisier_id):
    if not poate_verifica_documente(request.user):
        raise PermissionDenied
    fisier = get_object_or_404(
        FisierInbox.objects.select_related(
            "firma",
            "perioada_contabila",
            "analiza",
            "analiza__tip_document_sugerat",
            "analiza__cont_financiar_sugerat",
        ),
        pk=fisier_id,
        status=FisierInbox.Status.DISPONIBIL,
    )
    analiza = fisier.analiza
    pagini = list(PaginaFisierInbox.objects.filter(analiza_id=analiza.pk).order_by("numar_pagina"))
    for pagina in pagini:
        pagina.preview_url = url_acces_pagina_inbox(request=request, pagina=pagina)

    formular = SegmentDocumentInboxFormSet(
        request.POST or None,
        fisier=fisier,
        initial=_initial_segmentare(fisier) if request.method == "GET" else None,
        prefix="segmente",
    )
    if request.method == "POST" and formular.is_valid():
        try:
            documente = separa_fisier_inbox(
                fisier_id=fisier.pk,
                actor=request.user,
                segmente=[
                    SegmentDocument(
                        pagina_start=date["pagina_start"],
                        pagina_sfarsit=date["pagina_sfarsit"],
                        tip_document_id=date["tip_document"].pk,
                        cont_financiar_id=(
                            date["cont_financiar"].pk if date["cont_financiar"] else None
                        ),
                        directie=date["directie"],
                        observatii=date["observatii"],
                    )
                    for date in (form.cleaned_data for form in formular.forms)
                ],
                context=context_audit_din_request(request),
            )
        except (
            EroareClasificareInbox,
            TipDocument.DoesNotExist,
            ContFinanciar.DoesNotExist,
        ) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                f"Separarea a fost confirmată: {len(documente)} document(e) create.",
            )
            if len(documente) == 1:
                return redirect("document_detaliu", document_id=documente[0].pk)
            return redirect("coada_clasificare_inbox")

    return render(
        request,
        "documente/separa_inbox.html",
        {
            "fisier": fisier,
            "analiza": analiza,
            "pagini": pagini,
            "formular": formular,
        },
    )
