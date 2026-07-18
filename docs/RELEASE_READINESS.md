# Release readiness — Conta Saga

Acesta este runbook-ul de release pentru implementarea descrisă de SPECS R5.
Nu presupune Docker. Dezvoltarea locală folosește Postgres.app, iar mediul de
producție poate folosi PostgreSQL și R2 administrate.

## 1. Configurare obligatorie

Aplicația publică folosește `config.settings.prod`; Admin-ul platformei,
izolat de rețea și accesibil numai superuserului, folosește
`config.settings.admin_prod`.

În secret manager sau în mediul procesului trebuie definite cel puțin:

- `DJANGO_SECRET_KEY` — valoare aleatoare, unică și de minimum 50 caractere;
- `DJANGO_ALLOWED_HOSTS` și `DJANGO_CSRF_TRUSTED_ORIGINS`;
- credențialele PostgreSQL pentru `web_app`, `worker` și `migrare`;
- `DOCUMENT_STORAGE_BACKEND=r2` și toate variabilele `R2_*`;
- un `DJANGO_EMAIL_BACKEND` real și configurația lui;
- pentru SMTP: `DJANGO_EMAIL_HOST`, port, TLS/SSL, credențiale și o adresă
  `DJANGO_DEFAULT_FROM_EMAIL` livrabilă;
- decizia HSTS: durată, subdomenii și preload;
- `DJANGO_TRUST_X_FORWARDED_PROTO=true` numai în spatele unui proxy TLS de
  încredere.
- dacă proxy-ul este folosit, `DJANGO_CLIENT_IP_HEADER=HTTP_X_FORWARDED_FOR`
  numai după ce proxy-ul este configurat să suprascrie headerul primit de la
  client; valoarea este folosită pentru audit și limitarea autentificării.

## 2. Ordinea release-ului

1. Rulează backup-ul bazei și confirmă versionarea/retention policy pe bucket.
2. Rulează migrările exclusiv cu rolul `migrare`:
   `uv run python manage.py migrate --settings=config.settings.migration`.
3. Construiește fișierele statice:
   `uv run python manage.py collectstatic --noinput --settings=config.settings.prod`.
4. Rulează verificarea strictă:
   `uv run python manage.py release_readiness --strict --settings=config.settings.prod`.
5. Pornește aplicația publică prin WSGI:
   `uv run gunicorn config.wsgi:application --bind 127.0.0.1:8000`.
6. Pornește separat Admin-ul cu `DJANGO_SETTINGS_MODULE=config.settings.admin_prod`
   și un bind/hostname inaccesibil public.
7. Pornește joburile periodice și workerul de export.
8. Verifică `/health/live/` și `/health/ready/`; numai readiness `200` permite
   introducerea instanței în trafic.

## 3. Criterii automate de PASS

`release_readiness --strict` trebuie să confirme:

- zero erori și zero avertismente Django deployment;
- `default` este un rol PostgreSQL non-superuser fără `BYPASSRLS`;
- `privileged` este non-superuser și are `BYPASSRLS`;
- nicio migrare neaplicată;
- storage accesibil;
- cozile operaționale inspectabile și fără elemente netriate; orice element
  pending/retry sau eșuat produce avertisment și blochează modul `--strict`.

Fișierele inbox disponibile pentru clasificare, erorile istorice și loturile
încă deschise sunt raportate separat ca volum de business și nu blochează un
release. Numai obiectele temporare ajunse la expirare fără cleanup sunt o
problemă operațională.

În CI/staging se rulează suplimentar:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run python manage.py makemigrations --check --dry-run
bash specsv5/test_rls.sh
```

Suita SQL reconstruiește baza ei de test și reconciliază rolurile tehnice;
se rulează numai într-un cluster de test/staging controlat.

## 4. Backup și restore

Providerul PostgreSQL trebuie să ofere backup zilnic și PITR. Înaintea
release-ului se produce și un dump logic criptat/transportat în storage-ul
operațional, de exemplu cu `pg_dump --format=custom --no-owner --no-acl`.

Trimestrial, restore-ul se verifică într-o bază izolată cu `pg_restore`, apoi
se rulează migrările, `release_readiness` și un smoke test al autentificării,
RLS, uploadului și descărcării. Fișierele din R2 au backup separat prin
versionare și retention policy; dump-ul PostgreSQL nu conține obiectele R2.

## 5. Porți externe — nu pot fi validate de repository

Release-ul de producție rămâne blocat până există dovezi pentru:

- validarea juridică a matricei de retenție și DPA-urilor;
- alegerea regiunii UE și contractele providerilor;
- testul real de backup/restore și valorile RPO/RTO;
- domeniile finale, certificatul TLS și decizia HSTS preload/subdomenii;
- credențiale R2/SMTP reale și teste de livrare;
- monitorizare centralizată, alerte și responsabil de incident;
- aprobarea ferestrei de release și a planului de rollback.
