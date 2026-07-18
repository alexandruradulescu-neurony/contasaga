from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("core", "0002_django_session_delete"),
    ]
    operations = [
        migrations.RunSQL(
            sql="""
                REVOKE ALL ON TABLE django_migrations, django_admin_log FROM app_user;
                GRANT SELECT ON TABLE django_migrations TO app_user;
                REVOKE INSERT, UPDATE ON TABLE
                    django_content_type,
                    auth_permission,
                    auth_group,
                    auth_group_permissions
                FROM app_user;
            """,
            reverse_sql=migrations.RunSQL.noop,
        )
    ]
