from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q
from django.utils import timezone

from notificari.models import Notificare
from notificari.services import (
    destinatari_clienti_reminder,
    programeaza_notificari,
    reincearca_emailuri_pendente,
)
from perioade.models import CerintaDocumentPerioada, PerioadaContabila


def parseaza_data(valoare: str | None) -> date:
    if valoare is None:
        return timezone.localdate()
    try:
        return date.fromisoformat(valoare)
    except ValueError as exc:
        raise CommandError("--date trebuie să fie în formatul YYYY-MM-DD.") from exc


def eticheta_reminder(data_rulare: date, termen: date) -> str | None:
    zile = (termen - data_rulare).days
    if zile == 0:
        return "T"
    if zile == 3:
        return "T-3"
    return None


class Command(BaseCommand):
    help = "Trimite reminderul T-3/T când perioada are cerințe lipsă."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="data_rulare",
            help="Data simulată, YYYY-MM-DD; implicit este data locală curentă.",
        )
        parser.add_argument("--retry-limit", type=int, default=100)
        parser.add_argument("--skip-retries", action="store_true")

    def handle(self, *args, **options):
        data_rulare = parseaza_data(options["data_rulare"])
        if options["retry_limit"] < 0:
            raise CommandError("--retry-limit nu poate fi negativ.")

        retry_trimise = retry_esuate = 0
        if not options["skip_retries"] and options["retry_limit"]:
            retry_trimise, retry_esuate = reincearca_emailuri_pendente(limit=options["retry_limit"])

        termene = (data_rulare, data_rulare + timedelta(days=3))
        perioade = list(
            PerioadaContabila.objects.using("privileged")
            .exclude(stare=PerioadaContabila.Stare.INCHISA)
            .filter(termen_predare__in=termene)
            .annotate(
                cerinte_lipsa=Count(
                    "cerinte",
                    filter=Q(cerinte__status=CerintaDocumentPerioada.Status.LIPSA),
                )
            )
            .filter(cerinte_lipsa__gt=0)
            .select_related("firma")
        )

        livrari_programate = 0
        for perioada in perioade:
            reper = eticheta_reminder(data_rulare, perioada.termen_predare)
            if reper is None:
                continue
            destinatari = destinatari_clienti_reminder(
                perioada.firma_id,
                using="privileged",
            )
            mesaj = (
                f"Termenul de predare pentru {perioada.firma.denumire}, "
                f"{perioada.luna:02d}/{perioada.an}, este "
                f"{perioada.termen_predare:%d.%m.%Y}. "
                f"Mai sunt {perioada.cerinte_lipsa} cerințe fără documente."
            )
            programeaza_notificari(
                destinatari=destinatari,
                tip=Notificare.Tip.REMINDER_TERMEN,
                entitate_tip="perioada",
                entitate_id=perioada.pk,
                mesaj=mesaj,
                eveniment_id=f"{perioada.termen_predare.isoformat()}:{reper}",
                cu_email=True,
                subiect_email=f"Reminder documente {reper} — {perioada.firma.denumire}",
                vizibila_in_app=False,
                using="privileged",
            )
            livrari_programate += len(destinatari)

        self.stdout.write(
            self.style.SUCCESS(
                f"Data: {data_rulare:%Y-%m-%d}; perioade eligibile: {len(perioade)}; "
                f"livrări evaluate: {livrari_programate}; "
                f"retry trimise: {retry_trimise}; retry încă nesemise: {retry_esuate}"
            )
        )
