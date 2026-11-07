# Walkthrough 02: duplicate detection

## What it does and why

Paying the same supplier invoice twice is one of the most common and most
expensive accounts-payable mistakes. The rules check one file at a time, so they
cannot see that a file has been seen before. Duplicate detection remembers every
invoice that was analysed and compares each new one with them.

- **Exact duplicate:** the same file content (same SHA-256 hash) was checked
  before. It is flagged, with a link to the first one.
- **Likely duplicate:** a different file that is probably the same invoice:
  - same supplier and the same invoice (transaction) ID, or
  - same supplier and the same amount, issued within 7 days of each other (only
    when both invoices have an issue date).
- A **likely** duplicate is sent to the review queue (even if it passes every
  rule), so a person decides. An exact duplicate is only flagged: it is the
  same file again, usually an accidental re-upload.

The flag never changes the validation status. It is shown in single and batch
results, on the review page and in the audit log.

## How it works, end to end

```
upload -> analyze_document (adds key_fields) -> record_result
            -> InvoiceStore.record: compare with earlier rows, insert this one with its flag
            -> audit log entry (duplicate_kind, duplicate_of)
            -> likely duplicate (or REQUIRES_REVIEW): ReviewStore.queue
            -> result.duplicate / result.review back to the page
```

| File | Role |
|:--|:--|
| `src/invoices/fields.py` | `key_fields()`: supplier ID and name, issue date, currency and amount from the parsed invoice, and `vendor_key()`, the normalised supplier. |
| `src/invoices/store.py` | `InvoiceStore.record()`: finds the earliest earlier match, stores the invoice with the flag, returns the flag. `flag_for()` looks up a file's first flag. |
| `src/storage/schema.py` | The `invoices` table: hash, key fields, status, origin, and the duplicate columns. |
| `src/api/analysis.py` | Adds `key_fields` to every analysis result. |
| `src/api/server.py` | `record_result()` runs the steps above for single, batch and streamed checks. |
| `frontend/js/result.js` | `duplicateNote()`, the box under the verdict (also used on the review page). |
| `src/api/samples/duplicate_id.xml` | The sample that shows a likely duplicate on a fresh demo. |

**Fingerprint.** `content_hash()` is the SHA-256 of the exact uploaded bytes. Two
files are an exact duplicate only if every byte matches; a re-saved file with
different spacing is not, but usually still matches a likely rule.

**Key fields.** The standardized record keys are the document paths in capitals
(`...ACCOUNTINGSUPPLIERPARTY.PARTY.PARTYNAME.NAME`). The supplier name is the
`NAME` under a supplier party; the supplier ID is an `ID` under one. The vendor
key is the ID if there is one, otherwise the name lower-cased with spaces
collapsed, so "Acme  Corp" and "acme corp" are the same supplier.

**Matching order.** Exact first, then same supplier and ID, then same supplier,
amount and date window. Always the earliest match. Two refinements keep the
flags honest:

- a likely match must be an **original**: an invoice that was itself flagged is
  not compared with later ones, so a chain of copies all point at the first;
- invoices recorded as **demo data** are never exact matches (checking a starter
  sample for the first time is not a duplicate), but do count for likely
  matches. That is how the "Likely duplicate" sample shows the feature.

**Audit log.** Each entry gets `duplicate_kind` and `duplicate_of`. The audit page
shows a tag, and the "Find it in the audit log" link opens the log searching for
the earlier file (`#/audit?q=...`).

## Design choices and trade-offs

- **Record every check, not just the first.** Each check is a row, so the
  history of when a file was seen is complete and per-vendor counts (feature 3)
  include repeats. The cost is a larger table; the comparison uses indexed
  columns (`content_hash`, `vendor_key`).
- **Compare and insert in one transaction,** so two simultaneous uploads of the
  same file cannot both think they are the first.
- **Likely duplicates go to a human, exact ones do not.** Likely is a guess and
  a person should confirm it; exact is a certainty and only needs a visible flag.
- **A fixed 7-day window and cent-level amount equality** are simple and
  explainable. A real system would let the business choose them.
- **No supplier, no likely match.** Without a supplier, matching on ID or amount
  alone would flag unrelated invoices. Such invoices can still be exact duplicates.

## Limits

- Matching is on the supplier text as written: "Acme Corp" and "Acme Corporation"
  are different vendors, and an invoice with a supplier ID never matches one with
  only a name.
- The XML is not stored, so only the key fields and the hash can be compared.
- Detection starts from when the database starts. On Render's free tier the disk
  is ephemeral, so recorded invoices (and flags) reset on every redeploy unless
  `DATABASE_URL` points at a free PostgreSQL such as Neon (optional).
- The startup batch of 400 synthetic invoices is not recorded, only checks made
  through the web page and the starter samples.

## Interview questions

**1. What is the difference between exact and likely duplicates?**
Exact means the same bytes, proven by the SHA-256 hash. Likely is a heuristic on
the key fields (supplier plus ID, or supplier plus amount within a date window),
so a person has to confirm it.

**2. Why hash the file instead of comparing contents?**
A fixed-size fingerprint can be indexed and compared in one query, and the XML
does not have to be stored.

**3. Why do likely duplicates go to review but exact ones do not?**
A guess needs a decision; a certainty only needs a flag. Queueing every re-upload
would also fill the queue with accidental repeats.

**4. How do you avoid a false alarm on the demo's sample invoices?**
Starter samples are recorded with origin `demo`, which is excluded from exact
matching, and a likely match must be an unflagged original. Checking a sample the
first time is therefore clean, and the second time is a real exact duplicate.

**5. What could go wrong with matching on supplier name?**
Spelling variants split one supplier into two (missed duplicates), and a shared
generic name can merge two (false alarms). Using a supplier ID when present
reduces both.

**6. Why one transaction for compare and insert?**
Without it two uploads of the same file at once could both find nothing earlier
and both be recorded as first.

**7. How would you scale it?**
The lookups use indexed columns, so they stay fast with many rows. For fuzzy
matching on names I would add a normalised-name column or a similarity index
(for example trigram search in PostgreSQL).

**8. How is it tested?**
Unit tests build crafted invoices for each rule and the cases that must not match
(other supplier, outside the window, no dates, no supplier), and API tests run a
real upload through to the review queue, the audit log and a rejection.
