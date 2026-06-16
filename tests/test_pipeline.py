import os
import pandas as pd
from scripts.run_pipeline import run_pipeline, RESULTS_CSV_PATH
from scripts.generate_data import run as generate_data

def test_core_pipeline():
    # 1. Ensure we have data
    generate_data()
    
    # 2. Run the pipeline
    run_pipeline()
    
    # 3. Verify persistence
    assert os.path.exists(RESULTS_CSV_PATH)
    
    # 4. Verify CSV contents
    df = pd.read_csv(RESULTS_CSV_PATH)
    assert len(df) == 10  # We generated 10 XMLs in Day 5
    
    # Check columns
    expected_columns = ['source_file', 'id', 'status', 'errors']
    for col in expected_columns:
        assert col in df.columns
        
    # Check if specific status types were captured properly
    assert 'VALID' in df['status'].values
    assert 'INVALID' in df['status'].values
    assert 'REQUIRES_REVIEW' in df['status'].values
