import hashlib
import logging

from django.conf import settings
from django.contrib.auth.views import LoginView
from django.core.cache import cache

from core.request_ip import ip_client

logger = logging.getLogger(__name__)


class LoginProtejatView(LoginView):
    """Autentificare cu limitare partajată per cont și adresă IP."""

    template_name = "registration/login.html"

    def _identitate(self) -> str:
        return self.request.POST.get("username", "").strip().lower()

    def _cheie(self, prefix: str, valoare: str) -> str:
        digest = hashlib.sha256(valoare.encode()).hexdigest()
        return f"login-rate:{prefix}:{digest}"

    def _chei(self) -> tuple[str, str]:
        identitate = self._identitate()
        ip = ip_client(self.request) or "necunoscut"
        return (
            self._cheie("account", identitate),
            self._cheie("ip", ip),
        )

    def _limitat(self) -> bool:
        cheie_cont, cheie_ip = self._chei()
        try:
            return bool(
                int(cache.get(cheie_cont, 0)) >= settings.LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS
                or int(cache.get(cheie_ip, 0)) >= settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS
            )
        except Exception:
            logger.exception("Starea limitării autentificării nu a putut fi citită")
            return False

    def _inregistreaza_esec(self) -> None:
        timeout = settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS
        try:
            for cheie in self._chei():
                if cache.add(cheie, 1, timeout=timeout):
                    continue
                cache.incr(cheie)
        except Exception:
            logger.exception("Eșecul de autentificare nu a putut fi contorizat")

    def _raspuns_limitare(self, form):
        form.add_error(
            None,
            "Prea multe încercări de autentificare. Încearcă din nou peste câteva minute.",
        )
        response = self.render_to_response(self.get_context_data(form=form), status=429)
        response["Retry-After"] = str(settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        return response

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST" and self._limitat():
            return self._raspuns_limitare(self.get_form())
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        self._inregistreaza_esec()
        if self._limitat():
            return self._raspuns_limitare(form)
        return super().form_invalid(form)

    def form_valid(self, form):
        cheie_cont, _ = self._chei()
        try:
            cache.delete(cheie_cont)
        except Exception:
            logger.exception("Contorul autentificării reușite nu a putut fi șters")
        return super().form_valid(form)
