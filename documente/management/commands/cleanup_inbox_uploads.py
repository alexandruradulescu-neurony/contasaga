from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from documente.models import FisierInbox
from documente.storage import get_document_storage


class Command(BaseCommand):
    help = "Elimină obiectele temporare expirate ale loturilor din inbox."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=1000)

    def handle(self, *args, **options):
        storage = get_document_storage()
        limit = options["limit"]
        if limit < 1:
            raise CommandError("--limit trebuie să fie cel puțin 1.")
        fisiere = list(
            FisierInbox.objects.using("privileged").filter(
                status__in=(FisierInbox.Status.IN_ASTEPTARE, FisierInbox.Status.EROARE),
                expira_la__lte=timezone.now(),
            )[:limit]
        )
        expirate = 0
        sterse = 0
        for fisier in fisiere:
            try:
                storage.delete(fisier.temp_storage_key)
            except Exception as exc:
                self.stderr.write(f"{fisier.pk}: {exc}")
                continue
            sterse += 1
            FisierInbox.objects.using("privileged").filter(pk=fisier.pk).update(
                status=FisierInbox.Status.EXPIRAT
            )
            expirate += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Curățare inbox: {sterse} obiecte temporare șterse, "
                f"{expirate} poziții marcate expirate."
            )
        )
