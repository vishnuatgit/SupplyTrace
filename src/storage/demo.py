"""
Starter content for a fresh demo, so a first-time visitor sees the features working:
the sample invoices are recorded as already-checked invoices, and the ones that fail a
rule or need approval are queued for review as if someone had sent them.
"""

import hashlib
import logging
import os

import pandas as pd

from src.api.analysis import analyze_document
from src.ingestion.parser import XMLParser
from src.ingestion.xml_loader import XMLLoader
from src.invoices.fields import key_fields
from src.invoices.store import DEMO_ORIGIN, InvoiceStore
from src.reviews.store import QUEUEABLE, ReviewStore

logger = logging.getLogger(__name__)

DEMO_ACTOR = "demo"


def seed_startup_batch(invoices: InvoiceStore, raw_dir: str, results_csv: str) -> int:
    """
    Records the 400 synthetic invoices of the startup batch as already-checked invoices, so
    the vendor directory has several suppliers to show. The status and risk score are the
    ones the batch pipeline already worked out (results.csv); the supplier, date and amount
    are read from the XML. Returns how many were recorded.
    """
    if not os.path.exists(results_csv):
        return 0
    recorded = 0
    for row in pd.read_csv(results_csv).fillna("").itertuples():
        path = os.path.join(raw_dir, row.source_file)
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            content = f.read()
        standardized = XMLParser.standardize(XMLLoader.parse_bytes(content))
        score = row.risk_score if isinstance(row.risk_score, int | float) else None
        result = {
            "filename": row.source_file,
            "id": str(row.id),
            "status": row.status,
            "key_fields": key_fields(standardized),
            "fields": {"AMOUNT": {"value": standardized["AMOUNT"]}},
            "prediction": {"risk_score": score},
        }
        invoices.record(result, hashlib.sha256(content).hexdigest(), DEMO_ORIGIN)
        recorded += 1
    return recorded


def seed_demo_data(
    reviews: ReviewStore,
    invoices: InvoiceStore,
    samples: list,
    samples_dir: str,
    predictor,
    startup_batch: tuple[str, str] | None = None,
) -> int:
    """
    Records the startup batch (raw folder and results.csv, when given) and the sample
    invoices, and queues the samples that are not VALID, but only on an empty database
    (so a restart never adds them twice). Returns how many samples were recorded.
    Best effort: a problem is logged and never stops the server starting.
    """
    try:
        if reviews.count() or invoices.count():
            return 0
        if startup_batch:
            seed_startup_batch(invoices, *startup_batch)
        recorded = 0
        for sample in samples:
            if sample.get("starter") is False:
                continue  # left for the visitor to try (see SAMPLES)
            with open(os.path.join(samples_dir, sample["file"]), "rb") as f:
                content = f.read()
            digest = hashlib.sha256(content).hexdigest()
            result = analyze_document(sample["file"], content, predictor)
            invoices.record(result, digest, DEMO_ORIGIN)
            recorded += 1
            if sample["expected"] in QUEUEABLE:
                reason = "Sample invoice: " + "; ".join(result["errors"] or [sample["description"]])
                review, _created = reviews.queue(result, digest, reason)
                if sample["expected"] == "REQUIRES_REVIEW":
                    reviews.assign(review["id"], "Asha", DEMO_ACTOR)
                    reviews.comment(
                        review["id"],
                        DEMO_ACTOR,
                        "Demo data. Open this review to try assigning, commenting, approving or rejecting.",
                    )
        return recorded
    except Exception as e:
        logger.error(f"Could not seed the demo data: {e}")
        return 0
