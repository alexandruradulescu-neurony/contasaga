from django.db import migrations

FORWARD_SQL = """
CREATE OR REPLACE FUNCTION fn_pregateste_intentie_upload() RETURNS trigger AS $$
DECLARE
    v_an smallint;
    v_luna smallint;
BEGIN
    IF NEW.id IS NULL THEN
        NEW.id := gen_random_uuid();
    END IF;

    SELECT p.an, p.luna
      INTO v_an, v_luna
    FROM public.documente d
    JOIN public.perioade_contabile p
      ON p.id = d.perioada_contabila_id
     AND p.firma_id = d.firma_id
    WHERE d.id = NEW.document_id
      AND d.firma_id = NEW.firma_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Documentul/perioada nu există în firma indicată';
    END IF;

    NEW.storage_key := format(
        'clients/%s/%s-%s/documents/%s',
        NEW.firma_id,
        v_an,
        lpad(v_luna::text, 2, '0'),
        NEW.id
    );
    NEW.expira_la := now() + interval '1 hour';
    NEW.folosita_la := NULL;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public, pg_temp;

ALTER TABLE fisiere_document
    DROP CONSTRAINT fk_fisier_upload_intentie;
ALTER TABLE fisiere_document
    ADD CONSTRAINT fk_fisier_upload_intentie
    FOREIGN KEY (upload_intentie_id, document_id, firma_id, storage_key)
    REFERENCES intentii_upload(id, document_id, firma_id, storage_key)
    ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE;
"""

REVERSE_SQL = """
CREATE OR REPLACE FUNCTION fn_pregateste_intentie_upload() RETURNS trigger AS $$
BEGIN
    IF NEW.id IS NULL THEN
        NEW.id := gen_random_uuid();
    END IF;
    NEW.storage_key := format('staging/%s/%s', NEW.firma_id, NEW.id);
    NEW.expira_la := now() + interval '1 hour';
    NEW.folosita_la := NULL;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public, pg_temp;

ALTER TABLE fisiere_document
    DROP CONSTRAINT fk_fisier_upload_intentie;
ALTER TABLE fisiere_document
    ADD CONSTRAINT fk_fisier_upload_intentie
    FOREIGN KEY (upload_intentie_id, document_id, firma_id, storage_key)
    REFERENCES intentii_upload(id, document_id, firma_id, storage_key)
    ON DELETE RESTRICT;
"""


class Migration(migrations.Migration):
    dependencies = [("documente", "0005_processing_lease")]

    operations = [migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL)]
