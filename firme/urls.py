from django.urls import path

from .configuration_views import configurare_firma
from .views import firma_editare, firma_noua

urlpatterns = [
    path("noua/", firma_noua, name="firma_noua"),
    path("<uuid:firma_id>/configurare/", configurare_firma, name="configurare_firma"),
    path("<uuid:firma_id>/editare/", firma_editare, name="firma_editare"),
]
