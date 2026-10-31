from src.dashboard.overview import build_overview


def entry(status, score=None, flag=None, errors="", origin="web"):
    return {
        "timestamp": "2026-10-31T10:00:00+00:00",
        "source_file": "f.xml",
        "validation_status": status,
        "risk_score": "N/A" if score is None else score,
        "risk_flag": flag or "N/A",
        "errors": errors,
        "origin": origin,
    }


def test_histogram_bins_scores_by_flag():
    entries = [
        entry("VALID", 1.6, "LOW"),
        entry("VALID", 50.0, "LOW"),  # exactly at the threshold: LOW, in the 50-60 bin
        entry("INVALID", 55.0, "HIGH"),
        entry("INVALID", 100.0, "HIGH"),  # the top edge falls in the last bin
        entry("INVALID"),  # not scored
    ]
    body = build_overview(entries)
    bins = body["risk_histogram"]
    assert len(bins) == 10 and bins[0]["from"] == 0 and bins[-1]["to"] == 100
    assert bins[0]["low"] == 1
    assert (bins[5]["low"], bins[5]["high"]) == (1, 1)
    assert bins[9]["high"] == 1
    assert body["scored"] == 4 and body["high_risk"] == 2 and body["low_risk"] == 2
    assert body["average_risk"] == round((1.6 + 50 + 55 + 100) / 4, 2)


def test_reasons_are_counted_per_message_and_status():
    entries = [
        entry(
            "INVALID", errors="Missing required field: ID; Invalid format: AMOUNT must be numeric"
        ),
        entry("INVALID", errors="Missing required field: ID"),
        entry("REQUIRES_REVIEW", errors="High value amount, requires manual review"),
    ]
    reasons = build_overview(entries)["top_reasons"]
    assert reasons[0] == {"reason": "Missing required field: ID", "status": "INVALID", "count": 2}
    assert {r["status"] for r in reasons} == {"INVALID", "REQUIRES_REVIEW"}


def test_unknown_values_are_ignored_not_counted():
    body = build_overview([entry("MAYBE", score=True, origin="elsewhere"), entry("VALID", "x")])
    assert body["total"] == 2
    assert body["counts"] == {"VALID": 1, "INVALID": 0, "REQUIRES_REVIEW": 0}
    assert sum(body["origins"].values()) == 1
    assert body["scored"] == 0


def test_recent_keeps_the_newest_entries():
    entries = [dict(entry("VALID"), source_file=f"{n}.xml") for n in range(20)]
    body = build_overview(entries, recent=3)
    assert [e["source_file"] for e in body["recent"]] == ["0.xml", "1.xml", "2.xml"]
    assert body["latest"] == entries[0]["timestamp"]


def test_empty_log():
    body = build_overview([])
    assert body["total"] == 0
    assert body["valid_share"] is None and body["invalid_rate"] is None
    assert body["average_risk"] is None and body["latest"] is None
    assert all(b["low"] == b["high"] == 0 for b in body["risk_histogram"])
