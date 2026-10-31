import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

import pandas as pd
import uvicorn
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
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
from src.pipeline.bootstrap import ensure_demo_results
from src.prediction.model import RiskPredictor
from src.prediction.model_card import build_model_card
from src.utils.audit import DEFAULT_MAX_BYTES, append_audit_entries, read_audit_entries
from src.validation.rules import REVIEW_THRESHOLD, RULES, Status

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
]

# Statuses and origins an audit entry can have (rejected files are not logged).
AuditStatus = Literal["VALID", "INVALID", "REQUIRES_REVIEW"]
AuditOrigin = Literal["web", "web-batch", "pipeline"]
MAX_AUDIT_PAGE = 500

TAGS = [
    {"name": "analysis", "description": "Check XML invoices: one file, or a batch of up to 20."},
    {"name": "dashboard", "description": "Totals and history for the web dashboard."},
    {"name": "audit", "description": "The JSON Lines audit log: one entry per checked file."},
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
    if BOOTSTRAP_DEMO_DATA:
        ensure_demo_results(DATA_DIR, results_csv_path(), audit_log_path())
    results = train_from_results(app.state.predictor, results_csv_path())
    app.state.model_card = build_model_card(app.state.predictor, results)
    yield


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
app.add_middleware(
    UploadSizeLimitMiddleware,
    max_bytes=MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES,
    paths=("/api/analyze",),
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

    # Write to the audit log (best effort: never fails the request)
    return log_result(result, origin="web")


async def read_batch(files: list[UploadFile]) -> list[tuple[str | None, bytes]]:
    """Reads every upload of a batch (each capped just over the size limit)."""
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=400, detail=TOO_MANY_FILES_DETAIL)
    return [(upload.filename, await upload.read(MAX_UPLOAD_BYTES + 1)) for upload in files]


async def check_batch_file(filename: str | None, content: bytes, predictor) -> dict:
    """One batch file through the single-file pipeline; a file that can't be read is REJECTED."""
    try:
        check_upload(filename, content, MAX_UPLOAD_BYTES)
        result = await run_in_threadpool(analyze_document, filename, content, predictor)
    except AnalysisError as e:
        return rejected_result(filename, e)
    return log_result(result, origin="web-batch")


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
    predictor = request.app.state.predictor
    results = [await check_batch_file(name, content, predictor) for name, content in uploads]
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
    predictor = request.app.state.predictor

    async def lines():
        yield json.dumps({"type": "start", "count": len(uploads)}) + "\n"
        results = []
        for index, (name, content) in enumerate(uploads):
            result = await check_batch_file(name, content, predictor)
            results.append(result)
            yield json.dumps({"type": "result", "index": index, "result": result}) + "\n"
        summary = {"type": "summary", "count": len(results), "summary": summarize(results)}
        yield json.dumps(summary) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


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
        None, description="web (single check), web-batch (batch check) or pipeline (startup batch)"
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
    entries = [entry for entry, _line in read_audit_entries(audit_log_path())]
    return build_overview(entries, recent)


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
