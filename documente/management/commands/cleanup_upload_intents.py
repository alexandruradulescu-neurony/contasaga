from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from documente.models import IntentieUpload
from documente.storage import EroareStorage, get_document_storage


class Command(BaseCommand):
    help = "Șterge obiectele locale/R2 și intențiile expirate care nu au fost consumate."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit trebuie să fie cel puțin 1.")
        storage = get_document_storage()
        intentii = list(
            IntentieUpload.objects.using("privileged")
            .filter(folosita_la__isnull=True, expira_la__lt=timezone.now())
            .order_by("expira_la")[: options["limit"]]
        )
        sterse = 0
        erori = 0
        for intentie in intentii:
            try:
                storage.delete(intentie.storage_key)
            except EroareStorage as exc:
                erori += 1
                self.stderr.write(f"{intentie.pk}: {exc}")
                continue
            intentie.delete(using="privileged")
            sterse += 1
        self.stdout.write(self.style.SUCCESS(f"Intenții șterse: {sterse}; erori: {erori}"))
