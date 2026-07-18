import time

from django.core.management.base import BaseCommand, CommandError

from exporturi.models import Export
from exporturi.services import genereaza_export


class Command(BaseCommand):
    help = "Generează exporturile ZIP aflate în lucru."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--interval", type=float, default=5.0)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit trebuie să fie cel puțin 1.")
        if options["interval"] < 0.5 or options["interval"] > 60:
            raise CommandError("--interval trebuie să fie între 0.5 și 60 de secunde.")

        while True:
            ids = list(
                Export.objects.using("privileged")
                .filter(status=Export.Status.IN_LUCRU)
                .order_by("creat_la")
                .values_list("pk", flat=True)[: options["limit"]]
            )
            finalizate = erori = 0
            for export_id in ids:
                export = genereaza_export(export_id)
                if export is None:
                    continue
                if export.status == Export.Status.FINALIZAT:
                    finalizate += 1
                elif export.status == Export.Status.EROARE:
                    erori += 1
            if ids:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Evaluate: {len(ids)}; finalizate: {finalizate}; erori: {erori}"
                    )
                )
            if not options["watch"]:
                break
            time.sleep(options["interval"])
