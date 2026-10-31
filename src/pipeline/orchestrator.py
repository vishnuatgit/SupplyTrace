import logging
import os
from datetime import UTC, datetime

import pandas as pd

from src.dashboard.exporter import DashboardExporter
from src.features.extractor import FeatureExtractor
from src.ingestion.parser import XMLParser
from src.ingestion.xml_loader import XMLLoader
from src.pipeline.synthetic import OUTCOMES_FILE
from src.prediction.model import RiskPredictor
from src.utils.audit import append_audit_entries
from src.validation.rules import Validator

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Coordinates the entire SupplyTrace pipeline:
    Ingestion -> Parsing -> Validation -> Feature Extraction -> Prediction -> Persistence
    """

    def __init__(self, raw_data_dir: str, results_csv_path: str, audit_log_path: str = None):
        self.raw_data_dir = raw_data_dir
        self.results_csv_path = results_csv_path
        results_dir = os.path.dirname(results_csv_path)
        self.dashboard_csv_path = os.path.join(results_dir, "powerbi_summary.csv")
        self.audit_log_path = audit_log_path or os.path.join(results_dir, "audit_log.jsonl")
        self.predictor = RiskPredictor()

    def process_record(self, raw_record: dict) -> dict:
        """Processes a single raw XML record through to feature extraction."""
        standardized = XMLParser.standardize(raw_record)
        status, errors = Validator.validate(standardized)

        file_path = os.path.join(self.raw_data_dir, standardized.get("_source_file", ""))
        features = FeatureExtractor.extract_features(standardized, file_path=file_path)

        row = {
            "source_file": standardized.get("_source_file", "unknown"),
            "id": standardized.get("ID", ""),
            "status": status.value,
            "errors": "; ".join(errors) if errors else "",
        }
        row.update(features)
        return row

    def attach_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds the training label column 'failed'. Outcomes come from outcomes.csv
        in the input folder (written by the synthetic data generator); files
        without a recorded outcome count as failed unless their status is VALID.
        """
        fallback = (df["status"] != "VALID").astype(int)
        outcomes_path = os.path.join(self.raw_data_dir, OUTCOMES_FILE)
        if os.path.exists(outcomes_path):
            outcomes = pd.read_csv(outcomes_path)
            recorded_by_file = dict(zip(outcomes["source_file"], outcomes["failed"], strict=True))
            recorded = df["source_file"].map(recorded_by_file)
            df["failed"] = recorded.fillna(fallback).astype(int)
        else:
            df["failed"] = fallback
        return df

    def train_and_predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Trains the ML model if possible and appends predictions."""
        logger.info("Training RiskPredictor on batch data...")
        self.predictor.fit(df)

        if self.predictor.is_trained:
            predictions = self.predictor.predict_risk_batch(df)
            df["risk_score"] = [p["risk_score"] for p in predictions]
            df["risk_flag"] = [p["risk_flag"] for p in predictions]
        else:
            logger.warning(
                "Not enough class diversity to train model. Defaulting risk scores to N/A."
            )
            df["risk_score"] = "N/A"
            df["risk_flag"] = "N/A"

        return df

    def run(self) -> pd.DataFrame:
        """Executes the full pipeline run and returns the results table."""
        logger.info("Starting Core Pipeline...")
        raw_records = XMLLoader.load_directory(self.raw_data_dir)
        logger.info(f"Loaded {len(raw_records)} XML files.")

        if not raw_records:
            logger.warning("No records to process.")
            return None

        results = [self.process_record(rec) for rec in raw_records]

        df = pd.DataFrame(results)
        df = self.attach_labels(df)
        df = self.train_and_predict(df)

        results_dir = os.path.dirname(self.results_csv_path)
        if results_dir:
            os.makedirs(results_dir, exist_ok=True)
        df.to_csv(self.results_csv_path, index=False)
        logger.info(f"Pipeline complete. Saved {len(df)} records to {self.results_csv_path}.")

        # Dashboard Export
        DashboardExporter.export_summary(df, self.dashboard_csv_path)

        # Write Audit Log
        self.write_audit_log(df)
        return df

    def write_audit_log(self, df: pd.DataFrame):
        """Appends one JSON audit entry per processed file (best effort)."""
        timestamp = datetime.now(UTC).isoformat()
        entries = [
            {
                "timestamp": timestamp,
                "source_file": row["source_file"],
                "transaction_id": row["id"],
                "validation_status": row["status"],
                "errors": row["errors"] if pd.notna(row["errors"]) else "",
                "risk_score": row["risk_score"],
                "risk_flag": row["risk_flag"],
                "origin": "pipeline",
                "xml_size": int(row["xml_size"]),
                "nesting_depth": int(row["nesting_depth"]),
                "missing_optional_fields": int(row["missing_optional_fields"]),
            }
            for _, row in df.iterrows()
        ]
        if append_audit_entries(self.audit_log_path, entries):
            logger.info(f"Audit trail written to {self.audit_log_path}")
