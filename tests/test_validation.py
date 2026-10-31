from src.validation.rules import Status, Validator, parse_amount


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
