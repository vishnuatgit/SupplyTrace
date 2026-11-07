# SupplyTrace architecture

## Overview

SupplyTrace checks supplier XML invoices. It parses each file safely, finds the transaction ID and the amount, applies deterministic validation rules, points every rule at a line of the file, adds an experimental risk score with an explanation of what drove it, and appends one line per file to an audit log that also feeds the dashboard. The rules decide the status; the risk score is advisory.

Every user and system flow, with diagrams and error paths, is in [process-flows.md](process-flows.md).

## One request

```text
Browser (frontend/)
  -> FastAPI                    src/api/server.py       upload limits, endpoints, security headers
  -> analyze_document()         src/api/analysis.py     the single-file pipeline, timed per stage
       XMLLoader                src/ingestion/xml_loader.py   defusedxml parse, flatten to dotted paths
       XMLParser                src/ingestion/parser.py       find ID and AMOUNT (and the key each came from)
       Validator.checklist      src/validation/rules.py       every rule: passed / broken / skipped -> status
       FeatureExtractor         src/features/extractor.py     eight risk signals
       RiskPredictor            src/prediction/model.py       Random Forest risk score and its explanation
       index_elements           src/ingestion/locator.py      line numbers, so every rule points at a line
  -> audit log                  src/utils/audit.py      JSON Lines, rotated at about 1 MB
  -> database                   src/storage/, src/invoices/, src/reviews/, src/vendors/   fingerprints, review queue, vendor notes
```

`POST /api/analyze`, `POST /api/analyze/batch` and `POST /api/analyze/batch/stream` all call `analyze_document()`, so a file gets the same result on its own, in a batch or in a streamed batch (tests compare them).

## Components

1. **Ingestion** (`src/ingestion/`). `XMLLoader` parses with `defusedxml` (no DTDs, so no entity expansion or external entities) and rejects documents nested more than 100 levels deep. A malformed document raises `XMLLoadError` with the parser's line, column and reason. It flattens the tree into dotted keys such as `Invoice.LegalMonetaryTotal.PayableAmount`, with namespaces removed per element. `XMLParser` maps the transaction ID and the amount from known tag names; a bare `ID` only counts within three levels of the root, so a nested bank-account ID is never taken for the transaction ID. `locator.py` makes a second, lightweight pass with Python's `expat` parser to record the line of every element, because ElementTree does not keep line numbers.
2. **Validation** (`src/validation/rules.py`). Five rules, each described once as a `Rule` (code, message, plain-language summary, a tiny example) and used by the validator, the API and the rules page. `Validator.checklist()` decides every rule's state (a rule that cannot be reached is skipped), and `Validator.check()` derives the status from it: a missing ID, a missing amount, a non-numeric amount or a negative amount makes a file `INVALID`; an amount above 1,000,000 makes it `REQUIRES_REVIEW`.
3. **Findings and checks** (`src/api/analysis.py`). Each broken rule is pointed at a line: the element holding the bad value, an element meant for the field that is present but empty, or the element the field was expected in (`LegalMonetaryTotal` or `Invoice`). The checklist adds the evidence for passed rules (where the ID and amount were found) and the reason a rule was skipped.
4. **Features** (`src/features/extractor.py`). Problems with the required fields, amount size, missing optional fields (issue date, currency, supplier, payment account) and nesting depth.
5. **Prediction** (`src/prediction/`). An experimental `RandomForestClassifier`, trained at startup on the synthetic batch (`src/pipeline/synthetic.py`, fixed seed). `RiskPredictor.explain()` splits each score into the base rate plus one contribution per feature by following every tree's decision path. `model_card.py` computes the model card: feature importances and a holdout evaluation against a rules-only baseline, all from the pipeline's own results.
6. **Batch pipeline** (`src/pipeline/`). Generates the synthetic invoices, runs them through the same components, and writes `results.csv`, `powerbi_summary.csv` and audit entries. The server runs it on startup when results are missing.
7. **Dashboard** (`src/dashboard/`). `overview.py` turns the audit log into the dashboard's numbers (totals, status split, risk histogram, top reasons, recent entries); `exporter.py` writes the one-row summary CSV for BI tools.
8. **Storage and the features on it** (`src/storage/`, `src/invoices/`, `src/reviews/`, `src/vendors/`). A small SQL database (SQLite by default, PostgreSQL through `DATABASE_URL`, tables written with SQLAlchemy Core). Every accepted check is recorded with a SHA-256 fingerprint and its key fields for duplicate detection; invoices above the review limit and likely duplicates go to the review queue (with an append-only history); vendors are computed from the recorded invoices and carry notes and a trusted flag. See the [walkthroughs](walkthroughs/) and [roadmap.md](roadmap.md).
9. **Frontend** (`frontend/`). Static HTML, CSS and JavaScript modules, no build step: a hash router over seven views (check, batch, review, vendors, audit log, rules and model, about), dark and light themes, and hand-drawn SVG charts. It is served by the same app with a strict Content-Security-Policy.

## Data on disk

| File | Written by | Read by |
|:--|:--|:--|
| `data/raw_xml/*.xml`, `outcomes.csv` | synthetic data generator | batch pipeline |
| `results/results.csv` | batch pipeline | model training, model card, `/api/history` |
| `results/powerbi_summary.csv` | batch pipeline | `/api/stats` |
| `results/audit_log.jsonl` | every check, vendor edits, and the batch pipeline | `/api/audit`, `/api/overview` |
| `data/supplytrace.db` (SQLite, unless `DATABASE_URL` is set) | every check (fingerprints), the review workflow, vendor notes | `/api/reviews`, `/api/vendors`, duplicate detection |

Uploaded files are parsed in memory and never written to disk. The database keeps the fingerprint and key fields of each file (and the analysis of queued ones), not the XML.
