import uuid

from django.db import migrations, models
from django.db.models.functions import Now


class Migration(migrations.Migration):
    dependencies = [("core", "0006_audit_log_state")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="IstoricStare",
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
                        ("firma_id", models.UUIDField()),
                        ("entitate_tip", models.CharField(max_length=30)),
                        ("entitate_id", models.UUIDField()),
                        ("stare_veche", models.CharField(blank=True, max_length=30, null=True)),
                        ("stare_noua", models.CharField(max_length=30)),
                        ("utilizator_id", models.UUIDField()),
                        ("comentariu", models.TextField(blank=True, null=True)),
                        (
                            "creat_la",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                    ],
                    options={
                        "verbose_name": "schimbare de stare",
                        "verbose_name_plural": "istoric stări",
                        "db_table": "istoric_stari",
                        "ordering": ("creat_la",),
                        "managed": False,
                    },
                )
            ],
        )
    ]
