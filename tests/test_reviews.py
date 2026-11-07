import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from src.api import server
from src.reviews.store import ReviewNotFound, ReviewStateError, ReviewStore
from src.storage.database import database_url
from src.storage.schema import metadata

SAMPLES = os.path.join(os.path.dirname(server.__file__), "samples")


def sample(name):
    with open(os.path.join(SAMPLES, name), "rb") as f:
        return f.read()


def fake_result(status="REQUIRES_REVIEW", filename="a.xml"):
    return {
        "filename": filename,
        "id": "TXN-1",
        "status": status,
        "errors": ["Amount is above the review limit"],
        "fields": {"AMOUNT": {"value": "4750000.00"}},
        "prediction": {"risk_score": 61.5, "risk_flag": "HIGH"},
        "checks": [],
        "risk_drivers": None,
    }


@pytest.fixture
def store():
    engine = create_engine("sqlite://")  # in memory
    metadata.create_all(engine)
    return ReviewStore(engine)


def queued(store, status="REQUIRES_REVIEW", digest="h1"):
    review, _created = store.queue(fake_result(status), digest, "why")
    return review["id"]


# ---------- State transitions ----------


def test_new_review_is_open_with_a_created_event(store):
    review_id = queued(store)
    review = store.get(review_id)
    assert review["state"] == "open"
    assert review["assignee"] is None
    assert [e["action"] for e in review["history"]] == ["created"]
    assert review["history"][0]["actor"] == "system"


def test_valid_invoice_cannot_be_queued(store):
    with pytest.raises(ValueError):
        store.queue(fake_result("VALID"), "h", "why")


def test_same_file_is_queued_only_once(store):
    first, created = store.queue(fake_result(), "same", "why")
    second, created_again = store.queue(fake_result(), "same", "why")
    assert created and not created_again
    assert first["id"] == second["id"]
    assert store.count() == 1


def test_assign_then_approve_records_every_step(store):
    review_id = queued(store)
    store.assign(review_id, "Asha", "Ravi")
    review = store.approve(review_id, "Asha", "Checked with the supplier")
    assert review["state"] == "approved"
    assert review["assignee"] == "Asha"
    assert [(e["actor"], e["action"]) for e in review["history"]] == [
        ("system", "created"),
        ("Ravi", "assigned"),
        ("Asha", "approved"),
    ]
    assert review["history"][2]["comment"] == "Checked with the supplier"


def test_cannot_approve_twice(store):
    review_id = queued(store)
    store.approve(review_id, "Asha", "ok")
    with pytest.raises(ReviewStateError):
        store.approve(review_id, "Asha", "again")
    with pytest.raises(ReviewStateError):
        store.reject(review_id, "Asha", "changed my mind")
    assert len(store.get(review_id)["history"]) == 2  # nothing extra was written


def test_cannot_assign_a_closed_review(store):
    review_id = queued(store)
    store.reject(review_id, "Asha", "duplicate bill")
    with pytest.raises(ReviewStateError):
        store.assign(review_id, "Ravi", "Asha")


def test_comments_are_allowed_after_a_decision(store):
    review_id = queued(store)
    store.approve(review_id, "Asha", "ok")
    review = store.comment(review_id, "Ravi", "Paid on Friday")
    assert review["state"] == "approved"
    assert review["history"][-1]["action"] == "commented"


@pytest.mark.parametrize("action", ["approve", "reject", "comment"])
@pytest.mark.parametrize("blank", ["", "   \n"])
def test_a_comment_is_required(store, action, blank):
    review_id = queued(store)
    with pytest.raises(ValueError):
        getattr(store, action)(review_id, "Asha", blank)
    assert store.get(review_id)["state"] == "open"


@pytest.mark.parametrize("action", ["approve", "reject", "comment"])
def test_unknown_id(store, action):
    with pytest.raises(ReviewNotFound):
        getattr(store, action)(999, "Asha", "hello")
    with pytest.raises(ReviewNotFound):
        store.assign(999, "Asha", "Ravi")
    with pytest.raises(ReviewNotFound):
        store.get(999)


def test_list_filters_and_counts(store):
    a = queued(store, "REQUIRES_REVIEW", "h1")
    b = queued(store, "INVALID", "h2")
    c = queued(store, "INVALID", "h3")
    store.assign(a, "Asha", "x")
    store.approve(c, "Asha", "fine")

    everything = store.list()
    assert everything["counts"] == {"open": 2, "approved": 1, "rejected": 0}
    assert [r["id"] for r in everything["reviews"]] == [c, b, a]  # newest first
    assert everything["assignees"] == ["Asha"]

    assert [r["id"] for r in store.list(state="open")["reviews"]] == [b, a]
    assert store.list(state="open")["matching"] == 2
    assert [r["id"] for r in store.list(assignee="asha")["reviews"]] == [a]
    assert [r["id"] for r in store.list(assignee="unassigned")["reviews"]] == [c, b]
    only_invalid = store.list(status="INVALID")
    assert only_invalid["counts"] == {"open": 1, "approved": 1, "rejected": 0}
    assert [r["id"] for r in store.list(q="txn-1")["reviews"]] == [c, b, a]
    assert store.list(q="nothing like this")["reviews"] == []


def test_events_cannot_be_changed_through_the_store(store):
    # The store has no update or delete for events: the history only grows.
    assert not any(hasattr(store, name) for name in ("delete", "edit", "remove", "update_event"))


# ---------- Database setup ----------


def test_database_url_defaults_to_a_sqlite_file(tmp_path):
    url = database_url(None, str(tmp_path / "x.db"))
    assert url.startswith("sqlite:///") and url.endswith("x.db")


def test_database_url_accepts_the_postgres_prefix_hosts_use():
    assert database_url("postgres://u:p@host/db", "x.db") == "postgresql://u:p@host/db"
    assert database_url("postgresql://u:p@host/db", "x.db") == "postgresql://u:p@host/db"


# ---------- API ----------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "AUDIT_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path / "data" / "raw_xml"))
    monkeypatch.setattr(server, "BOOTSTRAP_DEMO_DATA", False)
    with TestClient(server.app) as c:
        yield c


def check(client, name):
    return client.post("/api/analyze", files={"file": (name, sample(name), "text/xml")}).json()


def act(client, review_id, action, **body):
    return client.post(f"/api/reviews/{review_id}/{action}", json=body)


def test_requires_review_file_is_queued_automatically(client):
    result = check(client, "high_value.xml")
    assert result["status"] == "REQUIRES_REVIEW"
    assert result["review"]["state"] == "open"
    listing = client.get("/api/reviews").json()
    assert listing["counts"]["open"] == 1
    assert listing["reviews"][0]["id"] == result["review"]["id"]


def test_invalid_and_valid_files_are_not_queued_automatically(client):
    assert check(client, "bad_amount.xml")["review"] is None
    assert check(client, "valid_invoice.xml")["review"] is None
    assert client.get("/api/reviews").json()["reviews"] == []


def test_checking_the_same_file_again_does_not_queue_it_twice(client):
    first = check(client, "high_value.xml")["review"]["id"]
    assert check(client, "high_value.xml")["review"]["id"] == first
    assert len(client.get("/api/reviews").json()["reviews"]) == 1


def test_batch_queues_review_files(client):
    files = [("files", (n, sample(n), "text/xml")) for n in ("high_value.xml", "valid_invoice.xml")]
    body = client.post("/api/analyze/batch", files=files).json()
    by_name = {r["filename"]: r for r in body["results"]}
    assert by_name["high_value.xml"]["review"]["state"] == "open"
    assert by_name["valid_invoice.xml"]["review"] is None


def test_send_invalid_file_to_review(client):
    upload = {"file": ("bad_amount.xml", sample("bad_amount.xml"), "text/xml")}
    sent = client.post("/api/reviews", files=upload, data={"actor": "Ravi"})
    assert sent.status_code == 200
    assert sent.json()["created"] is True
    again = client.post("/api/reviews", files=upload, data={"actor": "Ravi"}).json()
    assert again["created"] is False
    assert again["review"]["id"] == sent.json()["review"]["id"]
    review = client.get(f"/api/reviews/{sent.json()['review']['id']}").json()
    assert review["validation_status"] == "INVALID"
    assert review["history"][0]["actor"] == "Ravi"
    assert review["result"]["checks"]  # the stored rule checklist


def test_result_shows_the_review_of_an_invalid_file_once_it_was_sent(client):
    upload = {"file": ("bad_amount.xml", sample("bad_amount.xml"), "text/xml")}
    review = client.post("/api/reviews", files=upload).json()["review"]
    assert check(client, "bad_amount.xml")["review"] == review


def test_valid_file_cannot_be_sent_to_review(client):
    upload = {"file": ("valid_invoice.xml", sample("valid_invoice.xml"), "text/xml")}
    assert client.post("/api/reviews", files=upload).status_code == 400


def test_send_to_review_rejects_unreadable_files(client):
    res = client.post("/api/reviews", files={"file": ("x.xml", b"<Invoice>", "text/xml")})
    assert res.status_code == 400
    assert "line" in res.json()


def test_api_workflow_and_error_codes(client):
    review_id = check(client, "high_value.xml")["review"]["id"]

    assert act(client, review_id, "assign", reviewer="Asha", actor="Ravi").status_code == 200
    assert (
        act(client, review_id, "comments", actor="Asha", comment="Looking now").status_code == 200
    )

    # A comment is required to decide (422), and the review stays open.
    assert act(client, review_id, "approve", actor="Asha", comment="  ").status_code == 422
    assert act(client, review_id, "approve", actor="Asha").status_code == 422
    assert act(client, review_id, "approve", actor="", comment="ok").status_code == 422
    assert client.get(f"/api/reviews/{review_id}").json()["state"] == "open"

    approved = act(client, review_id, "approve", actor="Asha", comment="PO matches")
    assert approved.status_code == 200
    assert approved.json()["state"] == "approved"

    # Cannot decide twice (409), cannot act on unknown ids (404).
    assert act(client, review_id, "approve", actor="Asha", comment="again").status_code == 409
    assert act(client, review_id, "reject", actor="Asha", comment="no").status_code == 409
    assert act(client, review_id, "assign", reviewer="X", actor="Y").status_code == 409
    assert act(client, 9999, "approve", actor="Asha", comment="ok").status_code == 404
    assert act(client, 9999, "comments", actor="Asha", comment="ok").status_code == 404
    assert client.get("/api/reviews/9999").status_code == 404

    history = client.get(f"/api/reviews/{review_id}").json()["history"]
    assert [(e["actor"], e["action"]) for e in history] == [
        ("system", "created"),
        ("Ravi", "assigned"),
        ("Asha", "commented"),
        ("Asha", "approved"),
    ]


def test_list_filters_over_http(client):
    check(client, "high_value.xml")
    client.post(
        "/api/reviews",
        files={"file": ("bad_amount.xml", sample("bad_amount.xml"), "text/xml")},
    )
    assert client.get("/api/reviews?status=INVALID").json()["matching"] == 1
    assert client.get("/api/reviews?q=high_value").json()["matching"] == 1
    assert client.get("/api/reviews?state=approved").json()["reviews"] == []
    assert client.get("/api/reviews?state=bogus").status_code == 422


# ---------- End to end ----------


def test_end_to_end_upload_review_decision_and_audit(client, tmp_path):
    """Upload -> flagged in the result -> in the queue -> assigned, decided -> history and audit."""
    result = check(client, "high_value.xml")
    assert result["status"] == "REQUIRES_REVIEW"
    review_id = result["review"]["id"]

    # The audit log has the check, and the queue has the same invoice.
    audit = client.get("/api/audit").json()["entries"][0]["entry"]
    assert audit["source_file"] == "high_value.xml"
    assert audit["validation_status"] == "REQUIRES_REVIEW"
    queue = client.get("/api/reviews?state=open").json()["reviews"]
    assert [(r["id"], r["filename"]) for r in queue] == [(review_id, "high_value.xml")]

    # The detail has the analysis the check produced.
    detail = client.get(f"/api/reviews/{review_id}").json()
    assert detail["result"]["checks"] == result["checks"]

    act(client, review_id, "assign", reviewer="Asha", actor="Ravi")
    act(client, review_id, "reject", actor="Asha", comment="Amount does not match the PO")

    assert client.get("/api/reviews?state=open").json()["reviews"] == []
    closed = client.get("/api/reviews?state=rejected").json()
    assert closed["reviews"][0]["assignee"] == "Asha"

    # Re-checking the file shows its decision instead of queueing it again.
    assert check(client, "high_value.xml")["review"] == {
        "id": review_id,
        "state": "rejected",
        "assignee": "Asha",
    }

    # The database file is where we configured it.
    assert os.path.exists(server.DB_PATH)
    engine = create_engine(f"sqlite:///{server.DB_PATH}")
    with engine.connect() as conn:
        n = conn.execute(text("select count(*) from review_events")).scalar()
    assert n == 3
    assert json.loads(client.get(f"/api/reviews/{review_id}").text)["state"] == "rejected"


def test_fresh_demo_server_seeds_the_queue(tmp_path, monkeypatch):
    """With the demo bootstrap on (as on Render) the queue starts with the sample invoices."""
    monkeypatch.setattr(server, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "AUDIT_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path / "data" / "raw_xml"))
    monkeypatch.setattr(server, "BOOTSTRAP_DEMO_DATA", True)
    with TestClient(server.app) as c:
        listing = c.get("/api/reviews").json()
        assert listing["counts"]["open"] == 5  # four INVALID samples and the high value one
        # Checking a sample that is already queued points at that review.
        high = c.post(
            "/api/analyze", files={"file": ("high_value.xml", sample("high_value.xml"), "text/xml")}
        ).json()
        assert high["review"]["assignee"] == "Asha"
        assert c.get("/api/reviews").json()["counts"]["open"] == 5
    # A restart does not add them again.
    with TestClient(server.app) as c:
        assert c.get("/api/reviews").json()["counts"]["open"] == 5
