import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import RequestFactory, SimpleTestCase

from documente.services import TranzitieDocumentInvalida
from documente.views import document_copie_upload, document_trimitere_lot


class BulkUploadViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, pk=uuid4())

    @patch("documente.views.creeaza_document")
    @patch("documente.views.get_object_or_404")
    def test_copy_creates_same_classification_and_returns_upload_urls(
        self, get_object_or_404, creeaza_document
    ):
        source_id = uuid4()
        period_id = uuid4()
        type_id = uuid4()
        account_id = uuid4()
        created_id = uuid4()
        get_object_or_404.return_value = SimpleNamespace(
            perioada_contabila_id=period_id,
            tip_document_id=type_id,
            cont_financiar_id=account_id,
            predare_documente_id=uuid4(),
            note="seria de iunie",
        )
        creeaza_document.return_value = SimpleNamespace(pk=created_id)
        request = self.factory.post(f"/documente/{source_id}/copie-upload/")
        request.user = self.user

        response = document_copie_upload(request, source_id)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(payload["document_id"], str(created_id))
        self.assertIn(str(created_id), payload["upload_init_url"])
        creeaza_document.assert_called_once()
        call = creeaza_document.call_args.kwargs
        self.assertEqual(call["perioada_id"], period_id)
        self.assertEqual(call["tip_document_id"], type_id)
        self.assertEqual(call["cont_financiar_id"], account_id)
        self.assertEqual(
            call["predare_documente_id"], get_object_or_404.return_value.predare_documente_id
        )
        self.assertIs(call["actor"], self.user)

    @patch("documente.views.creeaza_document")
    @patch("documente.views.get_object_or_404")
    def test_copy_reports_closed_period_as_json_error(self, get_object_or_404, creeaza_document):
        source_id = uuid4()
        get_object_or_404.return_value = SimpleNamespace(
            perioada_contabila_id=uuid4(),
            tip_document_id=uuid4(),
            cont_financiar_id=None,
            predare_documente_id=None,
            note=None,
        )
        creeaza_document.side_effect = TranzitieDocumentInvalida("Perioada este închisă.")
        request = self.factory.post(f"/documente/{source_id}/copie-upload/")
        request.user = self.user

        response = document_copie_upload(request, source_id)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["error"], "Perioada este închisă.")

    @patch("documente.views.trimite_documente_in_lot")
    @patch("documente.views.get_object_or_404")
    def test_batch_submit_returns_one_result_for_the_whole_series(
        self, get_object_or_404, trimite_documente_in_lot
    ):
        document_id = uuid4()
        second_id = uuid4()
        get_object_or_404.return_value = SimpleNamespace(pk=document_id)
        trimite_documente_in_lot.return_value = [
            SimpleNamespace(pk=document_id),
            SimpleNamespace(pk=second_id),
        ]
        request = self.factory.post(
            f"/documente/{document_id}/trimite-lot/",
            {"document_ids": [str(document_id), str(second_id)]},
        )
        request.user = self.user

        response = document_trimitere_lot(request, document_id)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["status"], "trimis")
        self.assertEqual(json.loads(response.content)["total"], 2)
        call = trimite_documente_in_lot.call_args.kwargs
        self.assertEqual(call["document_ids"], [str(document_id), str(second_id)])
        self.assertIs(call["actor"], self.user)

    @patch("documente.views.trimite_documente_in_lot")
    @patch("documente.views.get_object_or_404")
    def test_batch_submit_keeps_invalid_drafts_recoverable(
        self, get_object_or_404, trimite_documente_in_lot
    ):
        document_id = uuid4()
        get_object_or_404.return_value = SimpleNamespace(pk=document_id)
        trimite_documente_in_lot.side_effect = TranzitieDocumentInvalida(
            "Toate fișierele trebuie procesate."
        )
        request = self.factory.post(
            f"/documente/{document_id}/trimite-lot/",
            {"document_ids": [str(document_id)]},
        )
        request.user = self.user

        response = document_trimitere_lot(request, document_id)

        self.assertEqual(response.status_code, 400)
        self.assertIn("procesate", json.loads(response.content)["error"])
