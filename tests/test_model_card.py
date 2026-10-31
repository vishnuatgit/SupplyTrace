import pandas as pd

from src.features.extractor import FEATURE_DESCRIPTIONS
from src.prediction.model import RiskPredictor
from src.prediction.model_card import build_model_card, holdout_evaluation


def test_every_model_feature_is_described():
    assert list(FEATURE_DESCRIPTIONS) == RiskPredictor.FEATURE_COLUMNS


def test_holdout_metrics_are_consistent(synthetic_batch):
    holdout = holdout_evaluation(synthetic_batch["df"])
    assert holdout["train_rows"] + holdout["test_rows"] == len(synthetic_batch["df"])
    for name in ("model", "rules_baseline"):
        m = holdout[name]
        cells = m["true_positives"] + m["false_positives"]
        cells += m["true_negatives"] + m["false_negatives"]
        assert cells == holdout["test_rows"]
        assert m["true_positives"] + m["false_negatives"] == holdout["test_failed"]
        assert 0 <= m["accuracy"] <= 1 and 0 <= m["roc_auc"] <= 1


def test_model_makes_the_same_calls_as_the_rules(synthetic_batch):
    # The 50% band follows the rules exactly (see test_prediction), so on held-out
    # files the yes/no calls match the rules-only baseline.
    holdout = holdout_evaluation(synthetic_batch["df"])
    assert holdout["same_calls_as_rules"] is True
    assert holdout["model"]["accuracy"] == holdout["rules_baseline"]["accuracy"]


def test_holdout_is_deterministic(synthetic_batch):
    assert holdout_evaluation(synthetic_batch["df"]) == holdout_evaluation(synthetic_batch["df"])


def test_holdout_needs_labels_and_enough_rows():
    assert holdout_evaluation(None) is None
    tiny = pd.DataFrame({"status": ["VALID", "INVALID"], "failed": [0, 1]})
    assert holdout_evaluation(tiny) is None


def test_card_for_an_untrained_model():
    card = build_model_card(RiskPredictor(), None)
    assert card["trained"] is False
    assert card["holdout"] is None and card["training"] is None
    assert [f["name"] for f in card["features"]] == RiskPredictor.FEATURE_COLUMNS
    assert all(f["importance"] is None for f in card["features"])


def test_card_for_a_trained_model(synthetic_batch):
    predictor = RiskPredictor()
    predictor.fit(synthetic_batch["df"])
    card = build_model_card(predictor, synthetic_batch["df"])
    assert card["trained"] is True
    assert card["training"]["rows"] == len(synthetic_batch["df"])
    assert abs(sum(f["importance"] for f in card["features"]) - 1) < 0.01
    assert card["params"]["n_estimators"] == 100
