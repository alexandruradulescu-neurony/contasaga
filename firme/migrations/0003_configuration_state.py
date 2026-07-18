import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Now


class Migration(migrations.Migration):
    dependencies = [
        ("firme", "0002_admin_insert_returning"),
        ("conturi", "0002_access_state"),
    ]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="TipDocument",
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
                        ("cod", models.CharField(max_length=50, unique=True)),
                        ("denumire", models.CharField(max_length=100)),
                        ("categorie", models.CharField(max_length=30)),
                        ("necesita_serie_numar", models.BooleanField(default=False)),
                        ("necesita_cont_financiar", models.BooleanField(default=False)),
                        ("activ", models.BooleanField(default=True)),
                    ],
                    options={
                        "verbose_name": "tip de document",
                        "verbose_name_plural": "tipuri de document",
                        "db_table": "tipuri_document",
                        "ordering": ("denumire",),
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="ContFinanciar",
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
                        (
                            "tip",
                            models.CharField(
                                choices=[
                                    ("banca", "Cont bancar"),
                                    ("casa", "Casierie"),
                                    ("card", "Card"),
                                ],
                                max_length=20,
                            ),
                        ),
                        ("banca", models.CharField(blank=True, max_length=100, null=True)),
                        ("iban", models.CharField(blank=True, max_length=34, null=True)),
                        ("moneda", models.CharField(default="RON", max_length=3)),
                        ("denumire", models.CharField(max_length=100)),
                        ("activ", models.BooleanField(default=True)),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="conturi_financiare",
                                to="firme.firma",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "cont financiar",
                        "verbose_name_plural": "conturi financiare",
                        "db_table": "conturi_financiare",
                        "ordering": ("denumire",),
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="ConfigurareDocumentFirma",
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
                        ("obligatoriu", models.BooleanField(default=False)),
                        (
                            "frecventa",
                            models.CharField(
                                choices=[
                                    ("lunar", "Lunar"),
                                    ("ocazional", "Ocazional"),
                                    ("zilnic", "Zilnic"),
                                ],
                                default="lunar",
                                max_length=20,
                            ),
                        ),
                        ("termen_predare_zi", models.SmallIntegerField(blank=True, null=True)),
                        ("activ", models.BooleanField(default=True)),
                        ("observatii", models.TextField(blank=True, null=True)),
                        (
                            "creat_la",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                        (
                            "creat_de",
                            models.ForeignKey(
                                blank=True,
                                db_column="creat_de",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="configurari_documente_create",
                                to="conturi.utilizator",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="configurari_documente",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "tip_document",
                            models.ForeignKey(
                                db_column="tip_document_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="configurari_firme",
                                to="firme.tipdocument",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "configurare document",
                        "verbose_name_plural": "configurări documente",
                        "db_table": "configurare_documente_firma",
                        "managed": False,
                        "unique_together": {("firma", "tip_document")},
                    },
                ),
            ],
        )
    ]
