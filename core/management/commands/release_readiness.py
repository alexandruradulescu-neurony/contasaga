from django.conf import settings
from django.core import checks
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from documente.models import FisierDocument
from documente.processing import LEASE_PROCESARE
from documente.storage import get_document_storage
from exporturi.models import Export
from notificari.models import Notificare


class Command(BaseCommand):
    help = "Verifică blocajele tehnice înaintea unui release. Nu modifică date."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Tratează avertismentele de deployment ca blocaje.",
        )

    def _verifica_rol_db(self, alias: str, *, bypass_asteptat: bool) -> str | None:
        try:
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    """
                    SELECT current_user, rol.rolsuper, rol.rolbypassrls
                    FROM pg_roles rol
                    WHERE rol.rolname = current_user
                    """
                )
                nume, superuser, bypass = cursor.fetchone()
        except Exception as exc:
            return f"Conexiunea {alias} nu este disponibilă: {exc}"
        if superuser:
            return f"Rolul {nume} folosit de {alias} nu poate fi superuser."
        if bypass is not bypass_asteptat:
            return (
                f"Rolul {nume} folosit de {alias} are rolbypassrls={bypass}, "
                f"dar era așteptat {bypass_asteptat}."
            )
        self.stdout.write(self.style.SUCCESS(f"[OK] DB {alias}: {nume}"))
        return None

    def _verifica_migrari(self) -> str | None:
        try:
            executor = MigrationExecutor(connections["default"])
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except Exception as exc:
            return f"Starea migrărilor nu poate fi citită: {exc}"
        if plan:
            migrari = ", ".join(f"{migration.app_label}.{migration.name}" for migration, _ in plan)
            return f"Există migrări neaplicate: {migrari}"
        self.stdout.write(self.style.SUCCESS("[OK] Toate migrările sunt aplicate"))
        return None

    def _verifica_cache_partajat(self) -> str | None:
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        to_regclass('public.django_cache') IS NOT NULL,
                        has_table_privilege(current_user, 'public.django_cache',
                            'SELECT,INSERT,UPDATE,DELETE')
                    """
                )
                exista, are_drepturi = cursor.fetchone()
        except Exception as exc:
            return f"Cache-ul partajat nu poate fi verificat: {exc}"
        if not exista or not are_drepturi:
            return "Tabela django_cache sau drepturile web necesare lipsesc."
        self.stdout.write(self.style.SUCCESS("[OK] Cache PostgreSQL partajat"))
        return None

    def handle(self, *args, **options):
        erori: list[str] = []
        avertismente: list[str] = []

        mesaje = checks.run_checks(include_deployment_checks=True)
        for mesaj in mesaje:
            text = f"{mesaj.id}: {mesaj.msg}"
            if mesaj.level >= checks.ERROR:
                erori.append(text)
            elif mesaj.level >= checks.WARNING:
                avertismente.append(text)

        for alias, bypass in (("default", False), ("privileged", True)):
            if eroare := self._verifica_rol_db(alias, bypass_asteptat=bypass):
                erori.append(eroare)

        if eroare := self._verifica_migrari():
            erori.append(eroare)
        if eroare := self._verifica_cache_partajat():
            erori.append(eroare)

        try:
            get_document_storage().healthcheck()
            self.stdout.write(
                self.style.SUCCESS(f"[OK] Storage: {settings.DOCUMENT_STORAGE_BACKEND}")
            )
        except Exception as exc:
            erori.append(f"Storage-ul nu este disponibil: {exc}")

        try:
            cozi = {
                "fișiere în așteptare": FisierDocument.objects.using("privileged")
                .filter(stare_procesare="in_asteptare", sters_la__isnull=True)
                .count(),
                "fișiere retry": FisierDocument.objects.using("privileged")
                .filter(
                    stare_procesare="eroare",
                    incercari_procesare__lt=3,
                    sters_la__isnull=True,
                )
                .count(),
                "fișiere cu procesare blocată": FisierDocument.objects.using("privileged")
                .filter(
                    stare_procesare="in_lucru",
                    procesare_inceputa_la__lte=timezone.now() - LEASE_PROCESARE,
                    sters_la__isnull=True,
                )
                .count(),
                "fișiere active eșuate definitiv": FisierDocument.objects.using("privileged")
                .filter(
                    stare_procesare="eroare",
                    incercari_procesare__gte=3,
                    activ=True,
                    sters_la__isnull=True,
                )
                .count(),
                "exporturi în lucru": Export.objects.using("privileged")
                .filter(status=Export.Status.IN_LUCRU)
                .count(),
                "exporturi eșuate": Export.objects.using("privileged")
                .filter(status=Export.Status.EROARE)
                .count(),
                "emailuri de retrimis": Notificare.objects.using("privileged")
                .filter(
                    trimite_email=True,
                    email_trimis_la__isnull=True,
                    incercari_email__lt=3,
                )
                .count(),
                "emailuri eșuate definitiv": Notificare.objects.using("privileged")
                .filter(
                    trimite_email=True,
                    email_trimis_la__isnull=True,
                    incercari_email__gte=3,
                )
                .count(),
            }
            self.stdout.write("[INFO] Cozi: " + "; ".join(f"{k}={v}" for k, v in cozi.items()))
            for nume, valoare in cozi.items():
                if valoare:
                    avertismente.append(f"Coada operațională necesită triere: {nume}={valoare}")
        except Exception as exc:
            erori.append(f"Cozile operaționale nu pot fi inspectate: {exc}")

        for avertisment in avertismente:
            self.stdout.write(self.style.WARNING(f"[WARN] {avertisment}"))
        for eroare in erori:
            self.stderr.write(self.style.ERROR(f"[FAIL] {eroare}"))

        if erori or (options["strict"] and avertismente):
            raise CommandError(
                f"Release blocat: {len(erori)} erori, {len(avertismente)} avertismente."
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Release readiness tehnic: PASS ({len(avertismente)} avertismente)."
            )
        )
