import hashlib

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .models import ArhivaLunara
from .storage import EroareStorage, get_document_storage


@login_required
@require_GET
def arhiva_manifest(request, arhiva_id):
    arhiva = get_object_or_404(
        ArhivaLunara,
        pk=arhiva_id,
        status__in=(ArhivaLunara.Status.FINALIZATA, ArhivaLunara.Status.INLOCUITA),
    )
    if not arhiva.manifest_storage_key or not arhiva.manifest_checksum:
        raise Http404
    try:
        continut = get_document_storage().read_bytes(arhiva.manifest_storage_key)
    except EroareStorage as exc:
        raise Http404 from exc
    if hashlib.sha256(continut).hexdigest() != arhiva.manifest_checksum:
        raise Http404
    response = HttpResponse(continut, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="manifest-{arhiva.perioada_contabila_id}-v{arhiva.versiune}.csv"'
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response
