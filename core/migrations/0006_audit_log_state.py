import uuid

from django.db import migrations, models
from django.db.models.functions import Now


class Migration(migrations.Migration):
    dependencies = [("core", "0005_web_migration_history_read")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="AuditLog",
                    fields=[
                        (
                            "id",
                            models.UUIDField(
                                default=uuid.uuid4,
                                editable=False,
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("firma_id", models.UUIDField(blank=True, null=True)),
                        ("utilizator_id", models.UUIDField(blank=True, null=True)),
                        ("entitate_tip", models.CharField(max_length=30)),
                        ("entitate_id", models.UUIDField(blank=True, null=True)),
                        ("actiune", models.CharField(max_length=40)),
                        ("date_vechi", models.JSONField(blank=True, null=True)),
                        ("date_noi", models.JSONField(blank=True, null=True)),
                        ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                        (
                            "user_agent",
                            models.CharField(blank=True, max_length=255, null=True),
                        ),
                        (
                            "creat_la",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                    ],
                    options={
                        "verbose_name": "eveniment de audit",
                        "verbose_name_plural": "evenimente de audit",
                        "db_table": "audit_log",
                        "managed": False,
                    },
                )
            ],
        )
    ]
