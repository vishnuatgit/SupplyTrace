import os
import tempfile
from src.features.extractor import FeatureExtractor

def test_feature_extraction_complete_record():
    record = {'ID': '001', 'AMOUNT': '500'}
    features = FeatureExtractor.extract_features(record)
    
    assert 'missing_fields' in features
    assert features['missing_fields'] == 0
    assert 'xml_size' in features
    assert features['xml_size'] > 0
    assert 'processing_time' in features
    assert 'retry_attempts' in features
    assert features['retry_attempts'] == 0

def test_feature_extraction_missing_fields():
    record = {'AMOUNT': '500'} # Missing ID
    features = FeatureExtractor.extract_features(record)
    
    assert features['missing_fields'] == 1
    assert features['retry_attempts'] == 1

def test_feature_extraction_with_file():
    record = {'ID': '002', 'AMOUNT': '1000'}
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode='w') as f:
        f.write("<invoice><id>002</id><amount>1000</amount></invoice>")
        temp_path = f.name
        
    try:
        features = FeatureExtractor.extract_features(record, file_path=temp_path)
        assert features['xml_size'] == os.path.getsize(temp_path)
    finally:
        os.remove(temp_path)
