from django.db import migrations

SQL = """
CREATE TABLE IF NOT EXISTS django_cache (
    cache_key varchar(255) PRIMARY KEY,
    value text NOT NULL,
    expires timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS django_cache_expires ON django_cache (expires);

REVOKE ALL ON TABLE django_cache FROM app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE django_cache TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE django_cache TO app_admin;
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0007_history_state")]

    operations = [
        migrations.RunSQL(
            sql=SQL,
            reverse_sql="DROP TABLE IF EXISTS django_cache;",
        )
    ]
