import logging

import pandas as pd
from sklearn.ensemble import RandomForestClassifier

logger = logging.getLogger(__name__)


class RiskPredictor:
    """
    Machine Learning model to predict XML transaction failure risk.
    Uses features extracted during the ingestion pipeline.
    """

    # Features used for prediction (see FeatureExtractor). File size is
    # deliberately not one of them: it says little about whether a file fails.
    FEATURE_COLUMNS = [
        "missing_id",
        "missing_amount",
        "amount_not_numeric",
        "amount_negative",
        "amount_above_review_limit",
        "large_amount",
        "missing_optional_fields",
        "nesting_depth",
    ]

    # 1 if the file failed (or would fail) straight-through processing, else 0.
    TARGET_COLUMN = "failed"

    HIGH_RISK_THRESHOLD = 50

    def __init__(self):
        # A small Random Forest. With only eight features every split considers
        # all of them (max_features=None), so each rule-breaking group gets its
        # own leaves; min_samples_leaf=10 smooths the noisy simulated outcomes
        # of otherwise-valid files instead of memorising them.
        self.model = RandomForestClassifier(
            n_estimators=100, max_features=None, min_samples_leaf=10, random_state=42
        )
        self.is_trained = False
        self.feature_columns = list(self.FEATURE_COLUMNS)

    def fit(self, df: pd.DataFrame):
        """
        Trains the model using historical data from the pipeline.
        Uses the 'failed' column as the target when present; otherwise a file
        counts as failed when its 'status' is anything other than VALID.
        Stays untrained (with a warning) if the data has only one class.
        """
        if df.empty:
            logger.warning("Empty dataframe provided to fit(). Skipping training.")
            return

        for col in self.feature_columns:
            if col not in df.columns:
                raise ValueError(f"Missing required feature column: {col}")

        if self.TARGET_COLUMN in df.columns:
            y = df[self.TARGET_COLUMN].astype(int)
        elif "status" in df.columns:
            y = (df["status"] != "VALID").astype(int)
        else:
            raise ValueError(f"Missing target column: '{self.TARGET_COLUMN}' or 'status'")

        if y.nunique() < 2:
            logger.warning("Training data has only one class. Model left untrained.")
            return

        self.model.fit(df[self.feature_columns], y)
        self.is_trained = True
        logger.info(f"RiskPredictor trained on {len(df)} records.")

    def predict_risk(self, features: dict) -> dict:
        """
        Predicts the failure risk percentage for a single record's features.
        """
        return self.predict_risk_batch(pd.DataFrame([features]))[0]

    def predict_risk_batch(self, df: pd.DataFrame) -> list[dict]:
        """
        Predicts the failure risk percentage for every row of a feature table.
        """
        if not self.is_trained:
            raise RuntimeError("Model must be trained before predicting.")

        # predict_proba returns [[prob_0, prob_1], ...]; prob_1 is the failure risk
        probabilities = self.model.predict_proba(df[self.feature_columns])[:, 1]
        results = []
        for probability in probabilities:
            risk_score = round(float(probability) * 100, 2)
            flag = "HIGH" if risk_score > self.HIGH_RISK_THRESHOLD else "LOW"
            results.append({"risk_score": risk_score, "risk_flag": flag})
        return results
