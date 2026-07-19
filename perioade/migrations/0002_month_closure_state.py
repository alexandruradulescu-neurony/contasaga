from django.db import migrations, models

SQL = """
ALTER TABLE perioade_contabile DROP CONSTRAINT IF EXISTS chk_perioada_stare;
ALTER TABLE perioade_contabile ADD CONSTRAINT chk_perioada_stare CHECK (stare IN (
    'deschisa', 'documente_incomplete', 'gata_pentru_verificare', 'in_lucru',
    'inchidere_in_curs', 'inchisa'
));
"""

REVERSE_SQL = """
UPDATE perioade_contabile SET stare = 'in_lucru' WHERE stare = 'inchidere_in_curs';
ALTER TABLE perioade_contabile DROP CONSTRAINT IF EXISTS chk_perioada_stare;
ALTER TABLE perioade_contabile ADD CONSTRAINT chk_perioada_stare CHECK (stare IN (
    'deschisa', 'documente_incomplete', 'gata_pentru_verificare', 'in_lucru', 'inchisa'
));
"""


class Migration(migrations.Migration):
    dependencies = [("perioade", "0001_period_state")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL)],
            state_operations=[
                migrations.AlterField(
                    model_name="perioadacontabila",
                    name="stare",
                    field=models.CharField(
                        choices=[
                            ("deschisa", "Deschisă"),
                            ("documente_incomplete", "Documente incomplete"),
                            ("gata_pentru_verificare", "Gata pentru verificare"),
                            ("in_lucru", "În lucru"),
                            ("inchidere_in_curs", "În curs de închidere"),
                            ("inchisa", "Închisă"),
                        ],
                        default="deschisa",
                        max_length=30,
                    ),
                )
            ],
        )
    ]
