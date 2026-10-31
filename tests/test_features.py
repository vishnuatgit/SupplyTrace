import os
import tempfile

from src.features.extractor import FeatureExtractor
from src.prediction.model import RiskPredictor

# A standardized record as XMLParser produces it for a complete UBL-style invoice.
COMPLETE = {
    "INVOICE.DOCUMENTREFERENCE.TRANSACTIONID": "TXN-1",
    "INVOICE.ISSUEDATE": "2026-10-14",
    "INVOICE.DOCUMENTCURRENCYCODE": "USD",
    "INVOICE.ACCOUNTINGSUPPLIERPARTY.PARTY.PARTYNAME.NAME": "Acme",
    "INVOICE.PAYMENTMEANS.PAYEEFINANCIALACCOUNT.ID": "IBAN-1",
    "INVOICE.LEGALMONETARYTOTAL.PAYABLEAMOUNT": "500",
    "ID": "TXN-1",
    "AMOUNT": "500",
}


def test_feature_extraction_complete_record():
    features = FeatureExtractor.extract_features(COMPLETE)

    for col in RiskPredictor.FEATURE_COLUMNS:
        assert col in features
    assert features["missing_fields"] == 0
    assert features["missing_optional_fields"] == 0
    assert features["nesting_depth"] == 5
    assert features["xml_size"] > 0
    # Simulated values are gone: nothing is invented about latency or retries.
    assert "processing_time" not in features
    assert "retry_attempts" not in features


def test_feature_extraction_missing_fields():
    record = {"AMOUNT": "500"}  # Missing ID
    features = FeatureExtractor.extract_features(record)

    assert features["missing_fields"] == 1
    assert features["missing_id"] == 1
    assert features["missing_amount"] == 0
    assert features["missing_optional_fields"] == 4


def test_amount_signals():
    def signals(amount):
        features = FeatureExtractor.extract_features({"ID": "1", "AMOUNT": amount})
        return (
            features["missing_amount"],
            features["amount_not_numeric"],
            features["amount_negative"],
            features["large_amount"],
            features["amount_above_review_limit"],
        )

    assert signals("") == (1, 0, 0, 0, 0)
    assert signals("12,50.00") == (0, 1, 0, 0, 0)
    assert signals("-40") == (0, 0, 1, 0, 0)
    assert signals("99999.99") == (0, 0, 0, 0, 0)
    assert signals("100000") == (0, 0, 0, 1, 0)
    assert signals("5000000") == (0, 0, 0, 1, 1)


def test_optional_fields_and_depth_follow_the_document():
    sparse = {
        key: value
        for key, value in COMPLETE.items()
        if "ISSUEDATE" not in key and "ACCOUNTINGSUPPLIERPARTY" not in key
    }
    features = FeatureExtractor.extract_features(sparse)
    assert features["missing_optional_fields"] == 2
    assert features["nesting_depth"] == 4

    wrapped = {f"ENVELOPE.BODY.{key}": value for key, value in COMPLETE.items()}
    assert FeatureExtractor.extract_features(wrapped)["nesting_depth"] == 7


def test_feature_extraction_with_file():
    record = {"ID": "002", "AMOUNT": "1000"}

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w") as f:
        f.write("<invoice><id>002</id><amount>1000</amount></invoice>")
        temp_path = f.name

    try:
        features = FeatureExtractor.extract_features(record, file_path=temp_path)
        assert features["xml_size"] == os.path.getsize(temp_path)
    finally:
        os.remove(temp_path)


def test_explicit_xml_size_wins():
    assert FeatureExtractor.extract_features({"ID": "1"}, xml_size=1234)["xml_size"] == 1234


def test_feature_extraction_is_deterministic():
    record = {"ID": "003", "AMOUNT": "10"}
    assert FeatureExtractor.extract_features(record) == FeatureExtractor.extract_features(record)
