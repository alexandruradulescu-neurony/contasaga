from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0003_restrict_django_tables")]
    operations = [
        migrations.RunSQL(
            sql="""
                GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_admin;
                ALTER DEFAULT PRIVILEGES IN SCHEMA public
                    GRANT USAGE, SELECT ON SEQUENCES TO app_admin;
            """,
            reverse_sql=migrations.RunSQL.noop,
        )
    ]
