import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Now


class Migration(migrations.Migration):
    initial = True
    dependencies = [("core", "0001_bootstrap_schema")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="FirmaContabilitate",
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
                        ("denumire", models.CharField(max_length=255)),
                        ("cui", models.CharField(blank=True, max_length=20, null=True)),
                        ("activ", models.BooleanField(default=True)),
                        (
                            "creat_la",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                    ],
                    options={
                        "verbose_name": "firmă de contabilitate",
                        "verbose_name_plural": "firme de contabilitate",
                        "db_table": "cabinete_contabilitate",
                        "ordering": ("denumire",),
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="Firma",
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
                        ("cui", models.CharField(max_length=20)),
                        ("denumire", models.CharField(max_length=255)),
                        ("adresa", models.CharField(blank=True, max_length=500, null=True)),
                        (
                            "email_contact",
                            models.EmailField(blank=True, max_length=255, null=True),
                        ),
                        (
                            "telefon_contact",
                            models.CharField(blank=True, max_length=30, null=True),
                        ),
                        ("activa", models.BooleanField(default=True)),
                        (
                            "creat_la",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                        (
                            "cabinet",
                            models.ForeignKey(
                                db_column="cabinet_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="firme_cliente",
                                to="firme.firmacontabilitate",
                                verbose_name="firmă de contabilitate",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "firmă clientă",
                        "verbose_name_plural": "firme cliente",
                        "db_table": "firme",
                        "ordering": ("denumire",),
                        "managed": False,
                        "unique_together": {("cabinet", "cui")},
                    },
                ),
            ],
        )
    ]
