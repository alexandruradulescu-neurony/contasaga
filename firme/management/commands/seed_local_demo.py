from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from conturi.models import Utilizator
from firme.models import Firma, FirmaContabilitate


class Command(BaseCommand):
    help = "Creează date demo locale, idempotent, prin conexiunea privilegiată."

    def add_arguments(self, parser):
        parser.add_argument("--admin-password", required=True)
        parser.add_argument("--admin-email", default="admin.firma@localhost.test")

    def handle(self, *args, **options):
        if settings.RELEASE_ENVIRONMENT == "production" or not settings.DEBUG:
            raise CommandError("Datele demo locale nu pot fi create în mediul de producție.")
        if settings.DATABASES["default"]["USER"] != settings.DATABASES["privileged"]["USER"]:
            raise CommandError("Rulează comanda cu --settings=config.settings.admin")

        with transaction.atomic(using="default"):
            firma_contabilitate, _ = FirmaContabilitate.objects.update_or_create(
                cui="RO10000001",
                defaults={"denumire": "Contabilitate Locală SRL", "activ": True},
            )
            utilizator = Utilizator.objects.filter(email=options["admin_email"]).first()
            if utilizator is None:
                utilizator = Utilizator(email=options["admin_email"])
            utilizator.nume = "Administrator firmă"
            utilizator.rol = "admin_cabinet"
            utilizator.cabinet_id = firma_contabilitate.pk
            utilizator.is_active = True
            utilizator.is_staff = False
            utilizator.is_superuser = False
            utilizator.set_password(options["admin_password"])
            utilizator.save()

            Firma.objects.update_or_create(
                cabinet=firma_contabilitate,
                cui="RO20000001",
                defaults={
                    "denumire": "Client Demo SRL",
                    "adresa": "București, Sector 1",
                    "email_contact": "client@localhost.test",
                    "telefon_contact": "0700000000",
                    "activa": True,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Date demo pregătite. Autentificare aplicație: {options['admin_email']}"
            )
        )
