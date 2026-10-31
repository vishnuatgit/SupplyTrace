"""
The numbers behind the web dashboard, computed from the audit log: one entry
per checked file, from the startup batch and from every check since.
"""

import math
from collections import Counter

STATUSES = ("VALID", "INVALID", "REQUIRES_REVIEW")
ORIGINS = ("pipeline", "web", "web-batch")
RISK_BINS = 10  # 0-10%, 10-20%, ..., 90-100%
TOP_REASONS = 5


def _risk(entry: dict) -> float | None:
    """The entry's risk score as a number, or None when it was not scored."""
    score = entry.get("risk_score")
    if isinstance(score, bool) or not isinstance(score, int | float) or not math.isfinite(score):
        return None
    return float(score)


def _percent(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 2) if whole else None


def build_overview(entries: list[dict], recent: int = 15) -> dict:
    """
    Totals, the verdict split, a risk histogram split by flag, the most common
    reasons and the newest entries. `entries` are audit entries, newest first.
    """
    counts = dict.fromkeys(STATUSES, 0)
    origins = dict.fromkeys(ORIGINS, 0)
    reasons = Counter()
    histogram = [
        {"from": i * 100 // RISK_BINS, "to": (i + 1) * 100 // RISK_BINS, "low": 0, "high": 0}
        for i in range(RISK_BINS)
    ]
    scores = []

    for entry in entries:
        status = entry.get("validation_status")
        if status in counts:
            counts[status] += 1
        if entry.get("origin") in origins:
            origins[entry["origin"]] += 1
        for reason in filter(None, str(entry.get("errors") or "").split("; ")):
            reasons[(reason, status)] += 1
        score = _risk(entry)
        if score is not None:
            scores.append(score)
            band = "high" if entry.get("risk_flag") == "HIGH" else "low"
            histogram[min(int(score // (100 / RISK_BINS)), RISK_BINS - 1)][band] += 1

    total = len(entries)
    high = sum(b["high"] for b in histogram)
    return {
        "total": total,
        "counts": counts,
        "origins": origins,
        "valid_share": _percent(counts["VALID"], total),
        "invalid_rate": _percent(counts["INVALID"], total),
        "scored": len(scores),
        "average_risk": round(sum(scores) / len(scores), 2) if scores else None,
        "high_risk": high,
        "low_risk": len(scores) - high,
        "risk_histogram": histogram,
        "top_reasons": [
            {"reason": reason, "status": status, "count": count}
            for (reason, status), count in reasons.most_common(TOP_REASONS)
        ],
        "latest": entries[0].get("timestamp") if entries else None,
        "recent": entries[:recent],
    }
