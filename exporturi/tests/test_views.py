from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from exporturi.views import export_local_semnat


class ExportViewTests(SimpleTestCase):
    @patch("exporturi.views.deschide_export_local_semnat")
    def test_local_export_response_disables_caching_and_cross_origin_use(self, deschide):
        deschide.return_value = SimpleNamespace(
            fisier=BytesIO(b"zip"),
            content_disposition='attachment; filename="export.zip"',
        )

        response = export_local_semnat(RequestFactory().get("/export-local/?token=test"))

        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Cross-Origin-Resource-Policy"], "same-origin")
