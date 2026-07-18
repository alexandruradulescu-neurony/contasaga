import uuid

import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Now


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("conturi", "0002_access_state"),
        ("firme", "0003_configuration_state"),
        ("core", "0007_history_state"),
    ]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="PerioadaContabila",
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
                        ("luna", models.SmallIntegerField()),
                        ("an", models.SmallIntegerField()),
                        (
                            "stare",
                            models.CharField(
                                choices=[
                                    ("deschisa", "Deschisă"),
                                    ("documente_incomplete", "Documente incomplete"),
                                    ("gata_pentru_verificare", "Gata pentru verificare"),
                                    ("in_lucru", "În lucru"),
                                    ("inchisa", "Închisă"),
                                ],
                                default="deschisa",
                                max_length=30,
                            ),
                        ),
                        ("termen_predare", models.DateField(blank=True, null=True)),
                        ("confirmata_de_client_la", models.DateTimeField(blank=True, null=True)),
                        ("inchisa_la", models.DateTimeField(blank=True, null=True)),
                        ("observatii", models.TextField(blank=True, null=True)),
                        (
                            "creat_la",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                        (
                            "contabil_responsabil",
                            models.ForeignKey(
                                blank=True,
                                db_column="contabil_responsabil_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="perioade_responsabil",
                                to="conturi.utilizator",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="perioade_contabile",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "inchisa_de",
                            models.ForeignKey(
                                blank=True,
                                db_column="inchisa_de",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="perioade_inchise",
                                to="conturi.utilizator",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "perioadă contabilă",
                        "verbose_name_plural": "perioade contabile",
                        "db_table": "perioade_contabile",
                        "ordering": ("-an", "-luna"),
                        "managed": False,
                        "unique_together": {("firma", "luna", "an")},
                    },
                ),
                migrations.CreateModel(
                    name="CerintaDocumentPerioada",
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
                            "status",
                            models.CharField(
                                choices=[
                                    ("lipsa", "Lipsă"),
                                    ("partial", "Parțial"),
                                    ("primit", "Primit"),
                                    ("nu_se_aplica", "Nu se aplică"),
                                ],
                                default="lipsa",
                                max_length=20,
                            ),
                        ),
                        ("numar_documente_declarat", models.IntegerField(blank=True, null=True)),
                        ("observatii_client", models.TextField(blank=True, null=True)),
                        ("observatii_contabil", models.TextField(blank=True, null=True)),
                        (
                            "actualizat_la",
                            models.DateTimeField(db_default=Now(), editable=False),
                        ),
                        (
                            "cont_financiar",
                            models.ForeignKey(
                                blank=True,
                                db_column="cont_financiar_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="cerinte_perioade",
                                to="firme.contfinanciar",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="cerinte_documente",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="cerinte",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                        (
                            "tip_document",
                            models.ForeignKey(
                                db_column="tip_document_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="cerinte_perioade",
                                to="firme.tipdocument",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "cerință document",
                        "verbose_name_plural": "cerințe documente",
                        "db_table": "cerinte_documente_perioada",
                        "ordering": ("tip_document__denumire",),
                        "managed": False,
                    },
                ),
            ],
        )
    ]
