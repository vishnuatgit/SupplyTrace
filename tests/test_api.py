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
    # No synthetic batch here: these tests cover a server with no batch results.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "AUDIT_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path / "data" / "raw_xml"))
    monkeypatch.setattr(server, "BOOTSTRAP_DEMO_DATA", False)
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
    # Real measured server time, not a value simulated from the file size.
    assert isinstance(body["processing_ms"], float)
    assert body["features"]["xml_size"] == len(make_xml("TXN-42", "99.50"))


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


def test_external_entity_upload_is_rejected(client):
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b"<Invoice><TransactionID>&x;</TransactionID><Amount>1</Amount></Invoice>"
    )
    res = upload(client, xxe)
    assert res.status_code == 400
    assert res.json()["detail"] == "DTDs and entity declarations are not allowed"


def test_deeply_nested_upload_is_rejected(client):
    res = upload(client, b"<a>" * 5000 + b"</a>" * 5000)
    assert res.status_code == 400
    assert "too deep" in res.json()["detail"]


def test_upload_over_the_size_limit_gets_413(client):
    # Just over the limit: caught when the file is read
    res = upload(client, b"<a>" + b"x" * server.MAX_UPLOAD_BYTES + b"</a>")
    assert res.status_code == 413
    assert "up to 1 MB" in res.json()["detail"]

    # Far over: refused from the Content-Length header before the body is read
    res = upload(client, b"x" * (2 * server.MAX_UPLOAD_BYTES))
    assert res.status_code == 413
    assert "up to 1 MB" in res.json()["detail"]


def test_upload_limit_applies_without_content_length(client):
    # A chunked body has no Content-Length, so the middleware counts bytes as they arrive.
    def chunks():
        yield (
            b'--x\r\nContent-Disposition: form-data; name="file"; filename="big.xml"\r\n'
            b"Content-Type: text/xml\r\n\r\n<a>"
        )
        for _ in range(12):
            yield b"x" * 100_000
        yield b"</a>\r\n--x--\r\n"

    res = client.post(
        "/api/analyze",
        content=chunks(),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert res.status_code == 413


def test_upload_just_under_the_limit_is_accepted(client):
    xml = make_xml("TXN-9", "10")
    padding = b" " * (server.MAX_UPLOAD_BYTES - len(xml))
    res = upload(client, xml.replace(b"</Invoice>", padding + b"</Invoice>"))
    assert res.status_code == 200
    assert res.json()["status"] == "VALID"


def test_analysis_is_written_to_audit_log(client, tmp_path):
    upload(client, make_xml("TXN-7", "10"), name="a.xml")
    upload(client, make_xml("TXN-8", "abc"), name="b.xml")
    lines = (tmp_path / "results" / "audit_log.jsonl").read_text().splitlines()
    entries = [json.loads(line) for line in lines]
    assert [e["transaction_id"] for e in entries] == ["TXN-7", "TXN-8"]
    assert [e["validation_status"] for e in entries] == ["VALID", "INVALID"]
    assert "AMOUNT must be numeric" in entries[1]["errors"]


def test_unwritable_audit_log_does_not_fail_the_request(client, tmp_path, monkeypatch):
    # Simulates a read-only or missing disk: the audit directory cannot be created.
    blocker = tmp_path / "read_only"
    blocker.write_text("a file where a directory should be")
    monkeypatch.setattr(server, "AUDIT_DIR", str(blocker / "results"))
    res = upload(client, make_xml("TXN-5", "10"))
    assert res.status_code == 200
    assert res.json()["status"] == "VALID"


def test_stats_and_history_empty_without_batch_results(client):
    assert client.get("/api/history").json() == []
    assert client.get("/api/stats").json()["Total_Processed"] == 0


def test_samples_are_listed_and_served(client):
    samples = client.get("/api/samples").json()
    assert [s["id"] for s in samples][:3] == ["valid", "sparse", "missing-id"]
    res = client.get("/api/samples/valid")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    assert b"<TransactionID>TXN-48180</TransactionID>" in res.content
    assert client.get("/api/samples/..%2Fserver.py").status_code == 404
    assert client.get("/api/samples/nope").status_code == 404


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_no_cors_headers_for_other_origins(client):
    res = client.get("/api/stats", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in res.headers


def test_frontend_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "SupplyTrace" in res.text
    assert client.get("/favicon.svg").status_code == 200
