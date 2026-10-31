"""
The model card behind the "Rules and model" page: what the risk model is, what
it was trained on, and how it does on files it has not seen.

Every number here is computed from the pipeline's own results (results.csv);
nothing is typed in by hand. The holdout evaluation trains a fresh model on
75% of the rows and scores the other 25%, next to a rules-only baseline that
says a file fails exactly when its status is not VALID.
"""

import logging

import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split

from src.features.extractor import FEATURE_DESCRIPTIONS, FEATURE_LABELS, LARGE_AMOUNT
from src.pipeline import synthetic
from src.prediction.model import RiskPredictor

logger = logging.getLogger(__name__)

HOLDOUT_SHARE = 0.25
SPLIT_SEED = 42
# Below this many rows a holdout score says nothing useful.
MIN_ROWS_FOR_HOLDOUT = 40


def _round(value: float) -> float:
    return round(float(value), 4)


def _auc(y_true: pd.Series, scores) -> float | None:
    """ROC AUC, or None when only one class is present (it is undefined then)."""
    if y_true.nunique() < 2:
        return None
    return _round(roc_auc_score(y_true, scores))


def classification_metrics(y_true: pd.Series, flagged: pd.Series, scores) -> dict:
    """Accuracy, precision and recall of the yes/no calls, ROC AUC of the scores."""
    tn, fp, fn, tp = confusion_matrix(y_true, flagged, labels=[0, 1]).ravel()
    return {
        "accuracy": _round(accuracy_score(y_true, flagged)),
        "precision": _round(precision_score(y_true, flagged, zero_division=0)),
        "recall": _round(recall_score(y_true, flagged, zero_division=0)),
        "roc_auc": _auc(y_true, scores),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "true_negatives": int(tn),
        "false_negatives": int(fn),
    }


def holdout_evaluation(df: pd.DataFrame) -> dict | None:
    """
    Trains a fresh RiskPredictor on a stratified 75% of the rows and evaluates
    it on the remaining 25%. Returns None when the data cannot support it.
    """
    target = RiskPredictor.TARGET_COLUMN
    if df is None or target not in df.columns or "status" not in df.columns:
        return None
    y = df[target].astype(int)
    if len(df) < MIN_ROWS_FOR_HOLDOUT or y.nunique() < 2 or y.value_counts().min() < 2:
        return None

    train, test = train_test_split(df, test_size=HOLDOUT_SHARE, random_state=SPLIT_SEED, stratify=y)
    model = RiskPredictor()
    model.fit(train)
    if not model.is_trained:
        return None

    predictions = model.predict_risk_batch(test)
    scores = pd.Series([p["risk_score"] for p in predictions], index=test.index)
    flagged = pd.Series([p["risk_flag"] == "HIGH" for p in predictions], index=test.index)
    y_test = test[target].astype(int)
    rules_flagged = test["status"] != "VALID"
    valid = test["status"] == "VALID"

    return {
        "train_rows": len(train),
        "test_rows": len(test),
        "test_failed": int(y_test.sum()),
        "model": classification_metrics(y_test, flagged.astype(int), scores),
        "rules_baseline": classification_metrics(
            y_test, rules_flagged.astype(int), rules_flagged.astype(float)
        ),
        # The model's only extra information: how it ranks the files the rules pass.
        "valid_only": {
            "rows": int(valid.sum()),
            "failed": int(y_test[valid].sum()),
            "roc_auc": _auc(y_test[valid], scores[valid]),
        },
        "same_calls_as_rules": bool((flagged == rules_flagged).all()),
    }


def build_model_card(predictor: RiskPredictor, results: pd.DataFrame | None) -> dict:
    """Everything the model card shows, from the served model and its training data."""
    params = predictor.model.get_params()
    importances = (
        predictor.model.feature_importances_
        if predictor.is_trained
        else [None] * len(predictor.feature_columns)
    )
    features = [
        {
            "name": name,
            "label": FEATURE_LABELS[name],
            "description": FEATURE_DESCRIPTIONS[name],
            "importance": _round(importance) if importance is not None else None,
        }
        for name, importance in zip(predictor.feature_columns, importances, strict=True)
    ]

    training = None
    if results is not None and RiskPredictor.TARGET_COLUMN in results.columns:
        training = {
            "rows": len(results),
            "failed": int(results[RiskPredictor.TARGET_COLUMN].sum()),
        }

    holdout = None
    try:
        holdout = holdout_evaluation(results)
    except Exception as e:
        logger.error(f"Holdout evaluation failed: {e}")

    return {
        "trained": predictor.is_trained,
        "estimator": type(predictor.model).__name__,
        "params": {
            key: params[key]
            for key in ("n_estimators", "max_features", "min_samples_leaf", "random_state")
        },
        "high_risk_threshold": RiskPredictor.HIGH_RISK_THRESHOLD,
        "features": features,
        "training": training,
        "synthetic_data": {
            "count": synthetic.DEFAULT_COUNT,
            "seed": synthetic.DEFAULT_SEED,
            "case_weights": synthetic.CASE_WEIGHTS,
            "sparse_share": synthetic.SPARSE_SHARE,
            "envelope_share": synthetic.ENVELOPE_SHARE,
            "large_amount": LARGE_AMOUNT,
            "failure_base": synthetic.FAILURE_BASE,
            "failure_per_missing_optional": synthetic.FAILURE_PER_MISSING_OPTIONAL,
            "failure_large_amount": synthetic.FAILURE_LARGE_AMOUNT,
            "failure_envelope": synthetic.FAILURE_ENVELOPE,
            "failure_cap": synthetic.FAILURE_CAP,
        },
        "holdout": holdout,
        "holdout_share": HOLDOUT_SHARE,
        "split_seed": SPLIT_SEED,
    }
