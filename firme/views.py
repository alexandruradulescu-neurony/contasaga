from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from core.audit import context_audit_din_request

from .forms import FirmaForm
from .models import Firma
from .services import (
    CUIDuplicat,
    actualizeaza_firma,
    creeaza_firma,
    poate_administra_firme,
)


def _verifica_acces_view(request) -> None:
    if not poate_administra_firme(request.user):
        raise PermissionDenied


@login_required
def firma_noua(request):
    _verifica_acces_view(request)
    form = FirmaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            firma = creeaza_firma(
                utilizator=request.user,
                date=form.cleaned_data,
                context=context_audit_din_request(request),
            )
        except CUIDuplicat:
            form.add_error("cui", "Există deja o firmă cu acest CUI.")
        else:
            messages.success(request, f"Firma {firma.denumire} a fost creată.")
            return redirect("dashboard")
    return render(request, "firme/form.html", {"form": form, "titlu": "Firmă clientă nouă"})


@login_required
def firma_editare(request, firma_id):
    _verifica_acces_view(request)
    firma = get_object_or_404(Firma, pk=firma_id)
    form = FirmaForm(request.POST or None, instance=firma)
    if request.method == "POST" and form.is_valid():
        try:
            firma = actualizeaza_firma(
                firma_id=firma.pk,
                utilizator=request.user,
                date=form.cleaned_data,
                context=context_audit_din_request(request),
            )
        except CUIDuplicat:
            form.add_error("cui", "Există deja o firmă cu acest CUI.")
        else:
            messages.success(request, f"Firma {firma.denumire} a fost actualizată.")
            return redirect("dashboard")
    return render(
        request,
        "firme/form.html",
        {"form": form, "titlu": f"Editează {firma.denumire}", "firma": firma},
    )
