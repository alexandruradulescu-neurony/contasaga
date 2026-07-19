from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Rulează grupurile de operații periodice folosite de scheduler."

    def add_arguments(self, parser):
        parser.add_argument("mode", choices=("frequent", "daily"))

    def handle(self, *args, **options):
        if options["mode"] == "frequent":
            call_command("process_document_files", limit=100, stdout=self.stdout)
            call_command("process_document_analyses", limit=20, stdout=self.stdout)
            call_command("retry_notification_emails", limit=100, stdout=self.stdout)
            call_command("process_exports", limit=20, stdout=self.stdout)
        else:
            call_command("cleanup_upload_intents", limit=1000, stdout=self.stdout)
            call_command("cleanup_inbox_uploads", limit=1000, stdout=self.stdout)
            call_command("cleanup_expired_exports", limit=100, stdout=self.stdout)
