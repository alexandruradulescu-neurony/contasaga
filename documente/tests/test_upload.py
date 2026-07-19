import stat
from datetime import timedelta
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from django.test.client import RequestFactory
from django.utils import timezone

from documente.access import continut_local_semnat, url_acces_fisier
from documente.filetypes import TipFisierInvalid, detecteaza_tip, tip_pentru_upload
from documente.management.commands.migrate_document_storage_layout import (
    Command as MigrateStorageLayoutCommand,
)
from documente.management.commands.migrate_document_storage_layout import MutareObiect
from documente.models import Document, FisierDocument
from documente.processing import poate_porni_procesarea
from documente.storage import (
    EroareStorage,
    LocalDocumentStorage,
    R2DocumentStorage,
    get_document_storage,
)
from documente.storage_keys import (
    cheie_document,
    cheie_original_inbox,
    cheie_temporara_inbox,
    cheie_thumbnail,
    prefix_arhiva_finala,
    prefix_arhiva_staging,
    prefix_lunar,
)
from documente.upload import _utilizator_cu_acces_privilegiat, poate_atasa_fisiere


class FileTypeTests(SimpleTestCase):
    def test_declared_type_must_match_extension(self):
        self.assertEqual(tip_pentru_upload("factura.pdf", "application/pdf"), "application/pdf")
        self.assertEqual(
            tip_pentru_upload("fotografie.HEIC", "application/octet-stream"),
            "image/heic",
        )
        with self.assertRaises(TipFisierInvalid):
            tip_pentru_upload("factura.pdf", "image/png")

    def test_content_type_is_detected_from_magic_bytes(self):
        self.assertEqual(detecteaza_tip(b"%PDF-1.7\n"), "application/pdf")
        self.assertEqual(detecteaza_tip(b"\x89PNG\r\n\x1a\nrest"), "image/png")
        self.assertEqual(detecteaza_tip(b"\xff\xd8\xffrest"), "image/jpeg")
        with self.assertRaises(TipFisierInvalid):
            detecteaza_tip(b"not-a-document")


class StorageKeyLayoutTests(SimpleTestCase):
    def test_objects_are_grouped_by_client_and_accounting_month(self):
        firma_id = uuid4()
        intentie_id = uuid4()
        fisier_id = uuid4()

        self.assertEqual(
            cheie_document(
                firma_id=firma_id,
                an=2026,
                luna=7,
                intentie_id=intentie_id,
            ),
            f"clients/{firma_id}/2026-07/documents/{intentie_id}",
        )
        self.assertEqual(
            cheie_thumbnail(
                firma_id=firma_id,
                an=2026,
                luna=7,
                fisier_id=fisier_id,
            ),
            f"clients/{firma_id}/2026-07/thumbnails/{fisier_id}.png",
        )
        self.assertEqual(
            cheie_temporara_inbox(
                firma_id=firma_id,
                an=2026,
                luna=7,
                lot_id=intentie_id,
                fisier_id=fisier_id,
            ),
            f"clients/{firma_id}/2026-07/_temp/{intentie_id}/{fisier_id}.part",
        )
        self.assertEqual(
            cheie_original_inbox(
                firma_id=firma_id,
                an=2026,
                luna=7,
                lot_id=intentie_id,
                fisier_id=fisier_id,
            ),
            f"clients/{firma_id}/2026-07/inbox/{intentie_id}/originals/{fisier_id}",
        )

    def test_invalid_month_is_rejected(self):
        with self.assertRaises(ValueError):
            prefix_lunar(firma_id=uuid4(), an=2026, luna=13)

    def test_archive_prefixes_are_versioned_inside_the_month(self):
        firma_id = uuid4()
        self.assertEqual(
            prefix_arhiva_staging(firma_id=firma_id, an=2026, luna=7, versiune=2),
            f"clients/{firma_id}/2026-07/.system/staging/archive-v0002",
        )
        self.assertEqual(
            prefix_arhiva_finala(firma_id=firma_id, an=2026, luna=7, versiune=2),
            f"clients/{firma_id}/2026-07/archive/v0002",
        )

    def test_human_archive_files_do_not_create_visible_metadata_sidecars(self):
        with TemporaryDirectory() as directory:
            storage = LocalDocumentStorage(root=directory)
            storage.put_archive_bytes(
                "clients/client/2026-07/archive/v0001/primite/factura.pdf",
                b"pdf",
                "application/pdf",
            )

            self.assertEqual(
                storage.read_bytes("clients/client/2026-07/archive/v0001/primite/factura.pdf"),
                b"pdf",
            )
            self.assertFalse(
                storage._metadata_path(  # noqa: SLF001
                    "clients/client/2026-07/archive/v0001/primite/factura.pdf"
                ).exists()
            )

    @override_settings(DOCUMENT_STORAGE_BACKEND="local")
    def test_legacy_object_is_copied_only_when_content_matches(self):
        with TemporaryDirectory() as directory:
            with override_settings(DOCUMENT_LOCAL_STORAGE_ROOT=directory):
                get_document_storage.cache_clear()
                self.addCleanup(get_document_storage.cache_clear)
                storage = get_document_storage()
                storage.put_bytes("staging/source", b"abcdef", "application/pdf")
                mutare = MutareObiect(
                    veche="staging/source",
                    noua="clients/client/2026-07/documents/target",
                    content_type="application/pdf",
                    lipsa_permisa=False,
                )

                self.assertTrue(MigrateStorageLayoutCommand()._copiaza(mutare))
                self.assertEqual(storage.read_bytes(mutare.noua), b"abcdef")

                storage.put_bytes(mutare.noua, b"ABCDEF", "application/pdf")
                with self.assertRaises(CommandError):
                    MigrateStorageLayoutCommand()._copiaza(mutare)


class LocalStorageTests(SimpleTestCase):
    def test_round_trip_and_path_confinement(self):
        with TemporaryDirectory() as directory:
            storage = LocalDocumentStorage(root=directory)
            storage.put_bytes("staging/firma/fisier", b"continut", "application/pdf")
            self.assertEqual(storage.read_bytes("staging/firma/fisier"), b"continut")
            self.assertEqual(storage.head("staging/firma/fisier").dimensiune, 8)
            self.assertEqual(
                storage.head("staging/firma/fisier").content_type,
                "application/pdf",
            )
            self.assertEqual(stat.S_IMODE(storage.root.stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE(storage._path("staging/firma/fisier").stat().st_mode),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE(storage._metadata_path("staging/firma/fisier").stat().st_mode),
                0o600,
            )
            with self.assertRaises(EroareStorage):
                storage.put_bytes("../evadare", b"x", "application/pdf")

    def test_delete_prefix_removes_only_the_requested_subtree(self):
        with TemporaryDirectory() as directory:
            storage = LocalDocumentStorage(root=directory)
            storage.put_archive_bytes(
                "clients/firma/2026-07/archive/v0001/a.pdf", b"a", "application/pdf"
            )
            storage.put_archive_bytes(
                "clients/firma/2026-07/archive/v0001/b.pdf", b"b", "application/pdf"
            )
            storage.put_archive_bytes(
                "clients/firma/2026-07/archive/v0002/a.pdf", b"c", "application/pdf"
            )

            storage.delete_prefix("clients/firma/2026-07/archive/v0001")

            self.assertFalse(storage._path("clients/firma/2026-07/archive/v0001").exists())
            self.assertEqual(
                storage.read_bytes("clients/firma/2026-07/archive/v0002/a.pdf"),
                b"c",
            )

    def test_delete_prefix_rejects_storage_root(self):
        with TemporaryDirectory() as directory:
            storage = LocalDocumentStorage(root=directory)

            with self.assertRaises(EroareStorage):
                storage.delete_prefix("")

    def test_corrupt_local_metadata_is_reported_as_storage_error(self):
        with TemporaryDirectory() as directory:
            storage = LocalDocumentStorage(root=directory)
            storage.put_bytes("staging/firma/fisier", b"continut", "application/pdf")
            storage._metadata_path("staging/firma/fisier").write_text("{")

            with self.assertRaisesMessage(EroareStorage, "Metadatele fișierului sunt corupte."):
                storage.head("staging/firma/fisier")

    @override_settings(
        DOCUMENT_STORAGE_BACKEND="local",
        DOCUMENT_DOWNLOAD_URL_TTL=300,
    )
    def test_signed_local_access_does_not_require_a_session(self):
        with (
            TemporaryDirectory() as directory,
            override_settings(DOCUMENT_LOCAL_STORAGE_ROOT=directory),
        ):
            get_document_storage.cache_clear()
            storage = get_document_storage()
            storage.put_bytes("staging/firma/fisier", b"continut", "application/pdf")
            request = RequestFactory().get("/", HTTP_HOST="127.0.0.1")
            fisier = SimpleNamespace(
                stare_procesare=FisierDocument.StareProcesare.PROCESAT,
                storage_key="staging/firma/fisier",
                mime_type="application/pdf",
                nume_original="factura.pdf",
            )
            url = url_acces_fisier(request=request, fisier=fisier, descarcare=False)
            token = parse_qs(urlsplit(url).query)["token"][0]
            rezultat = continut_local_semnat(token=token)
            self.assertEqual(rezultat.continut, b"continut")
            self.assertEqual(rezultat.content_type, "application/pdf")
            self.assertEqual(rezultat.content_disposition, 'inline; filename="factura.pdf"')
            get_document_storage.cache_clear()


class R2StorageTests(SimpleTestCase):
    @override_settings(
        R2_ACCOUNT_ID="account-id",
        R2_ACCESS_KEY_ID="access-key",
        R2_SECRET_ACCESS_KEY="secret-key",
        R2_BUCKET_NAME="documents",
        DOCUMENT_UPLOAD_URL_TTL=3600,
    )
    @patch("documente.storage.boto3.client")
    def test_presigned_put_is_scoped_to_key_and_content_type(self, client_factory):
        client = client_factory.return_value
        client.generate_presigned_url.return_value = "https://signed.example/upload"
        storage = R2DocumentStorage()
        url = storage.presigned_put_url("staging/firm/intent", "application/pdf")
        self.assertEqual(url, "https://signed.example/upload")
        client_factory.assert_called_once_with(
            service_name="s3",
            endpoint_url="https://account-id.r2.cloudflarestorage.com",
            aws_access_key_id="access-key",
            aws_secret_access_key="secret-key",
            region_name="auto",
        )
        client.generate_presigned_url.assert_called_once_with(
            "put_object",
            Params={
                "Bucket": "documents",
                "Key": "staging/firm/intent",
                "ContentType": "application/pdf",
            },
            ExpiresIn=3600,
        )

    @override_settings(
        R2_ACCOUNT_ID="account-id",
        R2_ACCESS_KEY_ID="access-key",
        R2_SECRET_ACCESS_KEY="secret-key",
        R2_BUCKET_NAME="documents",
        DOCUMENT_DOWNLOAD_URL_TTL=300,
    )
    @patch("documente.storage.boto3.client")
    def test_presigned_get_controls_type_and_disposition(self, client_factory):
        client = client_factory.return_value
        client.generate_presigned_url.return_value = "https://signed.example/read"
        storage = R2DocumentStorage()
        url = storage.presigned_get_url(
            "staging/firm/file",
            content_type="application/pdf",
            content_disposition='attachment; filename="factura.pdf"',
        )
        self.assertEqual(url, "https://signed.example/read")
        client.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "documents",
                "Key": "staging/firm/file",
                "ResponseContentType": "application/pdf",
                "ResponseContentDisposition": 'attachment; filename="factura.pdf"',
            },
            ExpiresIn=300,
        )

    @override_settings(
        R2_ACCOUNT_ID="account-id",
        R2_ACCESS_KEY_ID="access-key",
        R2_SECRET_ACCESS_KEY="secret-key",
        R2_BUCKET_NAME="documents",
    )
    @patch("documente.storage.boto3.client")
    def test_delete_prefix_is_scoped_and_rejects_bucket_root(self, client_factory):
        client = client_factory.return_value
        paginator = client.get_paginator.return_value
        paginator.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "clients/firma/2026-07/archive/v0001/a.pdf"},
                    {"Key": "clients/firma/2026-07/archive/v0001/manifest.csv"},
                ]
            }
        ]
        storage = R2DocumentStorage()

        storage.delete_prefix("clients/firma/2026-07/archive/v0001")

        client.get_paginator.assert_called_once_with("list_objects_v2")
        paginator.paginate.assert_called_once_with(
            Bucket="documents",
            Prefix="clients/firma/2026-07/archive/v0001/",
        )
        client.delete_objects.assert_called_once_with(
            Bucket="documents",
            Delete={
                "Objects": [
                    {"Key": "clients/firma/2026-07/archive/v0001/a.pdf"},
                    {"Key": "clients/firma/2026-07/archive/v0001/manifest.csv"},
                ],
                "Quiet": True,
            },
        )
        with self.assertRaises(EroareStorage):
            storage.delete_prefix("/")


class UploadAuthorizationTests(SimpleTestCase):
    def test_only_author_can_attach_to_draft(self):
        author_id = uuid4()
        document = SimpleNamespace(stare=Document.Stare.DRAFT, incarcat_de_id=author_id)
        author = SimpleNamespace(
            pk=author_id,
            is_authenticated=True,
            is_active=True,
            rol="client_operator",
        )
        other = SimpleNamespace(
            pk=uuid4(),
            is_authenticated=True,
            is_active=True,
            rol="client_admin",
        )
        self.assertTrue(poate_atasa_fisiere(author, document))
        self.assertFalse(poate_atasa_fisiere(other, document))

    def test_draft_author_must_still_have_an_upload_role(self):
        author_id = uuid4()
        document = SimpleNamespace(stare=Document.Stare.DRAFT, incarcat_de_id=author_id)
        for role in ("superuser_platforma", "admin_cabinet"):
            user = SimpleNamespace(
                pk=author_id,
                is_authenticated=True,
                is_active=True,
                rol=role,
            )
            with self.subTest(role=role):
                self.assertFalse(poate_atasa_fisiere(user, document))

    def test_clients_can_attach_during_clarification(self):
        document = SimpleNamespace(
            stare=Document.Stare.NECESITA_CLARIFICARI,
            incarcat_de_id=uuid4(),
        )
        for role in (
            "superuser_platforma",
            "admin_cabinet",
            "contabil_coordonator",
            "contabil",
            "client_admin",
            "client_operator",
        ):
            user = SimpleNamespace(
                pk=uuid4(),
                is_authenticated=True,
                is_active=True,
                rol=role,
            )
            with self.subTest(role=role):
                self.assertIs(
                    poate_atasa_fisiere(user, document),
                    role in {"client_admin", "client_operator"},
                )

    @patch("documente.upload.UtilizatorFirma.objects")
    @patch("documente.upload.Utilizator.objects")
    def test_privileged_upload_rechecks_current_assignment(self, users, assignments):
        user = SimpleNamespace(
            pk=uuid4(),
            is_active=True,
            rol="client_operator",
        )
        users.using.return_value.get.return_value = user
        assignments.using.return_value.filter.return_value.exists.return_value = False

        with self.assertRaises(PermissionDenied):
            _utilizator_cu_acces_privilegiat(
                actor=user,
                document=SimpleNamespace(firma_id=uuid4()),
            )


class ProcessingConcurrencyTests(SimpleTestCase):
    def _file(self, state, *, deleted=False, attempts=0, started_at=None):
        return SimpleNamespace(
            stare_procesare=state,
            sters_la=object() if deleted else None,
            incercari_procesare=attempts,
            procesare_inceputa_la=started_at,
        )

    def test_in_progress_file_is_not_started_by_a_second_worker(self):
        self.assertFalse(
            poate_porni_procesarea(
                self._file(
                    FisierDocument.StareProcesare.IN_LUCRU,
                    started_at=timezone.now(),
                )
            )
        )

    def test_stale_processing_lease_can_be_recovered(self):
        moment = timezone.now()
        self.assertTrue(
            poate_porni_procesarea(
                self._file(
                    FisierDocument.StareProcesare.IN_LUCRU,
                    attempts=2,
                    started_at=moment - timedelta(minutes=16),
                ),
                moment=moment,
            )
        )

    def test_deleted_or_exhausted_file_is_not_resurrected(self):
        self.assertFalse(
            poate_porni_procesarea(self._file(FisierDocument.StareProcesare.EROARE, deleted=True))
        )
        self.assertFalse(
            poate_porni_procesarea(self._file(FisierDocument.StareProcesare.EROARE, attempts=3))
        )
        self.assertTrue(
            poate_porni_procesarea(self._file(FisierDocument.StareProcesare.EROARE, attempts=2))
        )
