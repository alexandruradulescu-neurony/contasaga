#!/bin/bash
# ============================================================================
# Teste funcționale — RELEASE R5, TOPOLOGIA DE PRODUCȚIE:
#   * rolurile create de roles.sql (migrare / web_app / worker), cu verificare
#   * baza deținută de `migrare` (NON-superuser)
#   * schema + seed instalate DE `migrare` (exact ca migrarea core.0001)
# AUTO-SUFICIENT și REPETABIL. Pe macOS poate rula cu
# PG_ADMIN_DIRECT=1 PGUSER=<superuserul local>.
# Fișiere necesare alături: roles.sql, schema_starter.sql, seed_test.sql
# ============================================================================
set -u

DB="${RLS_TEST_DB:-conta_test}"
SQL_DIR="$(cd "$(dirname "$0")" && pwd)"
PAROLA_MIGRARE="${RLS_MIGRATION_PASSWORD:-test}"
PAROLA_WEB="${RLS_WEB_PASSWORD:-test}"
PAROLA_WORKER="${RLS_WORKER_PASSWORD:-test}"

escape_pgpass() {
  local valoare="$1"
  valoare="${valoare//\\/\\\\}"
  valoare="${valoare//:/\\:}"
  printf '%s' "$valoare"
}

PGPASSFILE_TEMP="$(mktemp)"
chmod 600 "$PGPASSFILE_TEMP"
{
  printf '127.0.0.1:*:*:migrare:%s\n' "$(escape_pgpass "$PAROLA_MIGRARE")"
  printf '127.0.0.1:*:*:web_app:%s\n' "$(escape_pgpass "$PAROLA_WEB")"
  printf '127.0.0.1:*:*:worker:%s\n' "$(escape_pgpass "$PAROLA_WORKER")"
} > "$PGPASSFILE_TEMP"
export PGPASSFILE="$PGPASSFILE_TEMP"
unset PGPASSWORD
trap 'rm -f "$PGPASSFILE_TEMP"' EXIT

# Implicit rulează comenzile de cluster ca utilizatorul OS `postgres`.
# Pentru un cluster izolat în care utilizatorul curent este superuser:
#   PG_ADMIN_DIRECT=1 PGUSER=<superuser> bash test_rls.sh
run_as_pg_admin() {
  if [ "${PG_ADMIN_DIRECT:-0}" = "1" ]; then
    "$@"
  else
    local quoted
    printf -v quoted '%q ' "$@"
    su postgres -c "$quoted"
  fi
}

echo ">>> Reconstruiesc topologia de producție de la zero..."
run_as_pg_admin psql -d postgres -qc "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid <> pg_backend_pid();" > /dev/null 2>&1
run_as_pg_admin dropdb --if-exists "$DB" || { echo "EROARE: dropdb"; exit 2; }
run_as_pg_admin psql -d postgres -q -v ON_ERROR_STOP=1 -v parola_migrare="$PAROLA_MIGRARE" -v parola_web="$PAROLA_WEB" -v parola_worker="$PAROLA_WORKER" -f "$SQL_DIR/roles.sql" > /dev/null || { echo "EROARE: roles.sql (verificarea interna a esuat?)"; exit 2; }
run_as_pg_admin createdb -O migrare "$DB" || { echo "EROARE: createdb"; exit 2; }

psql -h 127.0.0.1 -U migrare -d $DB -q -v ON_ERROR_STOP=1 -f $SQL_DIR/schema_starter.sql > /dev/null || { echo "EROARE: schema (ca migrare)"; exit 2; }
psql -h 127.0.0.1 -U migrare -d $DB -q -v ON_ERROR_STOP=1 -f $SQL_DIR/seed_test.sql > /dev/null || { echo "EROARE: seed (ca migrare)"; exit 2; }

PSQL="psql -h 127.0.0.1 -U web_app -d $DB -tA"
WORKER="psql -h 127.0.0.1 -U worker -d $DB -tA"
MIGRARE="psql -h 127.0.0.1 -U migrare -d $DB -tA"

ADMIN_ID='99999999-0000-0000-0000-000000000001'
ANA_ID='99999999-0000-0000-0000-000000000002'
CLIENT_ID='99999999-0000-0000-0000-000000000003'
BETA_ID='99999999-0000-0000-0000-000000000004'
FIRMA_A='aaaaaaaa-0000-0000-0000-000000000001'
FIRMA_B='aaaaaaaa-0000-0000-0000-000000000002'
FIRMA_C='bbbbbbbb-0000-0000-0000-000000000001'
CAB_ALPHA='11111111-1111-1111-1111-111111111111'
CAB_BETA='22222222-2222-2222-2222-222222222222'
PERIOADA_A='dddddddd-0000-0000-0000-000000000001'
PERIOADA_C='dddddddd-0000-0000-0000-000000000002'

pass=0; fail=0
check() {
  if [ "$2" == "$3" ]; then echo "PASS: $1"; pass=$((pass+1));
  else echo "FAIL: $1 (așteptat='$2', obținut='$3')"; fail=$((fail+1)); fi
}
num() { grep -E '^[0-9]+$' | tail -1; }

# ------------------------------------------------ topologie owner
R=$($MIGRARE -c "SELECT count(*) FROM firme;")
check "T01: owner-ul migrare vede datele (seed OK, ENABLE nu FORCE)" "3" "$R"

# ------------------------------------------------ izolare (inclusiv utilizatori!)
R=$($PSQL -c "SELECT count(*) FROM documente;")
check "T02: fara identitate, documente invizibile" "0" "$R"
R=$($PSQL -c "SELECT count(*) FROM firme;")
check "T03: fara identitate, firme invizibile" "0" "$R"
R=$($PSQL -c "SELECT count(*) FROM utilizatori;")
check "T04: fara identitate, UTILIZATORI invizibili (B1 review 4)" "0" "$R"
R=$($PSQL -c "SELECT parola_hash FROM utilizatori LIMIT 1;" 2>&1 | grep -c "permission denied")
check "T05: parola_hash NELIZIBILA pe conexiunea web (coloana revocata)" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); SELECT count(*) FROM utilizatori; ROLLBACK;" | num)
check "T06: Ana vede exact utilizatorii tenantului ei (ea+admin+client=3)" "3" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); SELECT count(*) FROM utilizatori WHERE id='$BETA_ID'; ROLLBACK;" | num)
check "T07: utilizatorul altui cabinet e invizibil" "0" "$R"

R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); SELECT count(*) FROM firme; ROLLBACK;" | num)
check "T08: contabil alocat vede exact 1 firma" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ADMIN_ID',true); SELECT count(*) FROM firme; ROLLBACK;" | num)
check "T09: admin cabinet vede toate firmele cabinetului (fara recursie)" "2" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$BETA_ID',true); SELECT count(*) FROM firme WHERE cabinet_id='$CAB_ALPHA'; ROLLBACK;" | num)
check "T10: izolare intre cabinete" "0" "$R"

# ------------------------------------------------ atacul pg_temp
R=$($PSQL -c "BEGIN;
SELECT set_config('app.utilizator_id','$ANA_ID',true);
CREATE TEMP TABLE utilizator_firma (utilizator_id uuid, firma_id uuid);
INSERT INTO utilizator_firma VALUES ('$ANA_ID','$FIRMA_C');
CREATE TEMP TABLE utilizatori (id uuid, cabinet_id uuid, rol varchar);
INSERT INTO utilizatori VALUES ('$ANA_ID','$CAB_BETA','admin_cabinet');
SELECT count(*) FROM public.firme WHERE id='$FIRMA_C';
ROLLBACK;" | num)
check "T11: tabelele temporare NU pot ocoli izolarea (pg_temp ultimul)" "0" "$R"

# ------------------------------------------------ scrieri ilegale
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO utilizator_firma (utilizator_id, firma_id, rol_in_firma) VALUES ('$CLIENT_ID','$FIRMA_B','reprezentant_client'); ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T12: auto-alocarea la alta firma respinsa" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); INSERT INTO parteneri (firma_id, tip, denumire) VALUES ('$FIRMA_B','furnizor','Intrus SRL'); ROLLBACK;" 2>&1 | grep -c "row-level security")
check "T13: scriere pe firma nealocata respinsa (WITH CHECK)" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ADMIN_ID',true); INSERT INTO firme (cabinet_id, cui, denumire) VALUES ('$CAB_ALPHA','RO999','Firma Noua') RETURNING 1; ROLLBACK;" | num)
check "T14: admin poate crea firma cu RETURNING (compatibil ORM)" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ADMIN_ID',true); INSERT INTO firme (cabinet_id, cui, denumire) VALUES ('$CAB_BETA','RO888','Intrusa'); ROLLBACK;" 2>&1 | grep -c "row-level security")
check "T15: admin nu poate crea firma in alt cabinet" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ADMIN_ID',true); SELECT count(*) FROM cabinete_contabilitate; ROLLBACK;" | num)
check "T16: admin isi vede cabinetul" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ADMIN_ID',true); INSERT INTO utilizatori (nume,email,parola_hash,rol) VALUES ('X','x@x.ro','x','client_admin'); ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T17: INSERT in utilizatori revocat pentru app_user" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ADMIN_ID',true); UPDATE utilizatori SET parola_hash='hacked' WHERE id='$BETA_ID'; ROLLBACK;" 2>&1 | grep -c "UPDATE 0")
check "T18: NU pot schimba parola altui utilizator" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ADMIN_ID',true); UPDATE utilizatori SET telefon='0700' WHERE id='$ADMIN_ID'; ROLLBACK;" 2>&1 | grep -c "UPDATE 1")
check "T19: imi pot actualiza propriul profil" "1" "$R"
R=$($PSQL -c "UPDATE utilizatori SET last_login=now() WHERE id='$ADMIN_ID';" 2>&1 | grep -c "permission denied")
check "T20: web nu poate scrie last_login DELOC (coloana revocata la UPDATE)" "1" "$R"
R=$($WORKER -c "UPDATE utilizatori SET last_login=now() WHERE id='$ADMIN_ID';" 2>&1 | grep -c "UPDATE 1")
check "T21: worker-ul (BYPASSRLS) scrie last_login (serviciul de autentificare)" "1" "$R"

# ------------------------------------------------ cross-tenant
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); INSERT INTO audit_log (firma_id, utilizator_id, entitate_tip, actiune) VALUES ('$FIRMA_C','$ANA_ID','document','view'); ROLLBACK;" 2>&1 | grep -c "row-level security")
check "T22: audit pe firma altui cabinet respins" "1" "$R"

$WORKER -c "INSERT INTO documente (id, firma_id, perioada_contabila_id, tip_document_id, incarcat_de, stare)
  SELECT '10000000-0000-0000-0000-000000000001','$FIRMA_A','$PERIOADA_A', id, '$ANA_ID','draft' FROM tipuri_document WHERE cod='bon_consum';
  INSERT INTO documente (id, firma_id, perioada_contabila_id, tip_document_id, incarcat_de, stare)
  SELECT '10000000-0000-0000-0000-000000000003','$FIRMA_A','$PERIOADA_A', id, '$ANA_ID','draft' FROM tipuri_document WHERE cod='nir';
  INSERT INTO perioade_contabile (id, firma_id, luna, an) VALUES ('dddddddd-0000-0000-0000-000000000002','$FIRMA_C',6,2026);
  INSERT INTO documente (id, firma_id, perioada_contabila_id, tip_document_id, incarcat_de, stare)
  SELECT '10000000-0000-0000-0000-000000000002','$FIRMA_C','dddddddd-0000-0000-0000-000000000002', id, '$BETA_ID','draft' FROM tipuri_document WHERE cod='bon_consum';
  INSERT INTO intentii_upload (id, firma_id, document_id, utilizator_id) VALUES
    ('30000000-0000-0000-0000-000000000001','$FIRMA_A','10000000-0000-0000-0000-000000000001','$ANA_ID'),
    ('30000000-0000-0000-0000-000000000002','$FIRMA_C','10000000-0000-0000-0000-000000000002','$BETA_ID'),
    ('30000000-0000-0000-0000-000000000003','$FIRMA_A','10000000-0000-0000-0000-000000000003','$ANA_ID');
  INSERT INTO fisiere_document (id, document_id, firma_id, upload_intentie_id, storage_key, incarcat_de) VALUES
    ('20000000-0000-0000-0000-000000000001','10000000-0000-0000-0000-000000000001','$FIRMA_A','30000000-0000-0000-0000-000000000001','clients/$FIRMA_A/2026-06/documents/30000000-0000-0000-0000-000000000001','$ANA_ID'),
    ('20000000-0000-0000-0000-000000000002','10000000-0000-0000-0000-000000000002','$FIRMA_C','30000000-0000-0000-0000-000000000002','clients/$FIRMA_C/2026-06/documents/30000000-0000-0000-0000-000000000002','$BETA_ID'),
    ('20000000-0000-0000-0000-000000000003','10000000-0000-0000-0000-000000000003','$FIRMA_A','30000000-0000-0000-0000-000000000003','clients/$FIRMA_A/2026-06/documents/30000000-0000-0000-0000-000000000003','$ANA_ID');
  UPDATE intentii_upload SET folosita_la=now()
  WHERE id IN ('30000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000002','30000000-0000-0000-0000-000000000003');" > /dev/null 2>&1

$WORKER -c "INSERT INTO intentii_upload (id, firma_id, document_id, utilizator_id) VALUES ('30000000-0000-0000-0000-000000000004','$FIRMA_A','10000000-0000-0000-0000-000000000001','$ANA_ID');" > /dev/null 2>&1
R=$($WORKER -c "INSERT INTO fisiere_document (document_id, firma_id, upload_intentie_id, storage_key, incarcat_de, inlocuieste_fisier_id) VALUES ('10000000-0000-0000-0000-000000000001','$FIRMA_A','30000000-0000-0000-0000-000000000004','clients/$FIRMA_A/2026-06/documents/30000000-0000-0000-0000-000000000004','$ANA_ID','20000000-0000-0000-0000-000000000002');" 2>&1 | grep -c "fk_fisier_inlocuieste")
check "T23: inlocuirea unui fisier din alta firma respinsa" "1" "$R"
$WORKER -c "INSERT INTO intentii_upload (id, firma_id, document_id, utilizator_id) VALUES ('30000000-0000-0000-0000-000000000005','$FIRMA_A','10000000-0000-0000-0000-000000000001','$ANA_ID');" > /dev/null 2>&1
R=$($WORKER -c "INSERT INTO fisiere_document (document_id, firma_id, upload_intentie_id, storage_key, incarcat_de, inlocuieste_fisier_id) VALUES ('10000000-0000-0000-0000-000000000001','$FIRMA_A','30000000-0000-0000-0000-000000000005','clients/$FIRMA_A/2026-06/documents/30000000-0000-0000-0000-000000000005','$ANA_ID','20000000-0000-0000-0000-000000000003');" 2>&1 | grep -c "fk_fisier_inlocuieste")
check "T24: inlocuirea unui fisier din ALT DOCUMENT respinsa" "1" "$R"

R=$($WORKER -c "UPDATE perioade_contabile SET contabil_responsabil_id='$BETA_ID' WHERE id='$PERIOADA_A';" 2>&1 | grep -c "membru intern al cabinetului")
check "T25: responsabil din alt cabinet respins" "1" "$R"
$WORKER -c "INSERT INTO perioade_contabile (id, firma_id, luna, an) VALUES ('dddddddd-0000-0000-0000-000000000003','$FIRMA_B',6,2026);" > /dev/null 2>&1
R=$($WORKER -c "UPDATE perioade_contabile SET contabil_responsabil_id='$ANA_ID' WHERE id='dddddddd-0000-0000-0000-000000000003';" 2>&1 | grep -c "alocat firmei")
check "T26: contabil NEALOCAT firmei respins ca responsabil" "1" "$R"
R=$($WORKER -c "UPDATE perioade_contabile SET contabil_responsabil_id='$ADMIN_ID' WHERE id='dddddddd-0000-0000-0000-000000000003' RETURNING 1;" 2>&1 | grep -c "^1$")
check "T27: adminul cabinetului acceptat ca responsabil fara alocare" "1" "$R"

$WORKER -c "INSERT INTO istoric_stari (firma_id, entitate_tip, entitate_id, stare_noua, utilizator_id) VALUES ('$FIRMA_A','document','10000000-0000-0000-0000-000000000001','draft','$ANA_ID');" > /dev/null 2>&1
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); UPDATE istoric_stari SET stare_noua='acceptat'; ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T28: istoric_stari e append-only pentru app_user" "1" "$R"

$MIGRARE -c "CREATE TABLE t_viitor (id int); INSERT INTO t_viitor VALUES (1);" > /dev/null 2>&1
R=$($PSQL -c "DELETE FROM t_viitor;" 2>&1 | grep -c "permission denied")
check "T29: DELETE interzis pe tabelele viitoare" "1" "$R"
R=$($PSQL -c "SELECT count(*) FROM t_viitor;")
check "T30: SELECT permis pe tabelele viitoare" "1" "$R"

# ------------------------------------------------ CHECK-uri utilizatori (B3)
R=$($WORKER -c "INSERT INTO utilizatori (nume,email,parola_hash,rol,is_staff) VALUES ('S1','s1@x.ro','x','contabil',true);" 2>&1 | grep -c "chk_utilizatori_cabinet")
check "T31: is_staff fara superuser respins" "1" "$R"
R=$($WORKER -c "INSERT INTO utilizatori (nume,email,parola_hash,rol,is_superuser) VALUES ('S2','s2@x.ro','x','client_admin',true);" 2>&1 | grep -c "chk_utilizatori_cabinet")
check "T32: is_superuser pe rol obisnuit respins" "1" "$R"
R=$($WORKER -c "INSERT INTO utilizatori (nume,email,parola_hash,rol,is_superuser,is_staff,cabinet_id) VALUES ('S3','s3@x.ro','x','superuser_platforma',true,true,'$CAB_ALPHA');" 2>&1 | grep -c "chk_utilizatori_cabinet")
check "T33: superuser_platforma CU cabinet respins" "1" "$R"
R=$($WORKER -c "INSERT INTO utilizatori (nume,email,parola_hash,rol,is_superuser,is_staff) VALUES ('Root','root@platforma.ro','x','superuser_platforma',true,true) RETURNING 1;" 2>&1 | grep -c "^1$")
check "T34: superuser_platforma corect acceptat" "1" "$R"

# ------------------------------------------------ alocari: coerenta rol
R=$($WORKER -c "INSERT INTO utilizator_firma (utilizator_id, firma_id, rol_in_firma) VALUES ('$ANA_ID','$FIRMA_B','reprezentant_client');" 2>&1 | grep -c "contabil_alocat")
check "T35: contabil ca reprezentant_client respins" "1" "$R"
R=$($WORKER -c "INSERT INTO utilizator_firma (utilizator_id, firma_id, rol_in_firma) VALUES ('$CLIENT_ID','$FIRMA_B','operator_upload');" 2>&1 | grep -c "reprezentant_client")
check "T36: client_admin ca operator_upload respins" "1" "$R"

# ------------------------------------------------ invitatii
R=$($WORKER -c "INSERT INTO invitatii (firma_id, email, rol, token_hash, expira_la, creat_de) VALUES ('$FIRMA_A','x@y.ro','contabil','tok1', now() + interval '7 days', '$ADMIN_ID');" 2>&1 | grep -c "chk_inv_ancora")
check "T37: invitatie interna ancorata la firma respinsa" "1" "$R"
R=$($WORKER -c "INSERT INTO invitatii (firma_id, email, rol, rol_in_firma, token_hash, expira_la, creat_de) VALUES ('$FIRMA_A','x@y.ro','client_admin','contabil_alocat','tok2', now() + interval '7 days', '$ADMIN_ID');" 2>&1 | grep -c "chk_inv_ancora")
check "T38: invitatie client cu rol_in_firma incoerent respinsa" "1" "$R"
R=$($WORKER -c "INSERT INTO invitatii (firma_id, email, rol, rol_in_firma, token_hash, expira_la, acceptata_la, anulata_la, creat_de) VALUES ('$FIRMA_A','x@y.ro','client_admin','reprezentant_client','tok3', now() + interval '7 days', now(), now(), '$ADMIN_ID');" 2>&1 | grep -c "chk_inv_finalitate")
check "T39: invitatie simultan acceptata si anulata respinsa" "1" "$R"

# ------------------------------------------------ retentie
R=$($WORKER -c "UPDATE tipuri_document SET retentie_ani=1 WHERE cod='factura';" 2>&1 | grep -c "chk_td_retentie")
check "T40: retentie_ani sub minimul legal respinsa" "1" "$R"

# ------------------------------------------------ upload intents (D13)
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO intentii_upload (id, firma_id, document_id, utilizator_id) VALUES ('30000000-0000-0000-0000-000000000010','$FIRMA_A','10000000-0000-0000-0000-000000000001','$CLIENT_ID') RETURNING (storage_key='clients/$FIRMA_A/2026-06/documents/30000000-0000-0000-0000-000000000010' AND expira_la BETWEEN now()+interval '59 minutes' AND now()+interval '61 minutes' AND folosita_la IS NULL)::int; ROLLBACK;" | num)
check "T41: intent propriu acceptat; cheia/expirarea generate de DB" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO intentii_upload (firma_id, document_id, utilizator_id) VALUES ('$FIRMA_C','10000000-0000-0000-0000-000000000002','$CLIENT_ID'); ROLLBACK;" 2>&1 | grep -Ec "row-level security|Documentul/perioada nu există")
check "T42: intent pe firma straina respins" "1" "$R"

# ------------------------------------------------ checklist
R=$($WORKER -c "SELECT fn_genereaza_checklist_perioada('$PERIOADA_A');")
check "T43: checklist returneaza totalul corect (4)" "4" "$R"
R=$($WORKER -c "SELECT count(*) FROM cerinte_documente_perioada c JOIN tipuri_document t ON t.id=c.tip_document_id JOIN conturi_financiare f ON f.id=c.cont_financiar_id WHERE t.cod='extras_cont' AND f.tip='casa';")
check "T44: NU exista extras de cont pentru casierie" "0" "$R"
R=$($WORKER -c "SELECT fn_genereaza_checklist_perioada('$PERIOADA_A');")
check "T45: idempotenta (a doua rulare -> 0)" "0" "$R"

# ------------------------------------------------ integritate
$WORKER -c "INSERT INTO parteneri (id, firma_id, tip, denumire, cui) VALUES ('eeeeeeee-0000-0000-0000-000000000001','$FIRMA_A','furnizor','Furnizor SRL','RO777');" > /dev/null 2>&1
TIP_F=$($WORKER -c "SELECT id FROM tipuri_document WHERE cod='factura';")
$WORKER -c "INSERT INTO documente (firma_id, perioada_contabila_id, tip_document_id, partener_id, incarcat_de, serie, numar, stare) VALUES ('$FIRMA_A','$PERIOADA_A','$TIP_F','eeeeeeee-0000-0000-0000-000000000001','$ANA_ID','FF','100','trimis');" > /dev/null 2>&1
R=$($WORKER -c "INSERT INTO documente (firma_id, perioada_contabila_id, tip_document_id, partener_id, incarcat_de, serie, numar, stare) VALUES ('$FIRMA_A','$PERIOADA_A','$TIP_F','eeeeeeee-0000-0000-0000-000000000001','$ANA_ID','FF','100','trimis');" 2>&1 | grep -c "uq_doc_business")
check "T46: factura duplicata respinsa (uq_doc_business)" "1" "$R"

# ------------------------------------------------ regresii R5 (review v5)
R=$($WORKER -c "INSERT INTO documente (firma_id, perioada_contabila_id, tip_document_id, incarcat_de, retentie_extinsa_pana_la) SELECT '$FIRMA_A','$PERIOADA_A',id,'$ANA_ID','2030-01-01' FROM tipuri_document WHERE cod='bon_consum';" 2>&1 | grep -c "nu poate scurta termenul minim")
check "T47: extensia documentului nu poate scurta retentia legala" "1" "$R"

$PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO intentii_upload (id, firma_id, document_id, utilizator_id) VALUES ('30000000-0000-0000-0000-000000000011','$FIRMA_A','10000000-0000-0000-0000-000000000001','$CLIENT_ID'); COMMIT;" > /dev/null 2>&1
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); UPDATE intentii_upload SET firma_id='$FIRMA_C', document_id='10000000-0000-0000-0000-000000000002', storage_key='clients/foreign/rewritten', expira_la=now()+interval '30 days', folosita_la=now() WHERE id='30000000-0000-0000-0000-000000000011'; ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T48: intentul existent este imuabil pentru app_user" "1" "$R"

R=$($WORKER -c "INSERT INTO intentii_upload (firma_id, utilizator_id) VALUES ('$FIRMA_A','$ANA_ID');" 2>&1 | grep -Ec "not-null constraint|Documentul/perioada nu există")
check "T49: intentul fara document este respins" "1" "$R"

R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO fisiere_document (document_id,firma_id,upload_intentie_id,storage_key,incarcat_de) VALUES ('10000000-0000-0000-0000-000000000001','$FIRMA_A','30000000-0000-0000-0000-000000000011','clients/$FIRMA_A/2026-06/documents/30000000-0000-0000-0000-000000000011','$CLIENT_ID'); ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T50: app_user nu poate crea direct fisiere_document" "1" "$R"

R=$($WORKER -c "INSERT INTO fisiere_document (document_id,firma_id,upload_intentie_id,storage_key,incarcat_de) VALUES ('10000000-0000-0000-0000-000000000001','$FIRMA_A','30000000-0000-0000-0000-000000000001','clients/$FIRMA_A/2026-06/documents/30000000-0000-0000-0000-000000000001','$ANA_ID');" 2>&1 | grep -c "uq_fisier_upload_intentie")
check "T51: un intent poate produce cel mult un fisier" "1" "$R"

R=$($WORKER -c "INSERT INTO utilizator_firma (utilizator_id, firma_id, rol_in_firma) VALUES ('$ANA_ID','$FIRMA_C','contabil_alocat');" 2>&1 | grep -c "altui cabinet")
check "T52: alocarea cross-cabinet ramane respinsa" "1" "$R"

R=$($WORKER -c "SELECT count(*) FROM cerinte_documente_perioada WHERE perioada_contabila_id='$PERIOADA_A';")
check "T53: checklist-ul contine exact 4 cerinte" "4" "$R"
R=$($WORKER -c "SELECT count(*) FROM cerinte_documente_perioada c JOIN tipuri_document t ON t.id=c.tip_document_id WHERE c.perioada_contabila_id='$PERIOADA_A' AND t.cod='comanda';")
check "T54: documentul optional nu genereaza cerinta" "0" "$R"

R=$($WORKER -c "INSERT INTO istoric_stari (firma_id, entitate_tip, entitate_id, stare_noua, utilizator_id) VALUES ('$FIRMA_A','document','10000000-0000-0000-0000-000000000002','draft','$ANA_ID');" 2>&1 | grep -c "nu aparține firmei")
check "T55: istoric_stari nu poate indica entitatea altui tenant" "1" "$R"

# Reconcilierea rolurilor trebuie să ELIMINE privilegii injectate, nu doar
# să adauge ce lipsește.
run_as_pg_admin psql -d postgres -q -v ON_ERROR_STOP=1 -c "ALTER ROLE web_app CREATEDB REPLICATION; ALTER ROLE worker CREATEDB REPLICATION NOBYPASSRLS; ALTER ROLE app_user LOGIN INHERIT BYPASSRLS; GRANT app_admin TO web_app WITH ADMIN OPTION; GRANT app_user TO worker;" > /dev/null || { echo "EROARE: injectare roluri de test"; exit 2; }
run_as_pg_admin psql -d postgres -q -v ON_ERROR_STOP=1 -v parola_migrare="$PAROLA_MIGRARE" -v parola_web="$PAROLA_WEB" -v parola_worker="$PAROLA_WORKER" -f "$SQL_DIR/roles.sql" > /dev/null || { echo "EROARE: reconciliere roles.sql"; exit 2; }
R=$(run_as_pg_admin psql -d postgres -tA -c "SELECT count(*) FROM pg_roles WHERE (rolname='app_user' AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls) OR (rolname='app_admin' AND NOT rolcanlogin AND NOT rolinherit AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls) OR (rolname='migrare' AND rolcanlogin AND rolinherit AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls) OR (rolname='web_app' AND rolcanlogin AND rolinherit AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls) OR (rolname='worker' AND rolcanlogin AND rolinherit AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND rolbypassrls);")
check "T56: roles.sql reface profilul exact al celor 5 roluri" "5" "$R"
R=$(run_as_pg_admin psql -d postgres -tA -c "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid JOIN pg_roles g ON g.oid=m.member WHERE (r.rolname IN ('app_user','app_admin','migrare','web_app','worker') OR g.rolname IN ('app_user','app_admin','migrare','web_app','worker'));")
check "T57: raman exact cele 2 membership-uri permise" "2" "$R"

$MIGRARE -c "CREATE TABLE t_viitor_secventa (id bigint GENERATED ALWAYS AS IDENTITY);" > /dev/null 2>&1
R=$($WORKER -c "INSERT INTO t_viitor_secventa DEFAULT VALUES RETURNING id;" | num)
check "T58: app_admin poate folosi secventele tabelelor viitoare" "1" "$R"

R=$($WORKER -c "INSERT INTO intentii_upload (id,firma_id,document_id,inlocuieste_fisier_id,utilizator_id) VALUES ('30000000-0000-0000-0000-000000000020','$FIRMA_A','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000002','$ANA_ID');" 2>&1 | grep -c "fk_intentie_inlocuieste_fisier")
check "T59: intentul nu poate tinti fisierul altei firme" "1" "$R"
R=$($WORKER -c "INSERT INTO intentii_upload (id,firma_id,document_id,inlocuieste_fisier_id,utilizator_id) VALUES ('30000000-0000-0000-0000-000000000021','$FIRMA_A','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000003','$ANA_ID');" 2>&1 | grep -c "fk_intentie_inlocuieste_fisier")
check "T60: intentul nu poate tinti fisierul altui document" "1" "$R"
R=$($WORKER -c "INSERT INTO intentii_upload (id,firma_id,document_id,inlocuieste_fisier_id,utilizator_id) VALUES ('30000000-0000-0000-0000-000000000022','$FIRMA_A','10000000-0000-0000-0000-000000000001','20000000-0000-0000-0000-000000000001','$ANA_ID') RETURNING 1;" 2>&1 | grep -c "^1$")
check "T61: intentul poate tinti versiunea din acelasi document" "1" "$R"

$WORKER -c "INSERT INTO notificari (id,utilizator_id,tip,entitate_tip,entitate_id,mesaj,cheie_deduplicare) VALUES ('40000000-0000-0000-0000-000000000001','$CLIENT_ID','document_nou','document','10000000-0000-0000-0000-000000000001','Document nou','notif-test-1');" > /dev/null 2>&1
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); UPDATE notificari SET mesaj='rescris' WHERE id='40000000-0000-0000-0000-000000000001'; ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T62: app_user nu poate rescrie continutul notificarii" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); UPDATE notificari SET citita=true WHERE id='40000000-0000-0000-0000-000000000001'; ROLLBACK;" 2>&1 | grep -c "UPDATE 1")
check "T63: utilizatorul isi poate marca notificarea citita" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); UPDATE notificari SET citita=true WHERE id='40000000-0000-0000-0000-000000000001'; ROLLBACK;" 2>&1 | grep -c "UPDATE 0")
check "T64: utilizatorul nu poate marca notificarea altuia" "1" "$R"
R=$($WORKER -c "INSERT INTO notificari (utilizator_id,tip,mesaj,cheie_deduplicare) VALUES ('$ANA_ID','document_nou','Duplicat','notif-test-1');" 2>&1 | grep -c "uq_notificari_deduplicare")
check "T65: cheia notificarii previne livrarea duplicata" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); UPDATE notificari SET trimite_email=true, subiect_email='Atac' WHERE id='40000000-0000-0000-0000-000000000001'; ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T66: app_user nu poate modifica starea outbox-ului email" "1" "$R"
R=$($WORKER -c "INSERT INTO notificari (utilizator_id,tip,mesaj,trimite_email) VALUES ('$CLIENT_ID','reminder_termen','Invalid',true);" 2>&1 | grep -c "chk_notif_email_coerent")
check "T67: emailul cerut fara subiect este respins" "1" "$R"
R=$($WORKER -c "INSERT INTO notificari (utilizator_id,tip,mesaj,trimite_email,subiect_email,incercari_email) VALUES ('$CLIENT_ID','reminder_termen','Invalid',true,'Test',4);" 2>&1 | grep -c "chk_notif_incercari_email")
check "T68: outbox-ul nu poate depasi trei incercari" "1" "$R"

$WORKER -c "INSERT INTO exporturi (id,firma_id,perioada_contabila_id,solicitat_de) VALUES ('50000000-0000-0000-0000-000000000001','$FIRMA_A','$PERIOADA_A','$ANA_ID');" > /dev/null 2>&1
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); SELECT count(*) FROM exporturi WHERE id='50000000-0000-0000-0000-000000000001'; ROLLBACK;" | num)
check "T69: solicitantul isi vede exportul" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); SELECT count(*) FROM exporturi WHERE id='50000000-0000-0000-0000-000000000001'; ROLLBACK;" | num)
check "T70: alt utilizator al aceleiasi firme nu vede exportul" "0" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); UPDATE exporturi SET status='finalizat', storage_key='exports/atac.zip', expira_la=now()+interval '7 days' WHERE id='50000000-0000-0000-0000-000000000001'; ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T71: app_user nu poate falsifica finalizarea exportului" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); INSERT INTO exporturi (firma_id,perioada_contabila_id,solicitat_de) VALUES ('$FIRMA_A','$PERIOADA_A','$ANA_ID'); ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T72: app_user nu poate crea direct exporturi" "1" "$R"
R=$($WORKER -c "INSERT INTO exporturi (firma_id,perioada_contabila_id,solicitat_de,status) VALUES ('$FIRMA_A','$PERIOADA_A','$CLIENT_ID','finalizat');" 2>&1 | grep -c "chk_export_stare_coerenta")
check "T73: exportul finalizat fara obiect si expirare este respins" "1" "$R"
R=$($WORKER -c "INSERT INTO exporturi (firma_id,perioada_contabila_id,solicitat_de) VALUES ('$FIRMA_A','$PERIOADA_A','$ANA_ID');" 2>&1 | grep -c "uq_export_activ_solicitant")
check "T74: exista un singur export activ per solicitant si perioada" "1" "$R"

$WORKER -c "INSERT INTO predari_documente (id,firma_id,perioada_contabila_id,metoda,status,predat_de,numar_cutii,data_programata,creat_de) VALUES ('60000000-0000-0000-0000-000000000001','$FIRMA_A','$PERIOADA_A','curier','programata','Client Alpha',2,now() + interval '1 day','$CLIENT_ID');" > /dev/null 2>&1
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); SELECT count(*) FROM predari_documente WHERE id='60000000-0000-0000-0000-000000000001'; ROLLBACK;" | num)
check "T75: clientul vede predarea firmei sale" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$BETA_ID',true); SELECT count(*) FROM predari_documente WHERE id='60000000-0000-0000-0000-000000000001'; ROLLBACK;" | num)
check "T76: predarea este izolata de celalalt cabinet" "0" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$ANA_ID',true); UPDATE predari_documente SET status='returnata', data_returnare=now() WHERE id='60000000-0000-0000-0000-000000000001'; ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T77: app_user nu poate sari direct starea predarii" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO predari_documente (firma_id,perioada_contabila_id,metoda,predat_de,numar_cutii,data_programata) VALUES ('$FIRMA_A','$PERIOADA_A','curier','Client',1,now()); ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T78: app_user nu poate crea direct predari" "1" "$R"
R=$($WORKER -c "INSERT INTO predari_documente (firma_id,perioada_contabila_id,metoda,predat_de,numar_cutii,data_programata) VALUES ('$FIRMA_A','$PERIOADA_A','curier','Client',0,now());" 2>&1 | grep -c "chk_predare_stare_coerenta")
check "T79: predarea fizica fara cutii este respinsa" "1" "$R"
R=$($WORKER -c "INSERT INTO predari_documente (firma_id,perioada_contabila_id,metoda,status,predat_de,numar_cutii,data_programata) VALUES ('$FIRMA_A','$PERIOADA_A','posta','preluata','Client',1,now());" 2>&1 | grep -c "chk_predare_stare_coerenta")
check "T80: starea preluata fara responsabil si data este respinsa" "1" "$R"
R=$($WORKER -c "INSERT INTO predari_documente (firma_id,perioada_contabila_id,metoda,status,numar_cutii,data_receptie,digitizare_status,creat_de) VALUES ('$FIRMA_A','$PERIOADA_A','exclusiv_digital','receptionata',0,now(),'nu_este_necesara','$CLIENT_ID') RETURNING 1;" 2>&1 | grep -c "^1$")
check "T81: predarea exclusiv digitala coerenta este acceptata" "1" "$R"

R=$($WORKER -c "UPDATE fisiere_document SET stare_procesare='in_lucru', procesare_inceputa_la=NULL WHERE id='20000000-0000-0000-0000-000000000001';" 2>&1 | grep -c "chk_fisier_lease_coerenta")
check "T82: procesarea in lucru necesita inceputul lease-ului" "1" "$R"
R=$($WORKER -c "BEGIN; UPDATE fisiere_document SET stare_procesare='in_lucru', procesare_inceputa_la=now() WHERE id='20000000-0000-0000-0000-000000000001' RETURNING 1; ROLLBACK;" 2>&1 | grep -c "^1$")
check "T83: lease-ul coerent al procesarii este acceptat" "1" "$R"
R=$($WORKER -c "UPDATE fisiere_document SET stare_procesare='procesat', procesare_inceputa_la=now() WHERE id='20000000-0000-0000-0000-000000000001';" 2>&1 | grep -c "chk_fisier_lease_coerenta")
check "T84: starea finala nu poate pastra un lease activ" "1" "$R"

# ------------------------------------------------ bulk inbox lunar
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO loturi_incarcare (id,firma_id,perioada_contabila_id,creat_de,numar_fisiere_declarat,dimensiune_totala_declarata) VALUES ('70000000-0000-0000-0000-000000000001','$FIRMA_A','$PERIOADA_A','$CLIENT_ID',1,1024) RETURNING 1; COMMIT;" 2>&1 | grep -c "^1$")
check "T85: clientul poate crea un lot in firma si luna proprie" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO loturi_incarcare (firma_id,perioada_contabila_id,creat_de,numar_fisiere_declarat,dimensiune_totala_declarata) VALUES ('$FIRMA_C','$PERIOADA_C','$CLIENT_ID',1,1024); ROLLBACK;" 2>&1 | grep -c "row-level security")
check "T86: clientul nu poate crea lot in alta firma" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO fisiere_inbox (id,lot_id,firma_id,perioada_contabila_id,incarcat_de,nume_original,mime_type,dimensiune_declarata,temp_storage_key,expira_la) VALUES ('71000000-0000-0000-0000-000000000001','70000000-0000-0000-0000-000000000001','$FIRMA_A','$PERIOADA_A','$CLIENT_ID','factura.pdf','application/pdf',1024,'atac',now()) RETURNING (temp_storage_key='clients/$FIRMA_A/2026-06/_temp/70000000-0000-0000-0000-000000000001/71000000-0000-0000-0000-000000000001.part' AND status='in_asteptare' AND expira_la BETWEEN now()+interval '23 hours 59 minutes' AND now()+interval '24 hours 1 minute')::int; COMMIT;" | num)
check "T87: cheia temporara inbox si expirarea sunt generate de DB" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); UPDATE loturi_incarcare SET status='finalizat', finalizat_la=now() WHERE id='70000000-0000-0000-0000-000000000001'; ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T88: app_user nu poate falsifica finalizarea lotului" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); UPDATE fisiere_inbox SET status='disponibil',storage_key='atac',dimensiune_bytes=1,checksum=repeat('a',64),incarcat_la=now() WHERE id='71000000-0000-0000-0000-000000000001'; ROLLBACK;" 2>&1 | grep -c "permission denied")
check "T89: app_user nu poate publica direct fisierul inbox" "1" "$R"
R=$($WORKER -c "UPDATE fisiere_inbox SET status='disponibil',storage_key='clients/$FIRMA_A/2026-06/inbox/70000000-0000-0000-0000-000000000001/originals/71000000-0000-0000-0000-000000000001',mime_type='application/pdf',dimensiune_bytes=1024,checksum=repeat('a',64),incarcat_la=now() WHERE id='71000000-0000-0000-0000-000000000001' RETURNING 1;" 2>&1 | grep -c "^1$")
check "T90: serviciul privilegiat poate publica fisierul validat" "1" "$R"
R=$($PSQL -c "SELECT count(*) FROM loturi_incarcare;")
check "T91: fara identitate loturile inbox sunt invizibile" "0" "$R"
R=$($PSQL -c "SELECT count(*) FROM fisiere_inbox;")
check "T92: fara identitate fisierele inbox sunt invizibile" "0" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO fisiere_inbox (lot_id,firma_id,perioada_contabila_id,incarcat_de,nume_original,mime_type,dimensiune_declarata,temp_storage_key,expira_la) VALUES ('70000000-0000-0000-0000-000000000001','$FIRMA_A','$PERIOADA_A','$CLIENT_ID','a-doua-factura.pdf','application/pdf',1,'atac',now()); ROLLBACK;" 2>&1 | grep -c "depășește limitele declarate")
check "T93: triggerul nu permite mai multe fișiere decât declară lotul" "1" "$R"
R=$($PSQL -c "BEGIN; SELECT set_config('app.utilizator_id','$CLIENT_ID',true); INSERT INTO loturi_incarcare (firma_id,perioada_contabila_id,creat_de,numar_fisiere_declarat,dimensiune_totala_declarata) VALUES ('$FIRMA_A','$PERIOADA_A','$CLIENT_ID',501,1024); ROLLBACK;" 2>&1 | grep -c "chk_lot_numar_fisiere")
check "T94: baza impune limita maximă a lotului" "1" "$R"

echo ""
echo "=============================="
echo "TOTAL: $pass PASS, $fail FAIL"
echo "=============================="
exit $fail
