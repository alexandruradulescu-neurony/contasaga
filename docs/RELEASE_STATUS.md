# Release status — 19 iulie 2026

## Verdict curent

**Bootstrap-ul Railway este online; nepregătit încă pentru date reale de
producție.** Codul, schema și cozile trec verificările automate, iar serviciul
public răspunde prin HTTPS. Producția rămâne blocată de regiunea de date,
providerii de storage/email, joburile operaționale, domeniul final,
backup/restore și aprobările enumerate în `RELEASE_READINESS.md`.

## Dovezi automate

- 137/137 teste Django/pytest pe ramura `dev`;
- 124/124 verificări PostgreSQL/RLS pe topologia cu owner non-superuser;
- `ruff check` și `ruff format --check` fără erori;
- nicio migrare model lipsă și nicio migrare neaplicată;
- rolurile locale sunt corecte: `web_app` fără BYPASSRLS, `worker` cu
  BYPASSRLS, niciunul superuser;
- cache-ul PostgreSQL partajat este instalat și accesibil rolului web;
- health live/readiness răspund 200;
- configurația completată de producție trece `check --deploy`;
- configurația Gunicorn și build-ul WhiteNoise/collectstatic sunt valide;
- login throttling verificat: răspuns 429 la atingerea limitei.
- instalarea tuturor migrărilor într-o bază PostgreSQL goală este validă;
- `pip-audit` nu găsește vulnerabilități cunoscute, iar Bandit nu raportează
  probleme în codul aplicației;
- smoke test-urile autentificate pentru toate rolurile și ambele interfețe
  răspund corect.

## Stare Railway

- proiect `authentic-abundance`, mediu `production`;
- serviciul public `contasaga` urmărește exclusiv ramura GitHub `main`;
- `https://contasaga-production.up.railway.app` răspunde corect pentru login,
  static assets, live health și readiness;
- readiness confirmă baza PostgreSQL, storage-ul montat, rolurile tehnice,
  migrările, cache-ul partajat și cozi operaționale goale;
- documentele persistă pe volumul montat la `/data`, sub
  `/data/documents/clients/<client UUID>/<YYYY-MM>/`, iar configurația de
  producție nu conține valori `localhost`, `127.0.0.1` sau `.test`;
- verificarea strictă rămâne blocată intenționat de storage-ul local și
  backend-ul de email console;
- web-ul și PostgreSQL rulează momentan în US West; regiunea trebuie decisă și
  mutată în UE înaintea datelor reale;
- la cererea proprietarului, setul demo local a fost copiat integral în
  Railway: 6 utilizatori, o firmă de contabilitate, 2 firme client, alocări,
  checklisturi, istoric/audit și toate cele 20 de obiecte locale disponibile;
- sesiunile și cache-ul local nu au fost copiate, iar parolele demo trebuie
  schimbate înaintea folosirii cu date reale;
- cronurile, workerul și Admin-ul privilegiat separat nu sunt încă pornite.
- clasificarea/extragerea AI este dezactivată și nu există nicio cheie de
  provider în Railway; release-ul live curent nu conține încă implementările
  Phase 2–5 de pe `dev`.

Auditul complet din 18 iulie a întărit autorizarea operațiilor privilegiate,
izolarea destinatarilor notificărilor, concurența upload/procesare, recuperarea
workerelor prin lease, permisiunile storage-ului local, auditul configurațiilor
și paginarea cozii de verificare. Nu au rămas defecte de cod cunoscute care să
blocheze staging-ul.

## Stare locală

Cele trei documente QA care aveau obiecte locale absente au fost retrase logic,
cu audit păstrat. Toate cozile operaționale raportate de readiness sunt acum
zero; avertismentele rămase în dezvoltare sunt exclusiv setările HTTP locale
intenționat nesecurizate, nu blocaje de date.

Faza 1 a inboxului lunar pentru încărcare în masă este implementată și testată
pe `dev`: loturi de maximum 500 de fișiere, upload concurent cu retry, staging
în `_temp`, verificare de tip/checksum, publicare în `inbox`, audit, RLS și
curățare zilnică. Testele sintetice de browser au fost șterse după validare, iar
cozile locale au rămas curate. Schimbarea este în `main` și rulează pe instanța
Railway live; migrarea `documente.0007_bulk_inbox`, noile tabele și endpointurile
publice de health au fost verificate după deployment.

Faza 2 este implementată și validată pe `dev`: coadă globală pentru contabili,
clasificare manuală disponibilă indiferent de AI, adaptoare OpenAI și
DeepSeek-compatible, rezultate structurate cu încredere/dovezi, lease și retry,
confirmare/corectare/ignorare obligatoriu umană, audit și legătura dintre
originalul inbox și documentul creat. Migrarea este
`documente.0008_inbox_ai_analysis`. Funcția rămâne sigur dezactivată până la
configurarea cheii și aprobarea porților AI din runbook; nu a fost încă
promovată în `main` sau pe Railway.

Faza 3 este implementată și validată local pe `dev`: text PDF per pagină, OCR
Tesseract `ron+eng` pentru scanuri și imagini, preview-uri private, căutare în
textul citit, sugestii conservative de limite, formular de separare cu
acoperire completă obligatorie și derivări cu interval/checksum/actor. Migrarea
este `documente.0009_ocr_and_document_boundaries`. Testul end-to-end local a
citit un PDF de trei pagini, a propus corect intervalele 1–2 și 3–3 și a randat
coada și ecranul de separare; datele sintetice au fost apoi eliminate. Faza 3
nu este încă promovată în `main` sau Railway.

Faza 4 este implementată și validată local pe `dev`: extracție structurată
pentru părți/CUI, serie, număr, date, monedă și valori net/TVA/total,
normalizare și avertismente pentru reguli de business, fingerprint al tuturor
fișierelor sursă și precompletarea formularului. Acceptarea rămâne exclusiv o
decizie a contabilului și salvează sugestiile, valorile finale, corecția,
actorul și momentul. După epuizarea retry-urilor se continuă manual. Migrarea
este `documente.0010_structured_extraction_and_monthly_archive`; faza nu face
apeluri externe și nu creează joburi de extracție cât timp
`DOCUMENT_AI_ENABLED=false`.

Faza 5 este implementată și validată local pe `dev`: închiderea introduce
starea blocată `inchidere_in_curs`, apoi workerul construiește o arhivă
versionată și lizibilă pe disc, pe direcție și tip de document. Copiile de
staging și finale sunt reverificate SHA-256, iar manifestul CSV este publicat
ultimul. Perioada și documentele se închid/arhivează numai după commitul
validat; lease-ul recuperează workerii întrerupți, iar trei eșecuri readuc luna
auditat în `in_lucru`. Migrările sunt `perioade.0002_month_closure_state` și
`documente.0010_structured_extraction_and_monthly_archive`. Un smoke test real
pe storage local a verificat arhiva, manifestul și rollback-ul datelor
sintetice. Faza nu este încă promovată în `main` sau Railway.

## Porți externe

- credențiale și teste reale R2/SMTP;
- domenii, TLS, proxy și decizie HSTS;
- backup + restore demonstrat și versionarea obiectelor R2;
- monitorizare și alertare operațională;
- validarea juridică a retenției și DPA-urilor;
- plan de rollback și aprobarea ferestrei de release.
