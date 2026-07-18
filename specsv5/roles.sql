-- ============================================================================
-- db/roles.sql — RELEASE R5 — roluri la nivel de CLUSTER
--
-- ATENȚIE: se rulează CA SUPERUSER. Nu e suficient CREATEROLE: crearea unui
-- rol cu BYPASSRLS cere superuser (sau un rol care are el însuși BYPASSRLS)
-- — regulă PostgreSQL. Provisioning-ul (o dată per cluster):
--
--   psql -v parola_migrare='...' -v parola_web='...' -v parola_worker='...' \
--        -f roles.sql
--   createdb -O migrare <nume_baza>
--
-- Fișierul reconciliază un profil EXACT: existență, toate atributele de
-- securitate și singurele două membership-uri permise. Parolele se setează
-- DOAR la creare; rotația e separată, prin secret manager. La final,
-- VERIFICAREA oprește execuția dacă a rămas orice privilegiu suplimentar.
-- ============================================================================

\set ON_ERROR_STOP on

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_admin') THEN
        CREATE ROLE app_admin NOLOGIN;
    END IF;
END
$$;

SELECT format('CREATE ROLE migrare LOGIN PASSWORD %L', :'parola_migrare')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='migrare') \gexec

SELECT format('CREATE ROLE web_app LOGIN PASSWORD %L', :'parola_web')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='web_app') \gexec

SELECT format('CREATE ROLE worker LOGIN PASSWORD %L', :'parola_worker')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='worker') \gexec

-- Profil exact de atribute. R5 elimină explicit CREATEDB/REPLICATION și
-- repară inclusiv LOGIN-ul accidental pe rolurile de grup.
ALTER ROLE app_user  NOLOGIN NOINHERIT NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE app_admin NOLOGIN NOINHERIT NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE migrare   LOGIN INHERIT NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE web_app   LOGIN INHERIT NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE worker    LOGIN INHERIT BYPASSRLS   NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

-- Elimină orice membership suplimentar care implică rolurile aplicației.
-- Profilul permis este EXCLUSIV web_app→app_user și worker→app_admin.
DO $$
DECLARE
    v_membership record;
BEGIN
    FOR v_membership IN
        SELECT rol_parinte.rolname AS rol_parinte,
               rol_membru.rolname AS rol_membru
        FROM pg_auth_members m
        JOIN pg_roles rol_parinte ON rol_parinte.oid = m.roleid
        JOIN pg_roles rol_membru ON rol_membru.oid = m.member
        WHERE (rol_parinte.rolname IN ('app_user','app_admin','migrare','web_app','worker')
               OR rol_membru.rolname IN ('app_user','app_admin','migrare','web_app','worker'))
          AND NOT (
              (rol_parinte.rolname = 'app_user' AND rol_membru.rolname = 'web_app')
              OR (rol_parinte.rolname = 'app_admin' AND rol_membru.rolname = 'worker')
          )
    LOOP
        EXECUTE format('REVOKE %I FROM %I',
                       v_membership.rol_parinte, v_membership.rol_membru);
    END LOOP;
END
$$;

GRANT app_user  TO web_app;
GRANT app_admin TO worker;
-- Un membership preexistent putea avea ADMIN OPTION; GRANT simplu nu îl
-- elimină, deci îl revocăm explicit fără a revoca membership-ul.
REVOKE ADMIN OPTION FOR app_user  FROM web_app;
REVOKE ADMIN OPTION FOR app_admin FROM worker;

-- VERIFICARE: eșec zgomotos dacă provisioning-ul nu e complet
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname='app_user'
          AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND NOT rolbypassrls
    ) THEN
        RAISE EXCEPTION 'PROVISIONING EȘUAT: profilul app_user nu este exact';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname='app_admin'
          AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND NOT rolbypassrls
    ) THEN
        RAISE EXCEPTION 'PROVISIONING EȘUAT: profilul app_admin nu este exact';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname='migrare'
          AND rolcanlogin AND rolinherit AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND NOT rolbypassrls
    ) THEN
        RAISE EXCEPTION 'PROVISIONING EȘUAT: profilul migrare nu este exact';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname='web_app'
          AND rolcanlogin AND rolinherit AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND NOT rolbypassrls
    ) THEN
        RAISE EXCEPTION 'PROVISIONING EȘUAT: profilul web_app nu este exact';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname='worker'
          AND rolcanlogin AND rolinherit AND NOT rolsuper
          AND NOT rolcreatedb AND NOT rolcreaterole
          AND NOT rolreplication AND rolbypassrls
    ) THEN
        RAISE EXCEPTION 'PROVISIONING EȘUAT: profilul worker nu este exact';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_auth_members m
        JOIN pg_roles r ON r.oid = m.roleid
        JOIN pg_roles g ON g.oid = m.member
        WHERE r.rolname='app_user' AND g.rolname='web_app'
          AND NOT m.admin_option
    ) THEN
        RAISE EXCEPTION 'PROVISIONING EȘUAT: web_app nu e membru în app_user';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_auth_members m
        JOIN pg_roles r ON r.oid = m.roleid
        JOIN pg_roles g ON g.oid = m.member
        WHERE r.rolname='app_admin' AND g.rolname='worker'
          AND NOT m.admin_option
    ) THEN
        RAISE EXCEPTION 'PROVISIONING EȘUAT: worker nu e membru în app_admin';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_auth_members m
        JOIN pg_roles r ON r.oid = m.roleid
        JOIN pg_roles g ON g.oid = m.member
        WHERE (r.rolname IN ('app_user','app_admin','migrare','web_app','worker')
               OR g.rolname IN ('app_user','app_admin','migrare','web_app','worker'))
          AND NOT (
              (r.rolname='app_user' AND g.rolname='web_app' AND NOT m.admin_option)
              OR (r.rolname='app_admin' AND g.rolname='worker' AND NOT m.admin_option)
          )
    ) THEN
        RAISE EXCEPTION 'PROVISIONING EȘUAT: există membership-uri suplimentare sau ADMIN OPTION';
    END IF;
    RAISE NOTICE 'Provisioning R5 verificat: profile exacte și membership-uri minime';
END
$$;
