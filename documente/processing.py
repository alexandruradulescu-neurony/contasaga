import hashlib
import warnings
from datetime import timedelta
from io import BytesIO

import fitz
import pillow_heif
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageOps

from notificari.services import notifica_eroare_procesare_fisier

from .filetypes import detecteaza_tip, tipuri_compatibile
from .models import FisierDocument
from .storage import get_document_storage

pillow_heif.register_heif_opener()
Image.MAX_IMAGE_PIXELS = 50_000_000


class EroareProcesare(Exception):
    pass


LEASE_PROCESARE = timedelta(minutes=15)


def _procesare_expirata(fisier, *, moment=None) -> bool:
    moment = moment or timezone.now()
    return bool(
        fisier.stare_procesare == FisierDocument.StareProcesare.IN_LUCRU
        and fisier.procesare_inceputa_la
        and fisier.procesare_inceputa_la <= moment - LEASE_PROCESARE
    )


def poate_porni_procesarea(fisier, *, moment=None) -> bool:
    return bool(
        not fisier.sters_la
        and fisier.incercari_procesare < 3
        and (
            fisier.stare_procesare
            in {
                FisierDocument.StareProcesare.IN_ASTEPTARE,
                FisierDocument.StareProcesare.EROARE,
            }
            or _procesare_expirata(fisier, moment=moment)
        )
    )


def _thumbnail_pdf(continut: bytes) -> tuple[int, bytes]:
    try:
        document_pdf = fitz.open(stream=continut, filetype="pdf")
    except Exception as exc:
        raise EroareProcesare("PDF-ul nu poate fi deschis.") from exc
    with document_pdf:
        numar_pagini = document_pdf.page_count
        if numar_pagini < 1:
            raise EroareProcesare("PDF-ul nu conține pagini.")
        if numar_pagini > settings.DOCUMENT_UPLOAD_MAX_PAGES:
            raise EroareProcesare(
                f"PDF-ul depășește limita de {settings.DOCUMENT_UPLOAD_MAX_PAGES} pagini."
            )
        pagina = document_pdf.load_page(0)
        dreptunghi = pagina.rect
        factor = min(1.0, 420 / max(dreptunghi.width, dreptunghi.height))
        pixmap = pagina.get_pixmap(matrix=fitz.Matrix(factor, factor), alpha=False)
        return numar_pagini, pixmap.tobytes("png")


def _thumbnail_imagine(continut: bytes) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(continut)) as imagine:
                imagine.load()
                imagine = ImageOps.exif_transpose(imagine)
                imagine.thumbnail((420, 420))
                if imagine.mode not in {"RGB", "RGBA"}:
                    imagine = imagine.convert("RGB")
                rezultat = BytesIO()
                imagine.save(rezultat, format="PNG", optimize=True)
                return rezultat.getvalue()
    except Exception as exc:
        raise EroareProcesare("Imaginea nu poate fi deschisă.") from exc


def proceseaza_fisier(fisier_id, *, reincearca=False):
    procesare_epuizata = False
    with transaction.atomic(using="privileged"):
        fisier = (
            FisierDocument.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=fisier_id)
        )
        if _procesare_expirata(fisier) and fisier.incercari_procesare >= 3:
            fisier.stare_procesare = FisierDocument.StareProcesare.EROARE
            fisier.procesare_inceputa_la = None
            fisier.eroare_procesare = (
                "Procesarea a fost întreruptă și a epuizat numărul maxim de încercări."
            )
            fisier.save(
                using="privileged",
                update_fields=[
                    "stare_procesare",
                    "procesare_inceputa_la",
                    "eroare_procesare",
                ],
            )
            procesare_epuizata = True
        elif not poate_porni_procesarea(fisier):
            # Două workere pot selecta același rând înainte ca primul să-l
            # blocheze. Al doilea nu trebuie să proceseze în paralel și să
            # inverseze rezultatul unei înlocuiri deja finalizate.
            return fisier
        else:
            fisier.stare_procesare = FisierDocument.StareProcesare.IN_LUCRU
            fisier.procesare_inceputa_la = timezone.now()
            fisier.incercari_procesare += 1
            fisier.eroare_procesare = None
            fisier.save(
                using="privileged",
                update_fields=[
                    "stare_procesare",
                    "procesare_inceputa_la",
                    "incercari_procesare",
                    "eroare_procesare",
                ],
            )

    if procesare_epuizata:
        notifica_eroare_procesare_fisier(fisier=fisier)
        return fisier

    storage = get_document_storage()
    try:
        continut = storage.read_bytes(fisier.storage_key)
        if not continut or len(continut) > settings.DOCUMENT_UPLOAD_MAX_BYTES:
            raise EroareProcesare("Dimensiunea fișierului este invalidă.")
        tip_detectat = detecteaza_tip(continut)
        if fisier.mime_type and not tipuri_compatibile(fisier.mime_type, tip_detectat):
            raise EroareProcesare("Conținutul nu corespunde tipului fișierului.")
        checksum = hashlib.sha256(continut).hexdigest()
        if tip_detectat == "application/pdf":
            numar_pagini, thumbnail = _thumbnail_pdf(continut)
        else:
            numar_pagini = 1
            thumbnail = _thumbnail_imagine(continut)
        thumbnail_key = f"thumbnails/{fisier.firma_id}/{fisier.pk}.png"
        storage.put_bytes(thumbnail_key, thumbnail, "image/png")
    except Exception as exc:
        with transaction.atomic(using="privileged"):
            fisier = (
                FisierDocument.objects.using("privileged").select_for_update().get(pk=fisier_id)
            )
            if fisier.sters_la:
                fisier.stare_procesare = FisierDocument.StareProcesare.EROARE
                fisier.procesare_inceputa_la = None
                fisier.eroare_procesare = "Procesarea a fost oprită după ștergerea fișierului."
                fisier.save(
                    using="privileged",
                    update_fields=[
                        "stare_procesare",
                        "procesare_inceputa_la",
                        "eroare_procesare",
                    ],
                )
                return fisier
            fisier.stare_procesare = FisierDocument.StareProcesare.EROARE
            fisier.procesare_inceputa_la = None
            fisier.eroare_procesare = str(exc)[:2000]
            fisier.save(
                using="privileged",
                update_fields=[
                    "stare_procesare",
                    "procesare_inceputa_la",
                    "eroare_procesare",
                ],
            )
        if fisier.incercari_procesare >= 3:
            notifica_eroare_procesare_fisier(fisier=fisier)
        return fisier

    inlocuire_depasita = False
    with transaction.atomic(using="privileged"):
        fisier = FisierDocument.objects.using("privileged").select_for_update().get(pk=fisier_id)
        if fisier.sters_la:
            # Fișierul poate fi eliminat de autor cât timp procesarea rulează
            # în afara tranzacției. Nu îl reactivăm după ștergere.
            fisier.stare_procesare = FisierDocument.StareProcesare.EROARE
            fisier.procesare_inceputa_la = None
            fisier.eroare_procesare = "Procesarea a fost oprită după ștergerea fișierului."
            fisier.save(
                using="privileged",
                update_fields=[
                    "stare_procesare",
                    "procesare_inceputa_la",
                    "eroare_procesare",
                ],
            )
            return fisier
        if fisier.inlocuieste_fisier_id:
            fisier_inlocuit = (
                FisierDocument.objects.using("privileged")
                .select_for_update()
                .get(pk=fisier.inlocuieste_fisier_id)
            )
            if not fisier_inlocuit.activ or fisier_inlocuit.sters_la:
                fisier.mime_type = tip_detectat
                fisier.dimensiune_bytes = len(continut)
                fisier.checksum = checksum
                fisier.numar_pagini = numar_pagini
                fisier.thumbnail_key = thumbnail_key
                fisier.stare_procesare = FisierDocument.StareProcesare.EROARE
                fisier.procesare_inceputa_la = None
                fisier.eroare_procesare = (
                    "Versiunea inițială a fost deja înlocuită. "
                    "Reîncarcă pagina și încearcă din nou."
                )
                fisier.incercari_procesare = 3
                fisier.activ = False
                fisier.save(
                    using="privileged",
                    update_fields=[
                        "mime_type",
                        "dimensiune_bytes",
                        "checksum",
                        "numar_pagini",
                        "thumbnail_key",
                        "stare_procesare",
                        "procesare_inceputa_la",
                        "eroare_procesare",
                        "incercari_procesare",
                        "activ",
                    ],
                )
                inlocuire_depasita = True
            else:
                fisier_inlocuit.activ = False
                fisier_inlocuit.save(using="privileged", update_fields=["activ"])
        if not inlocuire_depasita:
            fisier.mime_type = tip_detectat
            fisier.dimensiune_bytes = len(continut)
            fisier.checksum = checksum
            fisier.numar_pagini = numar_pagini
            fisier.thumbnail_key = thumbnail_key
            fisier.stare_procesare = FisierDocument.StareProcesare.PROCESAT
            fisier.procesare_inceputa_la = None
            fisier.eroare_procesare = None
            fisier.activ = True
            fisier.save(
                using="privileged",
                update_fields=[
                    "mime_type",
                    "dimensiune_bytes",
                    "checksum",
                    "numar_pagini",
                    "thumbnail_key",
                    "stare_procesare",
                    "procesare_inceputa_la",
                    "eroare_procesare",
                    "activ",
                ],
            )
    if inlocuire_depasita:
        notifica_eroare_procesare_fisier(fisier=fisier)
    return fisier
