# Railway deployment

## Branch policy

- `main` is the only production deployment branch.
- `dev` is the development branch and is never connected to the live service.
- A production release is made by testing `dev`, merging it into `main`, and
  pushing `main`.

## Production project

- Railway project: `authentic-abundance`
- Environment: `production`
- Web service: `contasaga`, sourced from GitHub branch `main`
- Database service: `Postgres`, reachable by the web service over Railway's
  private network
- Railway domain: `https://contasaga-production.up.railway.app`

`railway.json` is the deployment source of truth for static collection,
migrations, the Gunicorn command, the readiness healthcheck, and restart
policy. Migrations run with the dedicated `migrare` database owner before a
new deployment is started.

## Current bootstrap status — 18 July 2026

- The `main` deployment is healthy and the public login page, static assets,
  PostgreSQL readiness, and the mounted document volume all answer correctly.
- PostgreSQL is initialized with the separate `migrare`, `web_app`, and
  `worker` roles. All migrations are applied and the operational queues are
  empty.
- No production tenant, user, or demo data has been seeded. This is
  intentional: production identities and company details must not be guessed
  from the local demo database.
- The public service does not expose Django Admin. The privileged platform
  admin still requires a separate, network-restricted Railway service using
  `config.settings.admin_prod`.
- The maintenance/export/reminder processes are not yet deployed as Railway
  cron/worker services. Do not enable them while email still uses the console
  backend, because console delivery is not real delivery.
- Both the web service and PostgreSQL (including their volumes) currently run
  in Railway's US West region. Move both to the selected EU region before
  storing real client data; a volume region migration causes downtime.

## Temporary bootstrap configuration

Until Cloudflare R2 is configured, document objects use the Railway volume
mounted at `/data`, under `/data/documents`. This supports a single web replica
but is not the final production storage design. Invitation and password-reset
email uses the console backend until real SMTP credentials are configured.

Before accepting real client data, replace both temporary choices:

1. Select the production data region and move both services and their volumes
   together. Re-run readiness and an upload/download smoke test afterwards.
2. Configure R2 and set `DOCUMENT_STORAGE_BACKEND=r2` plus all `R2_*`
   variables. Validate upload, download, CORS, retention, and object backup.
3. Configure a real SMTP backend and a deliverable `DJANGO_DEFAULT_FROM_EMAIL`.
   Validate invitation, reset-password, notification, and retry flows.
4. Add the final custom domain, update `DJANGO_ALLOWED_HOSTS` and
   `DJANGO_CSRF_TRUSTED_ORIGINS`, then decide the final HSTS policy.
5. Create the initial accounting-firm administrator and real tenant only after
   their legal identity, CUI, administrator email, and initial-password
   handoff have been agreed. Do not run `seed_local_demo` in production.
6. Deploy the frequent, daily, deadline-reminder, and export worker processes
   after R2 and SMTP pass their smoke tests.
7. Run and document a PostgreSQL restore test, configure monitoring/alerts,
   and complete the legal retention/DPA review from `RELEASE_READINESS.md`.
