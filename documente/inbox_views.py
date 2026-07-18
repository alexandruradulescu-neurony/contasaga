from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.audit import context_audit_din_request
from perioade.models import PerioadaContabila

from .access import EroareAccesFisier, url_acces_fisier_inbox
from .inbox import (
    EroareInbox,
    creeaza_lot_incarcare,
    finalizeaza_fisier_inbox,
    finalizeaza_lot_incarcare,
    initiaza_fisier_inbox,
    primeste_upload_local_inbox,
)
from .models import FisierInbox, LotIncarcare
from .services import poate_incarca_documente


@login_required
@require_GET
def inbox_perioada(request, perioada_id):
    perioada = get_object_or_404(
        PerioadaContabila.objects.select_related("firma"),
        pk=perioada_id,
    )
    loturi = list(
        LotIncarcare.objects.filter(perioada_contabila=perioada).prefetch_related("fisiere")[:30]
    )
    for lot in loturi:
        fisiere = list(lot.fisiere.all())
        lot.fisiere_afisate = fisiere
        lot.numar_disponibile = sum(
            fisier.status in {FisierInbox.Status.DISPONIBIL, FisierInbox.Status.CLASIFICAT}
            for fisier in fisiere
        )
        lot.numar_erori = sum(
            fisier.status in {FisierInbox.Status.EROARE, FisierInbox.Status.EXPIRAT}
            for fisier in fisiere
        )
    return render(
        request,
        "documente/inbox_perioada.html",
        {
            "perioada": perioada,
            "loturi": loturi,
            "poate_incarca": bool(
                poate_incarca_documente(request.user)
                and perioada.stare != PerioadaContabila.Stare.INCHISA
            ),
            "max_fisiere": settings.DOCUMENT_BATCH_MAX_FILES,
            "max_mb_fisier": settings.DOCUMENT_UPLOAD_MAX_BYTES // (1024 * 1024),
            "max_gb_lot": settings.DOCUMENT_BATCH_MAX_TOTAL_BYTES // (1024 * 1024 * 1024),
        },
    )


@login_required
@require_POST
def inbox_lot_creare(request, perioada_id):
    get_object_or_404(PerioadaContabila, pk=perioada_id)
    try:
        lot = creeaza_lot_incarcare(
            perioada_id=perioada_id,
            actor=request.user,
            numar_fisiere=int(request.POST.get("numar_fisiere", "0")),
            dimensiune_totala=int(request.POST.get("dimensiune_totala", "0")),
            nota=request.POST.get("nota", ""),
            context=context_audit_din_request(request),
        )
    except (EroareInbox, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(
        {
            "lot_id": str(lot.pk),
            "init_url": reverse("inbox_fisier_initiere", kwargs={"lot_id": lot.pk}),
            "finalize_url": reverse("inbox_lot_finalizare", kwargs={"lot_id": lot.pk}),
        },
        status=201,
    )


@login_required
@require_POST
def inbox_fisier_initiere(request, lot_id):
    get_object_or_404(LotIncarcare, pk=lot_id)
    try:
        rezultat = initiaza_fisier_inbox(
            lot_id=lot_id,
            actor=request.user,
            nume_original=request.POST.get("nume", ""),
            content_type=request.POST.get("content_type"),
            dimensiune_declarata=int(request.POST.get("dimensiune", "0")),
            request=request,
        )
    except (EroareInbox, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(
        {
            "fisier_id": str(rezultat.fisier.pk),
            "upload_url": rezultat.upload_url,
            "finalize_url": reverse(
                "inbox_fisier_finalizare",
                kwargs={"fisier_id": rezultat.fisier.pk},
            ),
            "method": "PUT",
            "headers": rezultat.headers,
        }
    )


@csrf_exempt
@require_http_methods(["PUT"])
def inbox_upload_local_put(request, fisier_id):
    try:
        lungime = int(request.headers.get("Content-Length", "0"))
        if not 1 <= lungime <= settings.DOCUMENT_UPLOAD_MAX_BYTES:
            raise EroareInbox("Fișierul trebuie să aibă cel mult 25 MB.")
        primeste_upload_local_inbox(
            fisier_id=fisier_id,
            token=request.GET.get("token", ""),
            content_type=request.content_type,
            continut=request.body,
        )
    except (EroareInbox, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({}, status=204)


@login_required
@require_POST
def inbox_fisier_finalizare(request, fisier_id):
    get_object_or_404(FisierInbox, pk=fisier_id)
    try:
        fisier = finalizeaza_fisier_inbox(
            fisier_id=fisier_id,
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except EroareInbox as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(
        {
            "fisier_id": str(fisier.pk),
            "nume": fisier.nume_original,
            "status": fisier.status,
        }
    )


@login_required
@require_POST
def inbox_lot_finalizare(request, lot_id):
    get_object_or_404(LotIncarcare, pk=lot_id)
    try:
        lot = finalizeaza_lot_incarcare(
            lot_id=lot_id,
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except EroareInbox as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(
        {
            "lot_id": str(lot.pk),
            "status": lot.status,
            "redirect_url": reverse(
                "inbox_perioada",
                kwargs={"perioada_id": lot.perioada_contabila_id},
            ),
        }
    )


@login_required
@require_GET
def inbox_fisier_descarcare(request, fisier_id):
    fisier = get_object_or_404(FisierInbox, pk=fisier_id)
    try:
        url = url_acces_fisier_inbox(request=request, fisier=fisier)
    except EroareAccesFisier as exc:
        messages.error(request, str(exc))
        return redirect(
            "inbox_perioada",
            perioada_id=fisier.perioada_contabila_id,
        )
    return redirect(url)
