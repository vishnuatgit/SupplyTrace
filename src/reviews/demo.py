"""
Starter content for the review queue on a fresh demo, so a first-time visitor
sees the workflow working: the sample invoices that fail a rule or need
approval are queued as if someone had sent them.
"""

import hashlib
import logging
import os

from src.api.analysis import analyze_document
from src.reviews.store import QUEUEABLE, ReviewStore

logger = logging.getLogger(__name__)

DEMO_ACTOR = "demo"


def seed_review_queue(store: ReviewStore, samples: list, samples_dir: str, predictor) -> int:
    """
    Queues the sample invoices that are not VALID, but only when the queue is empty
    (so a restart never adds them twice). Returns how many were queued.
    Best effort: a problem is logged and never stops the server from starting.
    """
    try:
        if store.count():
            return 0
        queued = 0
        for sample in samples:
            if sample["expected"] not in QUEUEABLE:
                continue
            with open(os.path.join(samples_dir, sample["file"]), "rb") as f:
                content = f.read()
            result = analyze_document(sample["file"], content, predictor)
            reason = "Sample invoice: " + "; ".join(result["errors"] or [sample["description"]])
            review, _created = store.queue(result, hashlib.sha256(content).hexdigest(), reason)
            queued += 1
            if sample["expected"] == "REQUIRES_REVIEW":
                store.assign(review["id"], "Asha", DEMO_ACTOR)
                store.comment(
                    review["id"],
                    DEMO_ACTOR,
                    "Demo data. Open this review to try assigning, commenting, approving or rejecting.",
                )
        return queued
    except Exception as e:
        logger.error(f"Could not seed the review queue: {e}")
        return 0
