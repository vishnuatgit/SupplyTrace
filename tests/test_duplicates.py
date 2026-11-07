import hashlib
import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.api import server
from src.api.analysis import analyze_document
from src.invoices.fields import vendor_key
from src.invoices.store import InvoiceStore, dates_close
from src.prediction.model import RiskPredictor
from src.storage.schema import metadata

SAMPLES = os.path.join(os.path.dirname(server.__file__), "samples")


def invoice_xml(txn="TXN-1", supplier="Acme Corp", amount="100.00", date="2026-10-14", extra=""):
    """A small crafted invoice. Pass None for txn, supplier, amount or date to leave it out."""
    parts = []
    if txn:
        parts.append(f"<DocumentReference><TransactionID>{txn}</TransactionID></DocumentReference>")
    if date:
        parts.append(
            f"<IssueDate>{date}</IssueDate><DocumentCurrencyCode>USD</DocumentCurrencyCode>"
        )
    if supplier:
        parts.append(
            "<AccountingSupplierParty><Party><PartyName>"
            f"<Name>{supplier}</Name></PartyName></Party></AccountingSupplierParty>"
        )
    if amount:
        parts.append(
            f"<LegalMonetaryTotal><PayableAmount>{amount}</PayableAmount></LegalMonetaryTotal>"
        )
    return f"<Invoice>{''.join(parts)}{extra}</Invoice>".encode()


def fingerprint(**kwargs):
    return hashlib.sha256(invoice_xml(**kwargs)).hexdigest()


@pytest.fixture
def store():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    return InvoiceStore(engine)


def record(store, name="a.xml", origin="web", **kwargs):
    content = invoice_xml(**kwargs)
    result = analyze_document(name, content, RiskPredictor())
    return store.record(result, hashlib.sha256(content).hexdigest(), origin)


# ---------- Key fields ----------


def test_key_fields_are_read_from_the_invoice():
    result = analyze_document("a.xml", invoice_xml(supplier="  Acme   Corp "), RiskPredictor())
    assert result["key_fields"] == {
        "supplier_id": "",
        "supplier_name": "Acme   Corp",
        "vendor_key": "acme corp",
        "issue_date": "2026-10-14",
        "currency": "USD",
        "amount": 100.0,
    }


def test_supplier_id_wins_over_name_for_the_vendor_key():
    xml = invoice_xml(
        extra="<AccountingSupplierParty><PartyIdentification><ID>GST-77</ID>"
        "</PartyIdentification></AccountingSupplierParty>"
    )
    fields = analyze_document("a.xml", xml, RiskPredictor())["key_fields"]
    assert fields["supplier_id"] == "GST-77"
    assert fields["vendor_key"] == "gst-77"
    assert vendor_key("", "") == ""


def test_missing_and_bad_values_become_empty():
    fields = analyze_document(
        "a.xml", invoice_xml(supplier=None, date="not a date", amount="12,50.00"), RiskPredictor()
    )["key_fields"]
    assert fields["vendor_key"] == ""
    assert fields["issue_date"] == ""
    assert fields["amount"] is None


def test_dates_close():
    assert dates_close("2026-10-14", "2026-10-21")
    assert not dates_close("2026-10-14", "2026-10-22")
    assert not dates_close("2026-10-14", "")
    assert not dates_close("", "")


# ---------- Detection ----------


def test_first_invoice_is_not_a_duplicate(store):
    assert record(store) is None


def test_same_content_is_an_exact_duplicate(store):
    record(store, name="first.xml")
    flag = record(store, name="second.xml")
    assert flag["kind"] == "exact"
    assert flag["of"]["filename"] == "first.xml"
    assert flag["of"]["invoice_id"] == "TXN-1"


def test_same_supplier_and_id_is_a_likely_duplicate(store):
    record(store, name="first.xml", amount="100.00")
    flag = record(store, name="second.xml", amount="250.00")
    assert flag["kind"] == "likely"
    assert "invoice ID (TXN-1)" in flag["reason"]
    assert flag["of"]["filename"] == "first.xml"


def test_supplier_name_is_compared_ignoring_case_and_spaces(store):
    record(store, supplier="Acme Corp")
    assert record(store, supplier="ACME   corp", amount="5.00")["kind"] == "likely"


def test_same_id_from_another_supplier_is_not_a_duplicate(store):
    record(store, supplier="Acme Corp")
    assert record(store, supplier="Globex", amount="5.00") is None


def test_same_supplier_and_amount_within_the_window(store):
    record(store, txn="TXN-1", amount="500.00", date="2026-10-14")
    flag = record(store, txn="TXN-2", amount="500.00", date="2026-10-18")
    assert flag["kind"] == "likely"
    assert "within 7 days" in flag["reason"]


def test_same_amount_outside_the_window_is_not_a_duplicate(store):
    record(store, txn="TXN-1", amount="500.00", date="2026-10-01")
    assert record(store, txn="TXN-2", amount="500.00", date="2026-10-14") is None


def test_same_amount_without_dates_is_not_a_duplicate(store):
    record(store, txn="TXN-1", amount="500.00", date=None)
    assert record(store, txn="TXN-2", amount="500.00", date=None) is None
    assert record(store, txn="TXN-3", amount="500.00", date="2026-10-14") is None


def test_different_amount_and_id_is_not_a_duplicate(store):
    record(store, txn="TXN-1", amount="500.00")
    assert record(store, txn="TXN-2", amount="501.00") is None


def test_without_a_supplier_only_exact_duplicates_are_found(store):
    record(store, supplier=None)
    assert record(store, supplier=None, amount="9.00") is None  # same ID, but no supplier to match
    assert record(store, supplier=None)["kind"] == "exact"


def test_exact_wins_over_likely_and_the_earliest_match_is_used(store):
    record(store, name="one.xml", txn="TXN-1", amount="100.00")
    record(store, name="two.xml", txn="TXN-1", amount="200.00")  # likely, of one.xml
    flag = record(store, name="three.xml", txn="TXN-1", amount="200.00")  # exact copy of two.xml
    assert flag["kind"] == "exact"
    assert flag["of"]["filename"] == "two.xml"
    flag = record(store, name="four.xml", txn="TXN-1", amount="300.00")
    assert flag["of"]["filename"] == "one.xml"


def test_demo_invoices_are_never_exact_matches_but_do_count_as_likely(store):
    record(store, name="sample.xml", origin="demo")
    assert record(store, name="sample.xml") is None  # checking a starter sample is not a duplicate
    flag = record(store, name="other.xml", amount="5.00")
    assert flag["kind"] == "likely"


def test_flag_for_returns_the_first_flag_of_a_file(store):
    record(store, name="one.xml", txn="TXN-1", amount="100.00")
    record(store, name="two.xml", txn="TXN-1", amount="200.00")
    assert store.flag_for(fingerprint(amount="200.00"))["kind"] == "likely"
    assert store.flag_for("0" * 64) is None
    assert store.flag_for(fingerprint()) is None  # the original


# ---------- API and end to end ----------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "AUDIT_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path / "data" / "raw_xml"))
    monkeypatch.setattr(server, "BOOTSTRAP_DEMO_DATA", False)
    with TestClient(server.app) as c:
        yield c


def check(client, content, name="invoice.xml"):
    return client.post("/api/analyze", files={"file": (name, content, "text/xml")}).json()


def test_second_upload_of_a_file_is_flagged_exact(client):
    first = check(client, invoice_xml(), "first.xml")
    second = check(client, invoice_xml(), "second.xml")
    assert first["duplicate"] is None
    assert second["duplicate"]["kind"] == "exact"
    assert second["duplicate"]["of"]["filename"] == "first.xml"
    assert second["fingerprint"] == first["fingerprint"]
    assert second["review"] is None  # an exact duplicate is flagged, not queued


def test_likely_duplicate_goes_to_review_even_when_valid(client):
    check(client, invoice_xml(amount="100.00"), "first.xml")
    result = check(client, invoice_xml(amount="250.00"), "second.xml")
    assert result["status"] == "VALID"
    assert result["duplicate"]["kind"] == "likely"
    review = client.get(f"/api/reviews/{result['review']['id']}").json()
    assert review["state"] == "open"
    assert review["validation_status"] == "VALID"
    assert review["duplicate"] == "likely"
    assert "Likely duplicate of invoice #1" in review["reason"]
    assert review["result"]["duplicate"]["of"]["filename"] == "first.xml"
    assert client.get("/api/reviews?status=VALID").json()["matching"] == 1


def test_duplicates_are_flagged_in_a_batch_and_in_the_audit_log(client):
    files = [
        ("files", ("a.xml", invoice_xml(), "text/xml")),
        ("files", ("b.xml", invoice_xml(), "text/xml")),
        ("files", ("c.xml", invoice_xml(amount="9.00"), "text/xml")),
    ]
    results = client.post("/api/analyze/batch", files=files).json()["results"]
    assert [(r["duplicate"] or {}).get("kind") for r in results] == [None, "exact", "likely"]
    entries = client.get("/api/audit").json()["entries"]
    assert [e["entry"]["duplicate_kind"] for e in entries] == ["likely", "exact", None]
    assert entries[0]["entry"]["duplicate_of"] == 1


def test_streamed_batch_flags_duplicates_too(client):
    files = [("files", (n, invoice_xml(), "text/xml")) for n in ("a.xml", "b.xml")]
    lines = [
        json.loads(x)
        for x in client.post("/api/analyze/batch/stream", files=files).text.splitlines()
    ]
    flags = [line["result"]["duplicate"] for line in lines if line["type"] == "result"]
    assert flags[0] is None
    assert flags[1]["kind"] == "exact"


def test_invalid_duplicate_sent_to_review_keeps_the_flag(client):
    check(client, invoice_xml(txn="TXN-1", amount="100.00"), "good.xml")
    bad = invoice_xml(txn="TXN-1", amount="12,50.00")
    assert check(client, bad, "bad.xml")["duplicate"]["kind"] == "likely"
    # The likely duplicate is already queued, so sending it by hand returns that review.
    sent = client.post("/api/reviews", files={"file": ("bad.xml", bad, "text/xml")}).json()
    assert sent["created"] is False
    review = client.get(f"/api/reviews/{sent['review']['id']}").json()
    assert review["result"]["duplicate"]["kind"] == "likely"


def test_end_to_end_duplicate_to_review_decision_and_audit(client):
    original = check(client, invoice_xml(amount="100.00"), "original.xml")
    assert original["duplicate"] is None and original["review"] is None

    copy = check(client, invoice_xml(amount="130.00"), "resubmitted.xml")
    assert copy["duplicate"]["kind"] == "likely"
    review_id = copy["review"]["id"]
    assert client.get("/api/reviews?state=open").json()["reviews"][0]["id"] == review_id

    client.post(
        f"/api/reviews/{review_id}/reject",
        json={"actor": "Asha", "comment": "Duplicate of original.xml"},
    )
    history = client.get(f"/api/reviews/{review_id}").json()["history"]
    assert [e["action"] for e in history] == ["created", "rejected"]

    # Checking the same resubmitted file again: exact duplicate, and its review is shown.
    again = check(client, invoice_xml(amount="130.00"), "resubmitted.xml")
    assert again["duplicate"]["kind"] == "exact"
    assert again["review"]["state"] == "rejected"
    audit = [e["entry"] for e in client.get("/api/audit").json()["entries"]]
    assert [a["duplicate_kind"] for a in audit] == ["exact", "likely", None]


def sample(name):
    with open(os.path.join(SAMPLES, name), "rb") as f:
        return f.read()


def test_fresh_demo_shows_duplicates_working(tmp_path, monkeypatch):
    """On a fresh demo server the starter samples are not duplicates; the duplicate sample is."""
    monkeypatch.setattr(server, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "AUDIT_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path / "data" / "raw_xml"))
    monkeypatch.setattr(server, "BOOTSTRAP_DEMO_DATA", True)
    with TestClient(server.app) as c:
        valid = check(c, sample("valid_invoice.xml"), "valid_invoice.xml")
        assert valid["duplicate"] is None
        dup = check(c, sample("duplicate_id.xml"), "duplicate_id.xml")
        assert dup["status"] == "VALID"
        assert dup["duplicate"]["kind"] == "likely"
        assert "TXN-48180" in dup["duplicate"]["reason"]
        assert dup["review"]["state"] == "open"
        # Checking the valid sample a second time is an exact duplicate of the first check.
        again = check(c, sample("valid_invoice.xml"), "valid_invoice.xml")
        assert again["duplicate"]["kind"] == "exact"
