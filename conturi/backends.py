from typing import Any

from django.contrib.auth.backends import BaseBackend
from django.contrib.auth.hashers import check_password
from django.http import HttpRequest

from .models import Utilizator
from .services import inregistreaza_autentificare

AUTH_FIELDS = (
    "id",
    "cabinet_id",
    "nume",
    "email",
    "password",
    "rol",
    "telefon",
    "is_active",
    "is_staff",
    "is_superuser",
    "last_login",
    "creat_la",
)


def hydrate_default_user(values: dict[str, Any]) -> Utilizator:
    user = Utilizator(**values)
    user._state.adding = False
    user._state.db = "default"
    return user


class PrivilegedAuthenticationBackend(BaseBackend):
    """Citește hash-ul privilegiat, dar nu propagă instanța acelui alias."""

    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> Utilizator | None:
        email = username or kwargs.get(Utilizator.USERNAME_FIELD)
        if not email or password is None:
            return None

        values = (
            Utilizator.objects.using("privileged")
            .filter(email__iexact=email.strip())
            .values(*AUTH_FIELDS)
            .first()
        )
        if not values or not values["is_active"]:
            return None
        if not check_password(password, values["password"]):
            return None
        values["last_login"] = inregistreaza_autentificare(values["id"])
        return hydrate_default_user(values)

    def get_user(self, user_id) -> Utilizator | None:
        values = (
            Utilizator.objects.using("privileged")
            .filter(pk=user_id, is_active=True)
            .values(*AUTH_FIELDS)
            .first()
        )
        return hydrate_default_user(values) if values else None
