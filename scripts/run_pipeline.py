import os
import logging
from src.pipeline.orchestrator import PipelineOrchestrator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

RAW_DATA_DIR = os.path.join("data", "raw_xml")
RESULTS_CSV_PATH = os.path.join("results", "results.csv")

def run_pipeline():
    orchestrator = PipelineOrchestrator(RAW_DATA_DIR, RESULTS_CSV_PATH)
    orchestrator.run()

if __name__ == "__main__":
    run_pipeline()
