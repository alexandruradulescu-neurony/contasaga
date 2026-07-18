import uuid

import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_predare_stare_coerenta'
    ) THEN
        ALTER TABLE predari_documente
            ADD CONSTRAINT chk_predare_stare_coerenta CHECK (
                (
                    metoda = 'exclusiv_digital'
                    AND status = 'receptionata'
                    AND numar_cutii = 0
                    AND data_programata IS NULL
                    AND preluat_de IS NULL
                    AND data_preluare IS NULL
                    AND data_receptie IS NOT NULL
                    AND data_returnare IS NULL
                )
                OR (
                    metoda <> 'exclusiv_digital'
                    AND predat_de IS NOT NULL
                    AND btrim(predat_de) <> ''
                    AND numar_cutii > 0
                    AND data_programata IS NOT NULL
                    AND (
                        (status = 'programata' AND preluat_de IS NULL
                            AND data_preluare IS NULL AND data_receptie IS NULL
                            AND data_returnare IS NULL)
                        OR (status = 'preluata' AND preluat_de IS NOT NULL
                            AND data_preluare IS NOT NULL AND data_receptie IS NULL
                            AND data_returnare IS NULL)
                        OR (status = 'receptionata' AND preluat_de IS NOT NULL
                            AND data_preluare IS NOT NULL AND data_receptie IS NOT NULL
                            AND data_returnare IS NULL
                            AND data_preluare <= data_receptie)
                        OR (status = 'returnata' AND preluat_de IS NOT NULL
                            AND data_preluare IS NOT NULL AND data_receptie IS NOT NULL
                            AND data_returnare IS NOT NULL
                            AND data_preluare <= data_receptie
                            AND data_receptie <= data_returnare)
                    )
                )
            );
    END IF;
END
$$;

DROP POLICY IF EXISTS pol_predari_all ON predari_documente;
DROP POLICY IF EXISTS pol_predari_select ON predari_documente;
CREATE POLICY pol_predari_select ON predari_documente FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));

REVOKE INSERT, UPDATE, DELETE ON predari_documente FROM app_user;
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
                    name="PredareDocumente",
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
                            "metoda",
                            models.CharField(
                                choices=[
                                    ("curier", "Curier"),
                                    ("posta", "Poștă"),
                                    ("ridicare_contabil", "Ridicare de către contabil"),
                                    ("predare_client", "Predare de către client"),
                                    ("exclusiv_digital", "Exclusiv digital"),
                                ],
                                max_length=30,
                            ),
                        ),
                        (
                            "status",
                            models.CharField(
                                choices=[
                                    ("programata", "Programată"),
                                    ("preluata", "Preluată"),
                                    ("receptionata", "Recepționată"),
                                    ("returnata", "Returnată"),
                                ],
                                default="programata",
                                max_length=20,
                            ),
                        ),
                        (
                            "predat_de",
                            models.CharField(blank=True, max_length=255, null=True),
                        ),
                        ("numar_cutii", models.IntegerField(default=0)),
                        ("data_programata", models.DateTimeField(blank=True, null=True)),
                        ("data_preluare", models.DateTimeField(blank=True, null=True)),
                        ("data_receptie", models.DateTimeField(blank=True, null=True)),
                        ("data_returnare", models.DateTimeField(blank=True, null=True)),
                        ("observatii", models.TextField(blank=True, null=True)),
                        (
                            "creat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        (
                            "creat_de",
                            models.ForeignKey(
                                blank=True,
                                db_column="creat_de",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="predari_create",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="predari_documente",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                blank=True,
                                db_column="perioada_contabila_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="predari_documente",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                        (
                            "preluat_de",
                            models.ForeignKey(
                                blank=True,
                                db_column="preluat_de",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="predari_preluate",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "predare de documente",
                        "verbose_name_plural": "predări de documente",
                        "db_table": "predari_documente",
                        "ordering": ("-creat_la",),
                        "managed": False,
                    },
                )
            ],
        )
    ]
