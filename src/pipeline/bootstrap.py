import logging
import os

import pandas as pd

from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.synthetic import generate_dataset
from src.prediction.model import RiskPredictor

logger = logging.getLogger(__name__)


def results_are_current(results_csv_path: str) -> bool:
    """True if the results file exists and has every feature the current model uses."""
    if not os.path.exists(results_csv_path):
        return False
    try:
        columns = pd.read_csv(results_csv_path, nrows=0).columns
    except Exception:
        return False
    return set(RiskPredictor.FEATURE_COLUMNS).issubset(columns)


def ensure_demo_results(raw_data_dir: str, results_csv_path: str, audit_log_path: str = None):
    """
    Makes sure batch results exist for the dashboard and the model. If they are
    missing or were written by an older version, regenerates the synthetic
    invoices in raw_data_dir and reruns the pipeline (the same as running
    scripts/generate_data.py and then scripts/run_pipeline.py).
    Best effort: returns False and logs the reason if that is not possible,
    for example on a read-only disk.
    """
    if results_are_current(results_csv_path):
        return True

    logger.info("No current batch results found. Generating the synthetic demo dataset...")
    try:
        generate_dataset(raw_data_dir)
        PipelineOrchestrator(raw_data_dir, results_csv_path, audit_log_path).run()
        return True
    except Exception as e:
        logger.error(f"Could not generate demo data: {e}")
        return False
