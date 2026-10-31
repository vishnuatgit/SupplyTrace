import os

from src.validation.rules import REVIEW_THRESHOLD, parse_amount

# Amounts at or above this are unusual for the synthetic suppliers, though still valid.
LARGE_AMOUNT = 100_000

# Optional invoice fields. A field counts as present when any segment of a
# populated flattened key matches one of its tag names (keys are uppercased).
OPTIONAL_FIELDS = {
    "issue_date": {"ISSUEDATE", "INVOICEDATE"},
    "currency": {"DOCUMENTCURRENCYCODE", "CURRENCYCODE", "CURRENCY"},
    "supplier": {"ACCOUNTINGSUPPLIERPARTY", "SUPPLIER", "SUPPLIERNAME", "SELLER", "SELLERPARTY"},
    "payment_account": {"PAYEEFINANCIALACCOUNT", "IBAN", "BANKACCOUNT"},
}

# What each model feature means, in plain language (shown on the model card).
FEATURE_DESCRIPTIONS = {
    "missing_id": "1 if no transaction ID was found",
    "missing_amount": "1 if no amount was found",
    "amount_not_numeric": "1 if the amount is not a plain decimal number",
    "amount_negative": "1 if the amount is below zero",
    "amount_above_review_limit": f"1 if the amount is above the {REVIEW_THRESHOLD:,} review limit",
    "large_amount": f"1 if the amount is {LARGE_AMOUNT:,} or more",
    "missing_optional_fields": (
        "How many of issue date, currency, supplier and payment account are absent (0 to 4)"
    ),
    "nesting_depth": "How many levels deep the most deeply nested value sits",
}

# Short names for the same features, for charts and the risk explanation.
FEATURE_LABELS = {
    "missing_id": "Transaction ID missing",
    "missing_amount": "Amount missing",
    "amount_not_numeric": "Amount not a number",
    "amount_negative": "Amount negative",
    "amount_above_review_limit": "Amount above review limit",
    "large_amount": f"Amount {LARGE_AMOUNT:,} or more",
    "missing_optional_fields": "Optional fields missing",
    "nesting_depth": "Nesting depth",
}

# Keys added by XMLParser.standardize rather than taken from the document.
_MAPPED_KEYS = {"ID", "AMOUNT", "_source_file"}


class FeatureExtractor:
    """
    Extracts risk signals from standardized records for the ML prediction model.
    """

    EXPECTED_FIELDS = {"ID", "AMOUNT"}

    @staticmethod
    def extract_features(record: dict, file_path: str = None, xml_size: int = None) -> dict:
        """
        Extracts the model features (see RiskPredictor.FEATURE_COLUMNS) plus two
        display-only values: missing_fields and xml_size.
        """
        features = {}

        # 1. Required fields: transaction ID and amount
        missing_id = not record.get("ID") or not str(record.get("ID")).strip()
        amount_kind, amount = parse_amount(record.get("AMOUNT"))
        features["missing_id"] = int(missing_id)
        features["missing_amount"] = int(amount_kind == "missing")
        features["amount_not_numeric"] = int(amount_kind == "invalid")
        features["amount_negative"] = int(amount_kind == "negative")

        # 2. Amount size: above the review limit, or merely large
        features["amount_above_review_limit"] = int(
            amount_kind == "ok" and amount > REVIEW_THRESHOLD
        )
        features["large_amount"] = int(amount_kind == "ok" and amount >= LARGE_AMOUNT)

        # 3. Structure: optional fields left out, and how deep the content sits
        segments = [
            key.split(".")
            for key, value in record.items()
            if key not in _MAPPED_KEYS and value and str(value).strip()
        ]
        present = {
            name
            for name, tags in OPTIONAL_FIELDS.items()
            if any(tags.intersection(parts) for parts in segments)
        }
        features["missing_optional_fields"] = len(OPTIONAL_FIELDS) - len(present)
        features["nesting_depth"] = max((len(parts) for parts in segments), default=0)

        # Display only: count of missing required fields, and payload size in bytes
        features["missing_fields"] = features["missing_id"] + features["missing_amount"]
        if xml_size is not None:
            features["xml_size"] = xml_size
        elif file_path and os.path.exists(file_path):
            features["xml_size"] = os.path.getsize(file_path)
        else:
            features["xml_size"] = len(str(record))

        return features
