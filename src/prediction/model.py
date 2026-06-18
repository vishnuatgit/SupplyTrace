import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import logging

logger = logging.getLogger(__name__)

class RiskPredictor:
    """
    Machine Learning model to predict XML transaction failure risk.
    Uses features extracted during the ingestion pipeline.
    """
    
    def __init__(self):
        # We use a simple Random Forest for robust out-of-the-box performance
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.is_trained = False
        
        # Features used for prediction
        self.feature_columns = [
            'missing_fields', 
            'xml_size', 
            'processing_time', 
            'retry_attempts'
        ]
        
    def fit(self, df: pd.DataFrame):
        """
        Trains the model using historical data from the pipeline.
        Requires the target column 'status' to exist.
        """
        if df.empty:
            logger.warning("Empty dataframe provided to fit(). Skipping training.")
            return
            
        for col in self.feature_columns:
            if col not in df.columns:
                raise ValueError(f"Missing required feature column: {col}")
                
        if 'status' not in df.columns:
            raise ValueError("Missing target column: 'status'")
            
        # Target engineering: 1 if INVALID or REQUIRES_REVIEW, 0 if VALID
        y = df['status'].apply(lambda x: 0 if x == 'VALID' else 1)
        X = df[self.feature_columns]
        
        self.model.fit(X, y)
        self.is_trained = True
        logger.info("RiskPredictor successfully trained.")

    def predict_risk(self, features: dict) -> dict:
        """
        Predicts the failure risk percentage for a single record's features.
        """
        if not self.is_trained:
            raise RuntimeError("Model must be trained before predicting.")
            
        X_input = pd.DataFrame([features])[self.feature_columns]
        
        # predict_proba returns [[prob_0, prob_1]]
        # We want prob_1 (probability of failure/invalid)
        probabilities = self.model.predict_proba(X_input)
        risk_score = round(probabilities[0][1] * 100, 2)
        
        return {
            "risk_score": risk_score,
            "risk_flag": "HIGH" if risk_score > 50 else "LOW"
        }
