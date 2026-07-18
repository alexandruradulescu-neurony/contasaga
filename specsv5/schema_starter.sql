-- ============================================================================
-- schema_starter.sql — RELEASE R5
-- Baza de date completă — aplicație management documente contabile.
-- (Identificator unic de release: R5. SPECS.md poartă același identificator.)
--
-- PRECONDIȚIE: rolurile există deja (db/roles.sql, rulat de provisioning CU
-- SUPERUSER — crearea unui rol BYPASSRLS cere superuser). Acest fișier se
-- rulează CU ROLUL `migrare` (owner-ul bazei, non-superuser), prin migrarea
-- Django core.0001 (RunSQL). Fără BEGIN/COMMIT explicit.
-- După bootstrap, ORICE schimbare de schemă = migrare Django nouă.
--
-- Decizii cheie:
--  D1: un membru intern aparține exact unui cabinet; superuserul platformei
--      are rol dedicat `superuser_platforma`, fără cabinet
--  D2: scrierile în utilizatori/utilizator_firma/invitatii doar prin
--      conexiunea privilegiată (service layer cu verificare de rol + audit)
--  D3 (R5): AUTENTIFICAREA citește pe conexiunea privilegiată, dar obiectul
--      request.user este rehidratat pe default, iar routerul trimite implicit
--      toate scrierile ORM pe default; privileged se folosește doar explicit
--      (login + încărcarea utilizatorului de sesiune). Pe conexiunea web,
--      utilizatori are RLS restrictiv la SELECT (rândul propriu + colegii
--      de cabinet + utilizatorii firmelor accesibile; fără identitate =
--      zero rânduri), UPDATE doar pe rândul propriu, iar coloana
--      parola_hash NU e lizibilă (grant pe listă de coloane).
--  D4: checklist doar din obligatoriu=true; compatibilitate document–cont
--  D5: CUI unic per cabinet
--  D9: app_user nu primește DELETE nici prin default privileges
--  D10: RLS folosește ENABLE, NU FORCE (owner-ul migrare ocolește RLS prin
--      design; rolurile aplicației nu sunt niciodată owner)
--  D11: funcțiile SECURITY DEFINER: search_path cu pg_temp ULTIMUL, tabele
--      calificate cu schema, EXECUTE revocat de la PUBLIC
--  D12 (R5): CHECK-ul leagă is_staff ↔ is_superuser ↔ rol: doar
--      `superuser_platforma` poate avea is_staff/is_superuser; Django Admin
--      folosește un AdminSite custom care cere explicit is_superuser
--  D13 (R5): upload-urile presigned trec printr-un „upload intent"
--      server-side, obligatoriu legat de document. DB generează storage_key
--      și expirarea; app_user nu poate rescrie sau consuma intenția direct
--
-- LIMITĂ ASUMATĂ (documentată): identitatea RLS e un parametru custom
-- (app.utilizator_id) pe care orice client SQL cu acces la conexiunea web
-- îl poate seta. RLS-ul de aici protejează împotriva filtrelor ORM uitate
-- și a bug-urilor de aplicație, NU împotriva SQL-ului arbitrar executat
-- direct pe conexiune. Apărarea la acel nivel: granturile revocate
-- structural (utilizatori, alocări, invitații, parola_hash, DELETE) —
-- acelea rezistă și la SQL arbitrar.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE OR REPLACE FUNCTION fn_set_actualizat_la() RETURNS trigger AS $$
BEGIN
    NEW.actualizat_la := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- A. ORGANIZAȚII ȘI ACCES
-- ============================================================================

CREATE TABLE cabinete_contabilitate (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    denumire    varchar(255) NOT NULL,
    cui         varchar(20) UNIQUE,
    activ       boolean NOT NULL DEFAULT true,
    creat_la    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE firme (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cabinet_id      uuid NOT NULL REFERENCES cabinete_contabilitate(id) ON DELETE RESTRICT,
    cui             varchar(20) NOT NULL,
    denumire        varchar(255) NOT NULL,
    adresa          varchar(500),
    email_contact   varchar(255),
    telefon_contact varchar(30),
    activa          boolean NOT NULL DEFAULT true,
    creat_la        timestamptz NOT NULL DEFAULT now(),
    -- D5: aceeași firmă (CUI) poate fi client la cabinete diferite
    CONSTRAINT uq_firma_cabinet_cui UNIQUE (cabinet_id, cui)
);

CREATE INDEX idx_firme_cabinet ON firme(cabinet_id);

-- Utilizatori: compatibil cu AUTH_USER_MODEL custom în Django
-- (USERNAME_FIELD = email; password -> db_column 'parola_hash')
CREATE TABLE utilizatori (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cabinet_id   uuid REFERENCES cabinete_contabilitate(id) ON DELETE RESTRICT,
    nume         varchar(255) NOT NULL,
    email        varchar(255) NOT NULL,
    parola_hash  varchar(255) NOT NULL,
    rol          varchar(30) NOT NULL,
    telefon      varchar(30),
    activ        boolean NOT NULL DEFAULT true,
    -- coloane cerute de Django auth/admin
    last_login   timestamptz,
    is_staff     boolean NOT NULL DEFAULT false,
    is_superuser boolean NOT NULL DEFAULT false,
    creat_la     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_utilizatori_rol CHECK (rol IN (
        'superuser_platforma',
        'admin_cabinet', 'contabil_coordonator', 'contabil',
        'client_admin', 'client_operator'
    )),
    -- D1 + D12: rolul, flag-urile Django și cabinetul sunt legate strict:
    --  * superuser_platforma: SINGURUL cu is_staff/is_superuser, fără cabinet
    --  * membrii interni: exact un cabinet, fără flag-uri Django
    --  * clienții: fără cabinet, fără flag-uri Django
    CONSTRAINT chk_utilizatori_cabinet CHECK (
        (rol = 'superuser_platforma'
            AND is_superuser = true AND is_staff = true
            AND cabinet_id IS NULL)
        OR (rol IN ('admin_cabinet','contabil_coordonator','contabil')
            AND is_superuser = false AND is_staff = false
            AND cabinet_id IS NOT NULL)
        OR (rol IN ('client_admin','client_operator')
            AND is_superuser = false AND is_staff = false
            AND cabinet_id IS NULL)
    )
);

-- email unic, insensibil la majuscule (aplicația salvează lowercase oricum)
CREATE UNIQUE INDEX uq_utilizatori_email ON utilizatori (lower(email));
CREATE INDEX idx_utilizatori_cabinet ON utilizatori(cabinet_id)
    WHERE cabinet_id IS NOT NULL;

CREATE TABLE utilizator_firma (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    utilizator_id uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    firma_id      uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    rol_in_firma  varchar(30) NOT NULL,
    data_alocare  timestamptz NOT NULL DEFAULT now(),
    alocat_de     uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    CONSTRAINT uq_utilizator_firma UNIQUE (utilizator_id, firma_id),
    CONSTRAINT chk_uf_rol CHECK (rol_in_firma IN (
        'contabil_alocat', 'reprezentant_client', 'operator_upload'
    ))
);

CREATE INDEX idx_utilizator_firma_utilizator ON utilizator_firma(utilizator_id);
CREATE INDEX idx_utilizator_firma_firma ON utilizator_firma(firma_id);

-- Coerență: un contabil nu poate fi alocat la firma altui cabinet, iar
-- rol_in_firma trebuie să corespundă rolului global (R5). Superuserul
-- platformei nu se alocă la firme.
CREATE OR REPLACE FUNCTION fn_valideaza_alocare() RETURNS trigger AS $$
DECLARE
    v_rol varchar(30);
    v_cabinet_utilizator uuid;
    v_cabinet_firma uuid;
BEGIN
    SELECT rol, cabinet_id INTO v_rol, v_cabinet_utilizator
    FROM utilizatori WHERE id = NEW.utilizator_id;

    SELECT cabinet_id INTO v_cabinet_firma
    FROM firme WHERE id = NEW.firma_id;

    IF v_rol = 'superuser_platforma' THEN
        RAISE EXCEPTION 'Superuserul platformei nu se alocă la firme';
    END IF;

    IF v_rol IN ('admin_cabinet','contabil_coordonator','contabil') THEN
        IF v_cabinet_utilizator IS DISTINCT FROM v_cabinet_firma THEN
            RAISE EXCEPTION 'Utilizatorul intern % aparține altui cabinet decât firma %',
                NEW.utilizator_id, NEW.firma_id;
        END IF;
        IF NEW.rol_in_firma <> 'contabil_alocat' THEN
            RAISE EXCEPTION 'Membrii interni se alocă doar ca contabil_alocat';
        END IF;
    ELSIF v_rol = 'client_admin' AND NEW.rol_in_firma <> 'reprezentant_client' THEN
        RAISE EXCEPTION 'client_admin se alocă doar ca reprezentant_client';
    ELSIF v_rol = 'client_operator' AND NEW.rol_in_firma <> 'operator_upload' THEN
        RAISE EXCEPTION 'client_operator se alocă doar ca operator_upload';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_valideaza_alocare
    BEFORE INSERT OR UPDATE ON utilizator_firma
    FOR EACH ROW EXECUTE FUNCTION fn_valideaza_alocare();

-- Invitații (ciclu de viață: creată -> acceptată / anulată / expirată)
CREATE TABLE invitatii (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cabinet_id    uuid REFERENCES cabinete_contabilitate(id) ON DELETE RESTRICT,
    firma_id      uuid REFERENCES firme(id) ON DELETE RESTRICT,
    email         varchar(255) NOT NULL,
    rol           varchar(30) NOT NULL,
    rol_in_firma  varchar(30),
    token_hash    varchar(64) NOT NULL UNIQUE,
    expira_la     timestamptz NOT NULL,
    acceptata_la  timestamptz,
    anulata_la    timestamptz,
    creat_de      uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    creat_la      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_inv_rol CHECK (rol IN (
        'admin_cabinet','contabil_coordonator','contabil',
        'client_admin','client_operator'
    )),
    -- invitație internă (cabinet, fără rol_in_firma) sau de client (firmă,
    -- cu rol_in_firma corespunzător rolului) — exact una, coerentă
    CONSTRAINT chk_inv_ancora CHECK (
        (cabinet_id IS NOT NULL AND firma_id IS NULL
            AND rol IN ('admin_cabinet','contabil_coordonator','contabil')
            AND rol_in_firma IS NULL)
        OR
        (cabinet_id IS NULL AND firma_id IS NOT NULL
            AND ((rol = 'client_admin'    AND rol_in_firma = 'reprezentant_client')
              OR (rol = 'client_operator' AND rol_in_firma = 'operator_upload')))
    ),
    -- o invitație nu poate fi simultan acceptată și anulată
    CONSTRAINT chk_inv_finalitate CHECK (
        NOT (acceptata_la IS NOT NULL AND anulata_la IS NOT NULL)
    )
);

CREATE INDEX idx_invitatii_email ON invitatii(lower(email));

-- ============================================================================
-- B. CONFIGURARE CONTABILĂ
-- ============================================================================

CREATE TABLE tipuri_document (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cod                     varchar(50) NOT NULL UNIQUE,
    denumire                varchar(100) NOT NULL,
    categorie               varchar(30) NOT NULL,
    necesita_serie_numar    boolean NOT NULL DEFAULT false,
    necesita_cont_financiar boolean NOT NULL DEFAULT false,
    -- D4: pentru documentele legate de conturi, tipurile de cont compatibile
    -- (ex: extras_cont -> {banca,card}; registru_casa -> {casa})
    tipuri_cont_compatibile text[],
    -- matricea de retenție: NULL = termenul legal implicit stabilit în
    -- aplicație; se validează juridic înainte de lansare
    retentie_ani            smallint,
    activ                   boolean NOT NULL DEFAULT true,
    CONSTRAINT chk_td_retentie CHECK (retentie_ani IS NULL OR retentie_ani >= 5),
    CONSTRAINT chk_td_categorie CHECK (categorie IN (
        'document_justificativ', 'trezorerie', 'document_operational',
        'document_suport', 'declaratie_sau_raport', 'altele'
    )),
    CONSTRAINT chk_td_conturi CHECK (
        (necesita_cont_financiar = false AND tipuri_cont_compatibile IS NULL) OR
        (necesita_cont_financiar = true  AND tipuri_cont_compatibile IS NOT NULL)
    )
);

CREATE TABLE configurare_documente_firma (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id           uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    tip_document_id    uuid NOT NULL REFERENCES tipuri_document(id) ON DELETE RESTRICT,
    obligatoriu        boolean NOT NULL DEFAULT false,
    frecventa          varchar(20) NOT NULL DEFAULT 'lunar',
    termen_predare_zi  smallint,
    activ              boolean NOT NULL DEFAULT true,
    observatii         text,
    creat_de           uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    creat_la           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_config_firma_tip UNIQUE (firma_id, tip_document_id),
    CONSTRAINT chk_cdf_frecventa CHECK (frecventa IN ('lunar', 'ocazional', 'zilnic')),
    CONSTRAINT chk_cdf_termen CHECK (termen_predare_zi IS NULL OR termen_predare_zi BETWEEN 1 AND 31)
);

CREATE INDEX idx_config_doc_firma ON configurare_documente_firma(firma_id);

CREATE TABLE perioade_contabile (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id                 uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    luna                     smallint NOT NULL,
    an                       smallint NOT NULL,
    stare                    varchar(30) NOT NULL DEFAULT 'deschisa',
    termen_predare           date,
    contabil_responsabil_id  uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    confirmata_de_client_la  timestamptz,
    inchisa_la               timestamptz,
    inchisa_de               uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    observatii               text,
    creat_la                 timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_perioada_firma_luna_an UNIQUE (firma_id, luna, an),
    CONSTRAINT uq_perioada_id_firma UNIQUE (id, firma_id),
    CONSTRAINT chk_perioada_luna CHECK (luna BETWEEN 1 AND 12),
    CONSTRAINT chk_perioada_an CHECK (an BETWEEN 2000 AND 2100),
    CONSTRAINT chk_perioada_stare CHECK (stare IN (
        'deschisa', 'documente_incomplete', 'gata_pentru_verificare',
        'in_lucru', 'inchisa'
    ))
);

CREATE INDEX idx_perioade_firma_stare ON perioade_contabile(firma_id, stare);
CREATE INDEX idx_perioade_responsabil ON perioade_contabile(contabil_responsabil_id);

-- Responsabilul perioadei: membru intern al cabinetului firmei; pentru
-- rolul 'contabil' se cere ȘI alocarea la firmă (admin/coordonator văd
-- oricum tot cabinetul)
CREATE OR REPLACE FUNCTION fn_valideaza_responsabil() RETURNS trigger AS $$
DECLARE
    v_cabinet_firma uuid;
    v_cabinet_user uuid;
    v_rol varchar(30);
BEGIN
    IF NEW.contabil_responsabil_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT cabinet_id INTO v_cabinet_firma FROM firme WHERE id = NEW.firma_id;
    SELECT cabinet_id, rol INTO v_cabinet_user, v_rol
    FROM utilizatori WHERE id = NEW.contabil_responsabil_id;

    IF v_rol NOT IN ('admin_cabinet','contabil_coordonator','contabil')
       OR v_cabinet_user IS DISTINCT FROM v_cabinet_firma THEN
        RAISE EXCEPTION 'Responsabilul perioadei trebuie să fie membru intern al cabinetului firmei';
    END IF;

    IF v_rol = 'contabil' AND NOT EXISTS (
        SELECT 1 FROM utilizator_firma
        WHERE utilizator_id = NEW.contabil_responsabil_id
          AND firma_id = NEW.firma_id
    ) THEN
        RAISE EXCEPTION 'Contabilul responsabil trebuie să fie alocat firmei';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_valideaza_responsabil
    BEFORE INSERT OR UPDATE ON perioade_contabile
    FOR EACH ROW EXECUTE FUNCTION fn_valideaza_responsabil();

CREATE TABLE conturi_financiare (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id  uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    tip       varchar(20) NOT NULL,
    banca     varchar(100),
    iban      varchar(34),
    moneda    varchar(3) NOT NULL DEFAULT 'RON',
    denumire  varchar(100) NOT NULL,
    activ     boolean NOT NULL DEFAULT true,
    CONSTRAINT uq_cont_id_firma UNIQUE (id, firma_id),
    CONSTRAINT chk_cf_tip CHECK (tip IN ('banca', 'casa', 'card'))
);

CREATE INDEX idx_conturi_firma ON conturi_financiare(firma_id);
CREATE UNIQUE INDEX uq_conturi_iban ON conturi_financiare(firma_id, iban)
    WHERE iban IS NOT NULL;

CREATE TABLE parteneri (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id  uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    tip       varchar(20) NOT NULL,
    cui       varchar(20),
    denumire  varchar(255) NOT NULL,
    tara      varchar(2) NOT NULL DEFAULT 'RO',
    activ     boolean NOT NULL DEFAULT true,
    creat_de  uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    creat_la  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_partener_id_firma UNIQUE (id, firma_id),
    CONSTRAINT chk_part_tip CHECK (tip IN ('furnizor', 'client', 'ambele'))
);

CREATE INDEX idx_parteneri_firma ON parteneri(firma_id);
CREATE UNIQUE INDEX uq_parteneri_firma_cui ON parteneri(firma_id, cui)
    WHERE cui IS NOT NULL;

-- ============================================================================
-- C. DOCUMENTE
-- ============================================================================

CREATE TABLE documente (
    id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id                  uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id     uuid NOT NULL,
    predare_documente_id      uuid,
    tip_document_id           uuid NOT NULL REFERENCES tipuri_document(id) ON DELETE RESTRICT,
    partener_id               uuid,
    cont_financiar_id         uuid,
    incarcat_de               uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    directie                  varchar(10),
    serie                     varchar(20),
    numar                     varchar(30),
    data_document             date,
    data_scadenta             date,
    moneda                    varchar(3) NOT NULL DEFAULT 'RON',
    valoare_fara_tva          numeric(14,2),
    valoare_tva               numeric(14,2),
    valoare_totala            numeric(14,2),
    stare                     varchar(30) NOT NULL DEFAULT 'draft',
    incarcat_dupa_confirmare  boolean NOT NULL DEFAULT false,
    -- retenție dependentă de document, nu doar de tip (ex: documente care
    -- atestă proveniența bunurilor cu durată de viață mai mare decât
    -- termenul general) — setată de contabil, are prioritate față de
    -- tipuri_document.retentie_ani
    retentie_extinsa_pana_la  date,
    note                      text,
    sters_la                  timestamptz,
    sters_de                  uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    motiv_stergere            varchar(255),
    creat_la                  timestamptz NOT NULL DEFAULT now(),
    actualizat_la             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_doc_id_firma UNIQUE (id, firma_id),
    CONSTRAINT fk_doc_perioada FOREIGN KEY (perioada_contabila_id, firma_id)
        REFERENCES perioade_contabile(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT fk_doc_partener FOREIGN KEY (partener_id, firma_id)
        REFERENCES parteneri(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT fk_doc_cont FOREIGN KEY (cont_financiar_id, firma_id)
        REFERENCES conturi_financiare(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT chk_doc_directie CHECK (directie IS NULL OR directie IN ('primit', 'emis')),
    CONSTRAINT chk_doc_stare CHECK (stare IN (
        'draft', 'trimis', 'in_verificare', 'necesita_clarificari',
        'acceptat', 'procesat', 'arhivat', 'anulat'
    ))
);

CREATE INDEX idx_documente_perioada_tip ON documente(perioada_contabila_id, tip_document_id);
CREATE INDEX idx_documente_firma_stare ON documente(firma_id, stare);
CREATE INDEX idx_documente_partener ON documente(partener_id) WHERE partener_id IS NOT NULL;
CREATE INDEX idx_documente_cont ON documente(cont_financiar_id) WHERE cont_financiar_id IS NOT NULL;
CREATE INDEX idx_documente_nesterse ON documente(firma_id) WHERE sters_la IS NULL;
CREATE INDEX idx_documente_predare ON documente(predare_documente_id)
    WHERE predare_documente_id IS NOT NULL;

CREATE UNIQUE INDEX uq_doc_business ON documente
    (firma_id, tip_document_id, partener_id, serie, numar)
    WHERE partener_id IS NOT NULL
      AND serie IS NOT NULL
      AND numar IS NOT NULL
      AND sters_la IS NULL
      AND stare <> 'anulat';

CREATE TRIGGER trg_documente_actualizat
    BEFORE UPDATE ON documente
    FOR EACH ROW EXECUTE FUNCTION fn_set_actualizat_la();

-- Retenția specifică documentului poate doar EXTINDE termenul legal/tipului.
-- Termen minim: 1 iulie a anului următor exercițiului + max(5, retenția tipului).
CREATE OR REPLACE FUNCTION fn_valideaza_retentie_document() RETURNS trigger AS $$
DECLARE
    v_an smallint;
    v_retentie_ani smallint;
    v_minim date;
BEGIN
    IF NEW.retentie_extinsa_pana_la IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT p.an, GREATEST(5, COALESCE(t.retentie_ani, 5))
      INTO v_an, v_retentie_ani
    FROM public.perioade_contabile p
    JOIN public.tipuri_document t ON t.id = NEW.tip_document_id
    WHERE p.id = NEW.perioada_contabila_id
      AND p.firma_id = NEW.firma_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Perioada/tipul documentului nu există în firma indicată';
    END IF;

    v_minim := make_date((v_an + 1 + v_retentie_ani)::integer, 7, 1);
    IF NEW.retentie_extinsa_pana_la < v_minim THEN
        RAISE EXCEPTION 'Retenția extinsă (%) nu poate scurta termenul minim (%)',
            NEW.retentie_extinsa_pana_la, v_minim;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public, pg_temp;

CREATE TRIGGER trg_valideaza_retentie_document
    BEFORE INSERT OR UPDATE OF firma_id, perioada_contabila_id,
        tip_document_id, retentie_extinsa_pana_la ON documente
    FOR EACH ROW EXECUTE FUNCTION fn_valideaza_retentie_document();

-- Upload intents (D13 R5): documentul draft există înaintea intenției.
-- Cheia, expirarea și starea de consum sunt controlate de DB/server.
CREATE TABLE intentii_upload (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id       uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    document_id    uuid NOT NULL,
    -- ținta opțională a unei înlocuiri; FK-ul compus este adăugat după
    -- crearea fisiere_document, ca să păstreze documentul/tenantul identic
    inlocuieste_fisier_id uuid,
    utilizator_id  uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    storage_key    varchar(500) NOT NULL UNIQUE,
    nume_original  varchar(255),
    expira_la      timestamptz NOT NULL,
    folosita_la    timestamptz,
    creat_la       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_intentie_document FOREIGN KEY (document_id, firma_id)
        REFERENCES documente(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT uq_intentie_document_firma_key
        UNIQUE (id, document_id, firma_id, storage_key)
);

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

CREATE TRIGGER trg_pregateste_intentie_upload
    BEFORE INSERT ON intentii_upload
    FOR EACH ROW EXECUTE FUNCTION fn_pregateste_intentie_upload();

CREATE INDEX idx_intentii_expirate ON intentii_upload(expira_la)
    WHERE folosita_la IS NULL;

-- Un document = un obiect contabil, cu 1+ fișiere (pagini, față/verso,
-- versiuni reîncărcate). Un upload de N facturi creează N documente.
CREATE TABLE fisiere_document (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id           uuid NOT NULL,
    firma_id              uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    upload_intentie_id    uuid NOT NULL,
    storage_key           varchar(500) NOT NULL,
    nume_original         varchar(255),
    mime_type             varchar(100),
    dimensiune_bytes      bigint,
    checksum              varchar(64),
    numar_pagini          integer,
    -- poziția fișierului în document (afișare); NU e numărul de pagini
    ordine                smallint NOT NULL DEFAULT 1,
    versiune              integer NOT NULL DEFAULT 1,
    -- fișierul pe care îl înlocuiește (lanț de versiuni) — FK compus,
    -- ca să nu poată înlocui un fișier al altei firme
    inlocuieste_fisier_id uuid,
    -- pipeline-ul asincron de procesare (checksum, pagini, thumbnail)
    stare_procesare       varchar(20) NOT NULL DEFAULT 'in_asteptare',
    procesare_inceputa_la timestamptz,
    eroare_procesare      text,
    incercari_procesare   smallint NOT NULL DEFAULT 0,
    thumbnail_key         varchar(500),
    incarcat_de           uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    incarcat_la           timestamptz NOT NULL DEFAULT now(),
    activ                 boolean NOT NULL DEFAULT true,
    sters_la              timestamptz,
    sters_de              uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    CONSTRAINT uq_fisier_id_firma UNIQUE (id, firma_id),
    CONSTRAINT uq_fisier_id_document UNIQUE (id, document_id),
    CONSTRAINT uq_fisier_upload_intentie UNIQUE (upload_intentie_id),
    CONSTRAINT fk_fisier_document FOREIGN KEY (document_id, firma_id)
        REFERENCES documente(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT fk_fisier_upload_intentie
        FOREIGN KEY (upload_intentie_id, document_id, firma_id, storage_key)
        REFERENCES intentii_upload(id, document_id, firma_id, storage_key)
        ON DELETE RESTRICT DEFERRABLE INITIALLY IMMEDIATE,
    -- v6: înlocuirea e legată de ACELAȘI document (implicit aceeași firmă)
    CONSTRAINT fk_fisier_inlocuieste FOREIGN KEY (inlocuieste_fisier_id, document_id)
        REFERENCES fisiere_document(id, document_id) ON DELETE RESTRICT,
    CONSTRAINT chk_fisier_procesare CHECK (stare_procesare IN (
        'in_asteptare', 'in_lucru', 'procesat', 'eroare'
    )),
    CONSTRAINT chk_fisier_lease_coerenta CHECK (
        (stare_procesare = 'in_lucru' AND procesare_inceputa_la IS NOT NULL)
        OR (stare_procesare <> 'in_lucru' AND procesare_inceputa_la IS NULL)
    )
);

ALTER TABLE intentii_upload
    ADD CONSTRAINT fk_intentie_inlocuieste_fisier
    FOREIGN KEY (inlocuieste_fisier_id, document_id)
    REFERENCES fisiere_document(id, document_id) ON DELETE RESTRICT;

CREATE INDEX idx_fisiere_document ON fisiere_document(document_id);
CREATE INDEX idx_fisiere_checksum ON fisiere_document(checksum)
    WHERE checksum IS NOT NULL;
CREATE INDEX idx_fisiere_de_procesat ON fisiere_document(stare_procesare)
    WHERE stare_procesare IN ('in_asteptare','eroare');
CREATE INDEX idx_fisiere_procesare_blocata
    ON fisiere_document(procesare_inceputa_la)
    WHERE stare_procesare = 'in_lucru' AND sters_la IS NULL;

CREATE TABLE cerinte_documente_perioada (
    id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    perioada_contabila_id      uuid NOT NULL,
    firma_id                   uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    tip_document_id            uuid NOT NULL REFERENCES tipuri_document(id) ON DELETE RESTRICT,
    cont_financiar_id          uuid,
    status                     varchar(20) NOT NULL DEFAULT 'lipsa',
    numar_documente_declarat   integer,
    observatii_client          text,
    observatii_contabil        text,
    actualizat_la              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_cerinta_perioada FOREIGN KEY (perioada_contabila_id, firma_id)
        REFERENCES perioade_contabile(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT fk_cerinta_cont FOREIGN KEY (cont_financiar_id, firma_id)
        REFERENCES conturi_financiare(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT uq_cerinta UNIQUE NULLS NOT DISTINCT
        (perioada_contabila_id, tip_document_id, cont_financiar_id),
    CONSTRAINT chk_cerinta_status CHECK (status IN (
        'lipsa', 'partial', 'primit', 'nu_se_aplica'
    ))
);

CREATE INDEX idx_cerinte_perioada ON cerinte_documente_perioada(perioada_contabila_id);

CREATE TRIGGER trg_cerinte_actualizat
    BEFORE UPDATE ON cerinte_documente_perioada
    FOR EACH ROW EXECUTE FUNCTION fn_set_actualizat_la();

CREATE TABLE comentarii (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id               uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    document_id            uuid,
    perioada_contabila_id  uuid,
    utilizator_id          uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    text                   text NOT NULL,
    creat_la               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_com_document FOREIGN KEY (document_id, firma_id)
        REFERENCES documente(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT fk_com_perioada FOREIGN KEY (perioada_contabila_id, firma_id)
        REFERENCES perioade_contabile(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT chk_comentariu_ancora CHECK (
        (document_id IS NOT NULL AND perioada_contabila_id IS NULL) OR
        (document_id IS NULL AND perioada_contabila_id IS NOT NULL)
    )
);

CREATE INDEX idx_comentarii_document ON comentarii(document_id)
    WHERE document_id IS NOT NULL;
CREATE INDEX idx_comentarii_perioada ON comentarii(perioada_contabila_id)
    WHERE perioada_contabila_id IS NOT NULL;

CREATE TABLE istoric_stari (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id       uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    entitate_tip   varchar(30) NOT NULL,
    entitate_id    uuid NOT NULL,
    stare_veche    varchar(30),
    stare_noua     varchar(30) NOT NULL,
    utilizator_id  uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    comentariu     text,
    creat_la       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_istoric_entitate CHECK (entitate_tip IN ('document', 'perioada'))
);

CREATE INDEX idx_istoric_entitate ON istoric_stari(entitate_tip, entitate_id);

-- Relația entitate_tip + entitate_id rămâne polimorfică, dar nu este liberă:
-- triggerul verifică existența entității și apartenența la aceeași firmă.
CREATE OR REPLACE FUNCTION fn_valideaza_istoric_entitate() RETURNS trigger AS $$
BEGIN
    IF NEW.entitate_tip = 'document' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.documente d
            WHERE d.id = NEW.entitate_id AND d.firma_id = NEW.firma_id
        ) THEN
            RAISE EXCEPTION 'Documentul istoricului nu aparține firmei indicate';
        END IF;
    ELSIF NEW.entitate_tip = 'perioada' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.perioade_contabile p
            WHERE p.id = NEW.entitate_id AND p.firma_id = NEW.firma_id
        ) THEN
            RAISE EXCEPTION 'Perioada istoricului nu aparține firmei indicate';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public, pg_temp;

CREATE TRIGGER trg_valideaza_istoric_entitate
    BEFORE INSERT OR UPDATE OF firma_id, entitate_tip, entitate_id ON istoric_stari
    FOR EACH ROW EXECUTE FUNCTION fn_valideaza_istoric_entitate();

-- Export ZIP lunar (worker asincron cu stare urmăribilă)
CREATE TABLE exporturi (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id               uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id  uuid NOT NULL,
    solicitat_de           uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    status                 varchar(20) NOT NULL DEFAULT 'in_lucru',
    storage_key            varchar(500),
    eroare                 text,
    creat_la               timestamptz NOT NULL DEFAULT now(),
    expira_la              timestamptz,
    CONSTRAINT fk_export_perioada FOREIGN KEY (perioada_contabila_id, firma_id)
        REFERENCES perioade_contabile(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT chk_export_status CHECK (status IN (
        'in_lucru', 'finalizat', 'eroare', 'expirat'
    )),
    CONSTRAINT chk_export_stare_coerenta CHECK (
        (status = 'in_lucru' AND storage_key IS NULL
            AND eroare IS NULL AND expira_la IS NULL)
        OR (status = 'finalizat' AND storage_key IS NOT NULL
            AND eroare IS NULL AND expira_la IS NOT NULL)
        OR (status = 'eroare' AND storage_key IS NULL
            AND eroare IS NOT NULL AND expira_la IS NULL)
        OR (status = 'expirat' AND storage_key IS NULL AND eroare IS NULL)
    )
);

CREATE INDEX idx_exporturi_firma ON exporturi(firma_id);
CREATE UNIQUE INDEX uq_export_activ_solicitant
    ON exporturi(perioada_contabila_id, solicitat_de)
    WHERE status = 'in_lucru';

-- ============================================================================
-- D. LOGISTICĂ FIZICĂ
-- ============================================================================

CREATE TABLE predari_documente (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id               uuid NOT NULL REFERENCES firme(id) ON DELETE RESTRICT,
    perioada_contabila_id  uuid,
    metoda                 varchar(30) NOT NULL,
    status                 varchar(20) NOT NULL DEFAULT 'programata',
    predat_de              varchar(255),
    preluat_de             uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    numar_cutii            integer NOT NULL DEFAULT 0,
    data_programata        timestamptz,
    data_preluare          timestamptz,
    data_receptie          timestamptz,
    data_returnare         timestamptz,
    digitizare_status      varchar(30) NOT NULL DEFAULT 'nedecisa',
    numar_documente_estimat integer,
    digitizare_inceputa_la timestamptz,
    digitizare_inceputa_de uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    digitizare_finalizata_la timestamptz,
    digitizare_finalizata_de uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    observatii             text,
    creat_de               uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    creat_la               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT fk_predare_perioada FOREIGN KEY (perioada_contabila_id, firma_id)
        REFERENCES perioade_contabile(id, firma_id) ON DELETE RESTRICT,
    CONSTRAINT uq_predare_id_firma_perioada
        UNIQUE (id, firma_id, perioada_contabila_id),
    CONSTRAINT chk_predare_metoda CHECK (metoda IN (
        'curier', 'posta', 'ridicare_contabil', 'predare_client', 'exclusiv_digital'
    )),
    CONSTRAINT chk_predare_status CHECK (status IN (
        'programata', 'preluata', 'receptionata', 'returnata'
    )),
    CONSTRAINT chk_predare_stare_coerenta CHECK (
        (metoda = 'exclusiv_digital'
            AND status = 'receptionata'
            AND numar_cutii = 0
            AND data_programata IS NULL
            AND preluat_de IS NULL
            AND data_preluare IS NULL
            AND data_receptie IS NOT NULL
            AND data_returnare IS NULL)
        OR (metoda <> 'exclusiv_digital'
            AND predat_de IS NOT NULL AND btrim(predat_de) <> ''
            AND numar_cutii > 0
            AND data_programata IS NOT NULL
            AND (
                (status = 'programata' AND preluat_de IS NULL
                    AND data_preluare IS NULL AND data_receptie IS NULL
                    AND data_returnare IS NULL)
                OR (status = 'preluata' AND preluat_de IS NOT NULL
                    AND data_preluare IS NOT NULL AND data_receptie IS NULL
                    AND data_returnare IS NULL)
                OR (status = 'receptionata' AND preluat_de IS NOT NULL
                    AND data_preluare IS NOT NULL AND data_receptie IS NOT NULL
                    AND data_returnare IS NULL
                    AND data_preluare <= data_receptie)
                OR (status = 'returnata' AND preluat_de IS NOT NULL
                    AND data_preluare IS NOT NULL AND data_receptie IS NOT NULL
                    AND data_returnare IS NOT NULL
                    AND data_preluare <= data_receptie
                    AND data_receptie <= data_returnare)
            ))
    ),
    CONSTRAINT chk_predare_digitizare_coerenta CHECK (
        (numar_documente_estimat IS NULL OR numar_documente_estimat > 0)
        AND (
            (metoda = 'exclusiv_digital'
                AND digitizare_status = 'nu_este_necesara'
                AND numar_documente_estimat IS NULL
                AND digitizare_inceputa_la IS NULL
                AND digitizare_inceputa_de IS NULL
                AND digitizare_finalizata_la IS NULL
                AND digitizare_finalizata_de IS NULL)
            OR (metoda <> 'exclusiv_digital'
                AND (
                    (digitizare_status IN ('nedecisa', 'nu_este_necesara')
                        AND numar_documente_estimat IS NULL
                        AND digitizare_inceputa_la IS NULL
                        AND digitizare_inceputa_de IS NULL
                        AND digitizare_finalizata_la IS NULL
                        AND digitizare_finalizata_de IS NULL)
                    OR (digitizare_status = 'in_lucru'
                        AND digitizare_inceputa_la IS NOT NULL
                        AND digitizare_inceputa_de IS NOT NULL
                        AND digitizare_finalizata_la IS NULL
                        AND digitizare_finalizata_de IS NULL)
                    OR (digitizare_status = 'finalizata'
                        AND digitizare_inceputa_la IS NOT NULL
                        AND digitizare_inceputa_de IS NOT NULL
                        AND digitizare_finalizata_la IS NOT NULL
                        AND digitizare_finalizata_de IS NOT NULL
                        AND digitizare_inceputa_la <= digitizare_finalizata_la)
                )
                AND (status IN ('receptionata', 'returnata')
                    OR digitizare_status = 'nedecisa'))
        )
    )
);

CREATE INDEX idx_predari_firma ON predari_documente(firma_id);
CREATE INDEX idx_predari_perioada ON predari_documente(perioada_contabila_id)
    WHERE perioada_contabila_id IS NOT NULL;

ALTER TABLE documente
    ADD CONSTRAINT fk_document_predare
    FOREIGN KEY (predare_documente_id, firma_id, perioada_contabila_id)
    REFERENCES predari_documente(id, firma_id, perioada_contabila_id)
    ON DELETE RESTRICT;

-- ============================================================================
-- E. COMUNICARE
-- ============================================================================

CREATE TABLE notificari (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    utilizator_id  uuid NOT NULL REFERENCES utilizatori(id) ON DELETE RESTRICT,
    tip            varchar(40) NOT NULL,
    entitate_tip   varchar(30),
    entitate_id    uuid,
    mesaj          varchar(500) NOT NULL,
    cheie_deduplicare varchar(64),
    citita         boolean NOT NULL DEFAULT false,
    vizibila_in_app boolean NOT NULL DEFAULT true,
    trimite_email  boolean NOT NULL DEFAULT false,
    subiect_email  varchar(200),
    email_trimis_la timestamptz,
    incercari_email smallint NOT NULL DEFAULT 0,
    eroare_email   text,
    creat_la       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT chk_notif_incercari_email CHECK (
        incercari_email BETWEEN 0 AND 3
    ),
    CONSTRAINT chk_notif_email_coerent CHECK (
        (trimite_email AND subiect_email IS NOT NULL)
        OR (NOT trimite_email AND subiect_email IS NULL
            AND email_trimis_la IS NULL AND incercari_email = 0
            AND eroare_email IS NULL)
    ),
    CONSTRAINT chk_notif_tip CHECK (tip IN (
        'reminder_termen', 'document_nou', 'necesita_clarificari',
        'clarificari_rezolvate', 'perioada_confirmata', 'perioada_inchisa',
        'comentariu_nou', 'export_finalizat', 'eroare_procesare_fisier',
        'invitatie'
    ))
);

CREATE INDEX idx_notificari_utilizator_necitite ON notificari(utilizator_id)
    WHERE citita = false AND vizibila_in_app = true;
CREATE UNIQUE INDEX uq_notificari_deduplicare ON notificari(cheie_deduplicare)
    WHERE cheie_deduplicare IS NOT NULL;

-- ============================================================================
-- F. SECURITATE ȘI AUDIT
-- ============================================================================

CREATE TABLE audit_log (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firma_id       uuid REFERENCES firme(id) ON DELETE RESTRICT,
    utilizator_id  uuid REFERENCES utilizatori(id) ON DELETE RESTRICT,
    entitate_tip   varchar(30) NOT NULL,
    entitate_id    uuid,
    actiune        varchar(40) NOT NULL,
    date_vechi     jsonb,
    date_noi       jsonb,
    ip_address     varchar(45),
    user_agent     varchar(255),
    creat_la       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_audit_entitate ON audit_log(entitate_tip, entitate_id);
CREATE INDEX idx_audit_firma_data ON audit_log(firma_id, creat_la);
CREATE INDEX idx_audit_utilizator ON audit_log(utilizator_id);

-- ============================================================================
-- Funcție: generarea checklist-ului la deschiderea unei perioade (v4)
-- Reguli:
--  * doar configurările active cu obligatoriu = true generează cerințe;
--    documentele opționale/ocazionale pot fi încărcate oricând, dar nu apar
--    ca „lipsă" în checklist
--  * tipurile cu cont financiar generează câte un rând DOAR pentru conturile
--    active de tip compatibil (extras_cont -> banca/card; registru_casa -> casa)
--  * returnează numărul TOTAL de cerințe create
-- ============================================================================

CREATE OR REPLACE FUNCTION fn_genereaza_checklist_perioada(p_perioada_id uuid)
RETURNS integer AS $$
DECLARE
    v_firma_id uuid;
    v_count_simple integer := 0;
    v_count_conturi integer := 0;
BEGIN
    SELECT firma_id INTO v_firma_id
    FROM perioade_contabile WHERE id = p_perioada_id;

    IF v_firma_id IS NULL THEN
        RAISE EXCEPTION 'Perioada % nu există', p_perioada_id;
    END IF;

    INSERT INTO cerinte_documente_perioada
        (perioada_contabila_id, firma_id, tip_document_id, cont_financiar_id, status)
    SELECT p_perioada_id, v_firma_id, c.tip_document_id, NULL, 'lipsa'
    FROM configurare_documente_firma c
    JOIN tipuri_document t ON t.id = c.tip_document_id
    WHERE c.firma_id = v_firma_id
      AND c.activ AND t.activ
      AND c.obligatoriu = true
      AND t.necesita_cont_financiar = false
    ON CONFLICT DO NOTHING;

    GET DIAGNOSTICS v_count_simple = ROW_COUNT;

    INSERT INTO cerinte_documente_perioada
        (perioada_contabila_id, firma_id, tip_document_id, cont_financiar_id, status)
    SELECT p_perioada_id, v_firma_id, c.tip_document_id, cf.id, 'lipsa'
    FROM configurare_documente_firma c
    JOIN tipuri_document t ON t.id = c.tip_document_id
    JOIN conturi_financiare cf
      ON cf.firma_id = c.firma_id
     AND cf.activ
     AND cf.tip = ANY(t.tipuri_cont_compatibile)
    WHERE c.firma_id = v_firma_id
      AND c.activ AND t.activ
      AND c.obligatoriu = true
      AND t.necesita_cont_financiar = true
    ON CONFLICT DO NOTHING;

    GET DIAGNOSTICS v_count_conturi = ROW_COUNT;

    RETURN v_count_simple + v_count_conturi;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- ROW LEVEL SECURITY (v4)
--
-- Model:
--  * conexiunea web = rol de login membru în app_user (fără BYPASSRLS)
--  * conexiunea worker/administrare = rol de login CU ATRIBUTUL BYPASSRLS
--    propriu (ATENȚIE: BYPASSRLS NU se moștenește prin apartenența la rol!)
--  * aplicația setează la fiecare request, în interiorul tranzacției:
--        SELECT set_config('app.utilizator_id', '<uuid>', true);
--
-- Accesul la firme:
--  * alocările directe din utilizator_firma, PLUS
--  * pentru admin_cabinet și contabil_coordonator: toate firmele cabinetului
--
-- Scrieri administrative (D2): utilizatori, utilizator_firma, invitatii NU
-- pot fi scrise de app_user — doar prin conexiunea privilegiată, din
-- service layer, cu verificare de rol în aplicație și audit.
-- ============================================================================

-- PRECONDIȚIE: app_user și app_admin există (create de db/roles.sql).
-- Acest fișier doar acordă drepturi.

GRANT USAGE ON SCHEMA public TO app_user, app_admin;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_admin;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_admin;

-- D2: scrierile administrative NU trec prin app_user
REVOKE INSERT, UPDATE ON utilizatori       FROM app_user;
REVOKE INSERT, UPDATE ON utilizator_firma  FROM app_user;
REVOKE INSERT, UPDATE ON invitatii         FROM app_user;
REVOKE INSERT, UPDATE ON cabinete_contabilitate FROM app_user;
REVOKE INSERT, UPDATE ON tipuri_document   FROM app_user;
-- D13 R5: intenția se creează pe web, dar este imuabilă după INSERT;
-- fișierul se creează/înlocuiește doar prin finalizarea privilegiată.
REVOKE UPDATE ON intentii_upload FROM app_user;
REVOKE INSERT, UPDATE ON fisiere_document FROM app_user;

-- D3 (R5): coloana parola_hash NU e lizibilă pe conexiunea web — grant pe
-- listă explicită de coloane. Autentificarea (care are nevoie de hash)
-- rulează pe conexiunea privilegiată. Managerul Django al modelului face
-- defer("password") pe web; orice cod care uită primește "permission
-- denied for column" — eșec zgomotos, nu scurgere silențioasă.
REVOKE SELECT ON utilizatori FROM app_user;
GRANT SELECT (id, cabinet_id, nume, email, rol, telefon, activ,
              last_login, is_staff, is_superuser, creat_la)
    ON utilizatori TO app_user;
-- utilizatorul își poate actualiza profilul propriu și parola proprie
-- (autentificat, identitate setată) — LIMITAT LA RÂNDUL PROPRIU prin RLS
GRANT UPDATE (nume, telefon, parola_hash) ON utilizatori TO app_user;

-- D9: tabelele create ulterior de migrările Django primesc automat drepturi,
-- dar app_user NU primește DELETE nici pe cele viitoare. Tabelele tehnice
-- care au nevoie de DELETE (ex: django_session) îl primesc explicit,
-- punctual, în migrarea care le creează:
--     GRANT DELETE ON django_session TO app_user;
-- ATENȚIE: ALTER DEFAULT PRIVILEGES se aplică obiectelor create de rolul
-- care execută comanda (aici: rolul de migrare/owner). Toate migrările
-- viitoare TREBUIE să ruleze cu același rol, altfel granturile implicite
-- nu se aplică.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_admin;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO app_admin;
-- Convenție: orice tabel de business nou primește, în aceeași migrare,
-- RLS + politici; altfel ar fi vizibil integral prin app_user.

-- ----------------------------------------------------------------------------
-- Funcții helper. SECURITY DEFINER (owner = migrare, care ocolește RLS ca
-- owner — altfel politicile ar intra în recursie). Blindaj (D11):
--   * search_path fixat cu pg_temp ULTIMUL — altfel un utilizator poate
--     crea tabele temporare cu aceleași nume și ocoli izolarea (pg_temp
--     e implicit PRIMUL în search_path pentru relații)
--   * nume de tabele calificate cu schema, ca apărare suplimentară
--   * EXECUTE revocat de la PUBLIC, acordat doar rolurilor aplicației
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_utilizator_curent() RETURNS uuid AS $$
    SELECT NULLIF(current_setting('app.utilizator_id', true), '')::uuid;
$$ LANGUAGE sql STABLE SET search_path = public, pg_temp;

CREATE OR REPLACE FUNCTION fn_rol_curent() RETURNS varchar AS $$
    SELECT rol FROM public.utilizatori WHERE id = public.fn_utilizator_curent();
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp;

CREATE OR REPLACE FUNCTION fn_cabinet_curent() RETURNS uuid AS $$
    SELECT cabinet_id FROM public.utilizatori WHERE id = public.fn_utilizator_curent();
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp;

CREATE OR REPLACE FUNCTION fn_firmele_utilizatorului() RETURNS SETOF uuid AS $$
    -- alocări directe
    SELECT firma_id FROM public.utilizator_firma
    WHERE utilizator_id = public.fn_utilizator_curent()
    UNION
    -- admin/coordonator: toate firmele cabinetului propriu
    SELECT f.id
    FROM public.firme f
    JOIN public.utilizatori u ON u.cabinet_id = f.cabinet_id
    WHERE u.id = public.fn_utilizator_curent()
      AND u.rol IN ('admin_cabinet', 'contabil_coordonator');
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp;

-- Utilizatorii vizibili pe conexiunea web (D3 R5): rândul propriu,
-- colegii de cabinet și utilizatorii alocați firmelor accesibile.
-- Fără identitate setată => mulțime vidă.
CREATE OR REPLACE FUNCTION fn_utilizatorii_vizibili() RETURNS SETOF uuid AS $$
    SELECT public.fn_utilizator_curent()
    WHERE public.fn_utilizator_curent() IS NOT NULL
    UNION
    SELECT u.id FROM public.utilizatori u
    WHERE u.cabinet_id IS NOT NULL
      AND u.cabinet_id = public.fn_cabinet_curent()
    UNION
    SELECT uf.utilizator_id FROM public.utilizator_firma uf
    WHERE uf.firma_id IN (SELECT public.fn_firmele_utilizatorului());
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp;

REVOKE EXECUTE ON FUNCTION fn_utilizator_curent(), fn_rol_curent(),
    fn_cabinet_curent(), fn_firmele_utilizatorului(),
    fn_utilizatorii_vizibili() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION fn_utilizator_curent(), fn_rol_curent(),
    fn_cabinet_curent(), fn_firmele_utilizatorului(),
    fn_utilizatorii_vizibili() TO app_user, app_admin;

-- ----------------------------------------------------------------------------
-- Politici. Convenție: politici SEPARATE pe operații, cu WITH CHECK explicit
-- la orice politică ce acoperă INSERT/UPDATE (lecția pol_uf din v3).
-- ----------------------------------------------------------------------------

-- D3 (R5): pe conexiunea web, utilizatori e vizibil DOAR în interiorul
-- tenantului (fn_utilizatorii_vizibili). Fără identitate => zero rânduri.
-- Login-ul și încărcarea utilizatorului de sesiune NU mai trec pe web —
-- rulează pe conexiunea privilegiată (SPECS §7). UPDATE strict pe rândul
-- propriu. INSERT/DELETE: fără politici și fără GRANT => interzise.
ALTER TABLE utilizatori ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_utilizatori_select ON utilizatori FOR SELECT
    USING (id IN (SELECT fn_utilizatorii_vizibili()));
CREATE POLICY pol_utilizatori_update ON utilizatori FOR UPDATE
    USING (id = fn_utilizator_curent())
    WITH CHECK (id = fn_utilizator_curent());

ALTER TABLE cabinete_contabilitate ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_cabinet_select ON cabinete_contabilitate FOR SELECT
    USING (id = fn_cabinet_curent());

ALTER TABLE firme ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_firme_select ON firme FOR SELECT
    USING (
        (cabinet_id = fn_cabinet_curent()
         AND fn_rol_curent() IN ('admin_cabinet', 'contabil_coordonator'))
        OR id IN (SELECT fn_firmele_utilizatorului())
    );
CREATE POLICY pol_firme_insert ON firme FOR INSERT
    WITH CHECK (cabinet_id = fn_cabinet_curent()
                AND fn_rol_curent() = 'admin_cabinet');
CREATE POLICY pol_firme_update ON firme FOR UPDATE
    USING (cabinet_id = fn_cabinet_curent()
           AND fn_rol_curent() = 'admin_cabinet')
    WITH CHECK (cabinet_id = fn_cabinet_curent());

ALTER TABLE utilizator_firma ENABLE ROW LEVEL SECURITY;
-- doar citire pentru app_user (scrierile sunt oricum revocate):
-- propriile alocări + personalul cabinetului vede alocările firmelor lui
CREATE POLICY pol_uf_select ON utilizator_firma FOR SELECT
    USING (
        utilizator_id = fn_utilizator_curent()
        OR firma_id IN (SELECT fn_firmele_utilizatorului())
    );

ALTER TABLE invitatii ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_inv_select ON invitatii FOR SELECT
    USING (
        (cabinet_id IS NOT NULL AND cabinet_id = fn_cabinet_curent())
        OR (firma_id IS NOT NULL AND firma_id IN (SELECT fn_firmele_utilizatorului()))
    );

-- Tabele de tenant standard: SELECT/UPDATE pe firmele accesibile,
-- INSERT/UPDATE cu WITH CHECK identic.

ALTER TABLE configurare_documente_firma ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_config_all ON configurare_documente_firma
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()))
    WITH CHECK (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE perioade_contabile ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_perioade_all ON perioade_contabile
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()))
    WITH CHECK (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE conturi_financiare ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_conturi_all ON conturi_financiare
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()))
    WITH CHECK (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE parteneri ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_parteneri_all ON parteneri
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()))
    WITH CHECK (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE documente ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_documente_all ON documente
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()))
    WITH CHECK (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE fisiere_document ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_fisiere_select ON fisiere_document FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE cerinte_documente_perioada ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_cerinte_all ON cerinte_documente_perioada
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()))
    WITH CHECK (firma_id IN (SELECT fn_firmele_utilizatorului()));

ALTER TABLE comentarii ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_comentarii_all ON comentarii
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()))
    WITH CHECK (firma_id IN (SELECT fn_firmele_utilizatorului())
                AND utilizator_id = fn_utilizator_curent());

ALTER TABLE istoric_stari ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_istoric_select ON istoric_stari FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));
CREATE POLICY pol_istoric_insert ON istoric_stari FOR INSERT
    WITH CHECK (firma_id IN (SELECT fn_firmele_utilizatorului())
                AND utilizator_id = fn_utilizator_curent());
REVOKE UPDATE ON istoric_stari FROM app_user;  -- istoricul e append-only

ALTER TABLE intentii_upload ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_intentii_select ON intentii_upload FOR SELECT
    USING (utilizator_id = fn_utilizator_curent());
CREATE POLICY pol_intentii_insert ON intentii_upload FOR INSERT
    WITH CHECK (firma_id IN (SELECT fn_firmele_utilizatorului())
                AND utilizator_id = fn_utilizator_curent());
-- UPDATE/DELETE: fără politică și fără GRANT pentru app_user. Consumul este
-- atomic în service layer pe conexiunea privileged (SELECT FOR UPDATE,
-- INSERT fisiere_document, UPDATE folosita_la, COMMIT).

ALTER TABLE exporturi ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_exporturi_select ON exporturi FOR SELECT
    USING (solicitat_de = fn_utilizator_curent()
           AND firma_id IN (SELECT fn_firmele_utilizatorului()));
-- Solicitarea, starea și cheia obiectului sunt controlate exclusiv de
-- serviciul privilegiat, după verificarea rolului și apartenenței la cabinet.
REVOKE INSERT, UPDATE, DELETE ON exporturi FROM app_user;

ALTER TABLE predari_documente ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_predari_select ON predari_documente FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));
-- Orice schimbare de stare trece prin serviciul privilegiat, cu verificare
-- de rol/apartenență și audit; conexiunea web are exclusiv citire.
REVOKE INSERT, UPDATE, DELETE ON predari_documente FROM app_user;

ALTER TABLE notificari ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_notif_select ON notificari FOR SELECT
    USING (utilizator_id = fn_utilizator_curent());
CREATE POLICY pol_notif_update ON notificari FOR UPDATE
    USING (utilizator_id = fn_utilizator_curent())
    WITH CHECK (utilizator_id = fn_utilizator_curent());
-- INSERT de notificări: doar procesele de sistem (app_admin)
REVOKE INSERT ON notificari FROM app_user;
-- utilizatorul poate marca drept citit doar propriul rând; conținutul,
-- destinatarul și cheia de deduplicare rămân controlate de sistem
REVOKE UPDATE ON notificari FROM app_user;
GRANT UPDATE (citita) ON notificari TO app_user;

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY pol_audit_select ON audit_log FOR SELECT
    USING (firma_id IN (SELECT fn_firmele_utilizatorului()));
CREATE POLICY pol_audit_insert ON audit_log FOR INSERT
    WITH CHECK (utilizator_id = fn_utilizator_curent()
                AND (firma_id IS NULL
                     OR firma_id IN (SELECT fn_firmele_utilizatorului())));
REVOKE UPDATE ON audit_log FROM app_user;  -- audit-ul e append-only

-- ============================================================================
-- SEED: tipuri de document standard
-- ============================================================================

INSERT INTO tipuri_document
    (cod, denumire, categorie, necesita_serie_numar, necesita_cont_financiar, tipuri_cont_compatibile) VALUES
    ('factura',        'Factură',               'document_justificativ', true,  false, NULL),
    ('aviz_expeditie', 'Aviz de expediție',     'document_justificativ', true,  false, NULL),
    ('bon_consum',     'Bon de consum',         'document_justificativ', false, false, NULL),
    ('nir',            'Notă intrare recepție', 'document_justificativ', false, false, NULL),
    ('extras_cont',    'Extras de cont',        'trezorerie',            false, true,  ARRAY['banca','card']),
    ('chitanta',       'Chitanță',              'trezorerie',            true,  false, NULL),
    ('registru_casa',  'Registru de casă',      'trezorerie',            false, true,  ARRAY['casa']),
    ('comanda',        'Comandă',               'document_operational',  false, false, NULL)
ON CONFLICT (cod) DO NOTHING;

-- ============================================================================
-- SFÂRȘIT SCHEMA. Vezi db/roles.sql pentru rolurile de cluster (rulate de
-- provisioning ÎNAINTE de acest fișier) și SPECS §8 pentru modelul complet
-- de conexiuni (default = app_user; privileged = login cu BYPASSRLS propriu;
-- migrare = owner-ul bazei, mereu același rol).
-- ============================================================================
