from django.urls import path

from .allocation_views import alocare_stergere, alocari

urlpatterns = [
    path("", alocari, name="alocari"),
    path("<uuid:alocare_id>/sterge/", alocare_stergere, name="alocare_stergere"),
]
