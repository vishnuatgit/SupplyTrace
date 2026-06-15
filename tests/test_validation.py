from src.validation.rules import Validator, Status

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
