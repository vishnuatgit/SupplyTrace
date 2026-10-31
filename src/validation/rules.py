import re
from dataclasses import dataclass
from enum import Enum

_NUMBER_RE = re.compile(r"^-?(\d+(\.\d*)?|\.\d+)$", re.ASCII)

# Amounts above this need a person to approve them before processing.
REVIEW_THRESHOLD = 1_000_000


class Status(Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"


@dataclass(frozen=True)
class Rule:
    """One validation rule, described once and used by the validator, the API and the rules page."""

    code: str  # stable identifier; also the name of the matching model feature
    title: str  # short name for people
    field: str  # the standardized field it checks: "ID" or "AMOUNT"
    outcome: Status  # the status a file gets when it breaks this rule
    message: str  # shown to users and written to the audit log
    summary: str  # the rule in plain language
    example: str  # a tiny XML document that breaks the rule (the tests check that it does)


MISSING_ID = Rule(
    code="missing_id",
    title="Transaction ID is present",
    field="ID",
    outcome=Status.INVALID,
    message="Missing required field: ID",
    summary="Every invoice needs a transaction ID, so it can be matched and traced later.",
    example="<Invoice>\n  <PayableAmount>120.00</PayableAmount>\n</Invoice>",
)
MISSING_AMOUNT = Rule(
    code="missing_amount",
    title="Amount is present",
    field="AMOUNT",
    outcome=Status.INVALID,
    message="Missing required field: AMOUNT",
    summary="Every invoice needs a total amount to pay.",
    example="<Invoice>\n  <TransactionID>TXN-1</TransactionID>\n</Invoice>",
)
AMOUNT_NOT_NUMERIC = Rule(
    code="amount_not_numeric",
    title="Amount is a number",
    field="AMOUNT",
    outcome=Status.INVALID,
    message="Invalid format: AMOUNT must be numeric",
    summary=(
        "The amount must be a plain decimal number such as 2867.70: "
        "no thousands separators, currency codes or words."
    ),
    example=(
        "<Invoice>\n  <TransactionID>TXN-1</TransactionID>\n"
        "  <PayableAmount>12,50.00</PayableAmount>\n</Invoice>"
    ),
)
AMOUNT_NEGATIVE = Rule(
    code="amount_negative",
    title="Amount is not negative",
    field="AMOUNT",
    outcome=Status.INVALID,
    message="Invalid value: AMOUNT must not be negative",
    summary="An amount to pay cannot be below zero.",
    example=(
        "<Invoice>\n  <TransactionID>TXN-1</TransactionID>\n"
        "  <PayableAmount>-120.00</PayableAmount>\n</Invoice>"
    ),
)
AMOUNT_ABOVE_REVIEW_LIMIT = Rule(
    code="amount_above_review_limit",
    title="Amount is within the review limit",
    field="AMOUNT",
    outcome=Status.REQUIRES_REVIEW,
    message="High value amount, requires manual review",
    summary=(
        f"An amount above {REVIEW_THRESHOLD:,} is not wrong, "
        "but a person has to approve it before processing."
    ),
    example=(
        "<Invoice>\n  <TransactionID>TXN-1</TransactionID>\n"
        "  <PayableAmount>4750000.00</PayableAmount>\n</Invoice>"
    ),
)

# In the order the validator applies them.
RULES = (MISSING_ID, MISSING_AMOUNT, AMOUNT_NOT_NUMERIC, AMOUNT_NEGATIVE, AMOUNT_ABOVE_REVIEW_LIMIT)


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


# What can happen to a rule when a record is checked.
PASSED = "passed"
BROKEN = "broken"
SKIPPED = "skipped"  # not reached: an earlier problem means it cannot be checked


class Validator:
    """
    Deterministic rule-based validation engine for standardized supplier XML data.
    """

    @staticmethod
    def checklist(record: dict) -> list[tuple[Rule, str]]:
        """
        Every rule, in order, with what happened to it: PASSED, BROKEN or SKIPPED.
        The amount rules are skipped when there is no usable amount to check, and
        the review limit is only checked when every other rule passes.
        """
        has_id = bool(record.get("ID")) and bool(str(record.get("ID")).strip())
        amount_kind, amount = parse_amount(record.get("AMOUNT"))

        states = {
            MISSING_ID: PASSED if has_id else BROKEN,
            MISSING_AMOUNT: BROKEN if amount_kind == "missing" else PASSED,
        }
        if amount_kind == "missing":
            states[AMOUNT_NOT_NUMERIC] = SKIPPED
        else:
            states[AMOUNT_NOT_NUMERIC] = BROKEN if amount_kind == "invalid" else PASSED
        if amount_kind in ("missing", "invalid"):
            states[AMOUNT_NEGATIVE] = SKIPPED
        else:
            states[AMOUNT_NEGATIVE] = BROKEN if amount_kind == "negative" else PASSED

        if BROKEN in states.values():
            states[AMOUNT_ABOVE_REVIEW_LIMIT] = SKIPPED
        else:
            states[AMOUNT_ABOVE_REVIEW_LIMIT] = BROKEN if amount > REVIEW_THRESHOLD else PASSED

        return [(rule, states[rule]) for rule in RULES]

    @staticmethod
    def check(record: dict) -> tuple[Status, list[Rule]]:
        """
        Applies the rules to a standardized record.
        Returns the classification status and the rules the record breaks.
        """
        broken = [rule for rule, state in Validator.checklist(record) if state == BROKEN]
        if any(rule.outcome is Status.INVALID for rule in broken):
            return Status.INVALID, broken
        if broken:
            # A correct but very large amount needs a person to approve it
            return Status.REQUIRES_REVIEW, broken
        return Status.VALID, []

    @staticmethod
    def validate(record: dict) -> tuple[Status, list[str]]:
        """
        Validates a structured record based on deterministic rules.
        Returns the classification status and a list of error messages.
        """
        status, broken = Validator.check(record)
        return status, [rule.message for rule in broken]
