from typing import Any

from django.contrib.auth.base_user import BaseUserManager


class UtilizatorManager(BaseUserManager):
    use_in_migrations = True

    def get_queryset(self):
        # Hash-ul nu este selectabil prin rolul web. Îl lăsăm deferred și îl
        # cerem explicit doar în backend-ul privilegiat de autentificare.
        return super().get_queryset().defer("password")

    def _create_user(self, email: str, password: str | None, **extra_fields: Any):
        if not email:
            raise ValueError("Emailul este obligatoriu")
        email = self.normalize_email(email).strip().lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db or "default")
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        if extra_fields["is_staff"] or extra_fields["is_superuser"]:
            raise ValueError("create_user nu poate acorda privilegii de platformă")
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields: Any):
        extra_fields.update(
            {
                "rol": "superuser_platforma",
                "cabinet_id": None,
                "is_staff": True,
                "is_superuser": True,
            }
        )
        return self._create_user(email, password, **extra_fields)
