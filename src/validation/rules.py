import re
from enum import Enum

_NUMBER_RE = re.compile(r"^-?(\d+(\.\d*)?|\.\d+)$", re.ASCII)

# Amounts above this need a person to approve them before processing.
REVIEW_THRESHOLD = 1_000_000


class Status(Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


def parse_amount(raw) -> tuple[str, float | None]:
    """
    Classifies a raw amount as "missing", "invalid" (not a plain decimal number),
    "negative" or "ok", and returns its value when it is a number.
    """
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return "missing", None
    if not _NUMBER_RE.match(text):
        return "invalid", None
    value = float(text)
    if text.startswith("-"):
        return "negative", value
    return "ok", value


class Validator:
    """
    Deterministic rule-based validation engine for standardized supplier XML data.
    """

    @staticmethod
    def validate(record: dict) -> tuple[Status, list[str]]:
        """
        Validates a structured record based on deterministic rules.
        Returns the classification status and a list of error messages.
        """
        errors = []

        # Rule 1: Missing ID -> FAIL
        if not record.get("ID") or not str(record.get("ID")).strip():
            errors.append("Missing required field: ID")

        # Rule 2: Missing, non-numeric or negative Amount -> FAIL
        amount_kind, amount = parse_amount(record.get("AMOUNT"))
        if amount_kind == "missing":
            errors.append("Missing required field: AMOUNT")
        elif amount_kind == "invalid":
            errors.append("Invalid format: AMOUNT must be numeric")
        elif amount_kind == "negative":
            errors.append("Invalid value: AMOUNT must not be negative")

        # Classify
        if errors:
            return Status.INVALID, errors

        # Rule 3: Requires Review (suspicious large amounts)
        if amount > REVIEW_THRESHOLD:
            return Status.REQUIRES_REVIEW, ["High value amount, requires manual review"]

        return Status.VALID, []
