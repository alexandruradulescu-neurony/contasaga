from django.urls import path

from .views import export_descarcare, export_local_semnat, export_solicitare

urlpatterns = [
    path(
        "perioade/<uuid:perioada_id>/exporturi/solicita/",
        export_solicitare,
        name="export_solicitare",
    ),
    path(
        "exporturi/<uuid:export_id>/descarca/",
        export_descarcare,
        name="export_descarcare",
    ),
    path(
        "exporturi/local/semnat/",
        export_local_semnat,
        name="export_local_semnat",
    ),
]
