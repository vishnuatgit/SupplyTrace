import os
import pandas as pd
import logging
from src.ingestion.xml_loader import XMLLoader
from src.ingestion.parser import XMLParser
from src.validation.rules import Validator
from src.features.extractor import FeatureExtractor
from src.prediction.model import RiskPredictor
from src.dashboard.exporter import DashboardExporter

logger = logging.getLogger(__name__)

class PipelineOrchestrator:
    """
    Coordinates the entire SupplyTrace pipeline:
    Ingestion -> Parsing -> Validation -> Feature Extraction -> Prediction -> Persistence
    """
    
    def __init__(self, raw_data_dir: str, results_csv_path: str):
        self.raw_data_dir = raw_data_dir
        self.results_csv_path = results_csv_path
        self.dashboard_csv_path = os.path.join(os.path.dirname(results_csv_path), "powerbi_summary.csv")
        self.predictor = RiskPredictor()

    def process_record(self, raw_record: dict) -> dict:
        """Processes a single raw XML record through to feature extraction."""
        standardized = XMLParser.standardize(raw_record)
        status, errors = Validator.validate(standardized)
        
        file_path = os.path.join(self.raw_data_dir, standardized.get('_source_file', ''))
        features = FeatureExtractor.extract_features(standardized, file_path=file_path)
        
        row = {
            "source_file": standardized.get('_source_file', 'unknown'),
            "id": standardized.get('ID', ''),
            "status": status.value,
            "errors": "; ".join(errors) if errors else ""
        }
        row.update(features)
        return row

    def train_and_predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Trains the ML model if possible and appends predictions."""
        has_valid = (df['status'] == 'VALID').any()
        has_invalid = (df['status'] != 'VALID').any()
        
        if has_valid and has_invalid:
            logger.info("Training RiskPredictor on batch data...")
            self.predictor.fit(df)
            
            risk_scores = []
            risk_flags = []
            for _, row in df.iterrows():
                features = {col: row[col] for col in self.predictor.feature_columns}
                pred = self.predictor.predict_risk(features)
                risk_scores.append(pred['risk_score'])
                risk_flags.append(pred['risk_flag'])
                
            df['risk_score'] = risk_scores
            df['risk_flag'] = risk_flags
        else:
            logger.warning("Not enough class diversity to train model. Defaulting risk scores to N/A.")
            df['risk_score'] = 'N/A'
            df['risk_flag'] = 'N/A'
            
        return df

    def run(self):
        """Executes the full pipeline run."""
        logger.info("Starting Core Pipeline...")
        raw_records = XMLLoader.load_directory(self.raw_data_dir)
        logger.info(f"Loaded {len(raw_records)} XML files.")
        
        if not raw_records:
            logger.warning("No records to process.")
            return

        results = [self.process_record(rec) for rec in raw_records]
        
        df = pd.DataFrame(results)
        df = self.train_and_predict(df)
        
        os.makedirs(os.path.dirname(self.results_csv_path), exist_ok=True)
        df.to_csv(self.results_csv_path, index=False)
        logger.info(f"Pipeline complete. Saved {len(df)} records to {self.results_csv_path}.")
        
        # Dashboard Export
        DashboardExporter.export_summary(df, self.dashboard_csv_path)
