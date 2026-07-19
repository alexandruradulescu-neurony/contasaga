import json
from unittest.mock import patch

import fitz
from django.test import SimpleTestCase, override_settings

from documente.ai.contracts import (
    ContextAnalizaDocument,
    ContFinanciarPermis,
    EroareAnalizaAI,
    PaginaTextAnaliza,
    TipDocumentPermis,
)
from documente.ai.providers import (
    DeepSeekTextProvider,
    OpenAIResponsesProvider,
    construieste_provider,
)
from documente.analysis import proceseaza_coada_analize
from documente.classification_views import _fisiere_pentru_clasificare


def context_test(*, continut: bytes, mime_type: str) -> ContextAnalizaDocument:
    return ContextAnalizaDocument(
        nume_fisier="factura.pdf" if mime_type == "application/pdf" else "scan.jpg",
        mime_type=mime_type,
        continut=continut,
        denumire_firma="Client Demo SRL",
        cui_firma="RO123456",
        tipuri_document=(
            TipDocumentPermis(
                id="11111111-1111-1111-1111-111111111111",
                cod="factura",
                denumire="Factură",
                necesita_cont_financiar=False,
            ),
        ),
        conturi_financiare=(
            ContFinanciarPermis(
                id="22222222-2222-2222-2222-222222222222",
                denumire="Cont principal RON",
                tip="banca",
                moneda="RON",
            ),
        ),
        pagini_text=(PaginaTextAnaliza(numar=1, text="Factura furnizor numarul 100"),),
    )


def rezultat_provider(*, response_id="resp_123") -> dict:
    return {
        "id": response_id,
        "usage": {"input_tokens": 100, "output_tokens": 25},
        "output_text": json.dumps(
            {
                "document_type_code": "factura",
                "financial_account_id": None,
                "direction": "primit",
                "confidence": 0.94,
                "summary": "Factură de furnizor.",
                "extracted_text": "Furnizor Demo SRL Factura 100",
                "structured_fields": {
                    "issuer_name": "Furnizor Demo SRL",
                    "issuer_tax_id": "RO999",
                    "recipient_name": "Client Demo SRL",
                    "recipient_tax_id": "RO123456",
                    "series": "F",
                    "number": "100",
                    "document_date": "2026-07-10",
                    "due_date": "2026-08-10",
                    "currency": "RON",
                    "net_amount": "420.17",
                    "vat_amount": "79.83",
                    "total_amount": "500.00",
                },
                "evidence": [{"page": 1, "text": "Factura nr. 100"}],
                "segments": [
                    {
                        "start_page": 1,
                        "end_page": 1,
                        "document_type_code": "factura",
                        "financial_account_id": None,
                        "direction": "primit",
                        "structured_fields": {
                            "issuer_name": "Furnizor Demo SRL",
                            "issuer_tax_id": "RO999",
                            "recipient_name": "Client Demo SRL",
                            "recipient_tax_id": "RO123456",
                            "series": "F",
                            "number": "100",
                            "document_date": "2026-07-10",
                            "due_date": "2026-08-10",
                            "currency": "RON",
                            "net_amount": "420.17",
                            "vat_amount": "79.83",
                            "total_amount": "500.00",
                        },
                        "confidence": 0.94,
                        "reason": "O singură factură identificată.",
                    }
                ],
            }
        ),
    }


class ProviderOpenAITests(SimpleTestCase):
    @patch("documente.ai.providers._post_json")
    def test_pdf_is_sent_as_private_file_input_with_strict_schema(self, post_json):
        post_json.return_value = rezultat_provider()
        provider = OpenAIResponsesProvider(
            api_key="test-key",
            model="gpt-5.6-luna",
            base_url="https://api.openai.test/v1",
            timeout=30,
        )

        rezultat = provider.analizeaza(
            context_test(continut=b"%PDF-test", mime_type="application/pdf")
        )

        payload = post_json.call_args.kwargs["payload"]
        fisier = payload["input"][0]["content"][0]
        self.assertEqual(post_json.call_args.kwargs["url"], "https://api.openai.test/v1/responses")
        self.assertEqual(fisier["type"], "input_file")
        self.assertTrue(fisier["file_data"].startswith("data:application/pdf;base64,"))
        self.assertNotIn("detail", fisier)
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(rezultat.cod_tip_document, "factura")
        self.assertEqual(rezultat.directie, "primit")
        self.assertEqual(rezultat.raspuns_provider_id, "resp_123")
        self.assertEqual(rezultat.segmente[0]["pagina_start"], 1)
        self.assertEqual(rezultat.segmente[0]["directie"], "primit")
        self.assertEqual(rezultat.campuri_extrase["total_amount"], "500.00")

    @patch("documente.ai.providers._post_json")
    def test_image_is_sent_as_image_input(self, post_json):
        post_json.return_value = rezultat_provider()
        provider = OpenAIResponsesProvider(
            api_key="test-key",
            model="gpt-5.6-luna",
            base_url="https://api.openai.test/v1",
            timeout=30,
        )

        provider.analizeaza(context_test(continut=b"jpeg", mime_type="image/jpeg"))

        fisier = post_json.call_args.kwargs["payload"]["input"][0]["content"][0]
        self.assertEqual(fisier["type"], "input_image")
        self.assertTrue(fisier["image_url"].startswith("data:image/jpeg;base64,"))

    @patch("documente.ai.providers._post_json")
    def test_provider_metadata_is_bounded_before_persistence(self, post_json):
        response = rezultat_provider(response_id="r" * 400)
        response["usage"] = {"input_tokens": -1, "output_tokens": "25"}
        post_json.return_value = response
        provider = OpenAIResponsesProvider(
            api_key="test-key",
            model="gpt-5.6-luna",
            base_url="https://api.openai.test/v1",
            timeout=30,
        )

        rezultat = provider.analizeaza(
            context_test(continut=b"%PDF-test", mime_type="application/pdf")
        )

        self.assertEqual(len(rezultat.raspuns_provider_id), 255)
        self.assertIsNone(rezultat.tokeni_intrare)
        self.assertEqual(rezultat.tokeni_iesire, 25)


class ClassificationQueueSecurityTests(SimpleTestCase):
    def test_queue_projects_uploader_name_without_password_hash(self):
        sql = str(_fisiere_pentru_clasificare().query)

        self.assertNotIn("parola_hash", sql)
        self.assertIn("incarcat_de_nume", sql)


class ProviderDeepSeekTests(SimpleTestCase):
    @staticmethod
    def pdf_cu_text() -> bytes:
        document = fitz.open()
        page = document.new_page()
        page.insert_text((72, 72), "Factura furnizor numarul 100 valoare totala 500 RON")
        continut = document.tobytes()
        document.close()
        return continut

    @patch("documente.ai.providers._post_json")
    def test_text_pdf_uses_openai_compatible_chat_json(self, post_json):
        response = rezultat_provider(response_id="chat_1")
        response["choices"] = [{"message": {"content": response.pop("output_text")}}]
        response["usage"] = {"prompt_tokens": 80, "completion_tokens": 20}
        post_json.return_value = response
        provider = DeepSeekTextProvider(
            api_key="test-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.test",
            timeout=30,
        )

        rezultat = provider.analizeaza(
            context_test(continut=self.pdf_cu_text(), mime_type="application/pdf")
        )

        payload = post_json.call_args.kwargs["payload"]
        self.assertEqual(
            post_json.call_args.kwargs["url"],
            "https://api.deepseek.test/chat/completions",
        )
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertIn("Factura furnizor", payload["messages"][1]["content"])
        self.assertEqual(rezultat.tokeni_intrare, 80)

    @patch("documente.ai.providers._post_json")
    def test_image_uses_text_from_local_ocr(self, post_json):
        response = rezultat_provider(response_id="chat_image")
        response["choices"] = [{"message": {"content": response.pop("output_text")}}]
        post_json.return_value = response
        provider = DeepSeekTextProvider(
            api_key="test-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.test",
            timeout=30,
        )
        rezultat = provider.analizeaza(context_test(continut=b"jpeg", mime_type="image/jpeg"))
        self.assertEqual(rezultat.cod_tip_document, "factura")
        self.assertIn("Pagina 1", post_json.call_args.kwargs["payload"]["messages"][1]["content"])


class ConfigurareAnalizaTests(SimpleTestCase):
    @override_settings(DOCUMENT_AI_ENABLED=False)
    def test_disabled_queue_never_constructs_or_calls_provider(self):
        with patch("documente.analysis.construieste_provider") as factory:
            self.assertEqual(proceseaza_coada_analize(limit=10), (0, 0))
        factory.assert_not_called()

    @override_settings(
        DOCUMENT_AI_PROVIDER="openai",
        OPENAI_API_KEY="",
        DOCUMENT_AI_MODEL="gpt-5.6-luna",
        DOCUMENT_AI_BASE_URL="",
        DOCUMENT_AI_TIMEOUT_SECONDS=30,
    )
    def test_provider_requires_key_only_when_constructed(self):
        with self.assertRaisesMessage(EroareAnalizaAI, "OPENAI_API_KEY"):
            construieste_provider()

    @override_settings(
        DOCUMENT_AI_PROVIDER="deepseek",
        DEEPSEEK_API_KEY="test",
        DOCUMENT_AI_MODEL="deepseek-v4-flash",
        DOCUMENT_AI_BASE_URL="",
        DOCUMENT_AI_TIMEOUT_SECONDS=30,
    )
    def test_deepseek_provider_is_selectable_without_openai_key(self):
        provider = construieste_provider()
        self.assertEqual(provider.nume, "deepseek")
        self.assertEqual(provider.model, "deepseek-v4-flash")
