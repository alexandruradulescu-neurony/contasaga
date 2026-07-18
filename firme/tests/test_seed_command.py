from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from firme.management.commands.seed_local_demo import Command


class SeedLocalDemoCommandTests(SimpleTestCase):
    @override_settings(RELEASE_ENVIRONMENT="production", DEBUG=False)
    def test_command_is_blocked_in_production_before_database_access(self):
        with self.assertRaisesMessage(
            CommandError,
            "Datele demo locale nu pot fi create în mediul de producție.",
        ):
            Command().handle(
                admin_password="NeverUsed123!",
                admin_email="demo@example.test",
            )
