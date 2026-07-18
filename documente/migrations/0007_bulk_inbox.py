import uuid

import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

SQL = """
CREATE TABLE IF NOT EXISTS loturi_incarcare (
    id                           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id                     uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id        uuid NOT NULL,
    creat_de                     uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    status                       varchar(20) NOT NULL DEFAULT 'in_desfasurare',
    numar_fisiere_declarat       integer NOT NULL,
    dimensiune_totala_declarata  bigint NOT NULL,
    nota                         text,
    finalizat_la                 timestamptz,
    creat_la                     timestamptz NOT NULL DEFAULT now(),
    actualizat_la                timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_lot_firma_perioada UNIQUE (id, firma_id, perioada_contabila_id),
    CONSTRAINT fk_lot_perioada FOREIGN KEY (perioada_contabila_id, firma_id)
        REFERENCES perioade_contabile(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT chk_lot_status CHECK (status IN (
        'in_desfasurare', 'finalizat', 'partial', 'anulat'
    )),
    CONSTRAINT chk_lot_numar_fisiere CHECK (numar_fisiere_declarat BETWEEN 1 AND 500),
    CONSTRAINT chk_lot_dimensiune CHECK (
        dimensiune_totala_declarata BETWEEN 1 AND 2147483648
    ),
    CONSTRAINT chk_lot_nota CHECK (nota IS NULL OR char_length(nota) <= 2000),
    CONSTRAINT chk_lot_finalizare CHECK (
        (status = 'in_desfasurare' AND finalizat_la IS NULL)
        OR (status <> 'in_desfasurare' AND finalizat_la IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_loturi_perioada
    ON loturi_incarcare(perioada_contabila_id, creat_la DESC);

DROP TRIGGER IF EXISTS trg_loturi_actualizat ON loturi_incarcare;
CREATE TRIGGER trg_loturi_actualizat
    BEFORE UPDATE ON loturi_incarcare
    FOR EACH ROW EXECUTE FUNCTION fn_set_actualizat_la();

CREATE TABLE IF NOT EXISTS fisiere_inbox (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id                   uuid NOT NULL,
    firma_id                 uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id    uuid NOT NULL,
    incarcat_de              uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    temp_storage_key         varchar(500) NOT NULL UNIQUE,
    storage_key              varchar(500) UNIQUE,
    nume_original            varchar(255) NOT NULL,
    mime_type                varchar(100) NOT NULL,
    dimensiune_declarata     bigint NOT NULL,
    dimensiune_bytes         bigint,
    checksum                 varchar(64),
    status                   varchar(20) NOT NULL DEFAULT 'in_asteptare',
    eroare                   text,
    expira_la                timestamptz NOT NULL,
    incarcat_la              timestamptz,
    creat_la                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_inbox_lot FOREIGN KEY (lot_id, firma_id, perioada_contabila_id)
        REFERENCES loturi_incarcare(id, firma_id, perioada_contabila_id)
        ON DELETE RESTRICT,
    CONSTRAINT chk_inbox_dimensiune CHECK (
        dimensiune_declarata BETWEEN 1 AND 26214400
    ),
    CONSTRAINT chk_inbox_nume CHECK (char_length(btrim(nume_original)) > 0),
    CONSTRAINT chk_inbox_mime CHECK (mime_type IN (
        'application/pdf', 'image/jpeg', 'image/png', 'image/heic', 'image/heif'
    )),
    CONSTRAINT chk_inbox_status CHECK (status IN (
        'in_asteptare', 'disponibil', 'eroare', 'expirat', 'clasificat'
    )),
    CONSTRAINT chk_inbox_finalizare CHECK (
        (status = 'in_asteptare'
         AND storage_key IS NULL AND dimensiune_bytes IS NULL
         AND checksum IS NULL AND incarcat_la IS NULL AND eroare IS NULL)
        OR (status IN ('disponibil', 'clasificat')
            AND storage_key IS NOT NULL AND dimensiune_bytes = dimensiune_declarata
            AND checksum IS NOT NULL AND incarcat_la IS NOT NULL AND eroare IS NULL)
        OR (status = 'eroare' AND storage_key IS NULL AND eroare IS NOT NULL)
        OR (status = 'expirat' AND storage_key IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_inbox_lot ON fisiere_inbox(lot_id, creat_la);
CREATE INDEX IF NOT EXISTS idx_inbox_perioada_status
    ON fisiere_inbox(perioada_contabila_id, status, creat_la);
CREATE INDEX IF NOT EXISTS idx_inbox_expirate ON fisiere_inbox(expira_la)
    WHERE status = 'in_asteptare';

CREATE OR REPLACE FUNCTION fn_pregateste_fisier_inbox() RETURNS trigger AS $$
DECLARE
    v_an smallint;
    v_luna smallint;
    v_numar_declarat integer;
    v_total_declarat bigint;
    v_numar_curent integer;
    v_total_curent bigint;
BEGIN
    IF NEW.id IS NULL THEN
        NEW.id := gen_random_uuid();
    END IF;

    SELECT p.an, p.luna, l.numar_fisiere_declarat, l.dimensiune_totala_declarata
      INTO v_an, v_luna, v_numar_declarat, v_total_declarat
    FROM public.loturi_incarcare l
    JOIN public.perioade_contabile p
      ON p.id = l.perioada_contabila_id
     AND p.firma_id = l.firma_id
    WHERE l.id = NEW.lot_id
      AND l.firma_id = NEW.firma_id
      AND l.perioada_contabila_id = NEW.perioada_contabila_id
      AND l.creat_de = NEW.incarcat_de
      AND l.status = 'in_desfasurare'
    FOR UPDATE OF l;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Lotul nu este activ în firma și perioada indicate';
    END IF;

    SELECT count(*), coalesce(sum(dimensiune_declarata), 0)
      INTO v_numar_curent, v_total_curent
    FROM public.fisiere_inbox
    WHERE lot_id = NEW.lot_id;

    IF v_numar_curent >= v_numar_declarat
       OR v_total_curent + NEW.dimensiune_declarata > v_total_declarat THEN
        RAISE EXCEPTION 'Fișierul depășește limitele declarate ale lotului';
    END IF;

    NEW.temp_storage_key := format(
        'clients/%s/%s-%s/_temp/%s/%s.part',
        NEW.firma_id,
        v_an,
        lpad(v_luna::text, 2, '0'),
        NEW.lot_id,
        NEW.id
    );
    NEW.storage_key := NULL;
    NEW.dimensiune_bytes := NULL;
    NEW.checksum := NULL;
    NEW.status := 'in_asteptare';
    NEW.eroare := NULL;
    NEW.expira_la := now() + interval '24 hours';
    NEW.incarcat_la := NULL;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

REVOKE ALL ON FUNCTION fn_pregateste_fisier_inbox() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_pregateste_fisier_inbox() TO app_user, app_admin;

DROP TRIGGER IF EXISTS trg_pregateste_fisier_inbox ON fisiere_inbox;
CREATE TRIGGER trg_pregateste_fisier_inbox
    BEFORE INSERT ON fisiere_inbox
    FOR EACH ROW EXECUTE FUNCTION fn_pregateste_fisier_inbox();

GRANT SELECT, INSERT ON loturi_incarcare, fisiere_inbox TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON loturi_incarcare, fisiere_inbox TO app_admin;
REVOKE UPDATE, DELETE ON loturi_incarcare, fisiere_inbox FROM app_user;

ALTER TABLE loturi_incarcare ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pol_loturi_select ON loturi_incarcare;
DROP POLICY IF EXISTS pol_loturi_insert ON loturi_incarcare;
CREATE POLICY pol_loturi_select ON loturi_incarcare FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));
CREATE POLICY pol_loturi_insert ON loturi_incarcare FOR INSERT
    WITH CHECK (
        firma_id IN (SELECT fn_firmele_utilizatorului())
        AND creat_de = fn_utilizator_curent()
    );

ALTER TABLE fisiere_inbox ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pol_inbox_select ON fisiere_inbox;
DROP POLICY IF EXISTS pol_inbox_insert ON fisiere_inbox;
CREATE POLICY pol_inbox_select ON fisiere_inbox FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));
CREATE POLICY pol_inbox_insert ON fisiere_inbox FOR INSERT
    WITH CHECK (
        firma_id IN (SELECT fn_firmele_utilizatorului())
        AND incarcat_de = fn_utilizator_curent()
    );
"""

REVERSE_SQL = """
DROP TABLE IF EXISTS fisiere_inbox;
DROP TABLE IF EXISTS loturi_incarcare;
DROP FUNCTION IF EXISTS fn_pregateste_fisier_inbox();
"""


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("documente", "0006_monthly_storage_layout"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(sql=SQL, reverse_sql=REVERSE_SQL)],
            state_operations=[
                migrations.CreateModel(
                    name="LotIncarcare",
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
                                    ("in_desfasurare", "În desfășurare"),
                                    ("finalizat", "Finalizat"),
                                    ("partial", "Finalizat parțial"),
                                    ("anulat", "Anulat"),
                                ],
                                default="in_desfasurare",
                                max_length=20,
                            ),
                        ),
                        ("numar_fisiere_declarat", models.PositiveIntegerField()),
                        ("dimensiune_totala_declarata", models.BigIntegerField()),
                        ("nota", models.TextField(blank=True, null=True)),
                        ("finalizat_la", models.DateTimeField(blank=True, null=True)),
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
                            "creat_de",
                            models.ForeignKey(
                                db_column="creat_de",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="loturi_incarcare_create",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "firma",
                            models.ForeignKey(
                                db_column="firma_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="loturi_incarcare",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="loturi_incarcare",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "lot de încărcare",
                        "verbose_name_plural": "loturi de încărcare",
                        "db_table": "loturi_incarcare",
                        "ordering": ("-creat_la",),
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="FisierInbox",
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
                        ("temp_storage_key", models.CharField(max_length=500)),
                        (
                            "storage_key",
                            models.CharField(blank=True, max_length=500, null=True),
                        ),
                        ("nume_original", models.CharField(max_length=255)),
                        ("mime_type", models.CharField(max_length=100)),
                        ("dimensiune_declarata", models.BigIntegerField()),
                        ("dimensiune_bytes", models.BigIntegerField(blank=True, null=True)),
                        ("checksum", models.CharField(blank=True, max_length=64, null=True)),
                        (
                            "status",
                            models.CharField(
                                choices=[
                                    ("in_asteptare", "În așteptarea încărcării"),
                                    ("disponibil", "Disponibil pentru clasificare"),
                                    ("eroare", "Eroare"),
                                    ("expirat", "Expirat"),
                                    ("clasificat", "Clasificat"),
                                ],
                                default="in_asteptare",
                                max_length=20,
                            ),
                        ),
                        ("eroare", models.TextField(blank=True, null=True)),
                        (
                            "expira_la",
                            models.DateTimeField(
                                db_default=django.db.models.functions.datetime.Now()
                            ),
                        ),
                        ("incarcat_la", models.DateTimeField(blank=True, null=True)),
                        (
                            "creat_la",
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
                                related_name="fisiere_inbox",
                                to="firme.firma",
                            ),
                        ),
                        (
                            "incarcat_de",
                            models.ForeignKey(
                                db_column="incarcat_de",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="fisiere_inbox_incarcate",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "lot",
                            models.ForeignKey(
                                db_column="lot_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="fisiere",
                                to="documente.lotincarcare",
                            ),
                        ),
                        (
                            "perioada_contabila",
                            models.ForeignKey(
                                db_column="perioada_contabila_id",
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="fisiere_inbox",
                                to="perioade.perioadacontabila",
                            ),
                        ),
                    ],
                    options={
                        "verbose_name": "fișier inbox",
                        "verbose_name_plural": "fișiere inbox",
                        "db_table": "fisiere_inbox",
                        "ordering": ("creat_la",),
                        "managed": False,
                    },
                ),
            ],
        )
    ]
