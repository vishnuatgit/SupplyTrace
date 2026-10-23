import json

import pytest
from fastapi.testclient import TestClient

from src.api import server

NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"


def make_xml(transaction_id="TXN-1", amount="250.00"):
    tid = f"<DocumentReference><TransactionID>{transaction_id}</TransactionID></DocumentReference>"
    amt = f"<LegalMonetaryTotal><PayableAmount>{amount}</PayableAmount></LegalMonetaryTotal>"
    account = "<PaymentMeans><PayeeFinancialAccount><ID>IBAN-XYZ</ID></PayeeFinancialAccount></PaymentMeans>"
    return (
        f'<StandardBusinessDocument xmlns="{NS}"><Invoice>'
        f"{tid if transaction_id else ''}{account}{amt if amount else ''}"
        "</Invoice></StandardBusinessDocument>"
    ).encode()


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Every endpoint reads and writes under ./results, so run in a temp dir.
    monkeypatch.chdir(tmp_path)
    with TestClient(server.app) as c:
        yield c


def upload(client, content, name="invoice.xml"):
    return client.post("/api/analyze", files={"file": (name, content, "text/xml")})


def test_analyze_valid_namespaced_invoice(client):
    res = upload(client, make_xml("TXN-42", "99.50"))
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "VALID"
    assert body["id"] == "TXN-42"
    assert body["errors"] == []
    # No trained model in a fresh directory: risk is reported as N/A, not guessed.
    assert body["prediction"] == {"risk_score": "N/A", "risk_flag": "N/A"}


def test_missing_transaction_id_is_not_masked_by_nested_account_id(client):
    body = upload(client, make_xml(transaction_id=None)).json()
    assert body["status"] == "INVALID"
    assert "Missing required field: ID" in body["errors"]


def test_malformed_xml_returns_400_not_500(client):
    res = upload(client, b"<Invoice><ID>1</ID>")
    assert res.status_code == 400
    assert res.json()["detail"] == "Invalid or malformed XML file"


def test_non_xml_upload_rejected(client):
    res = upload(client, b"hello", name="notes.txt")
    assert res.status_code == 400


def test_analysis_is_written_to_audit_log(client, tmp_path):
    upload(client, make_xml("TXN-7", "10"), name="a.xml")
    upload(client, make_xml("TXN-8", "abc"), name="b.xml")
    lines = (tmp_path / "results" / "audit_log.jsonl").read_text().splitlines()
    entries = [json.loads(line) for line in lines]
    assert [e["transaction_id"] for e in entries] == ["TXN-7", "TXN-8"]
    assert [e["validation_status"] for e in entries] == ["VALID", "INVALID"]
    assert "AMOUNT must be numeric" in entries[1]["errors"]


def test_stats_and_history_empty_without_batch_results(client):
    assert client.get("/api/history").json() == []
    assert client.get("/api/stats").json()["Total_Processed"] == 0


def test_frontend_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "SupplyTrace" in res.text
