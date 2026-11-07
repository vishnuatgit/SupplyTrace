"""
Starter content for a fresh demo, so a first-time visitor sees the features working:
the sample invoices are recorded as already-checked invoices, and the ones that fail a
rule or need approval are queued for review as if someone had sent them.
"""

import hashlib
import logging
import os

from src.api.analysis import analyze_document
from src.invoices.store import DEMO_ORIGIN, InvoiceStore
from src.reviews.store import QUEUEABLE, ReviewStore

logger = logging.getLogger(__name__)

DEMO_ACTOR = "demo"


def seed_demo_data(
    reviews: ReviewStore, invoices: InvoiceStore, samples: list, samples_dir: str, predictor
) -> int:
    """
    Records the sample invoices and queues those that are not VALID, but only on an
    empty database (so a restart never adds them twice). Returns how many samples
    were recorded. Best effort: a problem is logged and never stops the server starting.
    """
    try:
        if reviews.count() or invoices.count():
            return 0
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
