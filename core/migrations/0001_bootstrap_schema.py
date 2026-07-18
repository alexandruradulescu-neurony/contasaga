from pathlib import Path

from django.db import migrations

SCHEMA_SQL = (Path(__file__).resolve().parents[2] / "specsv5" / "schema_starter.sql").read_text(
    encoding="utf-8"
)


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.RunSQL(sql=SCHEMA_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
