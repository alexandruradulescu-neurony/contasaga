import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

SQL = """
ALTER TABLE predari_documente
    ADD COLUMN IF NOT EXISTS digitizare_status varchar(30) NOT NULL DEFAULT 'nedecisa',
    ADD COLUMN IF NOT EXISTS numar_documente_estimat integer,
    ADD COLUMN IF NOT EXISTS digitizare_inceputa_la timestamptz,
    ADD COLUMN IF NOT EXISTS digitizare_inceputa_de uuid
        REFERENCES utilizatori(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS digitizare_finalizata_la timestamptz,
    ADD COLUMN IF NOT EXISTS digitizare_finalizata_de uuid
        REFERENCES utilizatori(id) ON DELETE RESTRICT;

UPDATE predari_documente
SET digitizare_status = 'nu_este_necesara'
WHERE metoda = 'exclusiv_digital' AND digitizare_status = 'nedecisa';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_predare_id_firma_perioada'
          AND conrelid = 'predari_documente'::regclass
    ) THEN
        ALTER TABLE predari_documente
            ADD CONSTRAINT uq_predare_id_firma_perioada
            UNIQUE (id, firma_id, perioada_contabila_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_predare_digitizare_coerenta'
          AND conrelid = 'predari_documente'::regclass
    ) THEN
        ALTER TABLE predari_documente
            ADD CONSTRAINT chk_predare_digitizare_coerenta CHECK (
                (numar_documente_estimat IS NULL OR numar_documente_estimat > 0)
                AND (
                    (metoda = 'exclusiv_digital'
                        AND digitizare_status = 'nu_este_necesara'
                        AND numar_documente_estimat IS NULL
                        AND digitizare_inceputa_la IS NULL
                        AND digitizare_inceputa_de IS NULL
                        AND digitizare_finalizata_la IS NULL
                        AND digitizare_finalizata_de IS NULL)
                    OR
                    (metoda <> 'exclusiv_digital'
                        AND (
                            (digitizare_status IN ('nedecisa', 'nu_este_necesara')
                                AND numar_documente_estimat IS NULL
                                AND digitizare_inceputa_la IS NULL
                                AND digitizare_inceputa_de IS NULL
                                AND digitizare_finalizata_la IS NULL
                                AND digitizare_finalizata_de IS NULL)
                            OR
                            (digitizare_status = 'in_lucru'
                                AND digitizare_inceputa_la IS NOT NULL
                                AND digitizare_inceputa_de IS NOT NULL
                                AND digitizare_finalizata_la IS NULL
                                AND digitizare_finalizata_de IS NULL)
                            OR
                            (digitizare_status = 'finalizata'
                                AND digitizare_inceputa_la IS NOT NULL
                                AND digitizare_inceputa_de IS NOT NULL
                                AND digitizare_finalizata_la IS NOT NULL
                                AND digitizare_finalizata_de IS NOT NULL
                                AND digitizare_inceputa_la <= digitizare_finalizata_la)
                        )
                        AND (
                            status IN ('receptionata', 'returnata')
                            OR digitizare_status = 'nedecisa'
                        ))
                )
            );
    END IF;
END
$$;
"""

REVERSE_SQL = """
ALTER TABLE predari_documente DROP CONSTRAINT IF EXISTS chk_predare_digitizare_coerenta;
ALTER TABLE predari_documente DROP CONSTRAINT IF EXISTS uq_predare_id_firma_perioada;
ALTER TABLE predari_documente
    DROP COLUMN IF EXISTS digitizare_finalizata_de,
    DROP COLUMN IF EXISTS digitizare_finalizata_la,
    DROP COLUMN IF EXISTS digitizare_inceputa_de,
    DROP COLUMN IF EXISTS digitizare_inceputa_la,
    DROP COLUMN IF EXISTS numar_documente_estimat,
    DROP COLUMN IF EXISTS digitizare_status;
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("logistica", "0001_handoff_state_and_security"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL)],
            state_operations=[
                migrations.AddField(
                    model_name="predaredocumente",
                    name="digitizare_status",
                    field=models.CharField(
                        choices=[
                            ("nedecisa", "Nedecisă"),
                            ("nu_este_necesara", "Nu este necesară"),
                            ("in_lucru", "În lucru"),
                            ("finalizata", "Finalizată"),
                        ],
                        default="nedecisa",
                        max_length=30,
                    ),
                ),
                migrations.AddField(
                    model_name="predaredocumente",
                    name="numar_documente_estimat",
                    field=models.IntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="predaredocumente",
                    name="digitizare_inceputa_la",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="predaredocumente",
                    name="digitizare_inceputa_de",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="digitizare_inceputa_de",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="digitizari_incepute",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                migrations.AddField(
                    model_name="predaredocumente",
                    name="digitizare_finalizata_la",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="predaredocumente",
                    name="digitizare_finalizata_de",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="digitizare_finalizata_de",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="digitizari_finalizate",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        )
    ]
