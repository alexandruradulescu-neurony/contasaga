import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BASE_DIR / ".env")


def env_list(name: str, default: str = "") -> list[str]:
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = env_bool("DJANGO_DEBUG")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "conturi",
    "firme",
    "perioade",
    "documente",
    "notificari",
    "exporturi",
    "logistica",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.RLSMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "notificari.context_processors.notificari_necitite",
            ],
        },
    }
]


def postgres_connection(user_variable: str, password_variable: str) -> dict[str, object]:
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "conta_saga"),
        "USER": os.environ[user_variable],
        "PASSWORD": os.environ[password_variable],
        "HOST": os.getenv("POSTGRES_HOST", "127.0.0.1"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 0,
        "ATOMIC_REQUESTS": False,
    }


DATABASES = {
    "default": postgres_connection("POSTGRES_WEB_USER", "POSTGRES_WEB_PASSWORD"),
    "privileged": postgres_connection("POSTGRES_PRIVILEGED_USER", "POSTGRES_PRIVILEGED_PASSWORD"),
}
DATABASE_ROUTERS = ["config.db_routers.DefaultDatabaseRouter"]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
        "OPTIONS": {"MAX_ENTRIES": 10000},
    }
}

AUTH_USER_MODEL = "conturi.Utilizator"
AUTHENTICATION_BACKENDS = ["conturi.backends.PrivilegedAuthenticationBackend"]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ro-ro"
TIME_ZONE = "Europe/Bucharest"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DOCUMENT_STORAGE_BACKEND = os.getenv("DOCUMENT_STORAGE_BACKEND", "local")
DOCUMENT_LOCAL_STORAGE_ROOT = Path(
    os.getenv("DOCUMENT_LOCAL_STORAGE_ROOT", BASE_DIR / ".local-storage")
)
DOCUMENT_UPLOAD_MAX_BYTES = 25 * 1024 * 1024
DOCUMENT_UPLOAD_MAX_PAGES = 300
DOCUMENT_UPLOAD_URL_TTL = 3600
DOCUMENT_DOWNLOAD_URL_TTL = int(os.getenv("DOCUMENT_DOWNLOAD_URL_TTL", "300"))
DATA_UPLOAD_MAX_MEMORY_SIZE = DOCUMENT_UPLOAD_MAX_BYTES + 1024
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME")

EMAIL_BACKEND = os.getenv(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.getenv("DJANGO_DEFAULT_FROM_EMAIL", "Conta Saga <no-reply@localhost>")
EMAIL_HOST = os.getenv("DJANGO_EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("DJANGO_EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.getenv("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("DJANGO_EMAIL_USE_TLS")
EMAIL_USE_SSL = env_bool("DJANGO_EMAIL_USE_SSL")
EMAIL_TIMEOUT = int(os.getenv("DJANGO_EMAIL_TIMEOUT", "10"))

LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS", "5"))
LOGIN_RATE_LIMIT_IP_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_IP_ATTEMPTS", "25"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
PASSWORD_RESET_RATE_LIMIT_ATTEMPTS = int(os.getenv("PASSWORD_RESET_RATE_LIMIT_ATTEMPTS", "3"))
PASSWORD_RESET_RATE_LIMIT_IP_ATTEMPTS = int(
    os.getenv("PASSWORD_RESET_RATE_LIMIT_IP_ATTEMPTS", "20")
)
PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS = int(
    os.getenv("PASSWORD_RESET_RATE_LIMIT_WINDOW_SECONDS", "900")
)
CLIENT_IP_HEADER = os.getenv("DJANGO_CLIENT_IP_HEADER", "")

RELEASE_ENVIRONMENT = os.getenv("RELEASE_ENVIRONMENT", "development")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
    },
}

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"
