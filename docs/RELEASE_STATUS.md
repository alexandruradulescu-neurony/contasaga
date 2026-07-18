# Release status — 18 iulie 2026

## Verdict curent

**Bootstrap-ul Railway este online; nepregătit încă pentru date reale de
producție.** Codul, schema și cozile trec verificările automate, iar serviciul
public răspunde prin HTTPS. Producția rămâne blocată de regiunea de date,
providerii de storage/email, joburile operaționale, domeniul final,
backup/restore și aprobările enumerate în `RELEASE_READINESS.md`.

## Dovezi automate

- 107/107 teste Django/pytest pe ramura `dev`;
- 94/94 verificări PostgreSQL/RLS pe topologia cu owner non-superuser;
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

## Porți externe

- credențiale și teste reale R2/SMTP;
- domenii, TLS, proxy și decizie HSTS;
- backup + restore demonstrat și versionarea obiectelor R2;
- monitorizare și alertare operațională;
- validarea juridică a retenției și DPA-urilor;
- plan de rollback și aprobarea ferestrei de release.
