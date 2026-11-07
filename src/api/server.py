import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

import pandas as pd
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints
from starlette.concurrency import run_in_threadpool

from src.api.analysis import (
    REJECTED,
    AnalysisError,
    analyze_document,
    check_upload,
    rejected_result,
    too_large_detail,
)
from src.api.upload_limit import UploadSizeLimitMiddleware
from src.dashboard.overview import build_overview
from src.ingestion.parser import AMOUNT_TAGS, ID_TAGS, MAX_GENERIC_ID_DEPTH
from src.invoices.store import InvoiceStore
from src.pipeline.bootstrap import ensure_demo_results
from src.prediction.model import RiskPredictor
from src.prediction.model_card import build_model_card
from src.reviews.store import (
    ANONYMOUS,
    QUEUEABLE,
    ReviewNotFound,
    ReviewStateError,
    ReviewStore,
)
from src.storage.database import DEFAULT_DB_PATH, create_database
from src.storage.demo import seed_demo_data
from src.utils.audit import DEFAULT_MAX_BYTES, append_audit_entries, read_audit_entries
from src.validation.rules import REVIEW_THRESHOLD, RULES, Status
from src.vendors.store import SORTS, VendorNotFound, VendorStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Settings, from environment variables. Relative paths are resolved against
# the working directory.
RESULTS_DIR = os.environ.get("SUPPLYTRACE_RESULTS_DIR", "results")
DATA_DIR = os.environ.get("SUPPLYTRACE_DATA_DIR", os.path.join("data", "raw_xml"))
AUDIT_DIR = os.environ.get("SUPPLYTRACE_AUDIT_DIR", RESULTS_DIR)
AUDIT_MAX_BYTES = int(os.environ.get("SUPPLYTRACE_AUDIT_MAX_BYTES", DEFAULT_MAX_BYTES))
MAX_UPLOAD_BYTES = int(os.environ.get("SUPPLYTRACE_MAX_UPLOAD_BYTES", 1_000_000))
# Generate the synthetic dataset on startup when batch results are missing.
BOOTSTRAP_DEMO_DATA = os.environ.get("SUPPLYTRACE_BOOTSTRAP", "1") != "0"
# Review history lives in SQLite at DB_PATH unless DATABASE_URL names another
# database (for example a free PostgreSQL on Neon).
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.environ.get("SUPPLYTRACE_DB_PATH", DEFAULT_DB_PATH)

# A batch check takes up to this many files, each up to MAX_UPLOAD_BYTES.
MAX_BATCH_FILES = 20

TOO_LARGE_DETAIL = too_large_detail(MAX_UPLOAD_BYTES)
BATCH_TOO_LARGE_DETAIL = (
    f"Batch is too large. The demo accepts up to {MAX_BATCH_FILES} XML files "
    f"of up to {MAX_UPLOAD_BYTES / 1_000_000:g} MB each."
)
TOO_MANY_FILES_DETAIL = f"Too many files. A batch can hold up to {MAX_BATCH_FILES} files."
# Room for the multipart headers around the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")
SAMPLES = [
    {
        "id": "valid",
        "label": "Valid invoice",
        "file": "valid_invoice.xml",
        "description": "Complete, and passes every rule",
        "expected": "VALID",
    },
    {
        "id": "sparse",
        "label": "Sparse invoice",
        "file": "sparse_invoice.xml",
        "description": "Passes, but leaves out date, currency, supplier and bank details",
        "expected": "VALID",
    },
    {
        "id": "missing-id",
        "label": "Missing ID",
        "file": "missing_id.xml",
        "description": "No transaction ID anywhere in the file",
        "expected": "INVALID",
    },
    {
        "id": "missing-amount",
        "label": "Missing amount",
        "file": "missing_amount.xml",
        "description": "No amount to pay",
        "expected": "INVALID",
    },
    {
        "id": "bad-amount",
        "label": "Bad amount",
        "file": "bad_amount.xml",
        "description": "Amount written as 12,50.00",
        "expected": "INVALID",
    },
    {
        "id": "negative-amount",
        "label": "Negative amount",
        "file": "negative_amount.xml",
        "description": "Amount to pay below zero",
        "expected": "INVALID",
    },
    {
        "id": "high-value",
        "label": "High value",
        "file": "high_value.xml",
        "description": "4,750,000.00, above the review limit",
        "expected": "REQUIRES_REVIEW",
    },
    {
        "id": "duplicate-id",
        "label": "Likely duplicate",
        "file": "duplicate_id.xml",
        "description": "Passes every rule, but has the valid invoice's supplier and transaction ID",
        "expected": "VALID",
        # Not recorded at startup, so the first visitor to check it sees the duplicate flag.
        "starter": False,
    },
]

# Statuses and origins an audit entry can have (rejected files are not logged).
AuditStatus = Literal["VALID", "INVALID", "REQUIRES_REVIEW"]
AuditOrigin = Literal["web", "web-batch", "pipeline", "vendor"]
MAX_AUDIT_PAGE = 500

TAGS = [
    {"name": "analysis", "description": "Check XML invoices: one file, or a batch of up to 20."},
    {"name": "dashboard", "description": "Totals and history for the web dashboard."},
    {"name": "audit", "description": "The JSON Lines audit log: one entry per checked file."},
    {
        "name": "vendors",
        "description": "Suppliers seen in analysed invoices, with statistics and notes.",
    },
    {
        "name": "reviews",
        "description": "The review queue: assign, comment, approve or reject, with full history.",
    },
    {"name": "reference", "description": "The validation rules and the risk model card."},
    {"name": "samples", "description": "Synthetic sample invoices for the demo."},
    {"name": "health", "description": "Liveness check for the hosting platform."},
]

# Error bodies, for the generated API docs.
ERROR_RESPONSES = {
    400: {
        "description": (
            "Not an .xml file, empty, malformed XML (with line and column), a DTD, or too deep"
        )
    },
    413: {"description": "The upload is over the size limit"},
}


def results_csv_path() -> str:
    return os.path.join(RESULTS_DIR, "results.csv")


def audit_log_path() -> str:
    return os.path.join(AUDIT_DIR, "audit_log.jsonl")


def train_from_results(predictor: RiskPredictor, csv_path: str) -> pd.DataFrame | None:
    """Train the model on startup if historical data exists. Returns that data."""
    if not os.path.exists(csv_path):
        logger.warning(f"No historical data at {csv_path}. Model will return N/A for risk.")
        return None
    try:
        logger.info(f"Training ML model from {csv_path}...")
        results = pd.read_csv(csv_path)
        predictor.fit(results)
        return results
    except Exception as e:
        logger.error(f"Failed to train model on startup: {e}")
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.predictor = RiskPredictor()
    engine = create_database(DATABASE_URL, DB_PATH)
    app.state.reviews = ReviewStore(engine)
    app.state.invoices = InvoiceStore(engine)
    app.state.vendors = VendorStore(engine)
    if BOOTSTRAP_DEMO_DATA:
        ensure_demo_results(DATA_DIR, results_csv_path(), audit_log_path())
    results = train_from_results(app.state.predictor, results_csv_path())
    if BOOTSTRAP_DEMO_DATA:
        seed_demo_data(
            app.state.reviews,
            app.state.invoices,
            SAMPLES,
            SAMPLES_DIR,
            app.state.predictor,
            (DATA_DIR, results_csv_path()),
        )
    app.state.model_card = build_model_card(app.state.predictor, results)
    yield
    engine.dispose()


app = FastAPI(
    title="SupplyTrace API",
    description=(
        "Checks supplier XML invoices with deterministic rules (VALID, INVALID or "
        "REQUIRES_REVIEW), points each rule at a line of the file, and adds an "
        "experimental risk score. Demo on synthetic data: please don't upload real invoices."
    ),
    openapi_tags=TAGS,
    lifespan=lifespan,
)


# The frontend is served by this app (same origin), so no CORS headers are needed.
@app.exception_handler(RequestValidationError)
async def upload_validation_handler(request: Request, exc: RequestValidationError):
    """No usable file in an upload (missing, or sent without a filename): the app's own message, still a 422."""
    upload_fields = {("body", "file"), ("body", "files")}
    if request.url.path.startswith(("/api/analyze", "/api/reviews")) and any(
        tuple(err.get("loc", ()))[:2] in upload_fields for err in exc.errors()
    ):
        return JSONResponse(
            {
                "detail": "Attach an XML file with a filename: the 'file' field for one invoice, 'files' for a batch."
            },
            status_code=422,
        )
    return await request_validation_exception_handler(request, exc)


app.add_middleware(
    UploadSizeLimitMiddleware,
    max_bytes=MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES,
    paths=("/api/analyze", "/api/reviews"),
    detail=TOO_LARGE_DETAIL,
)
app.add_middleware(
    UploadSizeLimitMiddleware,
    max_bytes=MAX_BATCH_FILES * MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES,
    paths=("/api/analyze/batch", "/api/analyze/batch/stream"),
    detail=BATCH_TOO_LARGE_DETAIL,
)


@app.post("/api/analyze", tags=["analysis"], responses=ERROR_RESPONSES)
async def analyze_xml(request: Request, file: UploadFile = File(...)):
    """
    Checks one XML invoice. Returns the status, the reasons, every rule with the
    line that shows it (`checks`), where the ID and amount were found, the
    features, the experimental risk score with what drove it, server timings, and
    whether (`logged`) and when (`logged_at`) it was written to the audit log.
    A malformed file gets a 400 whose body also has `line`, `column` and `reason`.
    """
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        check_upload(file.filename, content, MAX_UPLOAD_BYTES)
        # Parsing and scoring are CPU work: run them off the event loop.
        result = await run_in_threadpool(
            analyze_document, file.filename, content, request.app.state.predictor
        )
    except AnalysisError as e:
        return JSONResponse(e.to_json(), status_code=e.status_code)

    # Write to the audit log and queue it for review if needed (best effort: never fails the request)
    return await run_in_threadpool(record_result, result, content, "web", request.app.state)


async def read_batch(files: list[UploadFile]) -> list[tuple[str | None, bytes]]:
    """Reads every upload of a batch (each capped just over the size limit)."""
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=TOO_MANY_FILES_DETAIL)
    return [(upload.filename, await upload.read(MAX_UPLOAD_BYTES + 1)) for upload in files]


async def check_batch_file(filename: str | None, content: bytes, state) -> dict:
    """One batch file through the single-file pipeline; a file that can't be read is REJECTED."""
    try:
        check_upload(filename, content, MAX_UPLOAD_BYTES)
        result = await run_in_threadpool(analyze_document, filename, content, state.predictor)
    except AnalysisError as e:
        return rejected_result(filename, e)
    return await run_in_threadpool(record_result, result, content, "web-batch", state)


def summarize(results: list[dict]) -> dict:
    statuses = [s.value for s in Status] + [REJECTED]
    return {status: sum(r["status"] == status for r in results) for status in statuses}


@app.post("/api/analyze/batch", tags=["analysis"])
async def analyze_batch(request: Request, files: list[UploadFile] = File(...)):
    """
    Checks up to 20 files with the same pipeline as /api/analyze.
    A file that cannot be read gets status REJECTED instead of failing the batch.
    """
    uploads = await read_batch(files)
    state = request.app.state
    results = [await check_batch_file(name, content, state) for name, content in uploads]
    return {"count": len(results), "summary": summarize(results), "results": results}


@app.post(
    "/api/analyze/batch/stream",
    tags=["analysis"],
    response_class=StreamingResponse,
    responses={200: {"content": {"application/x-ndjson": {}}}},
)
async def analyze_batch_stream(request: Request, files: list[UploadFile] = File(...)):
    """
    The same batch check, reported as it runs: newline-delimited JSON with a
    `start` line (`count`), one `result` line per file (`index`, `result`) as soon
    as that file is checked, and a final `summary` line, so the page can show
    real progress.
    """
    uploads = await read_batch(files)
    state = request.app.state

    async def lines():
        yield json.dumps({"type": "start", "count": len(uploads)}) + "\n"
        results = []
        for index, (name, content) in enumerate(uploads):
            result = await check_batch_file(name, content, state)
            results.append(result)
            yield json.dumps({"type": "result", "index": index, "result": result}) + "\n"
        summary = {"type": "summary", "count": len(results), "summary": summarize(results)}
        yield json.dumps(summary) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


def content_hash(content: bytes) -> str:
    """The file's fingerprint: SHA-256 of its exact bytes."""
    return hashlib.sha256(content).hexdigest()


def record_result(result: dict, content: bytes, origin: str, state) -> dict:
    """
    What happens to every accepted file after it is analysed: it is written to the
    audit log, and a REQUIRES_REVIEW file is put in the review queue. `review` on
    the result says where it is in the queue (None when it is not queued).
    """
    result["fingerprint"] = content_hash(content)
    result["duplicate"] = record_invoice(state.invoices, result, result["fingerprint"], origin)
    log_result(result, origin)
    result["vendor"] = find_vendor(state.vendors, result)

    # Why a person should look at it (if at all): the rules, or a likely duplicate.
    reasons = []
    if result["status"] == "REQUIRES_REVIEW":
        reasons.append("Rules: " + "; ".join(result["errors"] or ["amount above the review limit"]))
    duplicate = result["duplicate"]
    if duplicate and duplicate["kind"] == "likely":
        reasons.append(
            f"Likely duplicate of invoice #{duplicate['of']['id']}: {duplicate['reason']}"
        )
    if reasons:
        result["review"] = queue_for_review(state.reviews, result, content, "; ".join(reasons))
    else:
        # Not queued, but show where it is if someone already sent this file.
        result["review"] = find_review(state.reviews, content)
    return result


def find_vendor(store: VendorStore, result: dict):
    """The vendor the invoice belongs to ({id, name, trusted}), or None. Display only."""
    try:
        return store.summary(result["key_fields"]["vendor_key"])
    except Exception as e:
        logger.error(f"Could not look up the vendor: {e}")
        return None


def record_invoice(store: InvoiceStore, result: dict, fingerprint: str, origin: str):
    """
    Records the invoice for duplicate detection (best effort, like the audit log) and
    returns its duplicate flag, or None when it is not a duplicate or the database failed.
    """
    try:
        return store.record(result, fingerprint, origin)
    except Exception as e:
        logger.error(f"Could not record {result['filename']}: {e}")
        return None


def find_review(store: ReviewStore, content: bytes):
    """The id, state and assignee of this file's review, or None (also None if the lookup fails)."""
    try:
        review = store.find(content_hash(content))
    except Exception as e:
        logger.error(f"Could not look up the review: {e}")
        return None
    return {key: review[key] for key in ("id", "state", "assignee")} if review else None


def queue_for_review(store: ReviewStore, result: dict, content: bytes, reason: str):
    """
    Queues the file (best effort: a database problem is logged, never raised, so
    the check itself still works). Returns the review's id, state and assignee.
    """
    try:
        review, _created = store.queue(result, content_hash(content), reason)
    except Exception as e:
        logger.error(f"Could not queue {result['filename']} for review: {e}")
        return None
    return {key: review[key] for key in ("id", "state", "assignee")}


def log_result(result: dict, origin: str) -> dict:
    """
    Writes a result to the audit log (best effort) and records on it whether that
    worked: `logged`, and `logged_at`, the timestamp of its audit entry (None when
    not written), which lets the page find its own checks in the shared log.
    """
    logged_at = write_single_audit_log(result, origin)
    result["logged"] = logged_at is not None
    result["logged_at"] = logged_at
    return result


def write_single_audit_log(result: dict, origin: str = "web") -> str | None:
    """
    Appends one analysis to the audit log. Returns the entry's timestamp, or None
    if it could not be written.
    """
    features = result["features"] or {}
    timestamp = datetime.now(UTC).isoformat()
    log_entry = {
        "timestamp": timestamp,
        "source_file": result["filename"],
        "transaction_id": result.get("id") or "N/A",
        "validation_status": result["status"],
        "errors": "; ".join(result["errors"]) if result["errors"] else "",
        "risk_score": result["prediction"]["risk_score"],
        "risk_flag": result["prediction"]["risk_flag"],
        "origin": origin,
        "duplicate_kind": (result.get("duplicate") or {}).get("kind"),
        "duplicate_of": ((result.get("duplicate") or {}).get("of") or {}).get("id"),
        "processing_ms": result["processing_ms"],
        "xml_size": features.get("xml_size"),
        "nesting_depth": features.get("nesting_depth"),
        "missing_optional_fields": features.get("missing_optional_fields"),
    }
    written = append_audit_entries(audit_log_path(), [log_entry], AUDIT_MAX_BYTES)
    return timestamp if written else None


def _matches(entry: dict, query: str) -> bool:
    """Case-insensitive search in the file name and the transaction ID."""
    haystack = f"{entry.get('source_file', '')} {entry.get('transaction_id', '')}"
    return query.casefold() in haystack.casefold()


@app.get("/api/audit", tags=["audit"])
def get_audit(
    status: AuditStatus | None = None,
    origin: AuditOrigin | None = Query(
        None,
        description="web (single check), web-batch (batch check), pipeline (startup batch) or vendor (vendor edit)",
    ),
    q: str | None = Query(None, max_length=200, description="Search file names and IDs"),
    limit: int = Query(50, ge=1, le=MAX_AUDIT_PAGE),
):
    """
    The most recent audit log entries, newest first, filtered by status, origin
    and a search over file names and transaction IDs. `counts` gives the number
    per status after the origin and search filters, so a status filter can show
    how many entries it would match. Each item has the parsed entry and its
    exact JSON line.
    """
    entries = read_audit_entries(audit_log_path())
    query = (q or "").strip()
    scoped = [
        (entry, line)
        for entry, line in entries
        if (origin is None or entry.get("origin") == origin)
        and (not query or _matches(entry, query))
    ]
    counts = {s.value: 0 for s in Status}
    for entry, _line in scoped:
        if entry.get("validation_status") in counts:
            counts[entry["validation_status"]] += 1
    matching = [
        {"entry": entry, "line": line}
        for entry, line in scoped
        if status is None or entry.get("validation_status") == status
    ]
    return {
        "total": len(entries),
        "counts": counts,
        "matching": len(matching),
        "entries": matching[:limit],
    }


@app.get("/api/overview", tags=["dashboard"])
def get_overview(recent: int = Query(15, ge=1, le=50)):
    """
    The dashboard, computed from the audit log: totals per status and origin,
    valid share, invalid rate, average risk, a 10-bin risk histogram split by
    flag, the most common reasons and the newest `recent` entries.
    """
    # Vendor edits are in the log too, but they are not checked files.
    entries = [e for e, _line in read_audit_entries(audit_log_path()) if "event" not in e]
    return build_overview(entries, recent)


# ---------- Review queue ----------

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class AssignBody(BaseModel):
    reviewer: Name
    actor: Name


class ActionBody(BaseModel):
    actor: Name
    comment: Comment


def review_call(action, *args):
    """Runs a store action, turning its errors into 404 (unknown id) and 409 (wrong state)."""
    try:
        return action(*args)
    except ReviewNotFound:
        raise HTTPException(status_code=404, detail="No such review") from None
    except ReviewStateError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.get("/api/reviews", tags=["reviews"])
def list_reviews(
    request: Request,
    state: Literal["open", "approved", "rejected"] | None = None,
    status: Literal["VALID", "INVALID", "REQUIRES_REVIEW"] | None = None,
    assignee: str | None = Query(None, max_length=60, description='A name, or "unassigned"'),
    q: str | None = Query(None, max_length=200, description="Search file names and IDs"),
    limit: int = Query(100, ge=1, le=500),
):
    """
    The review queue, newest first, filtered by state, invoice status, assignee and
    a search over file names and transaction IDs. `counts` gives the number per
    state after the other filters.
    """
    return request.app.state.reviews.list(state, assignee, status, (q or "").strip(), limit)


@app.get("/api/reviews/{review_id}", tags=["reviews"])
def get_review(request: Request, review_id: int):
    """One review: the invoice's analysis (rule checklist, risk drivers) and its full history."""
    return review_call(request.app.state.reviews.get, review_id)


@app.post("/api/reviews", tags=["reviews"], responses=ERROR_RESPONSES)
async def send_to_review(
    request: Request,
    file: UploadFile = File(...),
    actor: str = Form(ANONYMOUS, max_length=60),
):
    """
    Sends an INVALID (or REQUIRES_REVIEW) invoice to the review queue. The file is
    analysed again here, so the queue never holds a result the client made up.
    `created` is false when the same file is already in the queue.
    """
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        check_upload(file.filename, content, MAX_UPLOAD_BYTES)
        result = await run_in_threadpool(
            analyze_document, file.filename, content, request.app.state.predictor
        )
    except AnalysisError as e:
        return JSONResponse(e.to_json(), status_code=e.status_code)
    if result["status"] not in QUEUEABLE:
        raise HTTPException(
            status_code=400,
            detail="Only invoices that fail a rule or need review can be sent to review",
        )
    fingerprint = content_hash(content)
    result["fingerprint"] = fingerprint
    result["duplicate"] = request.app.state.invoices.flag_for(fingerprint)
    reason = "Sent to review: " + "; ".join(result["errors"] or ["needs review"])
    review, created = await run_in_threadpool(
        request.app.state.reviews.queue,
        result,
        fingerprint,
        reason,
        actor.strip() or ANONYMOUS,
    )
    return {"created": created, "review": {k: review[k] for k in ("id", "state", "assignee")}}


@app.post("/api/reviews/{review_id}/assign", tags=["reviews"])
def assign_review(request: Request, review_id: int, body: AssignBody):
    """Assigns an open review to a reviewer (a name). 409 when it is already closed."""
    return review_call(request.app.state.reviews.assign, review_id, body.reviewer, body.actor)


@app.post("/api/reviews/{review_id}/comments", tags=["reviews"])
def comment_on_review(request: Request, review_id: int, body: ActionBody):
    """Adds a comment to the history (any state). The comment cannot be blank."""
    return review_call(request.app.state.reviews.comment, review_id, body.actor, body.comment)


@app.post("/api/reviews/{review_id}/approve", tags=["reviews"])
def approve_review(request: Request, review_id: int, body: ActionBody):
    """Approves an open review. A comment is required; 409 when it is already decided."""
    return review_call(request.app.state.reviews.approve, review_id, body.actor, body.comment)


@app.post("/api/reviews/{review_id}/reject", tags=["reviews"])
def reject_review(request: Request, review_id: int, body: ActionBody):
    """Rejects an open review. A comment is required; 409 when it is already decided."""
    return review_call(request.app.state.reviews.reject, review_id, body.actor, body.comment)


# ---------- Vendor directory ----------


class VendorBody(BaseModel):
    actor: Name
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    trusted: bool | None = None


def vendor_call(action, *args):
    """Runs a vendor store call, turning an unknown vendor into a 404."""
    try:
        return action(*args)
    except VendorNotFound:
        raise HTTPException(status_code=404, detail="No such vendor") from None


@app.get("/api/vendors", tags=["vendors"])
def list_vendors(
    request: Request,
    q: str | None = Query(None, max_length=200, description="Search vendor names and IDs"),
    trusted: bool | None = None,
    sort: Literal[SORTS] = "name",
):
    """
    Every vendor seen in the analysed invoices: invoice count, status breakdown, total and
    average amount, duplicates flagged, average risk score and when it was last seen, plus
    its notes and trusted flag. Sorted by name, or by a statistic (largest first).
    """
    return request.app.state.vendors.list((q or "").strip(), trusted, sort)


@app.get("/api/vendors/{vendor_id}", tags=["vendors"])
def get_vendor(request: Request, vendor_id: str):
    """One vendor with its statistics, notes and trusted flag."""
    return vendor_call(request.app.state.vendors.get, vendor_id)


@app.get("/api/vendors/{vendor_id}/invoices", tags=["vendors"])
def get_vendor_invoices(
    request: Request,
    vendor_id: str,
    status: Literal["VALID", "INVALID", "REQUIRES_REVIEW"] | None = None,
    duplicates: bool = Query(False, description="Only invoices flagged as duplicates"),
    limit: int = Query(100, ge=1, le=500),
):
    """The vendor's invoices, newest first, with their duplicate flag and review (if any)."""
    return vendor_call(request.app.state.vendors.invoices, vendor_id, status, duplicates, limit)


@app.put("/api/vendors/{vendor_id}", tags=["vendors"])
def update_vendor(request: Request, vendor_id: str, body: VendorBody):
    """
    Saves a vendor's notes and/or trusted flag (fields left out are not changed) and
    writes the change to the audit log. Neither field affects validation.
    """
    if body.notes is None and body.trusted is None:
        raise HTTPException(status_code=422, detail="Send notes, trusted or both")
    vendor, changed = vendor_call(
        request.app.state.vendors.update, vendor_id, body.actor, body.notes, body.trusted
    )
    if changed:
        write_vendor_audit_entry(vendor, changed, body.actor)
    return vendor


def write_vendor_audit_entry(vendor: dict, changed: dict, actor: str):
    """Notes the change in the audit log (best effort, like every audit write)."""
    parts = []
    if "trusted" in changed:
        parts.append("Marked as a trusted vendor" if changed["trusted"] else "Trusted flag removed")
    if "notes" in changed:
        parts.append("Notes updated" if changed["notes"] else "Notes cleared")
    append_audit_entries(
        audit_log_path(),
        [
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "vendor_update",
                "origin": "vendor",
                "source_file": f"Vendor: {vendor['name']}",
                "transaction_id": "N/A",
                "errors": "",
                "actor": actor,
                "vendor_id": vendor["id"],
                "detail": f"{'; '.join(parts)} by {actor}",
                "trusted": vendor["trusted"],
            }
        ],
        AUDIT_MAX_BYTES,
    )


@app.get("/api/rules", tags=["reference"])
def list_rules():
    """The validation rules in plain language, and where the ID and amount are looked for."""
    return {
        "rules": [
            {
                "code": rule.code,
                "title": rule.title,
                "field": rule.field,
                "outcome": rule.outcome.value,
                "message": rule.message,
                "summary": rule.summary,
                "example": rule.example,
            }
            for rule in RULES
        ],
        "id_tags": list(ID_TAGS),
        "amount_tags": list(AMOUNT_TAGS),
        "generic_id_max_depth": MAX_GENERIC_ID_DEPTH,
        "review_threshold": REVIEW_THRESHOLD,
    }


@app.get("/api/model", tags=["reference"])
def get_model_card(request: Request):
    """The risk model's card: settings, features, training data and holdout metrics."""
    return request.app.state.model_card


@app.get("/api/stats", tags=["dashboard"])
async def get_dashboard_stats():
    """Totals from the last batch run (powerbi_summary.csv), for BI tools."""
    summary_path = os.path.join(RESULTS_DIR, "powerbi_summary.csv")
    if not os.path.exists(summary_path):
        return {
            "Total_Processed": 0,
            "Valid_Transactions": 0,
            "Invalid_Transactions": 0,
            "Requires_Review": 0,
            "Failure_Rate_Percent": 0.0,
            "Average_Risk_Score": 0.0,
            "Scored_Transactions": 0,
            "Total_High_Risk_Flags": 0,
        }

    try:
        df = pd.read_csv(summary_path)
        if df.empty:
            raise ValueError("Summary CSV is empty")

        # Convert first row to dictionary
        stats = df.iloc[0].to_dict()
        return stats
    except Exception as e:
        logger.error(f"Failed to read stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to load dashboard statistics") from e


@app.get("/api/history", tags=["dashboard"])
async def get_history():
    """The 15 most recent rows of the last batch run (results.csv), newest first."""
    csv_path = results_csv_path()
    if not os.path.exists(csv_path):
        return []
    try:
        df = pd.read_csv(csv_path)
        # Take last 15 records, fill NaN with empty string
        df = df.tail(15).fillna("")
        records = df.to_dict(orient="records")
        # Return in reverse chronological order (newest first)
        return records[::-1]
    except Exception as e:
        logger.error(f"Failed to read history: {e}")
        raise HTTPException(status_code=500, detail="Failed to load transaction history") from e


@app.get("/api/samples", tags=["samples"])
async def list_samples():
    """Sample invoices the frontend offers as one-click examples, with their expected status."""
    return [
        {
            "id": s["id"],
            "label": s["label"],
            "filename": s["file"],
            "description": s["description"],
            "expected": s["expected"],
        }
        for s in SAMPLES
    ]


@app.get("/api/samples/{sample_id}", tags=["samples"])
async def get_sample(sample_id: str):
    """One sample invoice as XML."""
    sample = next((s for s in SAMPLES if s["id"] == sample_id), None)
    if sample is None:
        raise HTTPException(status_code=404, detail="Unknown sample")
    with open(os.path.join(SAMPLES_DIR, sample["file"]), encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/xml")


@app.get("/healthz", tags=["health"])
async def healthz():
    """Cheap liveness check for the hosting platform."""
    return {"status": "ok"}


# The page loads only its own scripts and styles, plus Google Fonts.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' https://fonts.googleapis.com",
        "font-src https://fonts.gstatic.com",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    ]
)


class FrontendFiles(StaticFiles):
    """Static files that browsers revalidate on every load (a cheap 304), so a
    new deploy never runs against a stale, cached script. They carry a strict
    Content-Security-Policy; the API docs at /docs are not affected."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


# Serve the static frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/", FrontendFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("src.api.server:app", host="127.0.0.1", port=8000, reload=True)
