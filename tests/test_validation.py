import pytest

from src.ingestion.parser import XMLParser
from src.ingestion.xml_loader import XMLLoader
from src.prediction.model import RiskPredictor
from src.validation.rules import (
    AMOUNT_NOT_NUMERIC,
    BROKEN,
    MISSING_ID,
    PASSED,
    RULES,
    SKIPPED,
    Status,
    Validator,
    parse_amount,
)


def test_validation_valid():
    record = {"ID": "001", "AMOUNT": "500"}
    status, errors = Validator.validate(record)
    assert status == Status.VALID
    assert len(errors) == 0


def test_validation_missing_id():
    record = {"AMOUNT": "500"}
    status, errors = Validator.validate(record)
    assert status == Status.INVALID
    assert "Missing required field: ID" in errors


def test_validation_empty_amount():
    record = {"ID": "001", "AMOUNT": " "}
    status, errors = Validator.validate(record)
    assert status == Status.INVALID
    assert "Missing required field: AMOUNT" in errors


def test_validation_invalid_amount_format():
    record = {"ID": "001", "AMOUNT": "abc"}
    status, errors = Validator.validate(record)
    assert status == Status.INVALID
    assert "Invalid format: AMOUNT must be numeric" in errors


def test_validation_requires_review():
    record = {"ID": "002", "AMOUNT": "5000000"}
    status, errors = Validator.validate(record)
    assert status == Status.REQUIRES_REVIEW
    assert "High value amount, requires manual review" in errors


def test_validation_unicode_digit_amount_is_invalid_not_a_crash():
    # "²".isdigit() is True but float() rejects it; the rule must not crash.
    status, errors = Validator.validate({"ID": "001", "AMOUNT": "²"})
    assert status == Status.INVALID
    assert "Invalid format: AMOUNT must be numeric" in errors


def test_validation_review_threshold_boundary():
    assert Validator.validate({"ID": "1", "AMOUNT": "1000000"})[0] == Status.VALID
    assert Validator.validate({"ID": "1", "AMOUNT": "1000000.01"})[0] == Status.REQUIRES_REVIEW


def test_validation_negative_amount_has_its_own_message():
    status, errors = Validator.validate({"ID": "001", "AMOUNT": "-250.00"})
    assert status == Status.INVALID
    assert errors == ["Invalid value: AMOUNT must not be negative"]


def test_parse_amount_kinds():
    assert parse_amount(None) == ("missing", None)
    assert parse_amount("  ") == ("missing", None)
    assert parse_amount("12,50.00") == ("invalid", None)
    assert parse_amount("-5") == ("negative", -5.0)
    assert parse_amount(" 99.5 ") == ("ok", 99.5)


def test_every_rule_example_breaks_that_rule():
    # The examples on the rules page are real documents run through the pipeline.
    for rule in RULES:
        record = XMLParser.standardize(XMLLoader.parse_bytes(rule.example.encode()))
        status, broken = Validator.check(record)
        assert broken == [rule], rule.code
        assert status == rule.outcome


def test_rule_codes_match_model_features():
    # Each rule has a model feature of the same name (see FeatureExtractor).
    assert {rule.code for rule in RULES} <= set(RiskPredictor.FEATURE_COLUMNS)


def test_validate_returns_the_messages_of_the_broken_rules():
    status, broken = Validator.check({"AMOUNT": "abc"})
    assert status == Status.INVALID
    assert broken == [MISSING_ID, AMOUNT_NOT_NUMERIC]
    assert Validator.validate({"AMOUNT": "abc"})[1] == [r.message for r in broken]


def checklist_states(record):
    return {rule.code: state for rule, state in Validator.checklist(record)}


def test_checklist_covers_every_rule_in_order():
    rules = [rule for rule, _state in Validator.checklist({"ID": "1", "AMOUNT": "5"})]
    assert rules == list(RULES)
    assert set(checklist_states({"ID": "1", "AMOUNT": "5"}).values()) == {PASSED}


def test_checklist_skips_rules_it_cannot_reach():
    # No amount: the format and sign rules have nothing to check.
    states = checklist_states({"ID": "1"})
    assert states["missing_amount"] == BROKEN
    assert states["amount_not_numeric"] == SKIPPED
    assert states["amount_negative"] == SKIPPED
    assert states["amount_above_review_limit"] == SKIPPED

    # A non-numeric amount cannot be negative or too high.
    states = checklist_states({"ID": "1", "AMOUNT": "abc"})
    assert states["amount_not_numeric"] == BROKEN
    assert states["amount_negative"] == SKIPPED

    # The review limit only applies when everything else passes.
    states = checklist_states({"AMOUNT": "5000000"})
    assert states["missing_id"] == BROKEN
    assert states["amount_negative"] == PASSED
    assert states["amount_above_review_limit"] == SKIPPED
    assert checklist_states({"ID": "1", "AMOUNT": "5000000"})["amount_above_review_limit"] == BROKEN


@pytest.mark.parametrize(
    "record",
    [
        {},
        {"ID": "1"},
        {"AMOUNT": "5"},
        {"ID": "1", "AMOUNT": "abc"},
        {"ID": "1", "AMOUNT": "-1"},
        {"AMOUNT": "-1"},
        {"ID": "1", "AMOUNT": "1000000.01"},
        {"ID": " ", "AMOUNT": "1000000.01"},
        {"ID": "1", "AMOUNT": "0"},
    ],
)
def test_check_is_the_broken_part_of_the_checklist(record):
    status, broken = Validator.check(record)
    assert broken == [rule for rule, state in Validator.checklist(record) if state == BROKEN]
    if not broken:
        assert status == Status.VALID
    elif all(rule.outcome is Status.REQUIRES_REVIEW for rule in broken):
        assert status == Status.REQUIRES_REVIEW
    else:
        assert status == Status.INVALID
