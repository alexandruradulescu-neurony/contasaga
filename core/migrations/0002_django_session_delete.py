from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_bootstrap_schema"),
        ("sessions", "0001_initial"),
    ]
    operations = [
        migrations.RunSQL(
            sql="GRANT DELETE ON TABLE django_session TO app_user;",
            reverse_sql="REVOKE DELETE ON TABLE django_session FROM app_user;",
        )
    ]
