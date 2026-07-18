import hashlib
import logging

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.mail import send_mail
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from core.request_ip import ip_client

from .models import Utilizator
from .password_forms import CerereResetParolaForm, SetareParolaNouaForm
from .services import seteaza_parola

logger = logging.getLogger(__name__)


def _cheie_reset(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()
    return f"password-reset:{prefix}:{digest}"


def _permite_trimitere_reset(request, email: str) -> bool:
    chei = (
        _cheie_reset("account", email.strip().lower()),
        _cheie_reset("ip", ip_client(request) or "necunoscut"),
    )
    limite = (
        settings.PASSWORD_RESET_RATE_LIMIT_ATTEMPTS,
        settings.PASSWORD_RESET_RATE_LIMIT_IP_ATTEMPTS,
    )
    timeout = settings.PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS
    try:
        if any(
            int(cache.get(cheie, 0)) >= limita for cheie, limita in zip(chei, limite, strict=True)
        ):
            return False
        for cheie in chei:
            if not cache.add(cheie, 1, timeout=timeout):
                cache.incr(cheie)
        return True
    except Exception:
        logger.exception("Limitarea cererii de resetare nu a putut fi actualizată")
        return True


def _utilizator_pentru_email(email: str):
    return (
        Utilizator.objects.using("privileged")
        .filter(email__iexact=email.strip(), is_active=True)
        .first()
    )


def _utilizator_pentru_uid(uidb64: str):
    try:
        user_id = force_str(urlsafe_base64_decode(uidb64))
        return Utilizator.objects.using("privileged").get(pk=user_id, is_active=True)
    except (TypeError, ValueError, OverflowError, Utilizator.DoesNotExist):
        return None


def parola_reset_solicitare(request):
    form = CerereResetParolaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        if _permite_trimitere_reset(request, email):
            utilizator = _utilizator_pentru_email(email)
            if utilizator:
                uidb64 = urlsafe_base64_encode(force_bytes(utilizator.pk))
                token = default_token_generator.make_token(utilizator)
                cale = reverse(
                    "parola_reset_confirmare",
                    kwargs={"uidb64": uidb64, "token": token},
                )
                link = request.build_absolute_uri(cale)
                try:
                    send_mail(
                        subject="Resetare parolă Conta Saga",
                        message=(
                            f"Bună, {utilizator.nume}.\n\n"
                            f"Poți seta o parolă nouă folosind linkul:\n{link}\n\n"
                            "Dacă nu ai solicitat resetarea, ignoră acest mesaj."
                        ),
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[utilizator.email],
                        fail_silently=False,
                    )
                except Exception:
                    logger.exception("Emailul de resetare a parolei nu a putut fi trimis")
        return redirect("parola_reset_trimisa")
    return render(request, "registration/parola_reset_form.html", {"form": form})


def parola_reset_trimisa(request):
    return render(request, "registration/parola_reset_trimisa.html")


def parola_reset_confirmare(request, uidb64, token):
    utilizator = _utilizator_pentru_uid(uidb64)
    token_valid = bool(utilizator and default_token_generator.check_token(utilizator, token))
    if not token_valid:
        return render(
            request,
            "registration/parola_reset_invalida.html",
            status=400,
        )

    form = SetareParolaNouaForm(utilizator, request.POST or None)
    if request.method == "POST" and form.is_valid():
        seteaza_parola(utilizator, form.cleaned_data["new_password1"])
        return redirect("parola_reset_completa")
    return render(
        request,
        "registration/parola_reset_confirmare.html",
        {"form": form},
    )


def parola_reset_completa(request):
    return render(request, "registration/parola_reset_completa.html")
