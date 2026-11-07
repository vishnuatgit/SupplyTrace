import hashlib
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from src.api import server
from src.invoices.fields import vendor_key
from src.invoices.store import InvoiceStore
from src.storage.schema import metadata
from src.vendors.store import VendorNotFound, VendorStore, vendor_id

SAMPLES = os.path.join(os.path.dirname(server.__file__), "samples")


def fake(name="a.xml", txn="TXN-1", supplier="Acme Corp", amount="100.00", status="VALID", **kw):
    """The parts of an analysis result that the invoice store reads."""
    return {
        "filename": name,
        "id": txn,
        "status": status,
        "key_fields": {
            "supplier_id": "",
            "supplier_name": supplier,
            "vendor_key": vendor_key("", supplier),
            "issue_date": kw.get("date", ""),
            "currency": kw.get("currency", "USD"),
            "amount": float(amount) if amount else None,
        },
        "fields": {"AMOUNT": {"value": amount or ""}},
        "prediction": {"risk_score": kw.get("risk")},
    }


@pytest.fixture
def stores():
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    return InvoiceStore(engine), VendorStore(engine)


def add(invoices, result, origin="web"):
    return invoices.record(result, hashlib.sha256(result["filename"].encode()).hexdigest(), origin)


# ---------- Statistics ----------


def test_vendor_statistics(stores):
    invoices, vendors = stores
    add(invoices, fake("a.xml", "T1", amount="100.00", risk=10))
    add(invoices, fake("b.xml", "T2", amount="300.00", status="INVALID", risk=90))
    add(invoices, fake("c.xml", "T1", amount="50.00", risk=20))  # same ID: likely duplicate
    add(invoices, fake("d.xml", "T4", amount="", status="INVALID"))  # no amount, no score
    add(invoices, fake("e.xml", "T5", supplier="Globex", amount="7.00"))

    listing = vendors.list()
    assert listing["total"] == 2
    acme = next(v for v in listing["vendors"] if v["name"] == "Acme Corp")
    assert acme["invoice_count"] == 4
    assert acme["statuses"] == {"VALID": 2, "INVALID": 2, "REQUIRES_REVIEW": 0}
    assert acme["total_amount"] == 450.0
    assert acme["average_amount"] == 150.0  # three invoices had an amount
    assert acme["duplicates"] == 1
    assert acme["average_risk"] == 40.0  # (10 + 90 + 20) / 3
    assert acme["currency"] == "USD"
    assert acme["last_seen"] >= acme["first_seen"]
    assert acme["trusted"] is False and acme["notes"] == ""


def test_invoices_without_a_supplier_are_not_a_vendor(stores):
    invoices, vendors = stores
    add(invoices, fake(supplier=""))
    assert vendors.list()["vendors"] == []


def test_spelling_of_the_same_supplier_is_one_vendor_and_the_latest_name_is_shown(stores):
    invoices, vendors = stores
    add(invoices, fake("a.xml", "T1", supplier="acme corp"))
    add(invoices, fake("b.xml", "T2", supplier="ACME  Corp"))
    listing = vendors.list()
    assert listing["total"] == 1
    assert listing["vendors"][0]["name"] == "ACME  Corp"


def test_mixed_currencies_are_labelled(stores):
    invoices, vendors = stores
    add(invoices, fake("a.xml", "T1", currency="USD"))
    add(invoices, fake("b.xml", "T2", currency="EUR"))
    vendor = vendors.list()["vendors"][0]
    assert [c["currency"] for c in vendor["currencies"]] == ["EUR", "USD"] or [
        c["currency"] for c in vendor["currencies"]
    ] == ["USD", "EUR"]
    assert vendor["currency"] in ("USD", "EUR")  # the one with the most invoices (a tie: either)
    assert vendor["total_amount"] == 100.0  # not 200: dollars and euros are not added


def test_search_filter_and_sort(stores):
    invoices, vendors = stores
    for i in range(3):
        add(invoices, fake(f"a{i}.xml", f"A{i}", supplier="Acme", amount="10.00"))
    add(invoices, fake("g.xml", "G1", supplier="Globex", amount="999.00"))
    vendors.update(vendors.list(q="glob")["vendors"][0]["id"], "Ravi", None, True)

    assert [v["name"] for v in vendors.list(sort="name")["vendors"]] == ["Acme", "Globex"]
    assert [v["name"] for v in vendors.list(sort="invoices")["vendors"]] == ["Acme", "Globex"]
    assert [v["name"] for v in vendors.list(sort="total")["vendors"]] == ["Globex", "Acme"]
    assert [v["name"] for v in vendors.list(trusted=True)["vendors"]] == ["Globex"]
    assert vendors.list(trusted=True)["trusted"] == 1
    assert vendors.list(q="nothing")["vendors"] == []
    assert vendors.list(q="nothing")["total"] == 2


def test_vendor_invoices_with_filters(stores):
    invoices, vendors = stores
    add(invoices, fake("a.xml", "T1", amount="100.00"))
    add(invoices, fake("b.xml", "T1", amount="5.00", status="INVALID"))  # likely duplicate
    vid = vendors.list()["vendors"][0]["id"]
    everything = vendors.invoices(vid)
    assert [i["filename"] for i in everything["invoices"]] == ["b.xml", "a.xml"]
    assert everything["invoices"][0]["duplicate_kind"] == "likely"
    assert everything["invoices"][0]["duplicate_of"] == everything["invoices"][1]["id"]
    assert vendors.invoices(vid, duplicates=True)["matching"] == 1
    assert [i["filename"] for i in vendors.invoices(vid, status="VALID")["invoices"]] == ["a.xml"]


# ---------- Notes and the trusted flag ----------


def test_update_stores_notes_and_trusted_and_reports_changes(stores):
    invoices, vendors = stores
    add(invoices, fake())
    vid = vendors.list()["vendors"][0]["id"]

    vendor, changed = vendors.update(vid, "Ravi", "Pays net 30", True)
    assert changed == {"notes": "Pays net 30", "trusted": True}
    assert (vendor["notes"], vendor["trusted"], vendor["updated_by"]) == (
        "Pays net 30",
        True,
        "Ravi",
    )

    _, changed = vendors.update(vid, "Ravi", "Pays net 30", True)
    assert changed == {}  # nothing new

    vendor, changed = vendors.update(vid, "Asha", None, False)  # notes left alone
    assert changed == {"trusted": False}
    assert vendor["notes"] == "Pays net 30"
    assert vendor["updated_by"] == "Asha"


def test_unknown_vendor(stores):
    _, vendors = stores
    with pytest.raises(VendorNotFound):
        vendors.get("nope")
    with pytest.raises(VendorNotFound):
        vendors.update("nope", "Ravi", "x", None)
    assert vendors.summary("") is None
    assert vendors.summary("acme") is None


def test_summary_gives_the_id_name_and_trusted_flag(stores):
    invoices, vendors = stores
    add(invoices, fake())
    vid = vendor_id("acme corp")
    assert vendors.summary("acme corp") == {"id": vid, "name": "Acme Corp", "trusted": False}
    vendors.update(vid, "Ravi", None, True)
    assert vendors.summary("acme corp")["trusted"] is True


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


def xml(txn="TXN-1", supplier="Acme Corp", amount="100.00"):
    return (
        f"<Invoice><DocumentReference><TransactionID>{txn}</TransactionID></DocumentReference>"
        f"<IssueDate>2026-10-14</IssueDate><DocumentCurrencyCode>USD</DocumentCurrencyCode>"
        f"<AccountingSupplierParty><Party><PartyName><Name>{supplier}</Name></PartyName></Party>"
        f"</AccountingSupplierParty><LegalMonetaryTotal><PayableAmount>{amount}</PayableAmount>"
        "</LegalMonetaryTotal></Invoice>"
    ).encode()


def check(client, content, name="invoice.xml"):
    return client.post("/api/analyze", files={"file": (name, content, "text/xml")}).json()


def test_vendor_api_unknown_ids_and_bad_input(client):
    assert client.get("/api/vendors/nope").status_code == 404
    assert client.get("/api/vendors/nope/invoices").status_code == 404
    assert client.put("/api/vendors/nope", json={"actor": "A", "trusted": True}).status_code == 404
    check(client, xml())
    vid = client.get("/api/vendors").json()["vendors"][0]["id"]
    assert client.put(f"/api/vendors/{vid}", json={"actor": "A"}).status_code == 422
    assert client.put(f"/api/vendors/{vid}", json={"trusted": True}).status_code == 422
    assert (
        client.put(f"/api/vendors/{vid}", json={"actor": " ", "trusted": True}).status_code == 422
    )
    too_long = {"actor": "A", "notes": "x" * 2001}
    assert client.put(f"/api/vendors/{vid}", json=too_long).status_code == 422
    assert client.get("/api/vendors?sort=bogus").status_code == 422


def test_trusted_flag_is_stored_audited_and_never_changes_validation(client):
    bad = xml(txn="TXN-9", amount="12,50.00")
    before = check(client, bad, "bad.xml")
    vid = before["vendor"]["id"]
    assert before["vendor"]["trusted"] is False

    saved = client.put(
        f"/api/vendors/{vid}", json={"actor": "Ravi", "trusted": True, "notes": "Known supplier"}
    )
    assert saved.status_code == 200
    assert saved.json()["trusted"] is True
    assert client.get(f"/api/vendors/{vid}").json()["notes"] == "Known supplier"

    after = check(client, bad, "bad2.xml")
    assert after["vendor"]["trusted"] is True
    for field in ("status", "errors", "findings", "checks", "prediction", "features"):
        assert after[field] == before[field], field

    audit = [e["entry"] for e in client.get("/api/audit?origin=vendor").json()["entries"]]
    assert len(audit) == 1
    assert audit[0]["event"] == "vendor_update"
    assert audit[0]["actor"] == "Ravi"
    assert "trusted vendor" in audit[0]["detail"] and "Notes updated" in audit[0]["detail"]

    # An unchanged save writes nothing; vendor edits are not counted as checked files.
    client.put(f"/api/vendors/{vid}", json={"actor": "Ravi", "trusted": True})
    assert client.get("/api/audit?origin=vendor").json()["matching"] == 1
    assert client.get("/api/overview").json()["total"] == 2


def test_end_to_end_upload_vendor_stats_invoices_and_audit(client):
    check(client, xml("TXN-1", "Acme Corp", "100.00"), "a1.xml")
    dup = check(client, xml("TXN-1", "Acme Corp", "130.00"), "a2.xml")  # likely duplicate
    check(client, xml("TXN-2", "Globex", "55.00"), "g1.xml")
    check(client, xml("TXN-3", "Acme Corp", "12,50.00"), "a3.xml")  # invalid

    listing = client.get("/api/vendors").json()
    assert listing["total"] == 2
    acme = next(v for v in listing["vendors"] if v["name"] == "Acme Corp")
    assert acme["invoice_count"] == 3
    assert acme["statuses"] == {"VALID": 2, "INVALID": 1, "REQUIRES_REVIEW": 0}
    assert acme["total_amount"] == 230.0
    assert acme["duplicates"] == 1

    invoices = client.get(f"/api/vendors/{acme['id']}/invoices").json()
    assert [i["filename"] for i in invoices["invoices"]] == ["a3.xml", "a2.xml", "a1.xml"]
    flagged = client.get(f"/api/vendors/{acme['id']}/invoices?duplicates=true").json()
    assert [i["filename"] for i in flagged["invoices"]] == ["a2.xml"]
    assert flagged["invoices"][0]["review_id"] == dup["review"]["id"]  # link to the queue

    detail = client.get(f"/api/vendors/{acme['id']}").json()
    assert detail["invoice_count"] == 3
    assert client.get("/api/vendors?q=glob").json()["matching"] == 1


def test_fresh_demo_has_vendors_to_browse(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "AUDIT_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path / "data" / "raw_xml"))
    monkeypatch.setattr(server, "BOOTSTRAP_DEMO_DATA", True)
    with TestClient(server.app) as c:
        listing = c.get("/api/vendors").json()
        names = [v["name"] for v in listing["vendors"]]
        assert len(names) >= 6
        assert "Acme Corp Global" in names
        assert all(
            v["invoice_count"] > 0 and v["average_risk"] is not None for v in listing["vendors"]
        )
        with open(os.path.join(SAMPLES, "valid_invoice.xml"), "rb") as f:
            result = check(c, f.read(), "valid_invoice.xml")
        assert result["vendor"]["name"] == "Acme Corp Global"
        assert result["duplicate"] is None  # a starter sample is not a duplicate
