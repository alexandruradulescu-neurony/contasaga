import uuid

import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

SQL = """
ALTER TABLE notificari
    ADD COLUMN IF NOT EXISTS cheie_deduplicare varchar(64);

CREATE UNIQUE INDEX IF NOT EXISTS uq_notificari_deduplicare
    ON notificari(cheie_deduplicare)
    WHERE cheie_deduplicare IS NOT NULL;

REVOKE UPDATE ON notificari FROM app_user;
GRANT UPDATE (citita) ON notificari TO app_user;
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0007_history_state"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=SQL, reverse_sql=migrations.RunSQL.noop),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="Notificare",
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
                                    ("reminder_termen", "Reminder termen"),
                                    ("document_nou", "Document nou"),
                                    ("necesita_clarificari", "Necesită clarificări"),
                                    ("clarificari_rezolvate", "Clarificări rezolvate"),
                                    ("perioada_confirmata", "Perioadă confirmată"),
                                    ("perioada_inchisa", "Perioadă închisă"),
                                    ("comentariu_nou", "Comentariu nou"),
                                    ("export_finalizat", "Export finalizat"),
                                    (
                                        "eroare_procesare_fisier",
                                        "Eroare procesare fișier",
                                    ),
                                    ("invitatie", "Invitație"),
                                ],
                                max_length=40,
                            ),
                        ),
                        (
                            "entitate_tip",
                            models.CharField(blank=True, max_length=30, null=True),
                        ),
                        ("entitate_id", models.UUIDField(blank=True, null=True)),
                        ("mesaj", models.CharField(max_length=500)),
                        (
                            "cheie_deduplicare",
                            models.CharField(
                                blank=True,
                                max_length=64,
                                null=True,
                                unique=True,
                            ),
                        ),
                        ("citita", models.BooleanField(default=False)),
                        (
                            "creat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        (
                            "utilizator",
                            models.ForeignKey(
                                db_column="utilizator_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="notificari",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "notificare",
                        "verbose_name_plural": "notificări",
                        "db_table": "notificari",
                        "ordering": ("-creat_la",),
                        "managed": False,
                    },
                )
            ],
        )
    ]
