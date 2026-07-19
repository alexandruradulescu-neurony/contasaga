import uuid

import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

SQL = """
ALTER TABLE analize_fisiere_inbox
    ADD COLUMN IF NOT EXISTS campuri_extrase jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS avertismente_extragere jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS extractii_structurate_documente (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id           uuid NOT NULL,
    fisier_document_id    uuid NOT NULL,
    firma_id              uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id uuid NOT NULL,
    status                varchar(20) NOT NULL DEFAULT 'in_asteptare',
    provider              varchar(50),
    model                 varchar(100),
    versiune_prompt       varchar(50) NOT NULL DEFAULT 'structured-extraction-v1',
    incercari             smallint NOT NULL DEFAULT 0,
    procesare_inceputa_la timestamptz,
    reincearca_dupa       timestamptz NOT NULL DEFAULT now(),
    finalizata_la         timestamptz,
    eroare                text,
    checksum_sursa        varchar(64) NOT NULL,
    fisiere_sursa         jsonb NOT NULL DEFAULT '[]'::jsonb,
    campuri_sugerate      jsonb NOT NULL DEFAULT '{}'::jsonb,
    avertismente          jsonb NOT NULL DEFAULT '[]'::jsonb,
    incredere             numeric(5,4),
    raspuns_provider_id   varchar(255),
    tokeni_intrare        integer,
    tokeni_iesire         integer,
    status_revizuire      varchar(20) NOT NULL DEFAULT 'in_asteptare',
    revizuita_de          uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    revizuita_la          timestamptz,
    campuri_finale        jsonb NOT NULL DEFAULT '{}'::jsonb,
    creat_la              timestamptz NOT NULL DEFAULT now(),
    actualizat_la         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_extractie_document FOREIGN KEY (
        document_id, firma_id, perioada_contabila_id
    ) REFERENCES documente(id, firma_id, perioada_contabila_id) ON DELETE RESTRICT,
    CONSTRAINT fk_extractie_fisier FOREIGN KEY (fisier_document_id, firma_id)
        REFERENCES fisiere_document(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT uq_extractie_sursa UNIQUE (document_id, checksum_sursa),
    CONSTRAINT chk_extractie_status CHECK (status IN (
        'in_asteptare', 'in_lucru', 'finalizata', 'eroare'
    )),
    CONSTRAINT chk_extractie_revizuire CHECK (status_revizuire IN (
        'in_asteptare', 'confirmata', 'corectata', 'manuala'
    )),
    CONSTRAINT chk_extractie_incercari CHECK (incercari BETWEEN 0 AND 3),
    CONSTRAINT chk_extractie_lease CHECK (
        (status = 'in_lucru' AND procesare_inceputa_la IS NOT NULL)
        OR (status <> 'in_lucru' AND procesare_inceputa_la IS NULL)
    ),
    CONSTRAINT chk_extractie_rezultat CHECK (
        (status = 'finalizata' AND finalizata_la IS NOT NULL AND eroare IS NULL
         AND provider IS NOT NULL AND model IS NOT NULL)
        OR status <> 'finalizata'
    ),
    CONSTRAINT chk_extractie_revizuire_coerenta CHECK (
        (status_revizuire = 'in_asteptare' AND revizuita_de IS NULL
         AND revizuita_la IS NULL AND campuri_finale = '{}'::jsonb)
        OR (status_revizuire <> 'in_asteptare' AND revizuita_de IS NOT NULL
            AND revizuita_la IS NOT NULL)
    ),
    CONSTRAINT chk_extractie_json CHECK (
        jsonb_typeof(fisiere_sursa) = 'array'
        AND jsonb_typeof(campuri_sugerate) = 'object'
        AND jsonb_typeof(avertismente) = 'array'
        AND jsonb_typeof(campuri_finale) = 'object'
    ),
    CONSTRAINT chk_extractie_incredere CHECK (
        incredere IS NULL OR incredere BETWEEN 0 AND 1
    )
);

CREATE INDEX IF NOT EXISTS idx_extractii_coada
    ON extractii_structurate_documente(reincearca_dupa, creat_la)
    WHERE status IN ('in_asteptare', 'eroare') AND incercari < 3
      AND status_revizuire = 'in_asteptare';
CREATE INDEX IF NOT EXISTS idx_extractii_document
    ON extractii_structurate_documente(document_id, creat_la DESC);

DROP TRIGGER IF EXISTS trg_extractii_structurate_actualizat
    ON extractii_structurate_documente;
CREATE TRIGGER trg_extractii_structurate_actualizat
    BEFORE UPDATE ON extractii_structurate_documente
    FOR EACH ROW EXECUTE FUNCTION fn_set_actualizat_la();

CREATE TABLE IF NOT EXISTS arhive_lunare (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id              uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id uuid NOT NULL,
    versiune              integer NOT NULL,
    status                varchar(20) NOT NULL DEFAULT 'in_asteptare',
    prefix_staging        varchar(500) NOT NULL,
    prefix_final          varchar(500) NOT NULL,
    manifest_storage_key  varchar(500),
    manifest_checksum     varchar(64),
    numar_fisiere         integer NOT NULL DEFAULT 0,
    dimensiune_totala     bigint NOT NULL DEFAULT 0,
    incercari             smallint NOT NULL DEFAULT 0,
    procesare_inceputa_la timestamptz,
    reincearca_dupa       timestamptz NOT NULL DEFAULT now(),
    finalizata_la         timestamptz,
    eroare                text,
    solicitata_de         uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    audit_ip              inet,
    audit_user_agent      varchar(255),
    creat_la              timestamptz NOT NULL DEFAULT now(),
    actualizat_la         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_arhiva_perioada FOREIGN KEY (perioada_contabila_id, firma_id)
        REFERENCES perioade_contabile(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT uq_arhiva_tenant UNIQUE (id, firma_id, perioada_contabila_id),
    CONSTRAINT uq_arhiva_versiune UNIQUE (perioada_contabila_id, versiune),
    CONSTRAINT chk_arhiva_versiune CHECK (versiune >= 1),
    CONSTRAINT chk_arhiva_status CHECK (status IN (
        'in_asteptare', 'in_lucru', 'finalizata', 'eroare', 'inlocuita', 'anulata'
    )),
    CONSTRAINT chk_arhiva_incercari CHECK (incercari BETWEEN 0 AND 3),
    CONSTRAINT chk_arhiva_lease CHECK (
        (status = 'in_lucru' AND procesare_inceputa_la IS NOT NULL)
        OR (status <> 'in_lucru' AND procesare_inceputa_la IS NULL)
    ),
    CONSTRAINT chk_arhiva_rezultat CHECK (
        (status IN ('finalizata', 'inlocuita') AND finalizata_la IS NOT NULL
         AND manifest_storage_key IS NOT NULL AND manifest_checksum IS NOT NULL
         AND eroare IS NULL)
        OR status NOT IN ('finalizata', 'inlocuita')
    ),
    CONSTRAINT chk_arhiva_totaluri CHECK (numar_fisiere >= 0 AND dimensiune_totala >= 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_arhiva_activa
    ON arhive_lunare(perioada_contabila_id)
    WHERE status IN ('in_asteptare', 'in_lucru');
CREATE UNIQUE INDEX IF NOT EXISTS uq_arhiva_finala_curenta
    ON arhive_lunare(perioada_contabila_id)
    WHERE status = 'finalizata';
CREATE INDEX IF NOT EXISTS idx_arhive_coada
    ON arhive_lunare(reincearca_dupa, creat_la)
    WHERE status IN ('in_asteptare', 'eroare') AND incercari < 3;

CREATE TABLE IF NOT EXISTS fisiere_arhiva_lunara (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    arhiva_id             uuid NOT NULL REFERENCES arhive_lunare(id) ON DELETE RESTRICT,
    document_id           uuid NOT NULL,
    fisier_document_id    uuid NOT NULL,
    firma_id              uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id uuid NOT NULL,
    ordine                integer NOT NULL,
    categorie             varchar(150) NOT NULL,
    cale_relativa         varchar(500) NOT NULL,
    storage_key_sursa     varchar(500) NOT NULL,
    storage_key_arhiva    varchar(500) NOT NULL UNIQUE,
    nume_original         varchar(255) NOT NULL,
    mime_type             varchar(100),
    checksum_sursa        varchar(64) NOT NULL,
    checksum_arhiva       varchar(64) NOT NULL,
    dimensiune_bytes      bigint NOT NULL,
    creat_la              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_fisier_arhiva_tenant FOREIGN KEY (
        arhiva_id, firma_id, perioada_contabila_id
    ) REFERENCES arhive_lunare(id, firma_id, perioada_contabila_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fisier_arhiva_document FOREIGN KEY (
        document_id, firma_id, perioada_contabila_id
    ) REFERENCES documente(id, firma_id, perioada_contabila_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fisier_arhiva_sursa FOREIGN KEY (fisier_document_id, firma_id)
        REFERENCES fisiere_document(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT uq_fisier_arhiva_ordine UNIQUE (arhiva_id, ordine),
    CONSTRAINT uq_fisier_arhiva_sursa UNIQUE (arhiva_id, fisier_document_id),
    CONSTRAINT chk_fisier_arhiva_ordine CHECK (ordine >= 1),
    CONSTRAINT chk_fisier_arhiva_dimensiune CHECK (dimensiune_bytes >= 0),
    CONSTRAINT chk_fisier_arhiva_checksum CHECK (checksum_sursa = checksum_arhiva)
);

CREATE INDEX IF NOT EXISTS idx_fisiere_arhiva_document
    ON fisiere_arhiva_lunara(document_id, ordine);

DROP TRIGGER IF EXISTS trg_arhive_lunare_actualizat ON arhive_lunare;
CREATE TRIGGER trg_arhive_lunare_actualizat
    BEFORE UPDATE ON arhive_lunare
    FOR EACH ROW EXECUTE FUNCTION fn_set_actualizat_la();

GRANT SELECT ON extractii_structurate_documente, arhive_lunare,
    fisiere_arhiva_lunara TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON extractii_structurate_documente,
    arhive_lunare, fisiere_arhiva_lunara TO app_admin;
REVOKE INSERT, UPDATE, DELETE ON extractii_structurate_documente,
    arhive_lunare, fisiere_arhiva_lunara FROM app_user;

ALTER TABLE extractii_structurate_documente ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pol_extractii_structurate_select ON extractii_structurate_documente;
CREATE POLICY pol_extractii_structurate_select ON extractii_structurate_documente FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE arhive_lunare ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pol_arhive_lunare_select ON arhive_lunare;
CREATE POLICY pol_arhive_lunare_select ON arhive_lunare FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE fisiere_arhiva_lunara ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pol_fisiere_arhiva_select ON fisiere_arhiva_lunara;
CREATE POLICY pol_fisiere_arhiva_select ON fisiere_arhiva_lunara FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));
"""

REVERSE_SQL = """
DROP TABLE IF EXISTS fisiere_arhiva_lunara;
DROP TABLE IF EXISTS arhive_lunare;
DROP TABLE IF EXISTS extractii_structurate_documente;
ALTER TABLE analize_fisiere_inbox
    DROP COLUMN IF EXISTS avertismente_extragere,
    DROP COLUMN IF EXISTS campuri_extrase;
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("perioade", "0002_month_closure_state"),
        ("documente", "0009_ocr_and_document_boundaries"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL)],
            state_operations=[
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="campuri_extrase",
                    field=models.JSONField(default=dict),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="avertismente_extragere",
                    field=models.JSONField(default=list),
                ),
                migrations.CreateModel(
                    name="ExtractieStructurataDocument",
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
                                    ("in_asteptare", "În așteptare"),
                                    ("in_lucru", "În extragere"),
                                    ("finalizata", "Extrasă"),
                                    ("eroare", "Eroare"),
                                ],
                                default="in_asteptare",
                                max_length=20,
                            ),
                        ),
                        ("provider", models.CharField(blank=True, max_length=50, null=True)),
                        ("model", models.CharField(blank=True, max_length=100, null=True)),
                        (
                            "versiune_prompt",
                            models.CharField(default="structured-extraction-v1", max_length=50),
                        ),
                        ("incercari", models.SmallIntegerField(default=0)),
                        ("procesare_inceputa_la", models.DateTimeField(blank=True, null=True)),
                        (
                            "reincearca_dupa",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now()
                            ),
                        ),
                        ("finalizata_la", models.DateTimeField(blank=True, null=True)),
                        ("eroare", models.TextField(blank=True, null=True)),
                        ("checksum_sursa", models.CharField(max_length=64)),
                        ("fisiere_sursa", models.JSONField(default=list)),
                        ("campuri_sugerate", models.JSONField(default=dict)),
                        ("avertismente", models.JSONField(default=list)),
                        (
                            "incredere",
                            models.DecimalField(
                                blank=True,
                                decimal_places=4,
                                max_digits=5,
                                null=True,
                            ),
                        ),
                        (
                            "raspuns_provider_id",
                            models.CharField(blank=True, max_length=255, null=True),
                        ),
                        ("tokeni_intrare", models.PositiveIntegerField(blank=True, null=True)),
                        ("tokeni_iesire", models.PositiveIntegerField(blank=True, null=True)),
                        (
                            "status_revizuire",
                            models.CharField(
                                choices=[
                                    ("in_asteptare", "Așteaptă contabilul"),
                                    ("confirmata", "Confirmată"),
                                    ("corectata", "Corectată"),
                                    ("manuala", "Completare manuală"),
                                ],
                                default="in_asteptare",
                                max_length=20,
                            ),
                        ),
                        ("revizuita_la", models.DateTimeField(blank=True, null=True)),
                        ("campuri_finale", models.JSONField(default=dict)),
                        (
                            "creat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        (
                            "actualizat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        (
                            "document",
                            models.ForeignKey(
                                db_column="document_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="extractii_structurate",
                                to="documente.document",
                            ),
                        ),
                        (
                            "fisier_document",
                            models.ForeignKey(
                                db_column="fisier_document_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="extractii_structurate",
                                to="documente.fisierdocument",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="extractii_structurate",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="extractii_structurate",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                        (
                            "revizuita_de",
                            models.ForeignKey(
                                blank=True,
                                db_column="revizuita_de",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="extractii_structurate_revizuite",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "extragere structurată",
                        "verbose_name_plural": "extrageri structurate",
                        "db_table": "extractii_structurate_documente",
                        "ordering": ("-creat_la",),
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="ArhivaLunara",
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
                        ("versiune", models.PositiveIntegerField()),
                        (
                            "status",
                            models.CharField(
                                choices=[
                                    ("in_asteptare", "În așteptare"),
                                    ("in_lucru", "În pregătire"),
                                    ("finalizata", "Finalizată"),
                                    ("eroare", "Eroare"),
                                    ("inlocuita", "Înlocuită de o versiune nouă"),
                                    ("anulata", "Anulată"),
                                ],
                                default="in_asteptare",
                                max_length=20,
                            ),
                        ),
                        ("prefix_staging", models.CharField(max_length=500)),
                        ("prefix_final", models.CharField(max_length=500)),
                        (
                            "manifest_storage_key",
                            models.CharField(blank=True, max_length=500, null=True),
                        ),
                        (
                            "manifest_checksum",
                            models.CharField(blank=True, max_length=64, null=True),
                        ),
                        ("numar_fisiere", models.PositiveIntegerField(default=0)),
                        ("dimensiune_totala", models.BigIntegerField(default=0)),
                        ("incercari", models.SmallIntegerField(default=0)),
                        ("procesare_inceputa_la", models.DateTimeField(blank=True, null=True)),
                        (
                            "reincearca_dupa",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now()
                            ),
                        ),
                        ("finalizata_la", models.DateTimeField(blank=True, null=True)),
                        ("eroare", models.TextField(blank=True, null=True)),
                        ("audit_ip", models.GenericIPAddressField(blank=True, null=True)),
                        (
                            "audit_user_agent",
                            models.CharField(blank=True, max_length=255, null=True),
                        ),
                        (
                            "creat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        (
                            "actualizat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="arhive_lunare",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="arhive_lunare",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                        (
                            "solicitata_de",
                            models.ForeignKey(
                                db_column="solicitata_de",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="arhive_lunare_solicitate",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "arhivă lunară",
                        "verbose_name_plural": "arhive lunare",
                        "db_table": "arhive_lunare",
                        "ordering": ("-versiune",),
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="FisierArhivaLunara",
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
                        ("ordine", models.PositiveIntegerField()),
                        ("categorie", models.CharField(max_length=150)),
                        ("cale_relativa", models.CharField(max_length=500)),
                        ("storage_key_sursa", models.CharField(max_length=500)),
                        ("storage_key_arhiva", models.CharField(max_length=500, unique=True)),
                        ("nume_original", models.CharField(max_length=255)),
                        ("mime_type", models.CharField(blank=True, max_length=100, null=True)),
                        ("checksum_sursa", models.CharField(max_length=64)),
                        ("checksum_arhiva", models.CharField(max_length=64)),
                        ("dimensiune_bytes", models.BigIntegerField()),
                        (
                            "creat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        (
                            "arhiva",
                            models.ForeignKey(
                                db_column="arhiva_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="fisiere",
                                to="documente.arhivalunara",
                            ),
                        ),
                        (
                            "document",
                            models.ForeignKey(
                                db_column="document_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="fisiere_arhivate",
                                to="documente.document",
                            ),
                        ),
                        (
                            "fisier_document",
                            models.ForeignKey(
                                db_column="fisier_document_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="copii_arhiva",
                                to="documente.fisierdocument",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="fisiere_arhiva_lunara",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="fisiere_arhiva_lunara",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "fișier arhivă lunară",
                        "verbose_name_plural": "fișiere arhivă lunară",
                        "db_table": "fisiere_arhiva_lunara",
                        "ordering": ("ordine",),
                        "managed": False,
                    },
                ),
            ],
        )
    ]
