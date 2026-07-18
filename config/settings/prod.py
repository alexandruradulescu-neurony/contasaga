import os

from .base import *  # noqa: F403
from .base import env_bool, env_list

DEBUG = False
RELEASE_ENVIRONMENT = "production"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
# Railway probes the container over the private HTTP network. Health endpoints
# contain no private data and must answer directly so the deployment gate can
# observe their real status; every application route still redirects to HTTPS.
SECURE_REDIRECT_EXEMPT = [r"^health/(?:live/|ready/)?$"]
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "3600"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS")
SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

if env_bool("DJANGO_TRUST_X_FORWARDED_PROTO"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

for database in DATABASES.values():  # noqa: F405
    database["CONN_MAX_AGE"] = int(os.getenv("POSTGRES_CONN_MAX_AGE", "60"))
    database["CONN_HEALTH_CHECKS"] = True
