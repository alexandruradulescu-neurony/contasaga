from django.core.management.base import BaseCommand, CommandError

from notificari.services import reincearca_emailuri_pendente


class Command(BaseCommand):
    help = "Reîncearcă emailurile nesemise din outbox, de maximum trei ori fiecare."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit trebuie să fie cel puțin 1.")
        trimise, esuate = reincearca_emailuri_pendente(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(f"Emailuri trimise: {trimise}; încă nesemise: {esuate}")
        )
