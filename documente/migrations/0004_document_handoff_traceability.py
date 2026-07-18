import django.db.models.deletion
from django.db import migrations, models

SQL = """
ALTER TABLE documente
    ADD COLUMN IF NOT EXISTS predare_documente_id uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_document_predare'
          AND conrelid = 'documente'::regclass
    ) THEN
        ALTER TABLE documente
            ADD CONSTRAINT fk_document_predare
            FOREIGN KEY (predare_documente_id, firma_id, perioada_contabila_id)
            REFERENCES predari_documente(id, firma_id, perioada_contabila_id)
            ON DELETE RESTRICT;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_documente_predare
    ON documente(predare_documente_id)
    WHERE predare_documente_id IS NOT NULL;
"""

REVERSE_SQL = """
DROP INDEX IF EXISTS idx_documente_predare;
ALTER TABLE documente DROP CONSTRAINT IF EXISTS fk_document_predare;
ALTER TABLE documente DROP COLUMN IF EXISTS predare_documente_id;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documente", "0003_intentie_upload_inlocuire"),
        ("logistica", "0002_optional_digitization_workflow"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL)],
            state_operations=[
                migrations.AddField(
                    model_name="document",
                    name="predare_documente",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="predare_documente_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="documente_digitizate",
                        to="logistica.predaredocumente",
                    ),
                )
            ],
        )
    ]
