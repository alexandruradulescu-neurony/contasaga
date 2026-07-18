from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from core.audit import context_audit_din_request

from .configuration_forms import ConfigurareDocumentForm, ContFinanciarForm
from .configuration_services import salveaza_configurare, salveaza_cont_financiar
from .models import ConfigurareDocumentFirma, ContFinanciar, Firma
from .services import poate_administra_firme


@login_required
def configurare_firma(request, firma_id):
    if not poate_administra_firme(request.user):
        raise PermissionDenied
    firma = get_object_or_404(Firma, pk=firma_id)
    formular_config = ConfigurareDocumentForm(
        request.POST if request.POST.get("actiune") == "configurare" else None
    )
    formular_cont = ContFinanciarForm(
        request.POST if request.POST.get("actiune") == "cont" else None
    )

    if request.method == "POST" and request.POST.get("actiune") == "configurare":
        if formular_config.is_valid():
            date = formular_config.cleaned_data.copy()
            tip_document = date.pop("tip_document")
            salveaza_configurare(
                actor=request.user,
                firma=firma,
                tip_document=tip_document,
                date=date,
                context=context_audit_din_request(request),
            )
            messages.success(request, "Configurarea checklist-ului a fost salvată.")
            return redirect("configurare_firma", firma_id=firma.pk)
    elif request.method == "POST" and request.POST.get("actiune") == "cont":
        if formular_cont.is_valid():
            salveaza_cont_financiar(
                actor=request.user,
                firma=firma,
                date=formular_cont.cleaned_data,
                context=context_audit_din_request(request),
            )
            messages.success(request, "Contul financiar a fost adăugat.")
            return redirect("configurare_firma", firma_id=firma.pk)

    configurari = ConfigurareDocumentFirma.objects.select_related("tip_document").filter(
        firma=firma
    )
    conturi = ContFinanciar.objects.filter(firma=firma)
    return render(
        request,
        "firme/configurare.html",
        {
            "firma": firma,
            "formular_config": formular_config,
            "formular_cont": formular_cont,
            "configurari": configurari,
            "conturi": conturi,
        },
    )
