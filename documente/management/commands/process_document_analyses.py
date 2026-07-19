import time

from django.core.management.base import BaseCommand, CommandError

from documente.analysis import (
    asigura_analize_pentru_fisiere_disponibile,
    proceseaza_coada_analize,
)
from documente.archive import proceseaza_coada_arhive
from documente.extraction import (
    asigura_extrageri_pentru_documente,
    proceseaza_coada_extrageri,
)
from documente.reading import proceseaza_coada_citire


class Command(BaseCommand):
    help = (
        "Procesează citirea locală, analiza AI opțională, extragerea structurată "
        "și arhivele lunare."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--watch", action="store_true")
        parser.add_argument("--poll-seconds", type=int, default=10)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit trebuie să fie cel puțin 1.")
        if not 2 <= options["poll_seconds"] <= 300:
            raise CommandError("--poll-seconds trebuie să fie între 2 și 300.")

        while True:
            asigura_analize_pentru_fisiere_disponibile(limit=max(options["limit"] * 5, 100))
            citite, erori_citire = proceseaza_coada_citire(limit=options["limit"])
            finalizate, erori = proceseaza_coada_analize(limit=options["limit"])
            asigura_extrageri_pentru_documente(limit=max(options["limit"] * 5, 100))
            extrase, erori_extragere = proceseaza_coada_extrageri(limit=options["limit"])
            arhive, erori_arhiva = proceseaza_coada_arhive(limit=min(options["limit"], 5))
            if (
                citite
                or erori_citire
                or finalizate
                or erori
                or extrase
                or erori_extragere
                or arhive
                or erori_arhiva
            ):
                self.stdout.write(
                    f"Citiri finalizate: {citite}; erori citire: {erori_citire}; "
                    f"analize AI: {finalizate}; erori AI: {erori}; "
                    f"extrageri: {extrase}; erori extragere: {erori_extragere}; "
                    f"arhive: {arhive}; erori arhivă: {erori_arhiva}"
                )
            if not options["watch"]:
                break
            time.sleep(options["poll_seconds"])
