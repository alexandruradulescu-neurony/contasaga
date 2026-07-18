import json
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.core import signing
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

from documente.access import EroareAccesFisier, url_acces_fisier_inbox
from documente.inbox import (
    SALT_UPLOAD_INBOX_LOCAL,
    EroareInbox,
    creeaza_lot_incarcare,
    primeste_upload_local_inbox,
    valideaza_token_upload_local,
)
from documente.inbox_views import (
    inbox_fisier_finalizare,
    inbox_lot_creare,
    inbox_lot_finalizare,
)
from documente.models import FisierInbox


class InboxValidationTests(SimpleTestCase):
    def setUp(self):
        self.actor = SimpleNamespace(is_authenticated=True, is_active=True, rol="client_admin")

    @override_settings(DOCUMENT_BATCH_MAX_FILES=500, DOCUMENT_BATCH_MAX_TOTAL_BYTES=1024)
    def test_batch_limits_are_checked_before_database_work(self):
        with self.assertRaisesMessage(EroareInbox, "între 1 și 500"):
            creeaza_lot_incarcare(
                perioada_id=uuid4(),
                actor=self.actor,
                numar_fisiere=501,
                dimensiune_totala=100,
                nota="",
                context=SimpleNamespace(ip_address=None, user_agent=None),
            )
        with self.assertRaisesMessage(EroareInbox, "cel mult 2 GB"):
            creeaza_lot_incarcare(
                perioada_id=uuid4(),
                actor=self.actor,
                numar_fisiere=1,
                dimensiune_totala=1025,
                nota="",
                context=SimpleNamespace(ip_address=None, user_agent=None),
            )

    def test_signed_local_url_is_bound_to_one_inbox_file(self):
        fisier_id = uuid4()
        token = signing.dumps(
            {"fisier_id": str(fisier_id), "content_type": "application/pdf"},
            salt=SALT_UPLOAD_INBOX_LOCAL,
        )
        self.assertEqual(
            valideaza_token_upload_local(token=token, fisier_id=fisier_id),
            "application/pdf",
        )
        with self.assertRaisesMessage(EroareInbox, "nu corespunde"):
            valideaza_token_upload_local(token=token, fisier_id=uuid4())

    @patch("documente.inbox.transaction.atomic", return_value=nullcontext())
    @patch("documente.inbox.FisierInbox.objects")
    @patch("documente.inbox.get_document_storage")
    def test_local_upload_rejects_a_size_different_from_the_declared_file(
        self,
        get_storage,
        inbox_objects,
        _atomic,
    ):
        fisier_id = uuid4()
        token = signing.dumps(
            {"fisier_id": str(fisier_id), "content_type": "image/png"},
            salt=SALT_UPLOAD_INBOX_LOCAL,
        )
        storage = MagicMock(is_local=True)
        get_storage.return_value = storage
        inbox_objects.using.return_value.select_for_update.return_value.get.return_value = (
            SimpleNamespace(
                status=FisierInbox.Status.IN_ASTEPTARE,
                expira_la=timezone.now() + timedelta(hours=1),
                dimensiune_declarata=4,
                temp_storage_key="clients/test/_temp/file.part",
            )
        )

        with self.assertRaisesMessage(EroareInbox, "Dimensiunea încărcată"):
            primeste_upload_local_inbox(
                fisier_id=fisier_id,
                token=token,
                content_type="image/png",
                continut=b"123",
            )
        storage.put_bytes.assert_not_called()

    @patch("documente.access.get_document_storage")
    def test_available_inbox_original_gets_a_short_lived_local_download(self, get_storage):
        get_storage.return_value = SimpleNamespace(is_local=True)
        request = RequestFactory().get("/inbox/")
        fisier = SimpleNamespace(
            status=FisierInbox.Status.DISPONIBIL,
            storage_key="clients/test/2026-06/inbox/batch/originals/file",
            mime_type="application/pdf",
            nume_original="facturi-iunie.pdf",
        )

        url = url_acces_fisier_inbox(request=request, fisier=fisier)

        self.assertIn("/fisiere/local/semnat/?token=", url)

    def test_pending_inbox_file_cannot_be_downloaded(self):
        fisier = SimpleNamespace(
            status=FisierInbox.Status.IN_ASTEPTARE,
            storage_key=None,
            mime_type="application/pdf",
            nume_original="facturi-iunie.pdf",
        )

        with self.assertRaisesMessage(EroareAccesFisier, "nu este disponibil"):
            url_acces_fisier_inbox(
                request=RequestFactory().get("/inbox/"),
                fisier=fisier,
            )


class InboxViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, pk=uuid4())

    @patch("documente.inbox_views.creeaza_lot_incarcare")
    @patch("documente.inbox_views.get_object_or_404")
    def test_batch_creation_returns_per_file_and_batch_endpoints(self, get_object, create_batch):
        period_id = uuid4()
        batch_id = uuid4()
        create_batch.return_value = SimpleNamespace(pk=batch_id)
        request = self.factory.post(
            f"/perioade/{period_id}/inbox/loturi/",
            {
                "numar_fisiere": "100",
                "dimensiune_totala": "500000000",
                "nota": "Documentele lunii",
            },
        )
        request.user = self.user

        response = inbox_lot_creare(request, period_id)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(payload["lot_id"], str(batch_id))
        self.assertIn(str(batch_id), payload["init_url"])
        self.assertIn(str(batch_id), payload["finalize_url"])
        create_batch.assert_called_once()
        self.assertEqual(create_batch.call_args.kwargs["numar_fisiere"], 100)
        self.assertIs(create_batch.call_args.kwargs["actor"], self.user)

    @patch("documente.inbox_views.finalizeaza_fisier_inbox")
    @patch("documente.inbox_views.get_object_or_404")
    def test_file_finalization_reports_inbox_status(self, get_object, finalize_file):
        file_id = uuid4()
        finalize_file.return_value = SimpleNamespace(
            pk=file_id,
            nume_original="factura.pdf",
            status="disponibil",
        )
        request = self.factory.post(f"/inbox/fisiere/{file_id}/finalizeaza/")
        request.user = self.user

        response = inbox_fisier_finalizare(request, file_id)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "disponibil")
        self.assertEqual(payload["nume"], "factura.pdf")

    @patch("documente.inbox_views.finalizeaza_lot_incarcare")
    @patch("documente.inbox_views.get_object_or_404")
    def test_partial_batch_remains_traceable(self, get_object, finalize_batch):
        batch_id = uuid4()
        period_id = uuid4()
        finalize_batch.return_value = SimpleNamespace(
            pk=batch_id,
            perioada_contabila_id=period_id,
            status="partial",
        )
        request = self.factory.post(f"/inbox/loturi/{batch_id}/finalizeaza/")
        request.user = self.user

        response = inbox_lot_finalizare(request, batch_id)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "partial")
        self.assertIn(str(period_id), payload["redirect_url"])
