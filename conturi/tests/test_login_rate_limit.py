from django.conf import settings
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve

from conturi.auth_views import LoginProtejatView


class LoginRateLimitTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def _view(self, *, email="user@example.test", ip="192.0.2.10"):
        view = LoginProtejatView()
        view.request = self.factory.post(
            "/autentificare/",
            {"username": email, "password": "invalid"},
            REMOTE_ADDR=ip,
        )
        view.args = ()
        view.kwargs = {}
        return view

    def test_login_url_uses_protected_view(self):
        self.assertIs(resolve("/autentificare/").func.view_class, LoginProtejatView)

    def test_account_is_limited_after_configured_failures(self):
        for index in range(settings.LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS):
            self._view(ip=f"192.0.2.{index + 1}")._inregistreaza_esec()
        self.assertTrue(self._view(ip="198.51.100.1")._limitat())

    def test_ip_is_limited_across_accounts(self):
        for index in range(settings.LOGIN_RATE_LIMIT_IP_ATTEMPTS):
            self._view(email=f"user-{index}@example.test")._inregistreaza_esec()
        self.assertTrue(self._view(email="new@example.test")._limitat())

    def test_other_account_and_ip_are_not_affected(self):
        self._view()._inregistreaza_esec()
        self.assertFalse(self._view(email="other@example.test", ip="198.51.100.2")._limitat())
