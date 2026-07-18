from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.audit import context_audit_din_request

from .allocation_forms import AlocareForm
from .allocations import (
    EroareAlocare,
    creeaza_alocare,
    poate_gestiona_alocari,
    sterge_alocare,
)
from .models import Utilizator, UtilizatorFirma


@login_required
def alocari(request):
    if not poate_gestiona_alocari(request.user):
        raise PermissionDenied
    form = AlocareForm(request.POST or None, actor=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            creeaza_alocare(
                actor=request.user,
                utilizator=form.cleaned_data["utilizator"],
                firma=form.cleaned_data["firma"],
                context=context_audit_din_request(request),
            )
        except EroareAlocare as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(request, "Alocarea a fost creată.")
            return redirect("alocari")

    lista = list(
        UtilizatorFirma.objects.select_related("firma")
        .filter(rol_in_firma="contabil_alocat")
        .order_by("firma__denumire")
    )
    utilizatori = {
        utilizator.pk: utilizator
        for utilizator in Utilizator.objects.filter(
            pk__in=[alocare.utilizator_id for alocare in lista]
        )
    }
    for alocare in lista:
        alocare.utilizator_afisat = utilizatori.get(alocare.utilizator_id)
    return render(request, "conturi/alocari.html", {"form": form, "alocari": lista})


@login_required
@require_POST
def alocare_stergere(request, alocare_id):
    alocare = get_object_or_404(
        UtilizatorFirma.objects.select_related("firma"),
        pk=alocare_id,
        rol_in_firma="contabil_alocat",
    )
    try:
        sterge_alocare(
            actor=request.user,
            alocare=alocare,
            context=context_audit_din_request(request),
        )
    except EroareAlocare as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Alocarea a fost eliminată.")
    return redirect("alocari")
