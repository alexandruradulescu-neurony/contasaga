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

## Current bootstrap status — 19 July 2026

- The `main` deployment is healthy and the public login page, static assets,
  PostgreSQL readiness, and the mounted document volume all answer correctly.
- PostgreSQL is initialized with the separate `migrare`, `web_app`, and
  `worker` roles. All migrations are applied.
- At the owner's request, the complete development demo dataset was copied to
  Railway on 18 July 2026: six users, one accounting firm, two customer
  companies, their allocations and monthly checklists, audit/history records,
  document metadata, and all 20 locally available document/thumbnail objects.
  Database sessions and cache entries were intentionally not copied.
- The demo credentials are suitable only for the requested demonstration.
  Replace the demo identities and passwords before admitting real client data.
- The public service does not expose Django Admin. The privileged platform
  admin still requires a separate, network-restricted Railway service using
  `config.settings.admin_prod`.
- The maintenance/export/reminder processes are not yet deployed as Railway
  cron/worker services. Do not enable email jobs while email still uses the
  console backend, because console delivery is not real delivery.
- Phases 2–5 (AI-assisted classification, local OCR/splitting, structured
  extraction and finalized monthly archives) exist on `dev` but are not part
  of the current live release. After promotion, Railway's start command keeps
  their shared worker loop in the same service as Gunicorn so it can read the
  mounted volume. The loop makes no provider request while
  `DOCUMENT_AI_ENABLED=false`, but still performs local reading and archive
  finalization.
- Both the web service and PostgreSQL (including their volumes) currently run
  in Railway's US West region. Move both to the selected EU region before
  storing real client data; a volume region migration causes downtime.

## Temporary bootstrap configuration

Until Cloudflare R2 is configured, document objects use the Railway volume
mounted at `/data`, under `/data/documents`. Within that root, objects use
`clients/<client UUID>/<YYYY-MM>/documents/` and monthly `thumbnails/`
directories. This supports a single web replica but is not the final
production storage design. Invitation and password-reset email uses the
console backend until real SMTP credentials are configured.

The production build includes the monthly bulk inbox. The same monthly root
also has `_temp/<batch UUID>/` for expiring uploads and
`inbox/<batch UUID>/originals/` for validated immutable originals. Phase 3
adds `inbox/<batch UUID>/previews/<file UUID>/` for page previews.
After the Phase 5 release, month closure also creates
`archive/vNNNN/primite|emise|fara-directie/<document-type>/` and writes the
verified commit manifest to `archive/vNNNN/.system/manifest.csv`. Temporary
archive copies remain under `.system/staging/archive-vNNNN/` and are cleaned
after success or failure.

Railpack reads `railpack.json` and installs `tesseract-ocr`,
`tesseract-ocr-eng` and `tesseract-ocr-ron` in the runtime image. Keep:

```text
DOCUMENT_OCR_ENABLED=true
DOCUMENT_OCR_COMMAND=tesseract
DOCUMENT_OCR_LANGUAGES=ron+eng
DOCUMENT_OCR_TIMEOUT_SECONDS=60
```

For the first Phases 2–5 release, keep external AI explicitly disabled:

```text
DOCUMENT_AI_ENABLED=false
DOCUMENT_AI_PROVIDER=openai
DOCUMENT_AI_MODEL=gpt-5.6-luna
```

After the provider and DPA checks pass, add `OPENAI_API_KEY` and change only
`DOCUMENT_AI_ENABLED=true`. For a DeepSeek-compatible endpoint use
`DOCUMENT_AI_PROVIDER=deepseek`, set `DOCUMENT_AI_MODEL`, optionally set
`DOCUMENT_AI_BASE_URL`, and add `DEEPSEEK_API_KEY`. Never expose either key to
browser code or store it in Git.

The same-service worker is acceptable only while Railway uses one web replica
and local volume storage. R2/S3-compatible shared storage and a separate,
monitored worker are required before multiple replicas or parallel OCR workers.

Before accepting real client data, replace both temporary choices:

1. Select the production data region and move both services and their volumes
   together. Re-run readiness and an upload/download smoke test afterwards.
2. Configure R2 and set `DOCUMENT_STORAGE_BACKEND=r2` plus all `R2_*`
   variables. Validate upload, download, CORS, retention, and object backup.
3. Configure a real SMTP backend and a deliverable `DJANGO_DEFAULT_FROM_EMAIL`.
   Validate invitation, reset-password, notification, and retry flows.
4. Add the final custom domain, update `DJANGO_ALLOWED_HOSTS` and
   `DJANGO_CSRF_TRUSTED_ORIGINS`, then decide the final HSTS policy.
5. Replace the copied demo accounts and companies with agreed production
   identities, legal company data, and individually delivered passwords. Do
   not run `seed_local_demo` directly in production.
6. Deploy the frequent, daily, deadline-reminder, and export worker processes
   after R2 and SMTP pass their smoke tests.
7. Run and document a PostgreSQL restore test, configure monitoring/alerts,
   and complete the legal retention/DPA review from `RELEASE_READINESS.md`.
