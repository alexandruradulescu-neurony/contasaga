from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from exporturi.models import Export
from exporturi.services import expira_export


class Command(BaseCommand):
    help = "Șterge obiectele ZIP expirate și marchează exporturile ca expirate."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit trebuie să fie cel puțin 1.")
        ids = list(
            Export.objects.using("privileged")
            .filter(
                status=Export.Status.FINALIZAT,
                expira_la__lte=timezone.now(),
            )
            .values_list("pk", flat=True)[: options["limit"]]
        )
        for export_id in ids:
            expira_export(export_id)
        self.stdout.write(self.style.SUCCESS(f"Exporturi expirate curățate: {len(ids)}"))
