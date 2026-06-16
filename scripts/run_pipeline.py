import os
import pandas as pd
import logging
from src.ingestion.xml_loader import XMLLoader
from src.ingestion.parser import XMLParser
from src.validation.rules import Validator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

RAW_DATA_DIR = os.path.join("data", "raw_xml")
RESULTS_CSV_PATH = os.path.join("results", "results.csv")

def run_pipeline():
    """
    Connects XML loading -> parsing -> validation -> saving to CSV.
    """
    logger.info("Starting Core Pipeline...")
    
    # 1. Ingestion
    raw_records = XMLLoader.load_directory(RAW_DATA_DIR)
    logger.info(f"Loaded {len(raw_records)} XML files.")
    
    results = []
    
    for raw_record in raw_records:
        # 2. Parsing / Standardization
        standardized_record = XMLParser.standardize(raw_record)
        
        # 3. Validation
        status, errors = Validator.validate(standardized_record)
        
        # Prepare row for persistence
        results.append({
            "source_file": standardized_record.get('_source_file', 'unknown'),
            "id": standardized_record.get('ID', ''),
            "status": status.value,
            "errors": "; ".join(errors) if errors else ""
        })
        
    # 4. CSV Persistence Pipeline
    os.makedirs(os.path.dirname(RESULTS_CSV_PATH), exist_ok=True)
    df = pd.DataFrame(results)
    
    if not df.empty:
        df.to_csv(RESULTS_CSV_PATH, index=False)
        logger.info(f"Pipeline complete. Saved {len(df)} records to {RESULTS_CSV_PATH}.")
    else:
        logger.warning("No records to save.")

if __name__ == "__main__":
    run_pipeline()
