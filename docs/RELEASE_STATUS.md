# Release status — 18 iulie 2026

## Verdict curent

**Pregătit pentru staging; nepregătit încă pentru producție.** Codul, schema și
cozile locale trec verificările automate, dar producția depinde de providerii,
domeniile, backup/restore-ul și aprobările enumerate în
`RELEASE_READINESS.md`.

## Dovezi automate

- 95/95 teste Django/pytest;
- 84/84 verificări PostgreSQL/RLS pe topologia cu owner non-superuser;
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

## Porți externe

- credențiale și teste reale R2/SMTP;
- domenii, TLS, proxy și decizie HSTS;
- backup + restore demonstrat și versionarea obiectelor R2;
- monitorizare și alertare operațională;
- validarea juridică a retenției și DPA-urilor;
- plan de rollback și aprobarea ferestrei de release.
