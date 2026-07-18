from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class ScheduledMaintenanceTests(SimpleTestCase):
    @patch("core.management.commands.run_scheduled_maintenance.call_command")
    def test_frequent_mode_covers_processing_email_and_exports(self, nested_call):
        call_command("run_scheduled_maintenance", "frequent")
        commands = [item.args[0] for item in nested_call.call_args_list]
        self.assertEqual(
            commands,
            ["process_document_files", "retry_notification_emails", "process_exports"],
        )

    @patch("core.management.commands.run_scheduled_maintenance.call_command")
    def test_daily_mode_covers_both_cleanup_jobs(self, nested_call):
        call_command("run_scheduled_maintenance", "daily")
        self.assertEqual(
            [item.args[0] for item in nested_call.call_args_list],
            ["cleanup_upload_intents", "cleanup_expired_exports"],
        )
