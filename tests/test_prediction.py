import pytest
import pandas as pd
from src.prediction.model import RiskPredictor

def test_model_untrained_prediction():
    predictor = RiskPredictor()
    features = {
        'missing_fields': 0, 'xml_size': 100, 'processing_time': 12.5, 'retry_attempts': 0
    }
    with pytest.raises(RuntimeError, match="Model must be trained before predicting."):
        predictor.predict_risk(features)

def test_model_fit_and_predict():
    # Create synthetic training data
    data = {
        'missing_fields': [0, 1, 0, 2],
        'xml_size': [150, 140, 160, 130],
        'processing_time': [15.0, 65.0, 14.5, 115.0],
        'retry_attempts': [0, 1, 0, 1],
        'status': ['VALID', 'INVALID', 'VALID', 'REQUIRES_REVIEW']
    }
    df = pd.DataFrame(data)
    
    predictor = RiskPredictor()
    predictor.fit(df)
    
    assert predictor.is_trained is True
    
    # Predict on a valid-looking record
    valid_features = {'missing_fields': 0, 'xml_size': 155, 'processing_time': 15.2, 'retry_attempts': 0}
    result_valid = predictor.predict_risk(valid_features)
    assert 'risk_score' in result_valid
    assert result_valid['risk_flag'] == 'LOW'
    
    # Predict on an invalid-looking record
    invalid_features = {'missing_fields': 2, 'xml_size': 135, 'processing_time': 110.0, 'retry_attempts': 1}
    result_invalid = predictor.predict_risk(invalid_features)
    assert result_invalid['risk_flag'] == 'HIGH'
