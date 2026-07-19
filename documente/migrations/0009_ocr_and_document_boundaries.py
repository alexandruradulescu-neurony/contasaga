import uuid

import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

SQL = """
ALTER TABLE analize_fisiere_inbox
    ADD COLUMN IF NOT EXISTS status_citire varchar(20) NOT NULL DEFAULT 'in_asteptare',
    ADD COLUMN IF NOT EXISTS incercari_citire smallint NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS citire_inceputa_la timestamptz,
    ADD COLUMN IF NOT EXISTS reincearca_citire_dupa timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS citire_finalizata_la timestamptz,
    ADD COLUMN IF NOT EXISTS eroare_citire text,
    ADD COLUMN IF NOT EXISTS metoda_citire varchar(20),
    ADD COLUMN IF NOT EXISTS numar_pagini smallint,
    ADD COLUMN IF NOT EXISTS limite_sugerate jsonb NOT NULL DEFAULT '[]'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'analize_fisiere_inbox'::regclass
          AND conname = 'uq_analiza_firma_perioada'
    ) THEN
        ALTER TABLE analize_fisiere_inbox
            ADD CONSTRAINT uq_analiza_firma_perioada
            UNIQUE (id, firma_id, perioada_contabila_id);
    END IF;
END;
$$;

ALTER TABLE analize_fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_analiza_revizuire;
ALTER TABLE analize_fisiere_inbox
    ADD CONSTRAINT chk_analiza_revizuire CHECK (status_revizuire IN (
        'in_asteptare', 'confirmata', 'corectata', 'segmentata', 'ignorata'
    ));
ALTER TABLE analize_fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_analiza_revizuire_coerenta;
ALTER TABLE analize_fisiere_inbox
    ADD CONSTRAINT chk_analiza_revizuire_coerenta CHECK (
        (status_revizuire = 'in_asteptare'
         AND revizuita_de IS NULL AND revizuita_la IS NULL AND document_id IS NULL
         AND tip_document_final_id IS NULL AND cont_financiar_final_id IS NULL
         AND directie_finala IS NULL)
        OR (status_revizuire IN ('confirmata', 'corectata')
            AND revizuita_de IS NOT NULL AND revizuita_la IS NOT NULL
            AND document_id IS NOT NULL AND tip_document_final_id IS NOT NULL)
        OR (status_revizuire IN ('segmentata', 'ignorata')
            AND revizuita_de IS NOT NULL AND revizuita_la IS NOT NULL
            AND document_id IS NULL AND tip_document_final_id IS NULL
            AND cont_financiar_final_id IS NULL AND directie_finala IS NULL)
    );
ALTER TABLE analize_fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_analiza_status_citire;
ALTER TABLE analize_fisiere_inbox
    ADD CONSTRAINT chk_analiza_status_citire CHECK (status_citire IN (
        'in_asteptare', 'in_lucru', 'finalizata', 'eroare'
    ));
ALTER TABLE analize_fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_analiza_incercari_citire;
ALTER TABLE analize_fisiere_inbox
    ADD CONSTRAINT chk_analiza_incercari_citire CHECK (incercari_citire BETWEEN 0 AND 3);
ALTER TABLE analize_fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_analiza_lease_citire;
ALTER TABLE analize_fisiere_inbox
    ADD CONSTRAINT chk_analiza_lease_citire CHECK (
        (status_citire = 'in_lucru' AND citire_inceputa_la IS NOT NULL)
        OR (status_citire <> 'in_lucru' AND citire_inceputa_la IS NULL)
    );
ALTER TABLE analize_fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_analiza_rezultat_citire;
ALTER TABLE analize_fisiere_inbox
    ADD CONSTRAINT chk_analiza_rezultat_citire CHECK (
        (status_citire = 'finalizata'
         AND citire_finalizata_la IS NOT NULL
         AND metoda_citire IS NOT NULL
         AND numar_pagini BETWEEN 1 AND 300
         AND eroare_citire IS NULL)
        OR status_citire <> 'finalizata'
    );

CREATE INDEX IF NOT EXISTS idx_analize_citire
    ON analize_fisiere_inbox(reincearca_citire_dupa, creat_la)
    WHERE status_citire IN ('in_asteptare', 'eroare') AND incercari_citire < 3;
CREATE INDEX IF NOT EXISTS idx_analize_lease_citire
    ON analize_fisiere_inbox(citire_inceputa_la)
    WHERE status_citire = 'in_lucru';

CREATE TABLE IF NOT EXISTS pagini_fisiere_inbox (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analiza_id            uuid NOT NULL,
    fisier_inbox_id       uuid NOT NULL,
    firma_id              uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id uuid NOT NULL,
    numar_pagina          smallint NOT NULL,
    metoda                varchar(20) NOT NULL,
    text_extras           text NOT NULL DEFAULT '',
    incredere_ocr         numeric(5,4),
    preview_storage_key   varchar(500) NOT NULL UNIQUE,
    preview_checksum      varchar(64) NOT NULL,
    latime_preview        integer NOT NULL,
    inaltime_preview      integer NOT NULL,
    creat_la              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_pagina_analiza FOREIGN KEY (
        analiza_id, firma_id, perioada_contabila_id
    ) REFERENCES analize_fisiere_inbox(id, firma_id, perioada_contabila_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_pagina_inbox FOREIGN KEY (
        fisier_inbox_id, firma_id, perioada_contabila_id
    ) REFERENCES fisiere_inbox(id, firma_id, perioada_contabila_id)
        ON DELETE RESTRICT,
    CONSTRAINT uq_pagina_inbox UNIQUE (fisier_inbox_id, numar_pagina),
    CONSTRAINT chk_pagina_numar CHECK (numar_pagina BETWEEN 1 AND 300),
    CONSTRAINT chk_pagina_metoda CHECK (metoda IN ('text_pdf', 'tesseract', 'fara_text')),
    CONSTRAINT chk_pagina_incredere CHECK (
        incredere_ocr IS NULL OR incredere_ocr BETWEEN 0 AND 1
    ),
    CONSTRAINT chk_pagina_preview CHECK (
        latime_preview BETWEEN 1 AND 5000 AND inaltime_preview BETWEEN 1 AND 5000
    )
);

CREATE INDEX IF NOT EXISTS idx_pagini_analiza
    ON pagini_fisiere_inbox(analiza_id, numar_pagina);

CREATE TABLE IF NOT EXISTS derivari_fisiere_inbox (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    analiza_id            uuid NOT NULL,
    fisier_inbox_id       uuid NOT NULL,
    fisier_document_id    uuid NOT NULL UNIQUE,
    document_id           uuid NOT NULL,
    firma_id              uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id uuid NOT NULL,
    pagina_start          smallint NOT NULL,
    pagina_sfarsit        smallint NOT NULL,
    metoda                varchar(30) NOT NULL,
    checksum_sursa        varchar(64) NOT NULL,
    checksum_derivat      varchar(64) NOT NULL,
    creat_de              uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    creat_la              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_derivare_analiza FOREIGN KEY (
        analiza_id, firma_id, perioada_contabila_id
    ) REFERENCES analize_fisiere_inbox(id, firma_id, perioada_contabila_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_derivare_inbox FOREIGN KEY (
        fisier_inbox_id, firma_id, perioada_contabila_id
    ) REFERENCES fisiere_inbox(id, firma_id, perioada_contabila_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_derivare_fisier FOREIGN KEY (fisier_document_id, firma_id)
        REFERENCES fisiere_document(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT fk_derivare_document FOREIGN KEY (
        document_id, firma_id, perioada_contabila_id
    ) REFERENCES documente(id, firma_id, perioada_contabila_id) ON DELETE RESTRICT,
    CONSTRAINT chk_derivare_interval CHECK (
        pagina_start BETWEEN 1 AND 300
        AND pagina_sfarsit BETWEEN pagina_start AND 300
    ),
    CONSTRAINT chk_derivare_metoda CHECK (metoda IN (
        'copie_integrala', 'extragere_pagini'
    ))
);

CREATE INDEX IF NOT EXISTS idx_derivari_sursa
    ON derivari_fisiere_inbox(fisier_inbox_id, pagina_start);

GRANT SELECT ON pagini_fisiere_inbox, derivari_fisiere_inbox TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON pagini_fisiere_inbox, derivari_fisiere_inbox TO app_admin;
REVOKE INSERT, UPDATE, DELETE
    ON pagini_fisiere_inbox, derivari_fisiere_inbox FROM app_user;

ALTER TABLE pagini_fisiere_inbox ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pol_pagini_inbox_select ON pagini_fisiere_inbox;
CREATE POLICY pol_pagini_inbox_select ON pagini_fisiere_inbox FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE derivari_fisiere_inbox ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pol_derivari_inbox_select ON derivari_fisiere_inbox;
CREATE POLICY pol_derivari_inbox_select ON derivari_fisiere_inbox FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));
"""


REVERSE_SQL = """
DROP TABLE IF EXISTS derivari_fisiere_inbox;
DROP TABLE IF EXISTS pagini_fisiere_inbox;
ALTER TABLE analize_fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_analiza_revizuire;
ALTER TABLE analize_fisiere_inbox
    ADD CONSTRAINT chk_analiza_revizuire CHECK (status_revizuire IN (
        'in_asteptare', 'confirmata', 'corectata', 'ignorata'
    ));
ALTER TABLE analize_fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_analiza_revizuire_coerenta;
ALTER TABLE analize_fisiere_inbox
    ADD CONSTRAINT chk_analiza_revizuire_coerenta CHECK (
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
    );
DROP INDEX IF EXISTS idx_analize_lease_citire;
DROP INDEX IF EXISTS idx_analize_citire;
ALTER TABLE analize_fisiere_inbox
    DROP CONSTRAINT IF EXISTS chk_analiza_rezultat_citire,
    DROP CONSTRAINT IF EXISTS chk_analiza_lease_citire,
    DROP CONSTRAINT IF EXISTS chk_analiza_incercari_citire,
    DROP CONSTRAINT IF EXISTS chk_analiza_status_citire,
    DROP CONSTRAINT IF EXISTS uq_analiza_firma_perioada,
    DROP COLUMN IF EXISTS limite_sugerate,
    DROP COLUMN IF EXISTS numar_pagini,
    DROP COLUMN IF EXISTS metoda_citire,
    DROP COLUMN IF EXISTS eroare_citire,
    DROP COLUMN IF EXISTS citire_finalizata_la,
    DROP COLUMN IF EXISTS reincearca_citire_dupa,
    DROP COLUMN IF EXISTS citire_inceputa_la,
    DROP COLUMN IF EXISTS incercari_citire,
    DROP COLUMN IF EXISTS status_citire;
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("documente", "0008_inbox_ai_analysis"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL)],
            state_operations=[
                migrations.AlterField(
                    model_name="analizafisierinbox",
                    name="status_revizuire",
                    field=models.CharField(
                        choices=[
                            ("in_asteptare", "Așteaptă contabilul"),
                            ("confirmata", "Sugestie confirmată"),
                            ("corectata", "Sugestie corectată"),
                            ("segmentata", "Separare confirmată"),
                            ("ignorata", "Fișier ignorat"),
                        ],
                        default="in_asteptare",
                        max_length=20,
                    ),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="status_citire",
                    field=models.CharField(
                        choices=[
                            ("in_asteptare", "Așteaptă citirea"),
                            ("in_lucru", "În citire"),
                            ("finalizata", "Citit"),
                            ("eroare", "Eroare de citire"),
                        ],
                        default="in_asteptare",
                        max_length=20,
                    ),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="incercari_citire",
                    field=models.SmallIntegerField(default=0),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="citire_inceputa_la",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="reincearca_citire_dupa",
                    field=models.DateTimeField(
                        db_default=django.db.models.functions.datetime.Now()
                    ),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="citire_finalizata_la",
                    field=models.DateTimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="eroare_citire",
                    field=models.TextField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="metoda_citire",
                    field=models.CharField(blank=True, max_length=20, null=True),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="numar_pagini",
                    field=models.SmallIntegerField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name="analizafisierinbox",
                    name="limite_sugerate",
                    field=models.JSONField(default=list),
                ),
                migrations.CreateModel(
                    name="PaginaFisierInbox",
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
                        ("numar_pagina", models.SmallIntegerField()),
                        (
                            "metoda",
                            models.CharField(
                                choices=[
                                    ("text_pdf", "Text PDF"),
                                    ("tesseract", "OCR Tesseract"),
                                    ("fara_text", "Fără text detectat"),
                                ],
                                max_length=20,
                            ),
                        ),
                        ("text_extras", models.TextField(blank=True, default="")),
                        (
                            "incredere_ocr",
                            models.DecimalField(
                                blank=True,
                                decimal_places=4,
                                max_digits=5,
                                null=True,
                            ),
                        ),
                        ("preview_storage_key", models.CharField(max_length=500, unique=True)),
                        ("preview_checksum", models.CharField(max_length=64)),
                        ("latime_preview", models.PositiveIntegerField()),
                        ("inaltime_preview", models.PositiveIntegerField()),
                        (
                            "creat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        (
                            "analiza",
                            models.ForeignKey(
                                db_column="analiza_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="pagini",
                                to="documente.analizafisierinbox",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="pagini_fisiere_inbox",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "fisier_inbox",
                            models.ForeignKey(
                                db_column="fisier_inbox_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="pagini_extrase",
                                to="documente.fisierinbox",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="pagini_fisiere_inbox",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "pagină fișier inbox",
                        "verbose_name_plural": "pagini fișiere inbox",
                        "db_table": "pagini_fisiere_inbox",
                        "ordering": ("numar_pagina",),
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="DerivareFisierInbox",
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
                        ("pagina_start", models.SmallIntegerField()),
                        ("pagina_sfarsit", models.SmallIntegerField()),
                        (
                            "metoda",
                            models.CharField(
                                choices=[
                                    ("copie_integrala", "Copie integrală"),
                                    ("extragere_pagini", "Extragere pagini"),
                                ],
                                max_length=30,
                            ),
                        ),
                        ("checksum_sursa", models.CharField(max_length=64)),
                        ("checksum_derivat", models.CharField(max_length=64)),
                        (
                            "creat_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now(),
                                editable=False,
                            ),
                        ),
                        (
                            "analiza",
                            models.ForeignKey(
                                db_column="analiza_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="derivari",
                                to="documente.analizafisierinbox",
                            ),
                        ),
                        (
                            "creat_de",
                            models.ForeignKey(
                                db_column="creat_de",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="derivari_fisiere_inbox_create",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "document",
                            models.ForeignKey(
                                db_column="document_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="derivari_inbox",
                                to="documente.document",
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="derivari_fisiere_inbox",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "fisier_document",
                            models.OneToOneField(
                                db_column="fisier_document_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="derivare_inbox",
                                to="documente.fisierdocument",
                            ),
                        ),
                        (
                            "fisier_inbox",
                            models.ForeignKey(
                                db_column="fisier_inbox_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="derivari",
                                to="documente.fisierinbox",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="derivari_fisiere_inbox",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "derivare fișier inbox",
                        "verbose_name_plural": "derivări fișiere inbox",
                        "db_table": "derivari_fisiere_inbox",
                        "ordering": ("pagina_start",),
                        "managed": False,
                    },
                ),
            ],
        )
    ]
