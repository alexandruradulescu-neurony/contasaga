from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from core.views import health_live, health_ready


class HealthEndpointTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/health/ready/")

    def test_liveness_has_no_dependency_probe(self):
        response = health_live(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})

    @patch("core.views.stare_readiness", return_value={"database": True, "storage": True})
    def test_readiness_is_ok_when_all_dependencies_are_available(self, _probe):
        response = health_ready(self.request)
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {"status": "ok", "checks": {"database": True, "storage": True}},
        )

    @patch("core.views.stare_readiness", return_value={"database": True, "storage": False})
    def test_readiness_returns_503_when_a_dependency_is_unavailable(self, _probe):
        response = health_ready(self.request)
        self.assertEqual(response.status_code, 503)
        self.assertJSONEqual(
            response.content,
            {"status": "unavailable", "checks": {"database": True, "storage": False}},
        )
