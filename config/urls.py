from django.contrib.auth.views import LogoutView, PasswordChangeDoneView, PasswordChangeView
from django.urls import include, path

from conturi.auth_views import LoginProtejatView
from conturi.password_forms import SchimbareParolaForm
from conturi.password_views import (
    parola_reset_completa,
    parola_reset_confirmare,
    parola_reset_solicitare,
    parola_reset_trimisa,
)
from core.views import dashboard, health, health_live, health_ready, home

urlpatterns = [
    path("", home, name="home"),
    path(
        "autentificare/",
        LoginProtejatView.as_view(),
        name="login",
    ),
    path("deconectare/", LogoutView.as_view(), name="logout"),
    path(
        "parola/schimbare/",
        PasswordChangeView.as_view(
            template_name="registration/parola_schimbare.html",
            form_class=SchimbareParolaForm,
            success_url="/parola/schimbare/finalizata/",
        ),
        name="parola_schimbare",
    ),
    path(
        "parola/schimbare/finalizata/",
        PasswordChangeDoneView.as_view(
            template_name="registration/parola_schimbare_finalizata.html"
        ),
        name="parola_schimbare_finalizata",
    ),
    path("parola/resetare/", parola_reset_solicitare, name="parola_reset_solicitare"),
    path("parola/resetare/trimisa/", parola_reset_trimisa, name="parola_reset_trimisa"),
    path(
        "parola/resetare/<uidb64>/<token>/",
        parola_reset_confirmare,
        name="parola_reset_confirmare",
    ),
    path("parola/resetare/completa/", parola_reset_completa, name="parola_reset_completa"),
    path("dashboard/", dashboard, name="dashboard"),
    path("firme/", include("firme.urls")),
    path("invitatii/", include("conturi.urls")),
    path("alocari/", include("conturi.allocation_urls")),
    path("notificari/", include("notificari.urls")),
    path("", include("exporturi.urls")),
    path("", include("logistica.urls")),
    path("", include("perioade.urls")),
    path("", include("documente.urls")),
    path("health/", health, name="health"),
    path("health/live/", health_live, name="health_live"),
    path("health/ready/", health_ready, name="health_ready"),
]
