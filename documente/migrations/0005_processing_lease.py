from django.db import migrations, models

SQL = """
ALTER TABLE fisiere_document
    ADD COLUMN IF NOT EXISTS procesare_inceputa_la timestamptz;

UPDATE fisiere_document
SET procesare_inceputa_la = incarcat_la
WHERE stare_procesare = 'in_lucru'
  AND procesare_inceputa_la IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_fisier_lease_coerenta'
          AND conrelid = 'fisiere_document'::regclass
    ) THEN
        ALTER TABLE fisiere_document
            ADD CONSTRAINT chk_fisier_lease_coerenta CHECK (
                (stare_procesare = 'in_lucru' AND procesare_inceputa_la IS NOT NULL)
                OR (stare_procesare <> 'in_lucru' AND procesare_inceputa_la IS NULL)
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_fisiere_procesare_blocata
    ON fisiere_document(procesare_inceputa_la)
    WHERE stare_procesare = 'in_lucru' AND sters_la IS NULL;
"""

REVERSE_SQL = """
DROP INDEX IF EXISTS idx_fisiere_procesare_blocata;
ALTER TABLE fisiere_document DROP CONSTRAINT IF EXISTS chk_fisier_lease_coerenta;
ALTER TABLE fisiere_document DROP COLUMN IF EXISTS procesare_inceputa_la;
"""


class Migration(migrations.Migration):
    dependencies = [("documente", "0004_document_handoff_traceability")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL)],
            state_operations=[
                migrations.AddField(
                    model_name="fisierdocument",
                    name="procesare_inceputa_la",
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
        )
    ]
