import os
import random

class FeatureExtractor:
    """
    Extracts features from standardized records for the ML prediction model.
    """
    
    EXPECTED_FIELDS = {'ID', 'AMOUNT'}
    
    @staticmethod
    def extract_features(record: dict, file_path: str = None) -> dict:
        """
        Extracts features like missing_fields, xml_size, and processing_time.
        """
        features = {}
        
        # 1. Missing Fields
        # Count how many expected fields are missing or empty
        missing_count = 0
        for field in FeatureExtractor.EXPECTED_FIELDS:
            if not record.get(field) or not str(record.get(field)).strip():
                missing_count += 1
        features['missing_fields'] = missing_count
        
        # 2. XML Size (in bytes)
        # If file_path is provided and exists, get its size, else mock a size based on content length
        if file_path and os.path.exists(file_path):
            features['xml_size'] = os.path.getsize(file_path)
        else:
            # Mock size if file doesn't exist
            features['xml_size'] = len(str(record))
            
        # 3. Processing Time (Simulated)
        # In a real system, this would be measured during ingestion.
        # We simulate a latency between 10ms and 500ms based on missing fields and size.
        base_time = random.uniform(10.0, 50.0)
        penalty = missing_count * 50.0 + (features['xml_size'] * 0.1)
        features['processing_time'] = round(base_time + penalty, 2)
        
        # 4. Retry Attempts (Simulated)
        # If there are missing fields, sometimes retries happen.
        features['retry_attempts'] = 1 if missing_count > 0 else 0
        
        return features
