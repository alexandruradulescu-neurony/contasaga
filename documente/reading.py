import hashlib
import io
import re
import subprocess
import warnings
from dataclasses import dataclass
from datetime import timedelta

import fitz
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

from .models import AnalizaFisierInbox, FisierInbox, PaginaFisierInbox
from .storage import EroareStorage, get_document_storage

LEASE_CITIRE = timedelta(minutes=15)
MAX_INCERCARI_CITIRE = 3
MAX_PAGINI = 300
MAX_TEXT_PAGINA = 100_000
MAX_DIMENSIUNE_PREVIEW = 1400
MAX_DIMENSIUNE_OCR = 3500
Image.MAX_IMAGE_PIXELS = 50_000_000


class EroareCitireDocument(Exception):
    """Eroare sigură, potrivită pentru jurnal și reîncercare."""


@dataclass(frozen=True)
class PaginaCitita:
    numar: int
    metoda: str
    text: str
    preview: bytes
    latime: int
    inaltime: int
    incredere_ocr: float | None = None


def _cheie_preview(fisier: FisierInbox, numar_pagina: int) -> str:
    cheie = fisier.storage_key or ""
    prefix = cheie.split("/originals/", 1)[0]
    if not prefix:
        raise EroareCitireDocument("Cheia originalului din inbox este invalidă.")
    return f"{prefix}/previews/{fisier.pk}/{numar_pagina:04d}.png"


def _png_din_imagine(image: Image.Image, *, limita: int) -> tuple[bytes, int, int]:
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((limita, limita), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue(), image.width, image.height


def _ocr(png: bytes) -> str:
    if not settings.DOCUMENT_OCR_ENABLED:
        return ""
    comanda = [
        settings.DOCUMENT_OCR_COMMAND,
        "stdin",
        "stdout",
        "-l",
        settings.DOCUMENT_OCR_LANGUAGES,
        "--psm",
        "6",
    ]
    try:
        rezultat = subprocess.run(  # noqa: S603
            comanda,
            input=png,
            capture_output=True,
            check=False,
            timeout=settings.DOCUMENT_OCR_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise EroareCitireDocument(
            "Motorul OCR local nu este instalat sau nu este în PATH."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise EroareCitireDocument("Citirea OCR a unei pagini a depășit timpul permis.") from exc
    if rezultat.returncode != 0:
        mesaj = rezultat.stderr.decode("utf-8", errors="replace").strip()
        raise EroareCitireDocument(
            f"Motorul OCR nu a putut citi pagina: {mesaj[:500] or 'eroare necunoscută'}."
        )
    return rezultat.stdout.decode("utf-8", errors="replace").strip()[:MAX_TEXT_PAGINA]


def _citeste_pdf(continut: bytes) -> list[PaginaCitita]:
    try:
        document = fitz.open(stream=continut, filetype="pdf")
    except (fitz.FileDataError, RuntimeError, ValueError) as exc:
        raise EroareCitireDocument("PDF-ul este corupt sau nu poate fi deschis.") from exc
    try:
        if not 1 <= document.page_count <= MAX_PAGINI:
            raise EroareCitireDocument(f"PDF-ul trebuie să aibă între 1 și {MAX_PAGINI} pagini.")
        pagini = []
        for index, page in enumerate(document):
            text_pdf = page.get_text("text").strip()[:MAX_TEXT_PAGINA]
            dimensiune_maxima = max(page.rect.width, page.rect.height, 1)
            scala_preview = min(1.5, MAX_DIMENSIUNE_PREVIEW / dimensiune_maxima)
            pix_preview = page.get_pixmap(
                matrix=fitz.Matrix(scala_preview, scala_preview),
                alpha=False,
            )
            preview = pix_preview.tobytes("png")
            latime, inaltime = pix_preview.width, pix_preview.height
            if len(text_pdf) >= settings.DOCUMENT_OCR_MIN_TEXT_CHARS:
                metoda = PaginaFisierInbox.Metoda.TEXT_PDF
                text = text_pdf
            else:
                scala_ocr = min(2.5, MAX_DIMENSIUNE_OCR / dimensiune_maxima)
                pix_ocr = page.get_pixmap(
                    matrix=fitz.Matrix(scala_ocr, scala_ocr),
                    alpha=False,
                )
                text_ocr = _ocr(pix_ocr.tobytes("png"))
                text = text_ocr or text_pdf
                metoda = (
                    PaginaFisierInbox.Metoda.TESSERACT
                    if text_ocr
                    else PaginaFisierInbox.Metoda.FARA_TEXT
                )
            pagini.append(
                PaginaCitita(
                    numar=index + 1,
                    metoda=metoda,
                    text=text,
                    preview=preview,
                    latime=latime,
                    inaltime=inaltime,
                )
            )
        return pagini
    except EroareCitireDocument:
        raise
    except (RuntimeError, ValueError) as exc:
        raise EroareCitireDocument("Una dintre paginile PDF nu a putut fi citită.") from exc
    finally:
        document.close()


def _citeste_imagine(continut: bytes) -> list[PaginaCitita]:
    register_heif_opener()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(continut)) as sursa:
                sursa.load()
                image = ImageOps.exif_transpose(sursa).convert("RGB")
                preview, latime, inaltime = _png_din_imagine(
                    image.copy(),
                    limita=MAX_DIMENSIUNE_PREVIEW,
                )
                ocr_png, _, _ = _png_din_imagine(image, limita=MAX_DIMENSIUNE_OCR)
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        raise EroareCitireDocument("Imaginea este coruptă sau nu poate fi deschisă.") from exc
    text = _ocr(ocr_png)
    return [
        PaginaCitita(
            numar=1,
            metoda=(
                PaginaFisierInbox.Metoda.TESSERACT if text else PaginaFisierInbox.Metoda.FARA_TEXT
            ),
            text=text,
            preview=preview,
            latime=latime,
            inaltime=inaltime,
        )
    ]


def citeste_continut(*, continut: bytes, mime_type: str) -> list[PaginaCitita]:
    if mime_type == "application/pdf":
        return _citeste_pdf(continut)
    if mime_type.startswith("image/"):
        return _citeste_imagine(continut)
    raise EroareCitireDocument("Tipul fișierului nu poate fi citit pentru extragere.")


_TIP_DOCUMENT = re.compile(
    r"\b(factur(?:a|ă)|extras\s+de\s+cont|bon\s+(?:fiscal|de\s+consum)|chitan(?:ta|ță))\b",
    re.IGNORECASE,
)
_NUMAR_DOCUMENT = re.compile(
    r"\b(?:nr\.?|num[aă]r(?:ul)?)\s*[:.]?\s*([A-Z0-9][A-Z0-9./_-]{2,30})\b",
    re.IGNORECASE,
)


def sugereaza_limite(pagini: list[PaginaCitita]) -> list[dict]:
    """Propune numai rupturi susținute de un identificator clar schimbat."""
    inceputuri = [1]
    identificator_anterior = None
    for pagina in pagini:
        tip = _TIP_DOCUMENT.search(pagina.text[:3000])
        numar = _NUMAR_DOCUMENT.search(pagina.text[:3000])
        identificator = None
        if tip and numar:
            identificator = (
                tip.group(1).lower().replace("ă", "a").replace("ț", "t"),
                numar.group(1).upper(),
            )
        if (
            pagina.numar > 1
            and identificator
            and identificator_anterior
            and identificator != identificator_anterior
        ):
            inceputuri.append(pagina.numar)
        if identificator:
            identificator_anterior = identificator

    limite = []
    for pozitie, start in enumerate(inceputuri):
        sfarsit = inceputuri[pozitie + 1] - 1 if pozitie + 1 < len(inceputuri) else len(pagini)
        limite.append(
            {
                "pagina_start": start,
                "pagina_sfarsit": sfarsit,
                "sursa": "heuristica" if len(inceputuri) > 1 else "implicit",
                "incredere": 0.75 if len(inceputuri) > 1 else 0.0,
            }
        )
    return limite


def _poate_fi_citita(analiza: AnalizaFisierInbox, *, moment) -> bool:
    if analiza.status_revizuire != AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE:
        return False
    if analiza.incercari_citire >= MAX_INCERCARI_CITIRE:
        return False
    if analiza.status_citire == AnalizaFisierInbox.StatusCitire.IN_LUCRU:
        return bool(
            analiza.citire_inceputa_la and analiza.citire_inceputa_la <= moment - LEASE_CITIRE
        )
    return bool(
        analiza.status_citire
        in {
            AnalizaFisierInbox.StatusCitire.IN_ASTEPTARE,
            AnalizaFisierInbox.StatusCitire.EROARE,
        }
        and analiza.reincearca_citire_dupa <= moment
    )


def _salveaza_eroare(*, analiza_id, incercare, exc):
    with transaction.atomic(using="privileged"):
        analiza = (
            AnalizaFisierInbox.objects.using("privileged")
            .select_for_update(of=("self",))
            .get(pk=analiza_id)
        )
        if (
            analiza.status_citire != AnalizaFisierInbox.StatusCitire.IN_LUCRU
            or analiza.incercari_citire != incercare
            or analiza.status_revizuire != AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE
        ):
            return analiza
        analiza.status_citire = AnalizaFisierInbox.StatusCitire.EROARE
        analiza.citire_inceputa_la = None
        analiza.eroare_citire = str(exc)[:2000]
        analiza.reincearca_citire_dupa = timezone.now() + timedelta(
            minutes=5**analiza.incercari_citire
        )
        analiza.save(
            using="privileged",
            update_fields=[
                "status_citire",
                "citire_inceputa_la",
                "eroare_citire",
                "reincearca_citire_dupa",
            ],
        )
        return analiza


def proceseaza_citire(analiza_id):
    moment = timezone.now()
    with transaction.atomic(using="privileged"):
        analiza = (
            AnalizaFisierInbox.objects.using("privileged")
            .select_for_update(of=("self",))
            .select_related("fisier_inbox")
            .get(pk=analiza_id)
        )
        fisier = analiza.fisier_inbox
        if (
            analiza.status_citire == AnalizaFisierInbox.StatusCitire.IN_LUCRU
            and analiza.citire_inceputa_la
            and analiza.citire_inceputa_la <= moment - LEASE_CITIRE
            and analiza.incercari_citire >= MAX_INCERCARI_CITIRE
        ):
            analiza.status_citire = AnalizaFisierInbox.StatusCitire.EROARE
            analiza.citire_inceputa_la = None
            analiza.eroare_citire = (
                "Procesarea ultimei încercări a fost întreruptă înainte de finalizare."
            )
            analiza.save(
                using="privileged",
                update_fields=["status_citire", "citire_inceputa_la", "eroare_citire"],
            )
            return analiza
        if fisier.status != FisierInbox.Status.DISPONIBIL:
            return analiza
        if not _poate_fi_citita(analiza, moment=moment):
            return analiza
        analiza.status_citire = AnalizaFisierInbox.StatusCitire.IN_LUCRU
        analiza.incercari_citire += 1
        analiza.citire_inceputa_la = moment
        analiza.eroare_citire = None
        analiza.save(
            using="privileged",
            update_fields=[
                "status_citire",
                "incercari_citire",
                "citire_inceputa_la",
                "eroare_citire",
            ],
        )
        incercare_curenta = analiza.incercari_citire

    storage = get_document_storage()
    chei_preview = []
    try:
        continut = storage.read_bytes(fisier.storage_key)
        if hashlib.sha256(continut).hexdigest() != fisier.checksum:
            raise EroareCitireDocument(
                "Originalul nu mai corespunde checksum-ului înregistrat în inbox."
            )
        if fisier.mime_type == "application/pdf":
            pagini = _citeste_pdf(continut)
        elif fisier.mime_type.startswith("image/"):
            pagini = _citeste_imagine(continut)
        else:
            raise EroareCitireDocument("Tipul de fișier nu este acceptat pentru citire.")
        limite = sugereaza_limite(pagini)
        for pagina in pagini:
            cheie = _cheie_preview(fisier, pagina.numar)
            storage.put_bytes(cheie, pagina.preview, "image/png")
            chei_preview.append(cheie)
    except (EroareCitireDocument, EroareStorage, OSError) as exc:
        analiza = _salveaza_eroare(
            analiza_id=analiza_id,
            incercare=incercare_curenta,
            exc=exc,
        )
        if (
            analiza.status_citire == AnalizaFisierInbox.StatusCitire.EROARE
            and analiza.incercari_citire == incercare_curenta
        ):
            for cheie in chei_preview:
                storage.delete(cheie)
        return analiza

    try:
        with transaction.atomic(using="privileged"):
            analiza = (
                AnalizaFisierInbox.objects.using("privileged")
                .select_for_update(of=("self",))
                .get(pk=analiza_id)
            )
            if (
                analiza.status_citire != AnalizaFisierInbox.StatusCitire.IN_LUCRU
                or analiza.incercari_citire != incercare_curenta
                or analiza.status_revizuire != AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE
            ):
                return analiza
            PaginaFisierInbox.objects.using("privileged").filter(analiza_id=analiza.pk).delete()
            PaginaFisierInbox.objects.using("privileged").bulk_create(
                [
                    PaginaFisierInbox(
                        analiza_id=analiza.pk,
                        fisier_inbox_id=fisier.pk,
                        firma_id=fisier.firma_id,
                        perioada_contabila_id=fisier.perioada_contabila_id,
                        numar_pagina=pagina.numar,
                        metoda=pagina.metoda,
                        text_extras=pagina.text,
                        incredere_ocr=pagina.incredere_ocr,
                        preview_storage_key=cheie,
                        preview_checksum=hashlib.sha256(pagina.preview).hexdigest(),
                        latime_preview=pagina.latime,
                        inaltime_preview=pagina.inaltime,
                    )
                    for pagina, cheie in zip(pagini, chei_preview, strict=True)
                ]
            )
            metode = {pagina.metoda for pagina in pagini}
            if PaginaFisierInbox.Metoda.TESSERACT in metode:
                metoda = "ocr_mixt" if len(metode) > 1 else "tesseract"
            elif PaginaFisierInbox.Metoda.TEXT_PDF in metode:
                metoda = "text_pdf"
            else:
                metoda = "fara_text"
            analiza.status_citire = AnalizaFisierInbox.StatusCitire.FINALIZATA
            analiza.citire_inceputa_la = None
            analiza.citire_finalizata_la = timezone.now()
            analiza.eroare_citire = None
            analiza.metoda_citire = metoda
            analiza.numar_pagini = len(pagini)
            analiza.limite_sugerate = limite
            analiza.save(
                using="privileged",
                update_fields=[
                    "status_citire",
                    "citire_inceputa_la",
                    "citire_finalizata_la",
                    "eroare_citire",
                    "metoda_citire",
                    "numar_pagini",
                    "limite_sugerate",
                ],
            )
            return analiza
    except Exception:
        # Cheile sunt deterministe și provin dintr-o sursă imuabilă. Nu le
        # ștergem după un rollback DB: rândurile vechi pot indica aceleași
        # preview-uri, iar reîncercarea le va suprascrie idempotent.
        raise


def ids_citiri_de_procesat(*, limit: int) -> list:
    moment = timezone.now()
    limita_lease = moment - LEASE_CITIRE
    return list(
        AnalizaFisierInbox.objects.using("privileged")
        .filter(
            status_revizuire=AnalizaFisierInbox.StatusRevizuire.IN_ASTEPTARE,
            fisier_inbox__status=FisierInbox.Status.DISPONIBIL,
        )
        .filter(
            Q(
                status_citire__in=(
                    AnalizaFisierInbox.StatusCitire.IN_ASTEPTARE,
                    AnalizaFisierInbox.StatusCitire.EROARE,
                ),
                reincearca_citire_dupa__lte=moment,
                incercari_citire__lt=MAX_INCERCARI_CITIRE,
            )
            | Q(
                status_citire=AnalizaFisierInbox.StatusCitire.IN_LUCRU,
                citire_inceputa_la__lte=limita_lease,
            )
        )
        .order_by("reincearca_citire_dupa", "creat_la")
        .values_list("pk", flat=True)[:limit]
    )


def proceseaza_coada_citire(*, limit: int = 20) -> tuple[int, int]:
    finalizate = 0
    erori = 0
    for analiza_id in ids_citiri_de_procesat(limit=limit):
        analiza = proceseaza_citire(analiza_id)
        if analiza.status_citire == AnalizaFisierInbox.StatusCitire.FINALIZATA:
            finalizate += 1
        elif analiza.status_citire == AnalizaFisierInbox.StatusCitire.EROARE:
            erori += 1
    return finalizate, erori
