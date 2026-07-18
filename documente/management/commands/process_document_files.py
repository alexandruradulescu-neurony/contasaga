from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from documente.models import FisierDocument
from documente.processing import LEASE_PROCESARE, proceseaza_fisier


class Command(BaseCommand):
    help = "Procesează fișierele în așteptare și reîncearcă erorile de maximum trei ori."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["limit"] < 1:
            raise CommandError("--limit trebuie să fie cel puțin 1.")
        limita_blocare = timezone.now() - LEASE_PROCESARE
        ids = list(
            FisierDocument.objects.using("privileged")
            .filter(
                sters_la__isnull=True,
            )
            .filter(
                Q(
                    stare_procesare__in=(
                        FisierDocument.StareProcesare.IN_ASTEPTARE,
                        FisierDocument.StareProcesare.EROARE,
                    ),
                    incercari_procesare__lt=3,
                )
                | Q(
                    stare_procesare=FisierDocument.StareProcesare.IN_LUCRU,
                    procesare_inceputa_la__lte=limita_blocare,
                )
            )
            .order_by("incarcat_la")
            .values_list("pk", flat=True)[: options["limit"]]
        )
        procesate = 0
        erori = 0
        for fisier_id in ids:
            fisier = proceseaza_fisier(fisier_id, reincearca=True)
            if fisier.stare_procesare == FisierDocument.StareProcesare.PROCESAT:
                procesate += 1
            else:
                erori += 1
        self.stdout.write(self.style.SUCCESS(f"Procesate: {procesate}; cu eroare: {erori}"))
