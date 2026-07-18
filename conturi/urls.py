from django.urls import path

from .invitation_views import invitatie_acceptare, invitatie_anulare, invitatii

urlpatterns = [
    path("", invitatii, name="invitatii"),
    path("accepta/<str:token>/", invitatie_acceptare, name="invitatie_acceptare"),
    path("<uuid:invitatie_id>/anuleaza/", invitatie_anulare, name="invitatie_anulare"),
]
