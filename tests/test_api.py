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


def test_frontend_assets_are_served_and_revalidated(client):
    for path in ("/", "/styles.css", "/js/main.js", "/js/check.js", "/favicon.svg"):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.headers["cache-control"] == "no-cache"
    assert "javascript" in client.get("/js/main.js").headers["content-type"]


def test_single_result_points_findings_at_lines(client):
    xml = b"<Invoice>\n<TransactionID>T-1</TransactionID>\n<Amount>N/A</Amount>\n</Invoice>"
    body = upload(client, xml).json()
    assert body["fields"]["ID"]["line"] == 2
    assert body["findings"] == [
        {
            "rule": "amount_not_numeric",
            "field": "AMOUNT",
            "message": "Invalid format: AMOUNT must be numeric",
            "target": "value",
            "line": 3,
            "end_line": 3,
            "note": '<Amount> on line 3 holds "N/A".',
        }
    ]


def test_samples_have_descriptions(client):
    assert all(s["description"] for s in client.get("/api/samples").json())


# ---------- Batch check ----------


def upload_batch(client, files):
    parts = [("files", (name, content, "text/xml")) for name, content in files]
    return client.post("/api/analyze/batch", files=parts)


def test_batch_checks_every_file_with_the_single_file_pipeline(client):
    files = [
        ("ok.xml", make_xml("TXN-1", "10")),
        ("no_id.xml", make_xml(None, "10")),
        ("big.xml", make_xml("TXN-3", "5000000")),
    ]
    res = upload_batch(client, files)
    assert res.status_code == 200
    body = res.json()
    assert body["count"] == 3
    assert [r["status"] for r in body["results"]] == ["VALID", "INVALID", "REQUIRES_REVIEW"]
    assert body["summary"] == {"VALID": 1, "INVALID": 1, "REQUIRES_REVIEW": 1, "REJECTED": 0}

    # The same result as checking the file on its own (apart from the measured time)
    single = upload(client, files[1][1], name="no_id.xml").json()
    batch_row = body["results"][1]
    for key in ("status", "errors", "findings", "fields", "features", "prediction"):
        assert batch_row[key] == single[key]


def test_unreadable_files_are_rejected_without_failing_the_batch(client):
    files = [
        ("notes.txt", b"hello"),
        ("broken.xml", b"<Invoice>"),
        ("huge.xml", b"<a>" + b"x" * server.MAX_UPLOAD_BYTES + b"</a>"),
        ("ok.xml", make_xml("TXN-1", "10")),
    ]
    body = upload_batch(client, files).json()
    rows = body["results"]
    assert [r["status"] for r in rows] == ["REJECTED", "REJECTED", "REJECTED", "VALID"]
    assert rows[0]["errors"] == ["Only .xml files are supported"]
    assert rows[1]["errors"] == ["Invalid or malformed XML file"]
    assert "up to 1 MB" in rows[2]["errors"][0]
    assert body["summary"]["REJECTED"] == 3


def test_batch_file_count_is_capped(client):
    files = [(f"f{i}.xml", make_xml(f"TXN-{i}", "1")) for i in range(server.MAX_BATCH_FILES + 1)]
    res = upload_batch(client, files)
    assert res.status_code == 400
    assert f"up to {server.MAX_BATCH_FILES} files" in res.json()["detail"]
    assert upload_batch(client, files[:-1]).status_code == 200


def test_batch_body_over_the_limit_gets_413(client):
    too_big = b"x" * (server.MAX_BATCH_FILES * server.MAX_UPLOAD_BYTES + 100_000)
    res = upload_batch(client, [("a.xml", too_big)])
    assert res.status_code == 413
    assert "Batch is too large" in res.json()["detail"]


def test_batch_files_are_written_to_the_audit_log(client, tmp_path):
    upload_batch(client, [("a.xml", make_xml("TXN-1", "1")), ("b.txt", b"x")])
    upload(client, make_xml("TXN-2", "1"), name="c.xml")
    lines = (tmp_path / "results" / "audit_log.jsonl").read_text().splitlines()
    entries = [json.loads(line) for line in lines]
    # The rejected .txt file is not logged, like a rejected single upload.
    assert [(e["source_file"], e["origin"]) for e in entries] == [
        ("a.xml", "web-batch"),
        ("c.xml", "web"),
    ]


# ---------- Audit trail, rules, model card ----------


def test_audit_endpoint_lists_newest_first_and_filters(client):
    assert client.get("/api/audit").json() == {
        "total": 0,
        "counts": {"VALID": 0, "INVALID": 0, "REQUIRES_REVIEW": 0},
        "matching": 0,
        "entries": [],
    }
    upload(client, make_xml("TXN-1", "10"), name="a.xml")
    upload(client, make_xml("TXN-2", "abc"), name="b.xml")
    upload(client, make_xml("TXN-3", "20"), name="c.xml")

    body = client.get("/api/audit").json()
    assert body["total"] == 3
    assert body["counts"] == {"VALID": 2, "INVALID": 1, "REQUIRES_REVIEW": 0}
    assert [e["entry"]["source_file"] for e in body["entries"]] == ["c.xml", "b.xml", "a.xml"]
    # Each item carries its exact line from the log, ready to copy.
    assert json.loads(body["entries"][0]["line"]) == body["entries"][0]["entry"]

    invalid = client.get("/api/audit", params={"status": "INVALID"}).json()
    assert invalid["matching"] == 1
    assert invalid["entries"][0]["entry"]["transaction_id"] == "TXN-2"

    limited = client.get("/api/audit", params={"limit": 1}).json()
    assert limited["matching"] == 3 and len(limited["entries"]) == 1


def test_audit_endpoint_validates_its_parameters(client):
    assert client.get("/api/audit", params={"status": "MAYBE"}).status_code == 422
    assert client.get("/api/audit", params={"limit": 0}).status_code == 422
    assert client.get("/api/audit", params={"limit": 501}).status_code == 422


def test_rules_endpoint(client):
    body = client.get("/api/rules").json()
    assert [r["code"] for r in body["rules"]] == [
        "missing_id",
        "missing_amount",
        "amount_not_numeric",
        "amount_negative",
        "amount_above_review_limit",
    ]
    assert body["rules"][-1]["outcome"] == "REQUIRES_REVIEW"
    assert body["id_tags"][0] == "TransactionID"
    assert body["review_threshold"] == 1_000_000


def test_model_card_without_a_trained_model(client):
    card = client.get("/api/model").json()
    assert card["trained"] is False
    assert card["holdout"] is None
    assert len(card["features"]) == 8
    assert all(f["label"] for f in card["features"])


# ---------- Errors, streaming batch, dashboard, filters, headers ----------


def test_malformed_xml_response_points_at_the_line(client):
    res = upload(client, b"<Invoice>\n<ID>1</ID>\n<Amount>5</Total>\n</Invoice>")
    assert res.status_code == 400
    assert res.json() == {
        "detail": "Invalid or malformed XML file",
        "line": 3,
        "column": 12,
        "reason": "mismatched tag",
    }


def test_empty_file_is_refused_with_a_plain_message(client):
    for content in (b"", b" \n "):
        res = upload(client, content, name="empty.xml")
        assert res.status_code == 400
        assert res.json() == {"detail": "The file is empty"}
    row = upload_batch(client, [("empty.xml", b"")]).json()["results"][0]
    assert row["status"] == "REJECTED"
    assert row["errors"] == ["The file is empty"] and row["parse_error"] is None


def test_result_says_whether_it_was_logged(client, tmp_path, monkeypatch):
    body = upload(client, make_xml("TXN-1", "10")).json()
    assert body["logged"] is True
    # logged_at is the exact timestamp of the audit entry, so the page can find its own checks.
    entry = client.get("/api/audit").json()["entries"][0]["entry"]
    assert body["logged_at"] == entry["timestamp"]
    blocker = tmp_path / "read_only"
    blocker.write_text("a file where a directory should be")
    monkeypatch.setattr(server, "AUDIT_DIR", str(blocker / "results"))
    body = upload(client, make_xml("TXN-2", "10")).json()
    assert body["logged"] is False and body["logged_at"] is None


def test_batch_results_carry_their_audit_timestamp(client):
    rows = upload_batch(client, [("a.xml", make_xml("TXN-1", "1"))]).json()["results"]
    entry = client.get("/api/audit").json()["entries"][0]["entry"]
    assert rows[0]["logged"] is True and rows[0]["logged_at"] == entry["timestamp"]


def test_audit_entries_keep_the_display_features(client):
    body = upload(client, make_xml("TXN-1", "10"), name="a.xml").json()
    entry = client.get("/api/audit").json()["entries"][0]["entry"]
    assert entry["xml_size"] == body["features"]["xml_size"]
    assert entry["nesting_depth"] == body["features"]["nesting_depth"]
    assert entry["missing_optional_fields"] == body["features"]["missing_optional_fields"]
    assert entry["processing_ms"] == body["processing_ms"]


def read_stream(res):
    return [json.loads(line) for line in res.text.splitlines() if line]


def test_streamed_batch_reports_each_file_then_a_summary(client):
    files = [
        ("ok.xml", make_xml("TXN-1", "10")),
        ("notes.txt", b"hello"),
        ("big.xml", make_xml("TXN-3", "5000000")),
    ]
    parts = [("files", (name, content, "text/xml")) for name, content in files]
    res = client.post("/api/analyze/batch/stream", files=parts)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/x-ndjson")

    lines = read_stream(res)
    assert lines[0] == {"type": "start", "count": 3}
    assert [line["type"] for line in lines[1:]] == ["result", "result", "result", "summary"]
    assert [line["index"] for line in lines[1:4]] == [0, 1, 2]
    statuses = [line["result"]["status"] for line in lines[1:4]]
    assert statuses == ["VALID", "REJECTED", "REQUIRES_REVIEW"]

    # The same rows as the one-shot batch endpoint (apart from measured times).
    batch = upload_batch(client, files).json()
    assert lines[-1]["summary"] == batch["summary"]
    for line, row in zip(lines[1:4], batch["results"], strict=True):
        for key in ("filename", "status", "errors", "checks", "findings", "features"):
            assert line["result"][key] == row[key]


def test_streamed_batch_has_the_same_limits(client):
    files = [(f"f{i}.xml", make_xml(f"TXN-{i}", "1")) for i in range(server.MAX_BATCH_FILES + 1)]
    parts = [("files", (name, content, "text/xml")) for name, content in files]
    assert client.post("/api/analyze/batch/stream", files=parts).status_code == 400

    too_big = b"x" * (server.MAX_BATCH_FILES * server.MAX_UPLOAD_BYTES + 100_000)
    res = client.post(
        "/api/analyze/batch/stream", files=[("files", ("a.xml", too_big, "text/xml"))]
    )
    assert res.status_code == 413


def test_rejected_batch_row_says_where_the_xml_breaks(client):
    body = upload_batch(client, [("broken.xml", b"<Invoice>\n<ID>1</Invoice>")]).json()
    row = body["results"][0]
    assert row["status"] == "REJECTED"
    assert row["parse_error"]["line"] == 2
    assert row["parse_error"]["reason"] == "mismatched tag"


def test_audit_search_and_origin_filters(client):
    upload(client, make_xml("TXN-1", "10"), name="alpha.xml")
    upload(client, make_xml("TXN-2", "abc"), name="beta.xml")
    upload_batch(client, [("gamma.xml", make_xml("TXN-3", "10"))])

    by_name = client.get("/api/audit", params={"q": "BETA"}).json()
    assert [e["entry"]["source_file"] for e in by_name["entries"]] == ["beta.xml"]
    # Status counts follow the search, so each status filter shows what it would match.
    assert by_name["counts"] == {"VALID": 0, "INVALID": 1, "REQUIRES_REVIEW": 0}
    assert by_name["total"] == 3

    assert client.get("/api/audit", params={"q": "txn-3"}).json()["matching"] == 1

    batch_only = client.get("/api/audit", params={"origin": "web-batch"}).json()
    assert [e["entry"]["source_file"] for e in batch_only["entries"]] == ["gamma.xml"]
    singles = client.get("/api/audit", params={"origin": "web", "status": "VALID"}).json()
    assert [e["entry"]["source_file"] for e in singles["entries"]] == ["alpha.xml"]

    assert client.get("/api/audit", params={"origin": "elsewhere"}).status_code == 422
    assert client.get("/api/audit", params={"q": "x" * 201}).status_code == 422


def test_overview_is_computed_from_the_audit_log(client):
    empty = client.get("/api/overview").json()
    assert empty["total"] == 0 and empty["valid_share"] is None and empty["recent"] == []

    upload(client, make_xml("TXN-1", "10"), name="a.xml")
    upload(client, make_xml("TXN-2", "abc"), name="b.xml")
    upload(client, make_xml(None, "abc"), name="c.xml")

    body = client.get("/api/overview", params={"recent": 2}).json()
    assert body["total"] == 3
    assert body["counts"] == {"VALID": 1, "INVALID": 2, "REQUIRES_REVIEW": 0}
    assert body["origins"]["web"] == 3
    assert body["valid_share"] == 33.33 and body["invalid_rate"] == 66.67
    # No trained model in this test server, so nothing is scored.
    assert body["scored"] == 0 and body["average_risk"] is None
    assert body["top_reasons"][0] == {
        "reason": "Invalid format: AMOUNT must be numeric",
        "status": "INVALID",
        "count": 2,
    }
    assert [e["source_file"] for e in body["recent"]] == ["c.xml", "b.xml"]
    assert client.get("/api/overview", params={"recent": 0}).status_code == 422


def test_samples_list_their_expected_status(client):
    samples = client.get("/api/samples").json()
    assert {s["expected"] for s in samples} == {"VALID", "INVALID", "REQUIRES_REVIEW"}


def test_frontend_is_served_with_security_headers(client):
    res = client.get("/")
    policy = res.headers["content-security-policy"]
    assert "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
    assert res.headers["x-content-type-options"] == "nosniff"
    # The interactive API docs load their own scripts and are left alone.
    assert "content-security-policy" not in client.get("/docs").headers


def test_api_routes_are_grouped_in_the_docs(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/api/analyze"]["post"]["tags"] == ["analysis"]
    assert paths["/api/analyze/batch/stream"]["post"]["tags"] == ["analysis"]
    assert paths["/api/overview"]["get"]["tags"] == ["dashboard"]
    assert paths["/api/audit"]["get"]["tags"] == ["audit"]
