from django.test import SimpleTestCase

from config.db_routers import DefaultDatabaseRouter
from conturi.models import Utilizator


class DefaultDatabaseRouterTests(SimpleTestCase):
    def setUp(self):
        self.router = DefaultDatabaseRouter()

    def test_instance_loaded_privileged_still_writes_default(self):
        user = Utilizator(email="test@example.test", nume="Test", rol="client_admin")
        user._state.db = "privileged"
        self.assertEqual(self.router.db_for_write(Utilizator, instance=user), "default")

    def test_application_aliases_can_relate(self):
        first = Utilizator(email="a@example.test", nume="A", rol="client_admin")
        second = Utilizator(email="b@example.test", nume="B", rol="client_admin")
        first._state.db = "privileged"
        second._state.db = "default"
        self.assertTrue(self.router.allow_relation(first, second))
