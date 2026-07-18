import uuid

import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_export_activ_solicitant
    ON exporturi(perioada_contabila_id, solicitat_de)
    WHERE status = 'in_lucru';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_export_stare_coerenta'
    ) THEN
        ALTER TABLE exporturi ADD CONSTRAINT chk_export_stare_coerenta CHECK (
            (status = 'in_lucru' AND storage_key IS NULL
                AND eroare IS NULL AND expira_la IS NULL)
            OR (status = 'finalizat' AND storage_key IS NOT NULL
                AND eroare IS NULL AND expira_la IS NOT NULL)
            OR (status = 'eroare' AND storage_key IS NULL
                AND eroare IS NOT NULL AND expira_la IS NULL)
            OR (status = 'expirat' AND storage_key IS NULL AND eroare IS NULL)
        );
    END IF;
END
$$;

DROP POLICY IF EXISTS pol_exporturi_all ON exporturi;
DROP POLICY IF EXISTS pol_exporturi_select ON exporturi;
CREATE POLICY pol_exporturi_select ON exporturi FOR SELECT
    USING (
        solicitat_de = fn_utilizator_curent()
        AND firma_id IN (SELECT fn_firmele_utilizatorului())
    );

REVOKE INSERT, UPDATE, DELETE ON exporturi FROM app_user;
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("conturi", "0002_access_state"),
        ("perioade", "0001_period_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=SQL, reverse_sql=migrations.RunSQL.noop),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="Export",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        (
                            "status",
                            models.CharField(
                                choices=[
                                    ("in_lucru", "În lucru"),
                                    ("finalizat", "Finalizat"),
                                    ("eroare", "Eroare"),
                                    ("expirat", "Expirat"),
                                ],
                                default="in_lucru",
                                max_length=20,
                            ),
                        ),
                        (
                            "storage_key",
                            models.CharField(blank=True, max_length=500, null=True),
                        ),
                        ("eroare", models.TextField(blank=True, null=True)),
                        (
                            "creat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        ("expira_la", models.DateTimeField(blank=True, null=True)),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="exporturi",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="exporturi",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                        (
                            "solicitat_de",
                            models.ForeignKey(
                                db_column="solicitat_de",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="exporturi_solicitate",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "export",
                        "verbose_name_plural": "exporturi",
                        "db_table": "exporturi",
                        "ordering": ("-creat_la",),
                        "managed": False,
                    },
                )
            ],
        )
    ]
