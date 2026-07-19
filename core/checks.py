import shutil

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
    if settings.DOCUMENT_OCR_ENABLED:
        if not settings.DOCUMENT_OCR_COMMAND or not shutil.which(settings.DOCUMENT_OCR_COMMAND):
            errors.append(
                Error(
                    "Install the configured DOCUMENT_OCR_COMMAND before enabling OCR.",
                    id="core.E017",
                )
            )
        if not settings.DOCUMENT_OCR_LANGUAGES:
            errors.append(
                Error(
                    "Set DOCUMENT_OCR_LANGUAGES before enabling OCR.",
                    id="core.E018",
                )
            )
        if not 10 <= settings.DOCUMENT_OCR_TIMEOUT_SECONDS <= 300:
            errors.append(
                Error(
                    "DOCUMENT_OCR_TIMEOUT_SECONDS must be between 10 and 300.",
                    id="core.E019",
                )
            )
        if not 1 <= settings.DOCUMENT_OCR_MIN_TEXT_CHARS <= 1000:
            errors.append(
                Error(
                    "DOCUMENT_OCR_MIN_TEXT_CHARS must be between 1 and 1000.",
                    id="core.E020",
                )
            )
    if settings.DOCUMENT_AI_ENABLED:
        if settings.DOCUMENT_AI_PROVIDER not in {"openai", "deepseek"}:
            errors.append(
                Error(
                    "DOCUMENT_AI_PROVIDER must be openai or deepseek.",
                    id="core.E012",
                )
            )
        elif settings.DOCUMENT_AI_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
            errors.append(
                Error(
                    "Set OPENAI_API_KEY before enabling document AI.",
                    id="core.E013",
                )
            )
        elif settings.DOCUMENT_AI_PROVIDER == "deepseek" and not settings.DEEPSEEK_API_KEY:
            errors.append(
                Error(
                    "Set DEEPSEEK_API_KEY before enabling document AI.",
                    id="core.E014",
                )
            )
        if not settings.DOCUMENT_AI_MODEL:
            errors.append(
                Error(
                    "Set DOCUMENT_AI_MODEL before enabling document AI.",
                    id="core.E015",
                )
            )
        if not 10 <= settings.DOCUMENT_AI_TIMEOUT_SECONDS <= 600:
            errors.append(
                Error(
                    "DOCUMENT_AI_TIMEOUT_SECONDS must be between 10 and 600.",
                    id="core.E016",
                )
            )
    return errors
