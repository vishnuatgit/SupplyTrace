import pytest
from fastapi.testclient import TestClient

from src.api import server
from src.pipeline.synthetic import DEFAULT_COUNT


@pytest.fixture(scope="module")
def demo_client(tmp_path_factory):
    """A server started on an empty disk, as on a fresh host: it builds the demo batch itself."""
    root = tmp_path_factory.mktemp("fresh_host")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(server, "RESULTS_DIR", str(root / "results"))
        mp.setattr(server, "AUDIT_DIR", str(root / "results"))
        mp.setattr(server, "DATA_DIR", str(root / "data" / "raw_xml"))
        mp.setattr(server, "BOOTSTRAP_DEMO_DATA", True)
        with TestClient(server.app) as c:
            yield c


def test_fresh_server_builds_the_demo_batch(demo_client):
    stats = demo_client.get("/api/stats").json()
    assert stats["Total_Processed"] == DEFAULT_COUNT
    assert stats["Scored_Transactions"] == DEFAULT_COUNT

    history = demo_client.get("/api/history").json()
    assert len(history) == 15
    assert all(isinstance(row["risk_score"], float) for row in history)


@pytest.mark.parametrize(
    ("sample_id", "status"),
    [
        ("valid", "VALID"),
        ("sparse", "VALID"),
        ("missing-id", "INVALID"),
        ("missing-amount", "INVALID"),
        ("bad-amount", "INVALID"),
        ("negative-amount", "INVALID"),
        ("high-value", "REQUIRES_REVIEW"),
    ],
)
def test_sample_status_and_risk_band_agree(demo_client, sample_id, status):
    xml = demo_client.get(f"/api/samples/{sample_id}").content
    body = demo_client.post("/api/analyze", files={"file": ("s.xml", xml, "text/xml")}).json()

    assert body["status"] == status
    expected_flag = "LOW" if status == "VALID" else "HIGH"
    assert body["prediction"]["risk_flag"] == expected_flag


def test_sparse_invoice_scores_higher_than_complete_one(demo_client):
    def score(sample_id):
        xml = demo_client.get(f"/api/samples/{sample_id}").content
        res = demo_client.post("/api/analyze", files={"file": ("s.xml", xml, "text/xml")})
        return res.json()["prediction"]["risk_score"]

    assert score("valid") < score("sparse") < 50


@pytest.mark.parametrize(
    ("sample_id", "rule", "line"),
    [
        ("missing-id", "missing_id", 12),  # <Invoice>, where the ID was expected
        ("missing-amount", "missing_amount", 12),
        ("bad-amount", "amount_not_numeric", 47),  # the <PayableAmount> line
        ("negative-amount", "amount_negative", 47),
        ("high-value", "amount_above_review_limit", 47),
    ],
)
def test_sample_findings_point_at_the_right_line(demo_client, sample_id, rule, line):
    xml = demo_client.get(f"/api/samples/{sample_id}").content
    body = demo_client.post("/api/analyze", files={"file": ("s.xml", xml, "text/xml")}).json()
    [finding] = body["findings"]
    assert (finding["rule"], finding["line"]) == (rule, line)
    marked = xml.decode().splitlines()[line - 1].strip()
    assert marked.startswith(("<Invoice>", "<PayableAmount"))


def test_all_samples_as_one_batch(demo_client):
    files = [
        ("files", (s["filename"], demo_client.get(f"/api/samples/{s['id']}").content, "text/xml"))
        for s in demo_client.get("/api/samples").json()
    ]
    body = demo_client.post("/api/analyze/batch", files=files).json()
    assert body["summary"] == {"VALID": 3, "INVALID": 4, "REQUIRES_REVIEW": 1, "REJECTED": 0}


def test_every_sample_gets_its_expected_status(demo_client):
    for sample in demo_client.get("/api/samples").json():
        xml = demo_client.get(f"/api/samples/{sample['id']}").content
        res = demo_client.post(
            "/api/analyze", files={"file": (sample["filename"], xml, "text/xml")}
        )
        assert res.json()["status"] == sample["expected"], sample["id"]


def test_risk_drivers_explain_the_score(demo_client):
    xml = demo_client.get("/api/samples/bad-amount").content
    body = demo_client.post("/api/analyze", files={"file": ("s.xml", xml, "text/xml")}).json()
    drivers = body["risk_drivers"]
    total = drivers["base"] + sum(d["points"] for d in drivers["contributions"])
    assert abs(total - body["prediction"]["risk_score"]) < 0.1
    top = drivers["contributions"][0]
    assert (top["feature"], top["label"], top["value"]) == (
        "amount_not_numeric",
        "Amount not a number",
        1,
    )


def test_overview_starts_from_the_synthetic_batch(demo_client):
    body = demo_client.get("/api/overview").json()
    assert body["origins"]["pipeline"] == DEFAULT_COUNT
    assert body["total"] >= DEFAULT_COUNT
    assert body["scored"] == body["total"]
    assert sum(b["low"] + b["high"] for b in body["risk_histogram"]) == body["scored"]
    assert body["high_risk"] == sum(b["high"] for b in body["risk_histogram"])


def test_model_card_reports_holdout_metrics(demo_client):
    card = demo_client.get("/api/model").json()
    assert card["trained"] is True
    assert card["training"]["rows"] == DEFAULT_COUNT
    holdout = card["holdout"]
    assert holdout["test_rows"] == DEFAULT_COUNT * card["holdout_share"]
    assert holdout["same_calls_as_rules"] is True
    assert 0 < holdout["valid_only"]["failed"] < holdout["valid_only"]["rows"]
