from .base import *  # noqa: F403

DATABASES["default"] = DATABASES["privileged"].copy()  # noqa: F405
ROOT_URLCONF = "config.admin_urls"
