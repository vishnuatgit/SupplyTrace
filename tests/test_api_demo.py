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
