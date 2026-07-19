import io
from unittest.mock import patch

import fitz
from django.test import SimpleTestCase, override_settings
from PIL import Image

from documente.models import PaginaFisierInbox
from documente.reading import (
    PaginaCitita,
    _citeste_imagine,
    _citeste_pdf,
    _ocr,
    sugereaza_limite,
)
from documente.segmentation import (
    EroareClasificareInbox,
    SegmentDocument,
    _extrage_segment,
    _valideaza_acoperire,
)


def pdf_cu_pagini(*texte: str) -> bytes:
    document = fitz.open()
    for text in texte:
        page = document.new_page()
        page.insert_text((72, 72), text)
    continut = document.tobytes()
    document.close()
    return continut


class CitireLocalaTests(SimpleTestCase):
    @override_settings(DOCUMENT_OCR_ENABLED=True, DOCUMENT_OCR_MIN_TEXT_CHARS=10)
    @patch("documente.reading._ocr")
    def test_pdf_textual_uses_embedded_text_and_builds_preview(self, ocr):
        pagini = _citeste_pdf(
            pdf_cu_pagini(
                "Factura numarul 100 furnizor Demo SRL",
                "Continuare factura numarul 100",
            )
        )

        self.assertEqual(len(pagini), 2)
        self.assertEqual(pagini[0].metoda, PaginaFisierInbox.Metoda.TEXT_PDF)
        self.assertTrue(pagini[0].preview.startswith(b"\x89PNG"))
        ocr.assert_not_called()

    @override_settings(DOCUMENT_OCR_ENABLED=True)
    @patch("documente.reading._ocr", return_value="Bon fiscal numarul 200")
    def test_image_uses_ocr_and_keeps_page_preview(self, ocr):
        output = io.BytesIO()
        Image.new("RGB", (800, 600), "white").save(output, format="PNG")

        pagini = _citeste_imagine(output.getvalue())

        self.assertEqual(pagini[0].metoda, PaginaFisierInbox.Metoda.TESSERACT)
        self.assertEqual(pagini[0].text, "Bon fiscal numarul 200")
        self.assertLessEqual(max(pagini[0].latime, pagini[0].inaltime), 1400)
        ocr.assert_called_once()

    @override_settings(
        DOCUMENT_OCR_ENABLED=True,
        DOCUMENT_OCR_COMMAND="tesseract",
        DOCUMENT_OCR_LANGUAGES="ron+eng",
        DOCUMENT_OCR_TIMEOUT_SECONDS=30,
    )
    @patch("documente.reading.subprocess.run")
    def test_tesseract_is_invoked_without_a_shell(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = b"Factura"
        run.return_value.stderr = b""

        self.assertEqual(_ocr(b"png"), "Factura")

        args = run.call_args.args[0]
        self.assertEqual(args[:3], ["tesseract", "stdin", "stdout"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_boundary_heuristic_splits_only_on_changed_strong_identifier(self):
        pagini = [
            PaginaCitita(1, "text_pdf", "Factura nr. ABC-100", b"png", 1, 1),
            PaginaCitita(2, "text_pdf", "Detalii factura ABC-100", b"png", 1, 1),
            PaginaCitita(3, "text_pdf", "Factura nr. XYZ-200", b"png", 1, 1),
        ]

        limite = sugereaza_limite(pagini)

        self.assertEqual(
            [(item["pagina_start"], item["pagina_sfarsit"]) for item in limite],
            [(1, 2), (3, 3)],
        )

    @override_settings(DOCUMENT_OCR_ENABLED=False, DOCUMENT_OCR_MIN_TEXT_CHARS=10)
    def test_pdf_preview_is_bounded_even_for_oversized_page(self):
        document = fitz.open()
        page = document.new_page(width=10_000, height=8_000)
        page.insert_text((72, 72), "Factura cu text suficient")
        continut = document.tobytes()
        document.close()

        pagina = _citeste_pdf(continut)[0]

        self.assertLessEqual(max(pagina.latime, pagina.inaltime), 1400)


class SegmentareTests(SimpleTestCase):
    def test_segments_must_cover_every_page_once(self):
        with self.assertRaisesMessage(EroareClasificareInbox, "fără goluri"):
            _valideaza_acoperire(
                segmente=[SegmentDocument(2, 3, "tip", None, "primit")],
                numar_pagini=3,
            )

    def test_pdf_segment_contains_only_selected_pages(self):
        continut = pdf_cu_pagini("Prima factura", "A doua factura", "A treia factura")

        derivat, mime_type, metoda = _extrage_segment(
            continut=continut,
            mime_type="application/pdf",
            pagina_start=2,
            pagina_sfarsit=3,
        )

        with fitz.open(stream=derivat, filetype="pdf") as document:
            self.assertEqual(document.page_count, 2)
            self.assertIn("A doua factura", document[0].get_text())
            self.assertIn("A treia factura", document[1].get_text())
        self.assertEqual(mime_type, "application/pdf")
        self.assertEqual(metoda, "extragere_pagini")

    def test_whole_pdf_derivation_preserves_exact_source_bytes(self):
        continut = pdf_cu_pagini("Factura completa", "Pagina a doua")

        derivat, _, metoda = _extrage_segment(
            continut=continut,
            mime_type="application/pdf",
            pagina_start=1,
            pagina_sfarsit=2,
        )

        self.assertEqual(derivat, continut)
        self.assertEqual(metoda, "copie_integrala")
