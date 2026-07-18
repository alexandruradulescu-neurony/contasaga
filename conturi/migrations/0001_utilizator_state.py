import uuid

from django.db import migrations, models
from django.db.models.functions import Now

import conturi.managers


class Migration(migrations.Migration):
    initial = True
    dependencies = [("core", "0001_bootstrap_schema")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="Utilizator",
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
                        ("password", models.CharField(db_column="parola_hash", max_length=255)),
                        (
                            "last_login",
                            models.DateTimeField(blank=True, null=True, verbose_name="last login"),
                        ),
                        ("cabinet_id", models.UUIDField(blank=True, null=True)),
                        ("nume", models.CharField(max_length=255)),
                        ("email", models.EmailField(max_length=255, unique=True)),
                        (
                            "rol",
                            models.CharField(
                                choices=[
                                    ("superuser_platforma", "Superuser platformă"),
                                    ("admin_cabinet", "Administrator cabinet"),
                                    ("contabil_coordonator", "Contabil coordonator"),
                                    ("contabil", "Contabil"),
                                    ("client_admin", "Administrator client"),
                                    ("client_operator", "Operator client"),
                                ],
                                max_length=30,
                            ),
                        ),
                        ("telefon", models.CharField(blank=True, max_length=30, null=True)),
                        ("is_active", models.BooleanField(db_column="activ", default=True)),
                        ("is_staff", models.BooleanField(default=False)),
                        ("is_superuser", models.BooleanField(default=False)),
                        (
                            "creat_la",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                    ],
                    options={
                        "verbose_name": "utilizator",
                        "verbose_name_plural": "utilizatori",
                        "db_table": "utilizatori",
                        "managed": False,
                    },
                    managers=[("objects", conturi.managers.UtilizatorManager())],
                )
            ],
        )
    ]
