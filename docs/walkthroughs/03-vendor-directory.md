# Walkthrough 03: the vendor directory

## What it does and why

An invoice is a symptom; the supplier is often the cause. If one vendor sends
most of the invalid files, or keeps resubmitting the same bill, that is worth
knowing and acting on. The vendor directory turns the invoices SupplyTrace has
already analysed into a list of suppliers with the numbers that matter.

For each vendor it shows: invoice count, how many were valid, needed review or
were invalid, total and average amount, duplicates flagged, average risk score,
and when it was last seen. A vendor page lists its invoices (filter by status or
duplicates only, each linking to its review) and lets people keep **notes** and a
**trusted** flag.

The trusted flag is a note for people. It is stored, shown (in the directory, on
the vendor page and next to the supplier on every result), and written to the
audit log, but nothing in validation reads it: the rules, the risk score and the
duplicate check give the same answer for a trusted and an untrusted vendor.

## How it works, end to end

```
analysed invoice -> InvoiceStore.record (vendor_key, amount, status, risk...) -> invoices table
GET /api/vendors -> VendorStore: GROUP BY vendor_key -> statistics (+ profile rows)
PUT /api/vendors/{id} -> VendorStore.update -> vendor_profiles row -> audit log entry
result for any invoice -> VendorStore.summary -> result.vendor {id, name, trusted}
```

| File | Role |
|:--|:--|
| `src/invoices/fields.py` | `vendor_key()`: the supplier ID, or the name lower-cased with spaces collapsed. |
| `src/storage/schema.py` | `vendor_profiles` (notes, trusted, who and when); vendors themselves have no table. |
| `src/vendors/store.py` | `VendorStore`: statistics, the invoices list, `update()`. |
| `src/api/server.py` | `/api/vendors` endpoints, `find_vendor()` on every result, and the audit entry for edits. |
| `src/storage/demo.py` | Records the 400 startup invoices as demo data so the directory has several vendors on a fresh visit. |
| `frontend/js/vendors.js` | The Vendors page. |
| `frontend/js/result.js`, `audit.js` | The supplier line on results; the "Vendor update" rows in the audit log. |

**Vendors are derived, not entered.** A vendor is whatever `vendor_key` the
invoices carry. The statistics are one `GROUP BY` query over the `invoices`
table, so they can never drift from the data. Only the human additions (notes,
trusted) are stored, in `vendor_profiles`, created on the first edit.

**Vendor ids.** The key is free text (it can contain spaces or slashes), so the
URL uses a 12-character hash of it (`vendor_id()`).

**Amounts per currency.** Adding dollars to euros means nothing, so totals and
averages are computed per currency. The headline is the currency with the most
invoices, with a "+N" marker and a tooltip for the others.

**The audit log.** An edit appends an entry with `event: "vendor_update"`,
`origin: "vendor"`, the actor and a sentence such as "Marked as a trusted vendor
by Ravi". The audit page shows these as "Vendor update" rows (filter: Vendor
edits). The dashboard ignores them because they are not checked files. Saving
without a real change writes nothing.

## Design choices and trade-offs

- **Compute, don't maintain.** No counters to keep in step with invoices. The
  cost is a grouped query on every list, fine at this scale; with millions of
  rows I would add a summary table updated on insert.
- **Trusted is separate from validation by construction.** The flag lives in its
  own table and is read only by the vendor code and the display. A test checks
  that a trusted vendor's invoice gets an identical result.
- **Latest name wins.** The vendor is shown under the name on its newest invoice.
- **Notes and the flag are saved together** with the name of whoever saved them.
  There is no sign-in, so the name is self-declared (as in the review queue).

## Limits

- Vendors are recognised by the supplier text as written. "Acme Corp" and
  "Acme Corporation" are two vendors, and an invoice with a supplier ID and one
  with only a name are different vendors. Invoices with neither are not
  attributed to anyone.
- Statistics cover recorded invoices only: checks made through the page, the
  starter samples and the startup batch (as demo data). Every check counts,
  including repeats of the same file.
- On Render's free tier the disk is ephemeral, so notes and trusted flags reset
  on every redeploy unless `DATABASE_URL` points at a free PostgreSQL such as
  Neon (optional).
- Notes are plain text, shown as text (never as HTML), up to 2,000 characters.

## Interview questions

**1. Why is there no vendors table?**
A vendor is defined by the invoices, so the list and its numbers are a `GROUP BY`
over them. A separate table would need to be kept in sync and could disagree.
Only what people add (notes, trusted) is stored.

**2. How do you guarantee "trusted" doesn't change validation?**
The validator and the risk model never receive it; it lives in its own table and
is only joined for display. A test runs the same invalid file before and after
trusting the vendor and compares status, errors, checks, features and score.

**3. Why compute totals per currency?**
Adding amounts in different currencies is meaningless. Grouping by currency keeps
every number true, at the cost of a "+N" marker in the table.

**4. How is a vendor identified, and what goes wrong?**
By the supplier ID if present, otherwise the normalised name. Spelling variants
split a supplier in two, which I list as a limit; fuzzy matching or a supplier
master list would fix it.

**5. Why a hash in the URL instead of the name?**
The key is free text, so it needs escaping and may contain slashes. A short hash
is URL-safe and stable.

**6. What does the audit log record for an edit, and why?**
Who changed what and when, because trusting a vendor is a decision that affects
how people treat invoices later. The entry is written only when something really
changed.

**7. How would it scale?**
Add an index on `vendor_key` (already there) and, if needed, a summary table or
materialised view refreshed on insert, since the grouped query reads every
invoice row.

**8. How is it tested?**
Store tests cover the statistics on crafted invoices (statuses, totals, averages,
duplicates, currencies, search and sort); API tests cover 404 and 422 cases, the
audit entry, and an end-to-end run from uploads to the vendor numbers and the
vendor's invoice list with its review links.
