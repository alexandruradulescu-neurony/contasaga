from django.core.management.base import CommandError
from django.test import SimpleTestCase

from documente.management.commands.cleanup_upload_intents import (
    Command as CleanupUploadIntentsCommand,
)
from documente.management.commands.process_document_files import (
    Command as ProcessDocumentFilesCommand,
)
from exporturi.management.commands.cleanup_expired_exports import (
    Command as CleanupExpiredExportsCommand,
)
from notificari.management.commands.retry_notification_emails import (
    Command as RetryNotificationEmailsCommand,
)


class CommandLimitTests(SimpleTestCase):
    def test_batch_commands_reject_non_positive_limits_before_doing_work(self):
        commands = (
            CleanupUploadIntentsCommand,
            ProcessDocumentFilesCommand,
            CleanupExpiredExportsCommand,
            RetryNotificationEmailsCommand,
        )

        for command_class in commands:
            with self.subTest(command=command_class.__module__):
                with self.assertRaisesMessage(
                    CommandError,
                    "--limit trebuie să fie cel puțin 1.",
                ):
                    command_class().handle(limit=0)
