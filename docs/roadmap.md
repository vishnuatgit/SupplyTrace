# Roadmap: what gets built next, and what does not

SupplyTrace checks one invoice at a time and logs the result. The next step is
to make it useful to the people who handle what the checks find. Nine ideas
were on the wishlist. Three are built, and six are not, for the reasons
below.

## Decision: build these three (done)

1. **Review workflow.** A queue for invoices that need a person: assign a
   reviewer, comment, approve or reject (with a required comment), and keep a
   full append-only history per invoice. See
   [walkthrough 01](walkthroughs/01-review-workflow.md).
2. **Duplicate detection.** Record a fingerprint and the key fields of every
   analysed invoice and flag exact and likely duplicates, with a link to the
   earlier invoice and the reason.
3. **Vendor directory.** Vendors derived from analysed invoices, with
   per-vendor statistics, notes and a "trusted" flag that never changes a
   validation result.

They were built in this order because each one uses the one before: duplicates
send invoices to the review queue, and the vendor directory counts duplicates.
All three keep their state in a small database (SQLite by default, PostgreSQL
through `DATABASE_URL`).

## Decision: not building these

| Wishlist item | Decision | Why |
|:--|:--|:--|
| Batch processing | Already exists | `POST /api/analyze/batch` and the streamed `/api/analyze/batch/stream` check up to 20 files, and the Batch page shows progress as each file finishes. |
| Background processing with Celery and Redis | Not building | A file is analysed in a few milliseconds, so there is nothing to push into the background. It would also need a Redis server and a worker process, and a worker is not available on a free hosting plan. A queue would add moving parts and failure modes without making anything faster. |
| OCR (scanned or photographed invoices) | Not building | It is a different product: reading text out of images, then extracting fields from it. Accuracy on the free tier (Tesseract-class OCR) is poor on real invoices, and a wrong number silently read as right is worse than a clear "not an XML file". SupplyTrace is about structured data that can be checked exactly. |
| Version history of invoices | Deferred | It needs a decision on what a "version" is (a re-upload with the same ID? an edited file?) and on storing the XML, which the demo deliberately never does. Duplicate detection covers the most useful part, finding the earlier copy. Revisit if invoice storage is ever added. |
| Reviewer assignment and comments | Part of feature 1 | They are the review workflow, not a separate feature. |
| PostgreSQL | Optional | Supported by setting `DATABASE_URL`, but not required: the demo runs on SQLite with no new service. |

## Hosting note

The live demo runs on Render's free tier, whose disk is ephemeral: it is wiped
on every redeploy and restart. The SQLite file is lost with it, so review
history, fingerprints and vendor notes start again from the sample data. To
keep them, set `DATABASE_URL` to a free PostgreSQL (for example Neon) and add a
PostgreSQL driver such as `psycopg2-binary` to `requirements.txt`. Neither is
required for the demo to work.
