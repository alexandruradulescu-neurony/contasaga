import django.db.models.deletion
from django.db import migrations, models

SQL = """
ALTER TABLE intentii_upload
    ADD COLUMN IF NOT EXISTS inlocuieste_fisier_id uuid;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_intentie_inlocuieste_fisier'
          AND conrelid = 'intentii_upload'::regclass
    ) THEN
        ALTER TABLE intentii_upload
            ADD CONSTRAINT fk_intentie_inlocuieste_fisier
            FOREIGN KEY (inlocuieste_fisier_id, document_id)
            REFERENCES fisiere_document(id, document_id)
            ON DELETE RESTRICT;
    END IF;
END
$$;
"""

REVERSE_SQL = """
ALTER TABLE intentii_upload
    DROP CONSTRAINT IF EXISTS fk_intentie_inlocuieste_fisier;
ALTER TABLE intentii_upload
    DROP COLUMN IF EXISTS inlocuieste_fisier_id;
"""


class Migration(migrations.Migration):
    dependencies = [("documente", "0002_intentieupload")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="intentieupload",
                    name="inlocuieste_fisier",
                    field=models.ForeignKey(
                        blank=True,
                        db_column="inlocuieste_fisier_id",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="intentii_inlocuire",
                        to="documente.fisierdocument",
                    ),
                ),
            ],
        ),
    ]
