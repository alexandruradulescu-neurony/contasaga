import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Now


class Migration(migrations.Migration):
    dependencies = [
        ("conturi", "0001_utilizator_state"),
        ("firme", "0002_admin_insert_returning"),
    ]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="UtilizatorFirma",
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
                            "rol_in_firma",
                            models.CharField(
                                choices=[
                                    ("contabil_alocat", "Contabil alocat"),
                                    ("reprezentant_client", "Reprezentant client"),
                                    ("operator_upload", "Operator încărcare"),
                                ],
                                max_length=30,
                            ),
                        ),
                        (
                            "data_alocare",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                        (
                            "alocat_de",
                            models.ForeignKey(
                                blank=True,
                                db_column="alocat_de",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="alocari_create",
                                to="conturi.utilizator",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="alocari_utilizatori",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "utilizator",
                            models.ForeignKey(
                                db_column="utilizator_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="alocari_firme",
                                to="conturi.utilizator",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "alocare la firmă",
                        "verbose_name_plural": "alocări la firme",
                        "db_table": "utilizator_firma",
                        "managed": False,
                        "unique_together": {("utilizator", "firma")},
                    },
                ),
                migrations.CreateModel(
                    name="Invitatie",
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
                        ("email", models.EmailField(max_length=255)),
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
                        (
                            "rol_in_firma",
                            models.CharField(
                                blank=True,
                                choices=[
                                    ("contabil_alocat", "Contabil alocat"),
                                    ("reprezentant_client", "Reprezentant client"),
                                    ("operator_upload", "Operator încărcare"),
                                ],
                                max_length=30,
                                null=True,
                            ),
                        ),
                        ("token_hash", models.CharField(max_length=64, unique=True)),
                        ("expira_la", models.DateTimeField()),
                        ("acceptata_la", models.DateTimeField(blank=True, null=True)),
                        ("anulata_la", models.DateTimeField(blank=True, null=True)),
                        (
                            "creat_la",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                        (
                            "cabinet",
                            models.ForeignKey(
                                blank=True,
                                db_column="cabinet_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="invitatii_interne",
                                to="firme.firmacontabilitate",
                            ),
                        ),
                        (
                            "creat_de",
                            models.ForeignKey(
                                db_column="creat_de",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="invitatii_create",
                                to="conturi.utilizator",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                blank=True,
                                db_column="firma_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="invitatii_clienti",
                                to="firme.firma",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "invitație",
                        "verbose_name_plural": "invitații",
                        "db_table": "invitatii",
                        "ordering": ("-creat_la",),
                        "managed": False,
                    },
                ),
            ],
        )
    ]
