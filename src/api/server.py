import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pandas as pd
import uvicorn
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from src.api.upload_limit import UploadSizeLimitMiddleware
from src.features.extractor import FeatureExtractor
from src.ingestion.parser import XMLParser
from src.ingestion.xml_loader import XMLLoader, XMLLoadError
from src.pipeline.bootstrap import ensure_demo_results
from src.prediction.model import RiskPredictor
from src.utils.audit import DEFAULT_MAX_BYTES, append_audit_entries
from src.validation.rules import Validator

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

TOO_LARGE_DETAIL = (
    f"File is too large. The demo accepts XML files up to {MAX_UPLOAD_BYTES / 1_000_000:g} MB."
)
# Room for the multipart headers around the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")
SAMPLES = [
    {"id": "valid", "label": "Valid invoice", "file": "valid_invoice.xml"},
    {"id": "sparse", "label": "Sparse invoice", "file": "sparse_invoice.xml"},
    {"id": "missing-id", "label": "Missing ID", "file": "missing_id.xml"},
    {"id": "missing-amount", "label": "Missing amount", "file": "missing_amount.xml"},
    {"id": "bad-amount", "label": "Bad amount", "file": "bad_amount.xml"},
    {"id": "negative-amount", "label": "Negative amount", "file": "negative_amount.xml"},
    {"id": "high-value", "label": "High value", "file": "high_value.xml"},
]


def results_csv_path() -> str:
    return os.path.join(RESULTS_DIR, "results.csv")


def audit_log_path() -> str:
    return os.path.join(AUDIT_DIR, "audit_log.jsonl")


def train_from_results(predictor: RiskPredictor, csv_path: str):
    """Train the model on startup if historical data exists."""
    if not os.path.exists(csv_path):
        logger.warning(f"No historical data at {csv_path}. Model will return N/A for risk.")
        return
    try:
        logger.info(f"Training ML model from {csv_path}...")
        predictor.fit(pd.read_csv(csv_path))
    except Exception as e:
        logger.error(f"Failed to train model on startup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.predictor = RiskPredictor()
    if BOOTSTRAP_DEMO_DATA:
        ensure_demo_results(DATA_DIR, results_csv_path(), audit_log_path())
    train_from_results(app.state.predictor, results_csv_path())
    yield


app = FastAPI(title="SupplyTrace API", lifespan=lifespan)

# The frontend is served by this app (same origin), so no CORS headers are needed.
app.add_middleware(
    UploadSizeLimitMiddleware,
    max_bytes=MAX_UPLOAD_BYTES + MULTIPART_OVERHEAD_BYTES,
    paths=("/api/analyze",),
    detail=TOO_LARGE_DETAIL,
)


def predict(predictor: RiskPredictor, features: dict) -> dict:
    """Risk score from the model, or N/A when it is untrained or fails."""
    if predictor.is_trained:
        try:
            return predictor.predict_risk(features)
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
    return {"risk_score": "N/A", "risk_flag": "N/A"}


@app.post("/api/analyze")
async def analyze_xml(request: Request, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="Only .xml files are supported")

    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=TOO_LARGE_DETAIL)

    started = time.perf_counter()

    # 1. Ingest (in memory: the upload is never written to disk)
    try:
        raw_record = XMLLoader.parse_bytes(content)
    except XMLLoadError as e:
        logger.warning(f"Rejected {file.filename}: {e} ({e.__cause__ or 'no detail'})")
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        raw_record["_source_file"] = file.filename

        # 2. Standardize
        standardized = XMLParser.standardize(raw_record)

        # 3. Validate
        status, errors = Validator.validate(standardized)

        # 4. Extract Features
        features = FeatureExtractor.extract_features(standardized, xml_size=len(content))

        # 5. Predict Risk
        prediction = predict(request.app.state.predictor, features)
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail="Analysis failed") from e

    response_data = {
        "filename": file.filename,
        "id": standardized.get("ID", ""),
        "status": status.value,
        "errors": errors,
        "features": features,
        "prediction": prediction,
        # Measured server-side time from parsing to prediction, excluding the upload.
        "processing_ms": round((time.perf_counter() - started) * 1000, 2),
    }

    # Write to Audit Log (best effort: never fails the request)
    write_single_audit_log(response_data)

    return response_data


def write_single_audit_log(result: dict) -> bool:
    """Helper to append a single analysis transaction to the audit log."""
    log_entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source_file": result["filename"],
        "transaction_id": result.get("id") or "N/A",
        "validation_status": result["status"],
        "errors": "; ".join(result["errors"]) if result["errors"] else "",
        "risk_score": result["prediction"]["risk_score"],
        "risk_flag": result["prediction"]["risk_flag"],
    }
    return append_audit_entries(audit_log_path(), [log_entry], AUDIT_MAX_BYTES)


@app.get("/api/stats")
async def get_dashboard_stats():
    """Returns aggregated system metrics for the frontend dashboard."""
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


@app.get("/api/history")
async def get_history():
    """Returns the last 15 processed transactions for the dashboard log."""
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


@app.get("/api/samples")
async def list_samples():
    """Sample invoices the dashboard offers as one-click examples."""
    return [{"id": s["id"], "label": s["label"], "filename": s["file"]} for s in SAMPLES]


@app.get("/api/samples/{sample_id}")
async def get_sample(sample_id: str):
    sample = next((s for s in SAMPLES if s["id"] == sample_id), None)
    if sample is None:
        raise HTTPException(status_code=404, detail="Unknown sample")
    with open(os.path.join(SAMPLES_DIR, sample["file"]), encoding="utf-8") as f:
        return Response(content=f.read(), media_type="application/xml")


@app.get("/healthz")
async def healthz():
    """Cheap liveness check for the hosting platform."""
    return {"status": "ok"}


# Serve the static frontend
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("src.api.server:app", host="127.0.0.1", port=8000, reload=True)
