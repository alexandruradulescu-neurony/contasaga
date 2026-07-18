from .base import *  # noqa: F403

DATABASES["default"] = postgres_connection(  # noqa: F405
    "POSTGRES_MIGRATION_USER", "POSTGRES_MIGRATION_PASSWORD"
)
