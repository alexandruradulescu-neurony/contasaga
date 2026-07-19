import uuid

import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

SQL = """
ALTER TABLE fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_inbox_status;
ALTER TABLE fisiere_inbox
    ADD CONSTRAINT chk_inbox_status CHECK (status IN (
        'in_asteptare', 'disponibil', 'eroare', 'expirat', 'clasificat', 'ignorat'
    ));
ALTER TABLE fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_inbox_finalizare;
ALTER TABLE fisiere_inbox
    ADD CONSTRAINT chk_inbox_finalizare CHECK (
        (status = 'in_asteptare'
         AND storage_key IS NULL AND dimensiune_bytes IS NULL
         AND checksum IS NULL AND incarcat_la IS NULL AND eroare IS NULL)
        OR (status IN ('disponibil', 'clasificat', 'ignorat')
            AND storage_key IS NOT NULL AND dimensiune_bytes = dimensiune_declarata
            AND checksum IS NOT NULL AND incarcat_la IS NOT NULL AND eroare IS NULL)
        OR (status = 'eroare' AND storage_key IS NULL AND eroare IS NOT NULL)
        OR (status = 'expirat' AND storage_key IS NULL)
    );
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'fisiere_inbox'::regclass
          AND conname = 'uq_inbox_firma_perioada'
    ) THEN
        ALTER TABLE fisiere_inbox
            ADD CONSTRAINT uq_inbox_firma_perioada
            UNIQUE (id, firma_id, perioada_contabila_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'documente'::regclass
          AND conname = 'uq_doc_firma_perioada'
    ) THEN
        ALTER TABLE documente
            ADD CONSTRAINT uq_doc_firma_perioada
            UNIQUE (id, firma_id, perioada_contabila_id);
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS analize_fisiere_inbox (
    id                           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    fisier_inbox_id              uuid NOT NULL UNIQUE,
    firma_id                     uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id        uuid NOT NULL,
    status                       varchar(20) NOT NULL DEFAULT 'in_asteptare',
    provider                     varchar(50),
    model                        varchar(100),
    versiune_prompt              varchar(50) NOT NULL DEFAULT 'document-classifier-v1',
    incercari                    smallint NOT NULL DEFAULT 0,
    procesare_inceputa_la        timestamptz,
    reincearca_dupa              timestamptz NOT NULL DEFAULT now(),
    finalizata_la                timestamptz,
    eroare                       text,
    tip_document_sugerat_id      uuid REFERENCES tipuri_document(id) ON DELETE RESTRICT,
    cont_financiar_sugerat_id    uuid,
    directie_sugerata            varchar(10),
    incredere                    numeric(5,4),
    rezumat                      text,
    text_extras                  text,
    dovezi                       jsonb NOT NULL DEFAULT '[]'::jsonb,
    raspuns_provider_id          varchar(255),
    tokeni_intrare               integer,
    tokeni_iesire                integer,
    status_revizuire             varchar(20) NOT NULL DEFAULT 'in_asteptare',
    revizuita_de                 uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    revizuita_la                 timestamptz,
    tip_document_final_id        uuid REFERENCES tipuri_document(id) ON DELETE RESTRICT,
    cont_financiar_final_id      uuid,
    directie_finala              varchar(10),
    document_id                  uuid UNIQUE,
    observatii_revizuire         text,
    creat_la                     timestamptz NOT NULL DEFAULT now(),
    actualizat_la                timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_analiza_inbox FOREIGN KEY (
        fisier_inbox_id, firma_id, perioada_contabila_id
    ) REFERENCES fisiere_inbox(id, firma_id, perioada_contabila_id) ON DELETE RESTRICT,
    CONSTRAINT fk_analiza_perioada FOREIGN KEY (perioada_contabila_id, firma_id)
        REFERENCES perioade_contabile(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT fk_analiza_cont_sugerat FOREIGN KEY (cont_financiar_sugerat_id, firma_id)
        REFERENCES conturi_financiare(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT fk_analiza_cont_final FOREIGN KEY (cont_financiar_final_id, firma_id)
        REFERENCES conturi_financiare(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT fk_analiza_document FOREIGN KEY (document_id, firma_id, perioada_contabila_id)
        REFERENCES documente(id, firma_id, perioada_contabila_id) ON DELETE RESTRICT,
    CONSTRAINT chk_analiza_status CHECK (status IN (
        'in_asteptare', 'in_lucru', 'finalizata', 'eroare'
    )),
    CONSTRAINT chk_analiza_revizuire CHECK (status_revizuire IN (
        'in_asteptare', 'confirmata', 'corectata', 'ignorata'
    )),
    CONSTRAINT chk_analiza_directii CHECK (
        (directie_sugerata IS NULL OR directie_sugerata IN ('primit', 'emis'))
        AND (directie_finala IS NULL OR directie_finala IN ('primit', 'emis'))
    ),
    CONSTRAINT chk_analiza_incredere CHECK (incredere IS NULL OR incredere BETWEEN 0 AND 1),
    CONSTRAINT chk_analiza_incercari CHECK (incercari BETWEEN 0 AND 3),
    CONSTRAINT chk_analiza_lease CHECK (
        (status = 'in_lucru' AND procesare_inceputa_la IS NOT NULL)
        OR (status <> 'in_lucru' AND procesare_inceputa_la IS NULL)
    ),
    CONSTRAINT chk_analiza_revizuire_coerenta CHECK (
        (status_revizuire = 'in_asteptare'
         AND revizuita_de IS NULL AND revizuita_la IS NULL AND document_id IS NULL
         AND tip_document_final_id IS NULL AND cont_financiar_final_id IS NULL
         AND directie_finala IS NULL)
        OR (status_revizuire IN ('confirmata', 'corectata')
            AND revizuita_de IS NOT NULL AND revizuita_la IS NOT NULL
            AND document_id IS NOT NULL AND tip_document_final_id IS NOT NULL)
        OR (status_revizuire = 'ignorata'
            AND revizuita_de IS NOT NULL AND revizuita_la IS NOT NULL
            AND document_id IS NULL AND tip_document_final_id IS NULL
            AND cont_financiar_final_id IS NULL AND directie_finala IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_analize_de_procesat
    ON analize_fisiere_inbox(reincearca_dupa, creat_la)
    WHERE status IN ('in_asteptare', 'eroare') AND incercari < 3;
CREATE INDEX IF NOT EXISTS idx_analize_lease
    ON analize_fisiere_inbox(procesare_inceputa_la)
    WHERE status = 'in_lucru';
CREATE INDEX IF NOT EXISTS idx_analize_revizuire
    ON analize_fisiere_inbox(firma_id, status_revizuire, creat_la)
    WHERE status_revizuire = 'in_asteptare';

DROP TRIGGER IF EXISTS trg_analize_actualizat ON analize_fisiere_inbox;
CREATE TRIGGER trg_analize_actualizat
    BEFORE UPDATE ON analize_fisiere_inbox
    FOR EACH ROW EXECUTE FUNCTION fn_set_actualizat_la();

CREATE OR REPLACE FUNCTION fn_programeaza_analiza_inbox() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'disponibil'
       AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM NEW.status) THEN
        INSERT INTO public.analize_fisiere_inbox (
            fisier_inbox_id, firma_id, perioada_contabila_id
        ) VALUES (NEW.id, NEW.firma_id, NEW.perioada_contabila_id)
        ON CONFLICT (fisier_inbox_id) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

REVOKE ALL ON FUNCTION fn_programeaza_analiza_inbox() FROM PUBLIC;
DROP TRIGGER IF EXISTS trg_programeaza_analiza_inbox ON fisiere_inbox;
CREATE TRIGGER trg_programeaza_analiza_inbox
    AFTER INSERT OR UPDATE OF status ON fisiere_inbox
    FOR EACH ROW EXECUTE FUNCTION fn_programeaza_analiza_inbox();

INSERT INTO analize_fisiere_inbox (fisier_inbox_id, firma_id, perioada_contabila_id)
SELECT id, firma_id, perioada_contabila_id
FROM fisiere_inbox
WHERE status = 'disponibil'
ON CONFLICT (fisier_inbox_id) DO NOTHING;

GRANT SELECT ON analize_fisiere_inbox TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON analize_fisiere_inbox TO app_admin;
REVOKE INSERT, UPDATE, DELETE ON analize_fisiere_inbox FROM app_user;

ALTER TABLE analize_fisiere_inbox ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pol_analize_select ON analize_fisiere_inbox;
CREATE POLICY pol_analize_select ON analize_fisiere_inbox FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));
"""


REVERSE_SQL = """
DROP TRIGGER IF EXISTS trg_programeaza_analiza_inbox ON fisiere_inbox;
DROP FUNCTION IF EXISTS fn_programeaza_analiza_inbox();
DROP TABLE IF EXISTS analize_fisiere_inbox;
ALTER TABLE documente DROP CONSTRAINT IF EXISTS uq_doc_firma_perioada;
ALTER TABLE fisiere_inbox DROP CONSTRAINT IF EXISTS uq_inbox_firma_perioada;
ALTER TABLE fisiere_inbox DROP CONSTRAINT IF EXISTS chk_inbox_finalizare;
ALTER TABLE fisiere_inbox ADD CONSTRAINT chk_inbox_finalizare CHECK (
    (status = 'in_asteptare' AND storage_key IS NULL AND dimensiune_bytes IS NULL
     AND checksum IS NULL AND incarcat_la IS NULL AND eroare IS NULL)
    OR (status IN ('disponibil', 'clasificat') AND storage_key IS NOT NULL
        AND dimensiune_bytes = dimensiune_declarata AND checksum IS NOT NULL
        AND incarcat_la IS NOT NULL AND eroare IS NULL)
    OR (status = 'eroare' AND storage_key IS NULL AND eroare IS NOT NULL)
    OR (status = 'expirat' AND storage_key IS NULL)
);
ALTER TABLE fisiere_inbox DROP CONSTRAINT IF EXISTS chk_inbox_status;
ALTER TABLE fisiere_inbox ADD CONSTRAINT chk_inbox_status CHECK (status IN (
    'in_asteptare', 'disponibil', 'eroare', 'expirat', 'clasificat'
));
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("documente", "0007_bulk_inbox"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL)],
            state_operations=[
                migrations.AlterField(
                    model_name="fisierinbox",
                    name="status",
                    field=models.CharField(
                        choices=[
                            ("in_asteptare", "În așteptarea încărcării"),
                            ("disponibil", "Disponibil pentru clasificare"),
                            ("eroare", "Eroare"),
                            ("expirat", "Expirat"),
                            ("clasificat", "Clasificat"),
                            ("ignorat", "Ignorat"),
                        ],
                        default="in_asteptare",
                        max_length=20,
                    ),
                ),
                migrations.CreateModel(
                    name="AnalizaFisierInbox",
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
                                    ("in_lucru", "În analiză"),
                                    ("finalizata", "Analizată"),
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
                            models.CharField(default="document-classifier-v1", max_length=50),
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
                        (
                            "directie_sugerata",
                            models.CharField(
                                blank=True,
                                choices=[("primit", "Primit"), ("emis", "Emis")],
                                max_length=10,
                                null=True,
                            ),
                        ),
                        (
                            "incredere",
                            models.DecimalField(
                                blank=True, decimal_places=4, max_digits=5, null=True
                            ),
                        ),
                        ("rezumat", models.TextField(blank=True, null=True)),
                        ("text_extras", models.TextField(blank=True, null=True)),
                        ("dovezi", models.JSONField(default=list)),
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
                                    ("confirmata", "Sugestie confirmată"),
                                    ("corectata", "Sugestie corectată"),
                                    ("ignorata", "Fișier ignorat"),
                                ],
                                default="in_asteptare",
                                max_length=20,
                            ),
                        ),
                        (
                            "directie_finala",
                            models.CharField(
                                blank=True,
                                choices=[("primit", "Primit"), ("emis", "Emis")],
                                max_length=10,
                                null=True,
                            ),
                        ),
                        ("observatii_revizuire", models.TextField(blank=True, null=True)),
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
                            "cont_financiar_final",
                            models.ForeignKey(
                                blank=True,
                                db_column="cont_financiar_final_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="analize_confirmate",
                                to="firme.contfinanciar",
                            ),
                        ),
                        (
                            "cont_financiar_sugerat",
                            models.ForeignKey(
                                blank=True,
                                db_column="cont_financiar_sugerat_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="analize_sugerate",
                                to="firme.contfinanciar",
                            ),
                        ),
                        (
                            "document",
                            models.OneToOneField(
                                blank=True,
                                db_column="document_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="analiza_sursa_inbox",
                                to="documente.document",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="analize_fisiere_inbox",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "fisier_inbox",
                            models.OneToOneField(
                                db_column="fisier_inbox_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="analiza",
                                to="documente.fisierinbox",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="analize_fisiere_inbox",
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
                                related_name="analize_fisiere_revizuite",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "tip_document_final",
                            models.ForeignKey(
                                blank=True,
                                db_column="tip_document_final_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="analize_confirmate",
                                to="firme.tipdocument",
                            ),
                        ),
                        (
                            "tip_document_sugerat",
                            models.ForeignKey(
                                blank=True,
                                db_column="tip_document_sugerat_id",
                                null=True,
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="analize_sugerate",
                                to="firme.tipdocument",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "analiză fișier inbox",
                        "verbose_name_plural": "analize fișiere inbox",
                        "db_table": "analize_fisiere_inbox",
                        "ordering": ("creat_la",),
                        "managed": False,
                    },
                ),
            ],
        )
    ]
