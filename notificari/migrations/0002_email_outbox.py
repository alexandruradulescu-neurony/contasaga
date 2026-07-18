from django.conf import settings
from django.db import migrations, models

SQL = """
ALTER TABLE notificari
    ADD COLUMN IF NOT EXISTS vizibila_in_app boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS trimite_email boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS subiect_email varchar(200),
    ADD COLUMN IF NOT EXISTS email_trimis_la timestamptz,
    ADD COLUMN IF NOT EXISTS incercari_email smallint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS eroare_email text;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_notif_incercari_email'
    ) THEN
        ALTER TABLE notificari ADD CONSTRAINT chk_notif_incercari_email
            CHECK (incercari_email BETWEEN 0 AND 3);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_notif_email_coerent'
    ) THEN
        ALTER TABLE notificari ADD CONSTRAINT chk_notif_email_coerent CHECK (
            (trimite_email AND subiect_email IS NOT NULL)
            OR (NOT trimite_email AND subiect_email IS NULL
                AND email_trimis_la IS NULL AND incercari_email = 0
                AND eroare_email IS NULL)
        );
    END IF;
END
$$;

DROP INDEX IF EXISTS idx_notificari_utilizator_necitite;
CREATE INDEX idx_notificari_utilizator_necitite
    ON notificari(utilizator_id)
    WHERE citita = false AND vizibila_in_app = true;

REVOKE UPDATE ON notificari FROM app_user;
GRANT UPDATE (citita) ON notificari TO app_user;
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notificari", "0001_notification_state_and_security"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(sql=SQL, reverse_sql=migrations.RunSQL.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="notificare",
                    name="vizibila_in_app",
                    field=models.BooleanField(default=True),
                ),
                migrations.AddField(
                    model_name="notificare",
                    name="trimite_email",
                    field=models.BooleanField(default=False),
                ),
                migrations.AddField(
                    model_name="notificare",
                    name="subiect_email",
                    field=models.CharField(blank=True, max_length=200, null=True),
                ),
                migrations.AddField(
                    model_name="notificare",
                    name="email_trimis_la",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="notificare",
                    name="incercari_email",
                    field=models.SmallIntegerField(default=0),
                ),
                migrations.AddField(
                    model_name="notificare",
                    name="eroare_email",
                    field=models.TextField(blank=True, null=True),
                ),
            ],
        )
    ]
