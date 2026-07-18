from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import context_audit_din_request
from perioade.models import PerioadaContabila

from .forms import DigitizareForm, ProgramarePredareForm
from .models import PredareDocumente
from .services import (
    EroareLogistica,
    actualizeaza_estimarea_digitizarii,
    avanseaza_predare,
    finalizeaza_digitizarea,
    incepe_digitizarea,
    omite_digitizarea,
    poate_gestiona_predari,
    poate_programa_predare,
    programeaza_predare,
    redeschide_digitizarea,
)


@login_required
@require_POST
def predare_programare(request, perioada_id):
    perioada = get_object_or_404(PerioadaContabila, pk=perioada_id)
    if not poate_programa_predare(request.user):
        raise PermissionDenied
    formular = ProgramarePredareForm(request.POST)
    if not formular.is_valid():
        messages.error(request, "Predarea nu a fost programată. Verifică toate câmpurile.")
        return redirect("perioada_detaliu", perioada_id=perioada.pk)
    try:
        programeaza_predare(
            perioada_id=perioada.pk,
            actor=request.user,
            context=context_audit_din_request(request),
            **formular.cleaned_data,
        )
    except EroareLogistica as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Predarea documentelor a fost înregistrată.")
    return redirect("perioada_detaliu", perioada_id=perioada.pk)


def _tranzitie(request, predare_id, actiune, mesaj):
    predare = get_object_or_404(PredareDocumente, pk=predare_id)
    if not poate_gestiona_predari(request.user):
        raise PermissionDenied
    try:
        avanseaza_predare(
            predare_id=predare.pk,
            actiune=actiune,
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except EroareLogistica as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, mesaj)
    return redirect(
        "perioada_detaliu",
        perioada_id=predare.perioada_contabila_id,
    )


@login_required
@require_POST
def predare_preluare(request, predare_id):
    return _tranzitie(request, predare_id, "preia", "Predarea a fost preluată.")


@login_required
@require_POST
def predare_receptie(request, predare_id):
    return _tranzitie(
        request,
        predare_id,
        "receptioneaza",
        "Documentele au fost recepționate.",
    )


@login_required
@require_POST
def predare_returnare(request, predare_id):
    return _tranzitie(request, predare_id, "returneaza", "Documentele au fost returnate.")


def _redirect_predare(predare, *, selectata=False):
    url = reverse("perioada_detaliu", kwargs={"perioada_id": predare.perioada_contabila_id})
    if selectata:
        url = f"{url}?predare={predare.pk}#digitizare-activa"
    return redirect(url)


@login_required
@require_POST
def predare_digitizare_incepe(request, predare_id):
    predare = get_object_or_404(PredareDocumente, pk=predare_id)
    formular = DigitizareForm(request.POST)
    if not formular.is_valid():
        messages.error(request, "Estimarea documentelor este invalidă.")
        return _redirect_predare(predare)
    try:
        incepe_digitizarea(
            predare_id=predare.pk,
            actor=request.user,
            numar_documente_estimat=formular.cleaned_data["numar_documente_estimat"],
            context=context_audit_din_request(request),
        )
    except EroareLogistica as exc:
        messages.error(request, str(exc))
        return _redirect_predare(predare)
    messages.success(request, "Digitizarea a fost începută. Încărcările vor fi legate de predare.")
    return _redirect_predare(predare, selectata=True)


@login_required
@require_POST
def predare_digitizare_omite(request, predare_id):
    predare = get_object_or_404(PredareDocumente, pk=predare_id)
    try:
        omite_digitizarea(
            predare_id=predare.pk,
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except EroareLogistica as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Predarea va fi păstrată numai în evidența fizică.")
    return _redirect_predare(predare)


@login_required
@require_POST
def predare_digitizare_estimare(request, predare_id):
    predare = get_object_or_404(PredareDocumente, pk=predare_id)
    formular = DigitizareForm(request.POST)
    if not formular.is_valid():
        messages.error(request, "Estimarea documentelor este invalidă.")
        return _redirect_predare(predare, selectata=True)
    try:
        actualizeaza_estimarea_digitizarii(
            predare_id=predare.pk,
            actor=request.user,
            numar_documente_estimat=formular.cleaned_data["numar_documente_estimat"],
            context=context_audit_din_request(request),
        )
    except EroareLogistica as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Estimarea digitizării a fost actualizată.")
    return _redirect_predare(predare, selectata=True)


@login_required
@require_POST
def predare_digitizare_finalizare(request, predare_id):
    predare = get_object_or_404(PredareDocumente, pk=predare_id)
    try:
        finalizeaza_digitizarea(
            predare_id=predare.pk,
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except EroareLogistica as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Digitizarea predării a fost finalizată și auditată.")
    return _redirect_predare(predare)


@login_required
@require_POST
def predare_digitizare_redeschidere(request, predare_id):
    predare = get_object_or_404(PredareDocumente, pk=predare_id)
    try:
        redeschide_digitizarea(
            predare_id=predare.pk,
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except EroareLogistica as exc:
        messages.error(request, str(exc))
        return _redirect_predare(predare)
    messages.success(request, "Digitizarea a fost redeschisă pentru documente suplimentare.")
    return _redirect_predare(predare, selectata=True)
