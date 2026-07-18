import logging

from django.db import connections

from documente.storage import get_document_storage

logger = logging.getLogger(__name__)


def verifica_baza(alias: str = "default") -> bool:
    try:
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone() == (1,)
    except Exception:
        logger.exception("Verificarea bazei de date %s a eșuat", alias)
        return False


def verifica_storage() -> bool:
    try:
        get_document_storage().healthcheck()
        return True
    except Exception:
        logger.exception("Verificarea storage-ului a eșuat")
        return False


def stare_readiness() -> dict[str, bool]:
    return {
        "database": verifica_baza(),
        "storage": verifica_storage(),
    }
