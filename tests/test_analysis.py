import pytest

from src.api.analysis import AnalysisError, analyze_document, check_upload
from src.prediction.model import RiskPredictor


def analyze(xml: str) -> dict:
    # An untrained model: these tests are about validation and locating findings.
    return analyze_document("t.xml", xml.encode(), RiskPredictor())


def only_finding(result: dict) -> dict:
    assert len(result["findings"]) == 1
    return result["findings"][0]


def test_valid_document_reports_where_the_id_and_amount_were_found():
    result = analyze(
        "<Invoice>\n  <Ref><TransactionID>TXN-1</TransactionID></Ref>\n"
        "  <PayableAmount>10.00</PayableAmount>\n</Invoice>"
    )
    assert result["status"] == "VALID"
    assert result["findings"] == []
    assert result["fields"]["ID"] == {
        "value": "TXN-1",
        "path": "Invoice.Ref.TransactionID",
        "line": 2,
        "end_line": 2,
    }
    assert result["fields"]["AMOUNT"]["line"] == 3
    assert result["prediction"] == {"risk_score": "N/A", "risk_flag": "N/A"}


def test_bad_amount_points_at_the_amount_element():
    finding = only_finding(
        analyze(
            "<Invoice>\n<TransactionID>T</TransactionID>\n"
            "<Totals>\n<PayableAmount>1.250,00</PayableAmount>\n</Totals>\n</Invoice>"
        )
    )
    assert finding["rule"] == "amount_not_numeric"
    assert finding["target"] == "value"
    assert finding["line"] == 4
    assert '"1.250,00"' in finding["note"]


def test_high_value_finding_mentions_the_review_limit():
    result = analyze(
        "<Invoice>\n<TransactionID>T</TransactionID>\n<Amount>2000000</Amount>\n</Invoice>"
    )
    assert result["status"] == "REQUIRES_REVIEW"
    finding = only_finding(result)
    assert finding["rule"] == "amount_above_review_limit"
    assert finding["line"] == 3
    assert "1,000,000 review limit" in finding["note"]


def test_empty_element_is_pointed_at():
    finding = only_finding(
        analyze("<Invoice>\n<TransactionID>T</TransactionID>\n<PayableAmount/>\n</Invoice>")
    )
    assert finding["rule"] == "missing_amount"
    assert finding["target"] == "empty"
    assert finding["line"] == 3


def test_missing_amount_is_expected_in_the_totals_block():
    finding = only_finding(
        analyze(
            "<Invoice>\n<TransactionID>T</TransactionID>\n"
            "<LegalMonetaryTotal>\n<LineTotal>5</LineTotal>\n</LegalMonetaryTotal>\n</Invoice>"
        )
    )
    assert finding["target"] == "expected"
    assert finding["line"] == 3
    assert "<LegalMonetaryTotal> on line 3" in finding["note"]


def test_missing_id_ignores_a_nested_account_id():
    result = analyze(
        "<Doc>\n<Invoice>\n<PaymentMeans>\n<Account>\n<ID>IBAN-1</ID>\n</Account>\n"
        "</PaymentMeans>\n<PayableAmount>5</PayableAmount>\n</Invoice>\n</Doc>"
    )
    finding = only_finding(result)
    assert finding["rule"] == "missing_id"
    # Not the account <ID> on line 5: the invoice the ID was expected in.
    assert finding["target"] == "expected"
    assert finding["line"] == 2


def test_two_findings_keep_the_rule_order():
    result = analyze("<Invoice>\n<Amount>-5</Amount>\n</Invoice>")
    assert [f["rule"] for f in result["findings"]] == ["missing_id", "amount_negative"]
    assert result["errors"] == [f["message"] for f in result["findings"]]


def test_unreadable_document_is_an_analysis_error():
    with pytest.raises(AnalysisError) as error:
        analyze("<Invoice>")
    assert error.value.status_code == 400


def test_check_upload_refuses_other_extensions_and_big_files():
    with pytest.raises(AnalysisError) as error:
        check_upload("notes.txt", b"x", 10)
    assert error.value.status_code == 400
    with pytest.raises(AnalysisError) as error:
        check_upload("big.XML", b"x" * 11, 10)
    assert error.value.status_code == 413
    check_upload("ok.xml", b"x" * 10, 10)


def checks_by_rule(result: dict) -> dict:
    return {check["rule"]: check for check in result["checks"]}


def test_checks_list_every_rule_with_its_evidence():
    result = analyze(
        "<Invoice>\n<TransactionID>T-9</TransactionID>\n<PayableAmount>12,50</PayableAmount>\n</Invoice>"
    )
    checks = checks_by_rule(result)
    assert list(checks) == [
        "missing_id",
        "missing_amount",
        "amount_not_numeric",
        "amount_negative",
        "amount_above_review_limit",
    ]
    assert checks["missing_id"]["state"] == "passed"
    assert checks["missing_id"]["line"] == 2
    assert checks["missing_id"]["note"] == "T-9 found on line 2."
    assert checks["amount_not_numeric"]["state"] == "broken"
    assert checks["amount_not_numeric"]["outcome"] == "INVALID"
    assert checks["amount_not_numeric"]["line"] == 3
    assert checks["amount_negative"]["state"] == "skipped"
    assert checks["amount_above_review_limit"]["note"].startswith("Not checked")
    # The broken checks are exactly the findings.
    broken = [c for c in result["checks"] if c["state"] == "broken"]
    assert [(c["rule"], c["line"]) for c in broken] == [
        (f["rule"], f["line"]) for f in result["findings"]
    ]


def test_review_check_is_flagged_with_its_outcome():
    result = analyze("<Invoice>\n<ID>T</ID>\n<Amount>2000000</Amount>\n</Invoice>")
    check = checks_by_rule(result)["amount_above_review_limit"]
    assert (check["state"], check["outcome"], check["line"]) == ("broken", "REQUIRES_REVIEW", 3)


def test_stage_timings_are_measured():
    result = analyze("<Invoice><ID>T</ID><Amount>5</Amount></Invoice>")
    timings = result["timings_ms"]
    assert list(timings) == ["parse", "validate", "score", "locate"]
    assert all(t >= 0 for t in timings.values())
    assert sum(timings.values()) <= result["processing_ms"] + 0.05


def test_untrained_model_gives_no_risk_drivers():
    assert analyze("<Invoice><ID>T</ID><Amount>5</Amount></Invoice>")["risk_drivers"] is None


def test_malformed_xml_error_says_where():
    with pytest.raises(AnalysisError) as error:
        analyze("<Invoice>\n<ID>T</ID>\n<Amount>5</Total>\n</Invoice>")
    body = error.value.to_json()
    assert body == {
        "detail": "Invalid or malformed XML file",
        "line": 3,
        "column": 12,
        "reason": "mismatched tag",
    }


def test_errors_without_a_position_only_have_a_detail():
    with pytest.raises(AnalysisError) as error:
        check_upload("notes.txt", b"x", 10)
    assert error.value.to_json() == {"detail": "Only .xml files are supported"}
