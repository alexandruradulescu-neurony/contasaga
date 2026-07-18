from uuid import UUID

from django.contrib.auth.hashers import make_password
from django.utils import timezone

from .models import Utilizator


def inregistreaza_autentificare(utilizator_id: UUID):
    """Actualizează last_login numai după validarea parolei."""

    moment = timezone.now()
    Utilizator.objects.using("privileged").filter(pk=utilizator_id).update(last_login=moment)
    return moment


def seteaza_parola(utilizator: Utilizator, parola: str) -> None:
    """Setează parola dintr-un flux privilegiat, precum reset/invitație."""

    Utilizator.objects.using("privileged").filter(pk=utilizator.pk).update(
        password=make_password(parola)
    )
