# Walkthrough 01: the review workflow

## What it does and why

The rules label an invoice `VALID`, `INVALID` or `REQUIRES_REVIEW`. Until now
the label was the end of the story: a person had to notice it in the audit log.
The review workflow gives the labels a destination.

- An invoice labelled `REQUIRES_REVIEW` (amount above the limit) goes into a
  **review queue** automatically, and so does a likely duplicate (walkthrough 02).
- An `INVALID` invoice can be sent to the queue with a **Send to review** button
  on its result, when someone should follow it up with the supplier.
- A reviewer is **assigned**, people **comment**, and one of them **approves or
  rejects** it. A comment is required to decide.
- Every step is kept in a **history** (who, when, what, comment) that is only
  ever added to.

It does not change validation: the status still comes only from the rules.

## How it works, end to end

```
upload -> analyze_document -> record_result -> audit log
                                   |
                                   +-> REQUIRES_REVIEW or likely duplicate: ReviewStore.queue -> SQLite
POST /api/reviews (file)  -> analyse again -> ReviewStore.queue (INVALID sent by a person)
Review page -> /api/reviews/... -> ReviewStore.assign / comment / approve / reject
```

| File | Role |
|:--|:--|
| `src/storage/schema.py` | The two tables, written with SQLAlchemy Core: `reviews` (current state) and `review_events` (history). |
| `src/storage/database.py` | Builds the engine from `DATABASE_URL`, or a SQLite file (`SUPPLYTRACE_DB_PATH`, default `data/supplytrace.db`), and creates missing tables at startup. |
| `src/reviews/store.py` | `ReviewStore`: every read and every state change. The only code that writes the tables. |
| `src/storage/demo.py` | Fills an empty queue with the sample invoices so a first visit shows the workflow. |
| `src/api/server.py` | `record_result()` (audit log plus auto-queue) and the `/api/reviews` endpoints. |
| `frontend/js/review.js` | The Review page: queue, filters, one review with actions and history. |
| `frontend/js/result.js` | The "in the review queue" note and the "Send to review" button on `INVALID` results (single check and the batch drawer). |

**Data flow for an automatic review.** `POST /api/analyze` runs
`analyze_document()` (unchanged), then `record_result()` writes the audit entry
and, for `REQUIRES_REVIEW` or a likely duplicate, calls `ReviewStore.queue()`. That stores the whole
analysis (rule checklist, risk drivers) as JSON next to the review so the
detail page can show it later. The result sent back to the browser has a new
`review` field (`id`, `state`, `assignee`) that the page turns into a link.

**Why the file is uploaded again for "Send to review".** The browser could post
the result it already has, but then anyone could put made-up results in the
queue. Sending the XML again lets the server analyse it itself, which is cheap
(milliseconds).

**State and history.** A review is `open`, `approved` or `rejected`. Each action
goes through one method, `_act()`, which in a single transaction checks the
rules of the workflow, updates the review row and inserts a history row:

- the comment must not be blank (422 at the API, `ValueError` in the store);
- the review must exist (404);
- assign, approve and reject need an open review (409), so a review cannot be
  decided twice; comments are allowed at any time.

The history table has no update or delete code anywhere, so it only grows.

**One review per file.** `reviews.content_hash` (SHA-256 of the file bytes) is
unique. Checking the same file again finds the existing review instead of
adding another, and the result shows its current state.

## Design choices and trade-offs

- **SQLAlchemy Core, not the ORM.** Two tables and a handful of queries are
  clearer as explicit SQL expressions than as mapped classes. The same code
  runs on SQLite and PostgreSQL.
- **Timestamps as ISO text.** Sorts correctly and behaves the same on both
  databases, at the cost of not using native date types.
- **State on the row plus a history table.** Listing and filtering are simple
  (`WHERE state = 'open'`), while the history keeps the full story. The cost is
  that the two must change together, which the single transaction guarantees.
- **No sign-in.** The actor is a name typed on the page (remembered in the
  browser). It shows who did what but proves nothing. A real system would use
  authenticated users and would also check that only the assignee can decide.
- **The XML is not stored.** The demo promises uploads are not kept. The review
  keeps the analysis, not the file.
- **Queueing never breaks a check.** A database failure is logged and the
  result is still returned, like the audit log.

## Limits

- On Render's free tier the disk is ephemeral, so reviews and history reset on
  every redeploy or restart (the sample reviews are added again). Set
  `DATABASE_URL` to a free PostgreSQL such as Neon, and add a driver
  (`psycopg2-binary`) to `requirements.txt`, to keep them. This is optional.
- PostgreSQL support is by design (portable SQL) but is not exercised by the
  tests, which use SQLite.
- Anyone who opens the demo can act on any review; there are no permissions.
- There is no way to reopen a decided review or to unassign.

## Interview questions

**1. Why keep a separate history table instead of just updating the review?**
An update overwrites what was there. The history answers who did what and when,
and it cannot be rewritten because the code only ever inserts into it.

**2. How do you stop an invoice being approved twice?**
`_act()` loads the review inside a transaction and raises `ReviewStateError`
if it is not open, which the API turns into a 409. The check and the update
happen in the same transaction.

**3. Why upload the file again instead of sending the result back?**
The server should not trust data the client could have edited. Analysing again
costs milliseconds and guarantees the stored analysis is real.

**4. Why is `content_hash` unique?**
So the same file is queued once. The second upload finds the existing review,
which also avoids a queue full of copies when someone re-checks a file.

**5. SQLAlchemy Core or ORM, and why?**
Core. The schema is tiny, I wanted to see the SQL I was building, and Core
makes the queries plain function calls with no session or object state to
reason about.

**6. How does it run on PostgreSQL?**
`DATABASE_URL` is passed to `create_engine`. A leading `postgres://` is
rewritten to `postgresql://` because SQLAlchemy rejects the short form. The
tables use only portable types.

**7. What is not secure about it?**
There is no authentication: the name is self-declared and anyone can approve
anything. The workflow is real but the identity is not.

**8. How is it tested?**
Store tests cover the transitions (cannot approve twice, unknown id, comment
required, comments after a decision), API tests cover the status codes, and an
end-to-end test uploads a real sample, finds it in the queue, assigns and
rejects it, and checks the history and the audit log.
