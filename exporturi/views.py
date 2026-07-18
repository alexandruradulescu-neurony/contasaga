from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.audit import context_audit_din_request
from perioade.models import PerioadaContabila

from .access import (
    EroareAccesExport,
    deschide_export_local_semnat,
    url_descarcare_export,
)
from .models import Export
from .services import EroareExport, expira_export, poate_solicita_export, solicita_export


@login_required
@require_POST
def export_solicitare(request, perioada_id):
    perioada = get_object_or_404(PerioadaContabila, pk=perioada_id)
    if not poate_solicita_export(request.user):
        raise PermissionDenied
    try:
        rezultat = solicita_export(
            perioada_id=perioada.pk,
            actor=request.user,
            context=context_audit_din_request(request),
        )
    except EroareExport as exc:
        messages.error(request, str(exc))
    else:
        mesaj = (
            "Exportul a fost adăugat în coada de generare."
            if rezultat.creat
            else "Există deja un export în curs pentru această perioadă."
        )
        messages.success(request, mesaj)
    return redirect("perioada_detaliu", perioada_id=perioada.pk)


@login_required
@require_GET
def export_descarcare(request, export_id):
    export = get_object_or_404(
        Export.objects.select_related("firma", "perioada_contabila"),
        pk=export_id,
        solicitat_de_id=request.user.pk,
    )
    if not poate_solicita_export(request.user):
        raise PermissionDenied
    if export.expira_la and export.expira_la <= timezone.now():
        export = expira_export(export.pk)
    try:
        url = url_descarcare_export(request=request, export=export)
    except EroareAccesExport as exc:
        messages.error(request, str(exc))
        return redirect(
            "perioada_detaliu",
            perioada_id=export.perioada_contabila_id,
        )
    return redirect(url)


@require_GET
def export_local_semnat(request):
    try:
        continut = deschide_export_local_semnat(token=request.GET.get("token", ""))
    except EroareAccesExport as exc:
        raise Http404(str(exc)) from exc
    response = FileResponse(
        continut.fisier,
        content_type="application/zip",
    )
    response["Content-Disposition"] = continut.content_disposition
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Cross-Origin-Resource-Policy"] = "same-origin"
    # Fluxul citește exclusiv descriptorul local deja autorizat prin token;
    # iteratorul nu execută interogări după închiderea tranzacției RLS.
    response.rls_safe_streaming = True
    return response
