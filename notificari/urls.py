from django.urls import path

from .views import citeste_notificare, citeste_toate_notificarile, lista_notificari

urlpatterns = [
    path("", lista_notificari, name="lista_notificari"),
    path("citeste-toate/", citeste_toate_notificarile, name="citeste_toate_notificarile"),
    path("<uuid:notificare_id>/citeste/", citeste_notificare, name="citeste_notificare"),
]
