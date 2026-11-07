import os

import pandas as pd
import pytest

from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.synthetic import OUTCOMES_FILE, generate_dataset


@pytest.fixture(scope="session")
def synthetic_batch(tmp_path_factory):
    """The default synthetic dataset and its pipeline results, built once in a temp dir."""
    root = tmp_path_factory.mktemp("synthetic")
    raw_dir = os.path.join(root, "raw_xml")
    results_csv = os.path.join(root, "results", "results.csv")
    generate_dataset(raw_dir)
    df = PipelineOrchestrator(raw_dir, results_csv).run()
    outcomes = pd.read_csv(os.path.join(raw_dir, OUTCOMES_FILE))
    return {"raw_dir": raw_dir, "results_csv": results_csv, "df": df, "outcomes": outcomes}


@pytest.fixture(autouse=True)
def temp_database(tmp_path, monkeypatch):
    """Every test gets its own empty database file, so none touches the repository's data/."""
    from src.api import server

    monkeypatch.setattr(server, "DATABASE_URL", None)
    monkeypatch.setattr(server, "DB_PATH", str(tmp_path / "db" / "supplytrace.db"))
