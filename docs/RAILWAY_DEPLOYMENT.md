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

## Temporary bootstrap configuration

Until Cloudflare R2 is configured, document objects use the Railway volume
mounted at `/data`, under `/data/documents`. This supports a single web replica
but is not the final production storage design. Invitation and password-reset
email uses the console backend until real SMTP credentials are configured.

Before accepting real client data, replace both temporary choices:

1. Configure R2 and set `DOCUMENT_STORAGE_BACKEND=r2` plus all `R2_*`
   variables. Validate upload, download, CORS, retention, and object backup.
2. Configure a real SMTP backend and a deliverable `DJANGO_DEFAULT_FROM_EMAIL`.
   Validate invitation, reset-password, notification, and retry flows.
3. Add the final custom domain, update `DJANGO_ALLOWED_HOSTS` and
   `DJANGO_CSRF_TRUSTED_ORIGINS`, then decide the final HSTS policy.
4. Run and document a PostgreSQL restore test, configure monitoring/alerts,
   and complete the legal retention/DPA review from `RELEASE_READINESS.md`.
