import hashlib
import tempfile
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

from django.test import SimpleTestCase
from django.utils import timezone

from exporturi.services import EroareExport, _construieste_zip, poate_solicita_export


class ExportServiceTests(SimpleTestCase):
    def _user(self, role, *, active=True):
        return SimpleNamespace(
            is_authenticated=True,
            is_active=active,
            rol=role,
        )

    def test_export_role_matrix(self):
        permise = {"contabil", "contabil_coordonator"}
        for rol in (
            "superuser_platforma",
            "admin_cabinet",
            "contabil_coordonator",
            "contabil",
            "client_admin",
            "client_operator",
        ):
            with self.subTest(rol=rol):
                self.assertIs(poate_solicita_export(self._user(rol)), rol in permise)
        self.assertFalse(poate_solicita_export(self._user("contabil", active=False)))

    @patch("exporturi.services.get_document_storage")
    @patch("exporturi.services._documente_export")
    def test_zip_is_deterministic_grouped_and_has_manifest(self, documente, get_storage):
        continut = b"continut document contabil"
        fisier = SimpleNamespace(
            storage_key="staging/test/document",
            nume_original="../Factură Iulie.PDF",
            checksum=hashlib.sha256(continut).hexdigest(),
        )
        documente.return_value = [
            SimpleNamespace(
                pk=uuid4(),
                tip_document=SimpleNamespace(
                    categorie="Achiziții & cheltuieli",
                    cod="factura",
                    denumire="Factură",
                ),
                cont_financiar=None,
                partener=SimpleNamespace(denumire="Furnizor Test"),
                data_document="2026-07-10",
                serie="AB",
                numar="42",
                directie="primit",
                moneda="RON",
                valoare_totala="119.00",
                fisiere_export=[fisier],
            )
        ]
        get_storage.return_value.read_bytes.return_value = continut

        with tempfile.TemporaryDirectory() as folder:
            prima = Path(folder) / "prima.zip"
            a_doua = Path(folder) / "a-doua.zip"
            self.assertEqual(_construieste_zip(perioada_id=uuid4(), destinatie=prima), 1)
            self.assertEqual(_construieste_zip(perioada_id=uuid4(), destinatie=a_doua), 1)
            self.assertEqual(prima.read_bytes(), a_doua.read_bytes())
            with ZipFile(prima) as arhiva:
                self.assertEqual(
                    arhiva.namelist(),
                    [
                        "achizitii-cheltuieli/factura/0001_01_factura-iulie.pdf",
                        "manifest.csv",
                    ],
                )
                manifest = arhiva.read("manifest.csv").decode("utf-8-sig")
                self.assertIn("Furnizor Test", manifest)
                self.assertIn(fisier.checksum, manifest)
                self.assertEqual(
                    arhiva.read("achizitii-cheltuieli/factura/0001_01_factura-iulie.pdf"),
                    continut,
                )

    @patch("exporturi.services.get_document_storage")
    @patch("exporturi.services._documente_export")
    def test_zip_rejects_changed_source_file(self, documente, get_storage):
        documente.return_value = [
            SimpleNamespace(
                pk=uuid4(),
                tip_document=SimpleNamespace(categorie="vanzari", cod="factura"),
                cont_financiar=None,
                partener=None,
                data_document=None,
                serie=None,
                numar=None,
                directie=None,
                moneda="RON",
                valoare_totala=None,
                fisiere_export=[
                    SimpleNamespace(
                        storage_key="staging/test/document",
                        nume_original="factura.pdf",
                        checksum=hashlib.sha256(b"original").hexdigest(),
                    )
                ],
            )
        ]
        get_storage.return_value.read_bytes.return_value = b"modificat"

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(EroareExport):
                _construieste_zip(
                    perioada_id=uuid4(),
                    destinatie=Path(folder) / "export.zip",
                )

    def test_expiration_reference_is_seven_days(self):
        acum = timezone.now()
        expirare = acum + timedelta(days=7)
        self.assertEqual((expirare - acum).days, 7)
