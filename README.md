# Conta Saga

Aplicație Django pentru colaborarea dintre firmele de contabilitate și firmele cliente.

Producția este livrată în Railway exclusiv din ramura `main`; dezvoltarea
curentă rămâne pe `dev`. Configurația și pașii operaționali sunt documentați în
[`docs/RAILWAY_DEPLOYMENT.md`](docs/RAILWAY_DEPLOYMENT.md).

Specificația reconciliată cu implementarea se află în
[`specsv5/SPECS.md`](specsv5/SPECS.md). Identificatorii istorici `cabinet_*`
rămân intenționat în baza de date și în cod; interfața și documentația pentru
utilizatori folosesc „firmă de contabilitate”.

## Dezvoltare locală pe macOS

Proiectul folosește direct **Postgres.app**; Docker nu este necesar.

1. Pornește Postgres.app și verifică portul `5432`.
2. Instalează mediul Python: `uv sync`.
3. Provisioning local, o singură dată:
   `psql -d postgres -v parola_migrare=conta-local-migrare -v parola_web=conta-local-web -v parola_worker=conta-local-worker -f specsv5/roles.sql`
4. Creează baza: `createdb -O migrare conta_saga`.
5. Rulează migrările cu owner-ul dedicat:
   `uv run python manage.py migrate --settings=config.settings.migration`.
6. Pornește aplicația web: `uv run python manage.py runserver`.

Opțional, creează date locale demonstrative (firmă de contabilitate,
administrator și firmă clientă):
`uv run python manage.py seed_local_demo --settings=config.settings.admin --admin-password '<parola-locală>'`.

Admin-ul platformei rulează separat, pe alt port:
`uv run python manage.py runserver 127.0.0.1:8001 --settings=config.settings.admin`.

Aplicația principală folosește `web_app` și RLS. Aliasul `privileged` folosește
`worker` numai în servicii explicite. Django Admin-ul platformei pornește separat cu
`--settings=config.settings.admin` și nu este montat în aplicația principală.
Autentificarea are limitare partajată în PostgreSQL; schimbarea parolei este
disponibilă utilizatorilor autentificați, iar resetarea publică nu dezvăluie
dacă o adresă de email există.

## Stocarea documentelor

În dezvoltarea locală, `DOCUMENT_STORAGE_BACKEND=local` salvează obiectele în
`.local-storage/`. Documentele și thumbnail-urile sunt grupate în
`clients/<client UUID>/<YYYY-MM>/`, separat pentru fiecare firmă client și lună
contabilă. Fluxul folosește intenții semnate, upload `PUT`, finalizare unică și
aceeași validare ca backend-ul cloud; nu necesită Docker, Redis sau un cont
cloud.

Pagina lunii oferă și un inbox pentru încărcare în masă. Un lot poate conține
până la 500 de fișiere PDF/JPG/PNG/HEIC, maximum 25 MB fiecare și 2 GB în total.
Încărcările incomplete stau cel mult 24 de ore în
`_temp/<lot UUID>/`, iar originalele validate sunt mutate în
`inbox/<lot UUID>/originals/` și păstrează în baza de date numele inițial,
uploaderul, dimensiunea și checksum-ul. În această primă fază fișierele rămân
necategorizate; clasificarea contabilului și arhiva lunară cu nume lizibile sunt
fazele următoare descrise în
[`docs/BULK_INBOX_AND_MONTH_ARCHIVE.md`](docs/BULK_INBOX_AND_MONTH_ARCHIVE.md).

Pentru Cloudflare R2 setează `DOCUMENT_STORAGE_BACKEND=r2` și variabilele
`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`.
Bucket-ul trebuie să permită din originile aplicației metoda `PUT` și header-ul
`Content-Type`; exemplul este în `config/r2-cors.example.json`.

Fișierele sunt limitate la 25 MB și PDF-urile la 300 de pagini. Pipeline-ul
calculează SHA-256 și thumbnail-ul și validează efectiv PDF/JPG/PNG/HEIC.
Înlocuirile păstrează istoricul complet: versiunea veche rămâne activă până
când cea nouă este validată. Deschiderea și descărcarea folosesc adrese semnate
cu expirare scurtă (cinci minute implicit), atât local, cât și în R2.
Reprocesarea fișierelor eșuate poate fi pornită cu
`uv run python manage.py process_document_files`, iar intențiile expirate se
curăță cu `uv run python manage.py cleanup_upload_intents`. Obiectele temporare
ale inboxului se curăță cu `uv run python manage.py cleanup_inbox_uploads`.
Workerul recuperează
automat procesările întrerupte după expirarea lease-ului de 15 minute. În
storage-ul local, directoarele și fișierele sunt create cu acces exclusiv
pentru utilizatorul macOS care rulează aplicația.

Contabilii au acces la `/verificare/`, unde pot filtra documentele după firmă,
stare și perioadă, pot prelua documentul și pot crea un partener direct în
ecranul de verificare înaintea acceptării. Coada este paginată la 50 de
documente, păstrând filtrele între pagini.

## Notificări și email local

Centrul `/notificari/` afișează activitatea utilizatorului și numărul de
notificări necitite. Evenimentele sunt livrate numai după commit și sunt
deduplicate. În dezvoltare, emailurile se afișează în terminalul serverului
prin backend-ul console Django; nu este necesar un serviciu extern. Pentru un
backend SMTP setează `DJANGO_EMAIL_BACKEND` și `DJANGO_DEFAULT_FROM_EMAIL`.

Emailurile au stare persistentă și maximum trei încercări. Retrimiterea manuală
se poate rula cu `uv run python manage.py retry_notification_emails`.
Reminderul de termen verifică zilnic perioadele la T-3 și T și trimite email
administratorilor și operatorilor clientului numai dacă există cerințe `lipsa`:
`uv run python manage.py send_deadline_reminders`. Comanda este idempotentă și
reîncearcă mai întâi emailurile rămase în outbox.

Pe macOS, exemplul
`config/com.contasaga.deadline-reminders.plist.example` poate fi copiat în
`~/Library/LaunchAgents/com.contasaga.deadline-reminders.plist`. În copie,
înlocuiește `__PROJECT_DIR__` cu calea absolută a proiectului, creează folderul
`.local-logs`, apoi activează jobul:

```bash
mkdir -p .local-logs
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.contasaga.deadline-reminders.plist
```

Fișierul este doar un exemplu; proiectul nu instalează și nu activează automat
niciun serviciu persistent pe Mac.

## Exportul ZIP al perioadei

Un contabil poate solicita exportul din pagina unei perioade închise. Workerul
citește coada din PostgreSQL și construiește o arhivă deterministă, cu fișierele
grupate în `categorie/tip-document/` și un `manifest.csv`. Sursa fiecărui fișier
este verificată din nou prin checksum înainte de includere. Arhiva este păstrată
în același backend local/R2 și poate fi descărcată timp de 7 zile printr-o adresă
semnată scurt.

O rulare unică a cozii:

```bash
uv run python manage.py process_exports
```

În dezvoltarea locală, workerul continuu pornește cu
`uv run python manage.py process_exports --watch`. Exemplul opțional pentru
macOS este `config/com.contasaga.export-worker.plist.example`; la fel ca
reminderul, necesită înlocuirea `__PROJECT_DIR__` înainte de copierea în
`~/Library/LaunchAgents/`. Exporturile trecute de termen se curăță cu
`uv run python manage.py cleanup_expired_exports`.

## Predări fizice

În dosarul lunar, clienții și contabilii pot înregistra predarea documentelor
prin curier, poștă, ridicare de către contabil, predare la sediu sau exclusiv
digital. Pentru un transport fizic sunt obligatorii persoana care predă,
data programată și cel puțin o cutie. Contabilul marchează succesiv preluarea,
recepția și returnarea; tranzițiile nu pot fi sărite. Varianta exclusiv digitală
este recepționată imediat și nu intră în circuitul fizic.

Toate modificările logistice trec prin serviciul privilegiat și sunt auditate;
rolul web are numai acces de citire la tabela logistică.

## Operații periodice fără Docker

Comanda `run_scheduled_maintenance frequent` reîncearcă procesarea fișierelor,
emailurile din outbox și exporturile. Comanda `run_scheduled_maintenance daily`
curăță intențiile de upload, obiectele temporare ale inboxului și exporturile
expirate. Exemplele launchd sunt:

- `config/com.contasaga.frequent-maintenance.plist.example` — la 5 minute;
- `config/com.contasaga.daily-maintenance.plist.example` — zilnic;
- `config/com.contasaga.deadline-reminders.plist.example` — reminder T-3/T;
- `config/com.contasaga.export-worker.plist.example` — worker ZIP continuu.

Fișierele sunt exemple: înlocuiește `__PROJECT_DIR__`, creează `.local-logs/`
și copiază numai joburile dorite în `~/Library/LaunchAgents/`.

## Release readiness

Verificarea tehnică, fără modificări de date, rulează astfel:

```bash
uv run python manage.py release_readiness
uv run python manage.py release_readiness --strict --settings=config.settings.prod
```

Comanda verifică setările de deployment, rolurile PostgreSQL, migrările,
storage-ul și cozile operaționale. Producția folosește
`config.settings.prod`, iar Admin-ul separat `config.settings.admin_prod`.
Procedura completă și porțile externe sunt în
[`docs/RELEASE_READINESS.md`](docs/RELEASE_READINESS.md), iar verdictul curent
este în [`docs/RELEASE_STATUS.md`](docs/RELEASE_STATUS.md).
