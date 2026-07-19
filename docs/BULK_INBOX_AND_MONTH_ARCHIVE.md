# Bulk inbox and finalized monthly archive

## Implementation status — 19 July 2026

Phase 1 is implemented, validated, merged into `main` and deployed to Railway
production. Phases 2–5 are implemented and validated on `dev`; they have not
yet been merged into `main` or deployed. External AI remains disabled until a
provider key and the release gates are configured. Local OCR and the monthly
archive do not require an AI key.

## Product decision

A bulk upload is not an accounting document. It is an immutable source file
received for one customer and one accounting month. The file becomes an
accounting document only after classification or splitting.

Every batch belongs to exactly one customer and one accounting period. The
database remains authoritative while a month is open. Closing the month
materializes a human-readable filesystem archive grouped by document type.

## Storage lifecycle

```text
/data/documents/clients/<client UUID>/<YYYY-MM>/
├── _temp/<batch UUID>/<inbox file UUID>.part
├── inbox/<batch UUID>/originals/<inbox file UUID>
├── inbox/<batch UUID>/previews/<inbox file UUID>/<page>.png
├── documents/<document or upload UUID>
├── thumbnails/<file UUID>.png
├── .system/staging/archive-v0001/...
└── archive/v0001/
    ├── primite/<document type>/...
    ├── emise/<document type>/...
    ├── fara-directie/<document type>/...
    └── .system/manifest.csv
```

`_temp` contains only incomplete, expiring uploads. A validated upload is
copied to `inbox`, verified by SHA-256, recorded in the database, and then
removed from `_temp`. Inbox originals are immutable and retain their original
filename and uploader in the database.

## Delivery phases

### Phase 1 — bulk intake foundation

- create one batch for one customer and month;
- upload up to 500 PDF/JPG/PNG/HEIC files independently;
- limit each file to 25 MB and a batch to 2 GB;
- upload three files concurrently, with one automatic retry;
- isolate incomplete objects in `_temp` for 24 hours;
- validate extension, declared type and magic bytes before accepting a file;
- preserve checksum, original name, size, uploader, batch and timestamps;
- expose the monthly inbox and batch history to authorized users;
- let authorized users download each validated immutable original;
- clean expired temporary objects through scheduled maintenance.

Phase 1 does not create placeholder accounting documents and does not infer a
document category.

**Status:** implemented. The browser flow has been exercised with a multi-file
batch, including successful publication and rejection of a file whose extension
does not match its content. The PostgreSQL isolation suite includes the batch
and inbox tables.

### Phase 2 — AI-assisted accountant classification

- add an accountant queue across assigned customers;
- analyse each immutable inbox file through a provider-neutral adapter;
- suggest only configured document types, financial accounts and direction;
- show confidence, summary and short evidence beside the original;
- allow the accountant to classify immediately even if AI is disabled, slow
  or fails;
- promote classified inbox items to the existing document workflow;
- preserve provider/model/prompt version, immutable source lineage and every
  human confirmation, correction or ignore decision;
- block monthly closure while actionable inbox items remain unresolved.

The OpenAI adapter sends PDFs as file inputs and images as image inputs. The
DeepSeek-compatible adapter receives locally extracted text page by page,
including OCR for scans and images.
Provider output never creates or posts an accounting document by itself. The
accountant's explicit action is always authoritative.

**Status:** implemented and tested on `dev`. `DOCUMENT_AI_ENABLED=false` is the
safe default, so no external request occurs before configuration. The manual
queue works in that state. Enabling requires a provider key, data-processing
approval and a representative acceptance dataset.

### Phase 3 — OCR and document boundary detection

- extract embedded PDF text and OCR scans/images;
- generate page previews and searchable text;
- detect PDFs containing multiple documents;
- suggest page ranges, splits and merges;
- retain the immutable source upload;
- create derived accounting-document files with their own checksums and lineage.

**Status:** implemented and tested on `dev`. PDFs use embedded text per page
when it is usable and Tesseract `ron+eng` otherwise; images use Tesseract.
Heuristic or AI boundaries are suggestions only. The accountant must confirm a
complete, contiguous, non-overlapping set of page ranges. `pagini_fisiere_inbox`
stores page text and preview metadata; `derivari_fisiere_inbox` records source,
derived document, page interval, method and both SHA-256 checksums.

### Phase 4 — structured extraction

- extract supplier/customer, tax IDs, invoice numbers, dates, currency,
  amounts and VAT;
- validate totals and business rules;
- require an accountant review before exporting or posting data.

**Status:** implemented and tested on `dev`. The provider returns constrained
structured fields for both the whole source and detected segments. Values are
normalized locally (ISO dates, currency and decimal amounts), invalid values
are discarded, and total/date/customer-CUI inconsistencies are shown as
warnings. The current document version is fingerprinted from all active source
files. The acceptance form is prefilled only with suggestions; the accountant
must confirm or correct them, and the system stores the provider/model/prompt,
source versions, final values, reviewer and review time. After three provider
failures, the accountant can complete the document manually. No extraction job
or external request is created while `DOCUMENT_AI_ENABLED=false`.

### Phase 5 — finalized monthly filesystem archive

Closing a month requires every inbox item to be classified, explicitly ignored
or cancelled. The action moves the period to the locked
`inchidere_in_curs` state and a finalization job then:

1. calculate deterministic category folders and collision-safe filenames;
2. copy all final files to a staging archive and verify SHA-256 checksums;
3. generate `manifest.csv` with original and final names, categories and IDs;
4. write the final manifest as a commit marker and close the period only after
   validation;
5. keep technical artifacts under a hidden `.system` directory;
6. regenerate a new archive version after an audited reopening and reclosure.

**Status:** implemented and tested on `dev`. The archive is versioned and
stored under `archive/vNNNN`. Files are grouped under
`primite|emise|fara-directie/<document-type>/`. Names use a stable sequence,
document date, partner and series/number when available, or the sanitized
original stem as fallback, plus a short file UUID to prevent collisions. A
UTF-8 CSV manifest records source and archive checksums and lineage; values that
could become spreadsheet formulas are escaped. The final manifest is written
last as the publication marker. The period becomes `inchisa` and documents
become `arhivat` only after every copy and checksum has passed. Interrupted jobs
are recovered by lease, retry at most three times, and return the period to
`in_lucru` with history/audit if finalization cannot complete.

The current validation baseline is **137 Django/pytest tests** and **124
PostgreSQL/RLS checks**. Migration `documente.0010` installs structured
extraction and archive tables; `perioade.0002` installs the background-closing
state.

## Infrastructure boundary

The Railway configuration can run the reading/analysis/archive worker beside
Gunicorn in the same service, so both processes see the mounted `/data` volume.
`railpack.json` installs Tesseract plus Romanian and English language data in
the runtime image. This is intentionally a single-replica bridge. Before
parallel workers or horizontal scaling, source objects must move to shared
R2/S3-compatible storage and the worker loop must become a separately
monitored worker.
