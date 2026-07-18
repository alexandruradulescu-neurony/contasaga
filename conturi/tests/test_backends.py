import uuid

from django.contrib.auth.hashers import make_password
from django.test import SimpleTestCase

from conturi.backends import hydrate_default_user
from conturi.models import Utilizator


class HydrateDefaultUserTests(SimpleTestCase):
    def test_privileged_values_are_rebound_to_default(self):
        values = {
            "id": uuid.uuid4(),
            "cabinet_id": None,
            "nume": "Client",
            "email": "client@example.test",
            "password": make_password("secret"),
            "rol": "client_admin",
            "telefon": None,
            "is_active": True,
            "is_staff": False,
            "is_superuser": False,
            "last_login": None,
            "creat_la": None,
        }
        user = hydrate_default_user(values)
        self.assertEqual(user._state.db, "default")
        self.assertFalse(user._state.adding)

    def test_default_queryset_defers_password_hash(self):
        deferred_fields, is_deferred = Utilizator.objects.all().query.deferred_loading

        self.assertTrue(is_deferred)
        self.assertIn("password", deferred_fields)
