from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def production_configuration_checks(app_configs, **kwargs):
    if getattr(settings, "RELEASE_ENVIRONMENT", "development") != "production":
        return []

    errors = []
    if settings.DOCUMENT_STORAGE_BACKEND != "r2":
        errors.append(
            Error(
                "Production must use the R2 document storage backend.",
                id="core.E001",
            )
        )
    if settings.EMAIL_BACKEND == "django.core.mail.backends.console.EmailBackend":
        errors.append(
            Error(
                "Production must use a real email backend.",
                id="core.E002",
            )
        )
    invalid_hosts = {"localhost", "127.0.0.1", "*"}
    if not settings.ALLOWED_HOSTS or invalid_hosts.intersection(settings.ALLOWED_HOSTS):
        errors.append(
            Error(
                "Set explicit public hosts for production.",
                id="core.E003",
            )
        )
    if not settings.CSRF_TRUSTED_ORIGINS:
        errors.append(
            Error(
                "Set DJANGO_CSRF_TRUSTED_ORIGINS for production.",
                id="core.E004",
            )
        )
    cache_backend = settings.CACHES["default"]["BACKEND"]
    if cache_backend != "django.core.cache.backends.db.DatabaseCache":
        errors.append(
            Error(
                "Production login throttling requires the shared database cache.",
                id="core.E005",
            )
        )
    if (
        settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
        and settings.EMAIL_HOST in {"", "localhost"}
    ):
        errors.append(
            Error(
                "Set DJANGO_EMAIL_HOST for the production SMTP backend.",
                id="core.E006",
            )
        )
    if "@localhost" in settings.DEFAULT_FROM_EMAIL:
        errors.append(
            Error(
                "Set a deliverable DJANGO_DEFAULT_FROM_EMAIL address.",
                id="core.E007",
            )
        )
    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None) and not settings.CLIENT_IP_HEADER:
        errors.append(
            Error(
                "Set DJANGO_CLIENT_IP_HEADER when trusting a TLS proxy, "
                "and make the proxy overwrite it.",
                id="core.E008",
            )
        )
    limite_autentificare = (
        settings.LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS,
        settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        settings.PASSWORD_RESET_RATE_LIMIT_ATTEMPTS,
        settings.PASSWORD_RESET_RATE_LIMIT_IP_ATTEMPTS,
        settings.PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS,
    )
    if any(valoare < 1 for valoare in limite_autentificare):
        errors.append(
            Error(
                "Production authentication rate limits must all be positive.",
                id="core.E009",
            )
        )
    if not 30 <= settings.DOCUMENT_DOWNLOAD_URL_TTL <= 3600:
        errors.append(
            Error(
                "DOCUMENT_DOWNLOAD_URL_TTL must be between 30 and 3600 seconds.",
                id="core.E010",
            )
        )
    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        errors.append(
            Error(
                "DJANGO_EMAIL_USE_TLS and DJANGO_EMAIL_USE_SSL cannot both be enabled.",
                id="core.E011",
            )
        )
    return errors
