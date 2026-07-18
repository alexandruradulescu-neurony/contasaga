# Bulk inbox and finalized monthly archive

## Implementation status — 18 July 2026

Phase 1 is implemented and validated on the `dev` branch. It has not yet been
merged into `main` or deployed to production. Phases 2–6 below remain the
approved delivery plan; they are not represented as finished functionality.

## Product decision

A bulk upload is not an accounting document. It is an immutable source file
received for one customer and one accounting month. The file becomes an
accounting document only after classification or splitting.

Every batch belongs to exactly one customer and one accounting period. The
database remains authoritative while a month is open. Closing the month will
also materialize a human-readable filesystem archive grouped by document type.

## Storage lifecycle

```text
/data/documents/clients/<client UUID>/<YYYY-MM>/
├── _temp/<batch UUID>/<inbox file UUID>.part
├── inbox/<batch UUID>/originals/<inbox file UUID>
├── documents/<document or upload UUID>
├── thumbnails/<file UUID>.png
└── (final category folders and manifest after month closure)
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

### Phase 2 — manual accountant classification

- add an accountant queue across assigned customers;
- classify one or many inbox files by document type, financial account and
  direction;
- promote classified inbox items to the existing document workflow;
- preserve the inbox source link and audit every decision;
- block monthly closure while actionable inbox items remain unresolved.

### Phase 3 — reading and AI-assisted classification

- extract embedded PDF text and OCR scans/images;
- generate page previews and searchable text;
- suggest a constrained document type and checklist destination;
- record confidence, model/prompt version and evidence;
- require accountant confirmation until measured accuracy supports a stricter
  automation policy.

This phase classifies documents but does not extract accounting fields.

### Phase 4 — document boundary detection

- detect PDFs containing multiple documents;
- suggest page ranges, splits and merges;
- retain the immutable source upload;
- create derived accounting-document files with their own checksums and lineage.

### Phase 5 — structured extraction

- extract supplier/customer, tax IDs, invoice numbers, dates, currency,
  amounts and VAT;
- validate totals and business rules;
- require an accountant review before exporting or posting data.

### Phase 6 — finalized monthly filesystem archive

Closing a month will require every inbox item to be classified, explicitly
ignored or cancelled. A finalization job will then:

1. calculate deterministic category folders and collision-safe filenames;
2. copy all final files to a staging archive and verify SHA-256 checksums;
3. generate `manifest.csv` with original and final names, categories and IDs;
4. atomically publish the archive and close the period only after validation;
5. keep technical artifacts under a hidden `.system` directory;
6. regenerate a new archive version after an audited reopening and reclosure.

Initial filenames will use
`<sequence>__<sanitized original name>__<short ID>.<extension>`. Once structured
extraction exists, richer names may include date, partner and document number.

## Infrastructure boundary

The Railway volume supports Phase 1 with one application service. Before OCR
or AI workers are scaled independently, the source objects must move to shared
R2/S3-compatible storage so web and worker processes can access the same
immutable originals.
