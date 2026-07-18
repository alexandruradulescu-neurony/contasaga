from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Notificare


@login_required
def lista_notificari(request):
    notificari = Notificare.objects.filter(vizibila_in_app=True)
    doar_necitite = request.GET.get("stare") == "necitite"
    if doar_necitite:
        notificari = notificari.filter(citita=False)
    return render(
        request,
        "notificari/lista.html",
        {
            "notificari": notificari[:100],
            "doar_necitite": doar_necitite,
        },
    )


@login_required
@require_POST
def citeste_notificare(request, notificare_id):
    notificare = get_object_or_404(
        Notificare,
        pk=notificare_id,
        vizibila_in_app=True,
    )
    if not notificare.citita:
        notificare.citita = True
        notificare.save(update_fields=["citita"])
    messages.success(request, "Notificarea a fost marcată drept citită.")
    return redirect("lista_notificari")


@login_required
@require_POST
def citeste_toate_notificarile(request):
    actualizate = Notificare.objects.filter(
        citita=False,
        vizibila_in_app=True,
    ).update(citita=True)
    if actualizate:
        messages.success(request, "Toate notificările au fost marcate drept citite.")
    return redirect("lista_notificari")
