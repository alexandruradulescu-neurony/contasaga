import csv
import io
from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from documente.ai.contracts import ContextAnalizaDocument
from documente.ai.providers import _normalizeaza_campuri_structurate
from documente.archive import FisierPregatit, _categorie, _manifest, _nume_arhiva
from documente.models import Document


class StructuredExtractionNormalizationTests(SimpleTestCase):
    def context(self):
        return ContextAnalizaDocument(
            nume_fisier="factura.pdf",
            mime_type="application/pdf",
            continut=b"pdf",
            denumire_firma="Client Demo SRL",
            cui_firma="RO123456",
            tipuri_document=(),
            conturi_financiare=(),
        )

    def test_fields_are_bounded_normalized_and_totals_are_validated(self):
        campuri, avertismente = _normalizeaza_campuri_structurate(
            {
                "issuer_name": "Furnizor Demo",
                "issuer_tax_id": "RO999",
                "recipient_name": "Client Demo",
                "recipient_tax_id": "RO123456",
                "series": "F",
                "number": "100",
                "document_date": "2026-07-10",
                "due_date": "2026-07-01",
                "currency": "ron",
                "net_amount": "100.005",
                "vat_amount": "19",
                "total_amount": "120",
            },
            context=self.context(),
            directie="primit",
        )

        self.assertEqual(campuri["currency"], "RON")
        self.assertEqual(campuri["net_amount"], "100.01")
        self.assertIn("Totalul", " ".join(avertismente))
        self.assertIn("scadenței", " ".join(avertismente))

    def test_invalid_provider_values_are_discarded_not_promoted(self):
        campuri, avertismente = _normalizeaza_campuri_structurate(
            {
                "document_date": "10/07/2026",
                "currency": "RONX",
                "net_amount": "not-a-number",
            },
            context=self.context(),
            directie="emis",
        )

        self.assertIsNone(campuri["document_date"])
        self.assertIsNone(campuri["currency"])
        self.assertIsNone(campuri["net_amount"])
        self.assertGreaterEqual(len(avertismente), 3)

    def test_unknown_direction_does_not_create_a_false_customer_tax_id_warning(self):
        _, avertismente = _normalizeaza_campuri_structurate(
            {
                "issuer_tax_id": "RO999",
                "recipient_tax_id": "RO888",
            },
            context=self.context(),
            directie=None,
        )

        self.assertNotIn("firmei cliente", " ".join(avertismente))


class MonthlyArchiveNamingTests(SimpleTestCase):
    def document(self):
        return SimpleNamespace(
            id=uuid4(),
            directie=Document.Directie.PRIMIT,
            data_document=None,
            partener_id=None,
            partener=None,
            serie=None,
            numar=None,
            tip_document=SimpleNamespace(cod="factura furnizor"),
        )

    def test_category_and_filename_are_human_readable_and_collision_safe(self):
        document = self.document()
        fisier = SimpleNamespace(pk=uuid4(), nume_original="Factură iulie 2026.PDF")

        self.assertEqual(_categorie(document), "primite/factura-furnizor")
        nume = _nume_arhiva(document=document, fisier=fisier, ordine=7)
        self.assertTrue(nume.startswith("0007__factura-iulie-2026__"))
        self.assertTrue(nume.endswith(".pdf"))

    def test_manifest_is_utf8_csv_and_escapes_spreadsheet_formulas(self):
        arhiva = SimpleNamespace(versiune=2)
        fisier = FisierPregatit(
            ordine=1,
            document_id=uuid4(),
            fisier_document_id=uuid4(),
            categorie="primite/factura",
            cale_relativa="primite/factura/0001__factura.pdf",
            storage_key_sursa="source",
            storage_key_staging="stage",
            storage_key_final="final",
            nume_original="=HYPERLINK(1)",
            mime_type="application/pdf",
            checksum="a" * 64,
            dimensiune=100,
            tip_document="factura",
            directie="primit",
            data_document="2026-07-10",
            partener=" \t+formula",
            serie="F",
            numar="100",
        )

        manifest = _manifest(arhiva, [fisier]).decode("utf-8-sig")
        randuri = list(csv.reader(io.StringIO(manifest)))

        self.assertIn("archive_version,sequence", manifest)
        self.assertIn("'=HYPERLINK(1)", manifest)
        self.assertIn("' \t+formula", manifest)
        self.assertEqual(len(randuri), 2)
        self.assertEqual(len(randuri[0]), 17)
        self.assertEqual(len(randuri[1]), len(randuri[0]))
