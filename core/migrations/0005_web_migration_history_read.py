from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("core", "0004_privileged_sequences")]
    operations = [
        migrations.RunSQL(
            sql="GRANT SELECT ON TABLE django_migrations TO app_user;",
            reverse_sql="REVOKE SELECT ON TABLE django_migrations FROM app_user;",
        )
    ]
