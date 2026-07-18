from django.urls import path

from .views import (
    cerinta_actualizare,
    perioada_confirmare,
    perioada_detaliu,
    perioada_incepe,
    perioada_inchidere,
    perioada_redeschidere,
    perioade_firma,
)

urlpatterns = [
    path("firme/<uuid:firma_id>/perioade/", perioade_firma, name="perioade_firma"),
    path("perioade/<uuid:perioada_id>/", perioada_detaliu, name="perioada_detaliu"),
    path(
        "cerinte/<uuid:cerinta_id>/actualizeaza/", cerinta_actualizare, name="cerinta_actualizare"
    ),
    path("perioade/<uuid:perioada_id>/confirma/", perioada_confirmare, name="perioada_confirmare"),
    path("perioade/<uuid:perioada_id>/incepe/", perioada_incepe, name="perioada_incepe"),
    path("perioade/<uuid:perioada_id>/inchide/", perioada_inchidere, name="perioada_inchidere"),
    path(
        "perioade/<uuid:perioada_id>/redeschide/",
        perioada_redeschidere,
        name="perioada_redeschidere",
    ),
]
