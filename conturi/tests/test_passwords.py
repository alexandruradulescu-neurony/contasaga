from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from conturi.forms import UtilizatorCreationForm
from conturi.models import Utilizator
from conturi.password_forms import SchimbareParolaForm
from conturi.password_views import (
    _permite_trimitere_reset,
    parola_reset_confirmare,
    parola_reset_solicitare,
)


class PasswordWorkflowTests(SimpleTestCase):
    def test_platform_admin_creation_rejects_weak_passwords(self):
        form = UtilizatorCreationForm()
        form.cleaned_data = {
            "email": "admin@example.test",
            "nume": "Admin Platformă",
            "password1": "x",
            "password2": "x",
        }
        with self.assertRaises(ValidationError):
            form.clean_password2()

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def test_authenticated_change_updates_only_password_column(self):
        user = MagicMock()
        form = SchimbareParolaForm(user=user)
        form.cleaned_data = {"new_password1": "Noua-parola-sigura-2026"}
        self.assertIs(form.save(), user)
        user.set_password.assert_called_once_with("Noua-parola-sigura-2026")
        user.save.assert_called_once_with(update_fields=["password"])

    def test_reset_requests_are_rate_limited_without_revealing_accounts(self):
        request = self.factory.post("/parola/resetare/", REMOTE_ADDR="192.0.2.30")
        for _index in range(3):
            self.assertTrue(_permite_trimitere_reset(request, "user@example.test"))
        self.assertFalse(_permite_trimitere_reset(request, "user@example.test"))

    @patch("conturi.password_views._utilizator_pentru_email", return_value=None)
    def test_unknown_reset_email_gets_the_same_success_redirect(self, user_lookup):
        request = self.factory.post(
            "/parola/resetare/",
            {"email": "missing@example.test"},
            REMOTE_ADDR="192.0.2.31",
        )
        response = parola_reset_solicitare(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/parola/resetare/trimisa/")
        user_lookup.assert_called_once_with("missing@example.test")

    def test_invalid_reset_link_returns_400(self):
        request = self.factory.get("/parola/resetare/invalid/invalid/")
        request.user = AnonymousUser()
        response = parola_reset_confirmare(request, "invalid", "invalid")
        self.assertEqual(response.status_code, 400)

    @patch("conturi.password_views.seteaza_parola")
    @patch("conturi.password_views._utilizator_pentru_uid")
    def test_valid_reset_sets_password_through_privileged_service(self, lookup, seteaza):
        user = Utilizator(
            id=uuid4(),
            email="user@example.test",
            nume="User Test",
            rol=Utilizator.Rol.CLIENT_ADMIN,
            password=make_password("Parola-veche-2026"),
            is_active=True,
        )
        lookup.return_value = user
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        request = self.factory.post(
            f"/parola/resetare/{uid}/{token}/",
            {
                "new_password1": "Parola-noua-foarte-sigura-2026",
                "new_password2": "Parola-noua-foarte-sigura-2026",
            },
        )
        response = parola_reset_confirmare(request, uid, token)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/parola/resetare/completa/")
        seteaza.assert_called_once_with(user, "Parola-noua-foarte-sigura-2026")
