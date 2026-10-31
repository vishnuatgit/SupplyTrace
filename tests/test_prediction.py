import itertools

import pandas as pd
import pytest

from src.prediction.model import RiskPredictor


def make_row(**signals):
    row = dict.fromkeys(RiskPredictor.FEATURE_COLUMNS, 0)
    row["nesting_depth"] = 6
    row.update(signals)
    return row


def test_model_untrained_prediction():
    predictor = RiskPredictor()
    with pytest.raises(RuntimeError, match="Model must be trained before predicting."):
        predictor.predict_risk(make_row())


def test_model_fit_and_predict():
    # 30 clean files that went through and 30 missing their ID that failed
    rows = [dict(make_row(), failed=0) for _ in range(30)]
    rows += [dict(make_row(missing_id=1), failed=1) for _ in range(30)]
    predictor = RiskPredictor()
    predictor.fit(pd.DataFrame(rows))

    assert predictor.is_trained is True
    assert predictor.predict_risk(make_row())["risk_flag"] == "LOW"
    assert predictor.predict_risk(make_row(missing_id=1))["risk_flag"] == "HIGH"


def test_status_is_the_fallback_target():
    rows = [dict(make_row(), status="VALID") for _ in range(20)]
    rows += [dict(make_row(amount_negative=1), status="INVALID") for _ in range(20)]
    predictor = RiskPredictor()
    predictor.fit(pd.DataFrame(rows))
    assert predictor.predict_risk(make_row(amount_negative=1))["risk_score"] > 50


def test_single_class_leaves_model_untrained():
    predictor = RiskPredictor()
    predictor.fit(pd.DataFrame([dict(make_row(), failed=0) for _ in range(5)]))
    assert predictor.is_trained is False


def test_missing_feature_column_is_an_error():
    with pytest.raises(ValueError, match="Missing required feature column"):
        RiskPredictor().fit(pd.DataFrame({"failed": [0, 1]}))


def feature_grid():
    """Every coherent combination of signals, including depths never seen in training."""
    rows = []
    for mid, mam, nn, neg, rev, large, opt, depth in itertools.product(
        [0, 1], [0, 1], [0, 1], [0, 1], [0, 1], [0, 1], range(5), range(1, 16)
    ):
        if mam and (nn or neg or rev or large):
            continue  # no amount, so no amount signals
        if nn + neg + rev > 1 or ((nn or neg) and large) or (rev and not large):
            continue  # an amount is one of: non-numeric, negative, or a number
        rows.append(
            make_row(
                missing_id=mid,
                missing_amount=mam,
                amount_not_numeric=nn,
                amount_negative=neg,
                amount_above_review_limit=rev,
                large_amount=large,
                missing_optional_fields=opt,
                nesting_depth=depth,
            )
        )
    return pd.DataFrame(rows)


def test_risk_band_never_contradicts_the_rules(synthetic_batch):
    predictor = RiskPredictor()
    predictor.fit(synthetic_batch["df"])

    grid = feature_grid()
    breaks_a_rule = grid[
        ["missing_id", "missing_amount", "amount_not_numeric", "amount_negative"]
        + ["amount_above_review_limit"]
    ].any(axis=1)
    flags = [p["risk_flag"] for p in predictor.predict_risk_batch(grid)]
    grid["flag"] = flags

    assert (grid.loc[~breaks_a_rule, "flag"] == "LOW").all()
    assert (grid.loc[breaks_a_rule, "flag"] == "HIGH").all()


def test_valid_risk_rises_with_missing_optional_fields(synthetic_batch):
    predictor = RiskPredictor()
    predictor.fit(synthetic_batch["df"])
    scores = [
        predictor.predict_risk(make_row(missing_optional_fields=n))["risk_score"] for n in range(5)
    ]
    assert scores[0] < 5
    assert scores[0] < scores[2] < scores[4] < 50


def test_explanation_adds_up_to_the_score(synthetic_batch):
    predictor = RiskPredictor()
    predictor.fit(synthetic_batch["df"])
    for row in (make_row(), make_row(missing_optional_fields=3), make_row(amount_negative=1)):
        score = predictor.predict_risk(row)["risk_score"]
        explanation = predictor.explain(row)
        total = explanation["base"] + sum(d["points"] for d in explanation["contributions"])
        assert abs(total - score) < 0.1
        assert {d["feature"] for d in explanation["contributions"]} == set(
            RiskPredictor.FEATURE_COLUMNS
        )


def test_explanation_credits_the_broken_rule(synthetic_batch):
    predictor = RiskPredictor()
    predictor.fit(synthetic_batch["df"])
    top = predictor.explain(make_row(amount_not_numeric=1))["contributions"][0]
    assert top["feature"] == "amount_not_numeric"
    assert top["value"] == 1 and top["points"] > 30

    # A clean file is pulled below the base rate, mostly by the rules it passes.
    explanation = predictor.explain(make_row())
    assert explanation["contributions"][0]["points"] < 0


def test_explanation_needs_a_trained_model():
    with pytest.raises(RuntimeError, match="trained before explaining"):
        RiskPredictor().explain(make_row())
