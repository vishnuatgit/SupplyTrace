import os

import pandas as pd

from scripts.generate_data import main as generate_data
from scripts.run_pipeline import RESULTS_CSV_PATH, run_pipeline
from src.pipeline.bootstrap import ensure_demo_results, results_are_current
from src.pipeline.synthetic import DEFAULT_COUNT, EXPECTED_STATUS, generate_dataset


def test_core_pipeline(tmp_path, monkeypatch):
    # The scripts use paths relative to the working directory: keep them out of the repo.
    monkeypatch.chdir(tmp_path)

    # 1. Ensure we have data
    generate_data()

    # 2. Run the pipeline
    run_pipeline()

    # 3. Verify persistence
    assert os.path.exists(RESULTS_CSV_PATH)
    assert (tmp_path / "results" / "powerbi_summary.csv").exists()
    assert (tmp_path / "results" / "audit_log.jsonl").exists()

    # 4. Verify CSV contents
    df = pd.read_csv(RESULTS_CSV_PATH)
    assert len(df) == DEFAULT_COUNT

    # Check columns
    expected_columns = [
        "source_file",
        "id",
        "status",
        "errors",
        "missing_id",
        "missing_amount",
        "amount_not_numeric",
        "amount_negative",
        "amount_above_review_limit",
        "large_amount",
        "missing_optional_fields",
        "nesting_depth",
        "missing_fields",
        "xml_size",
        "failed",
        "risk_score",
        "risk_flag",
    ]
    for col in expected_columns:
        assert col in df.columns

    # Check that model trained and populated values instead of N/A
    assert pd.api.types.is_numeric_dtype(df["risk_score"])

    # Check if specific status types were captured properly
    assert {"VALID", "INVALID", "REQUIRES_REVIEW"} == set(df["status"])

    # The risk band agrees with the validation status for every batch file
    assert (df.loc[df["status"] == "VALID", "risk_flag"] == "LOW").all()
    assert (df.loc[df["status"] != "VALID", "risk_flag"] == "HIGH").all()


def test_generator_cases_match_validation_status(synthetic_batch):
    merged = synthetic_batch["df"].merge(synthetic_batch["outcomes"], on="source_file")
    assert len(merged) == DEFAULT_COUNT
    assert (merged["status"] == merged["case"].map(EXPECTED_STATUS)).all()


def test_outcome_labels_follow_the_documented_rules(synthetic_batch):
    df = synthetic_batch["df"]
    # Rule-breaking files always fail; otherwise-valid ones fail at most 20% of the time.
    assert (df.loc[df["status"] != "VALID", "failed"] == 1).all()
    valid_failure_rate = df.loc[df["status"] == "VALID", "failed"].mean()
    assert 0 < valid_failure_rate < 0.2


def test_generation_is_deterministic(tmp_path):
    first = generate_dataset(str(tmp_path / "a"), count=20)
    second = generate_dataset(str(tmp_path / "b"), count=20)
    assert first == second
    for row in first:
        name = row["source_file"]
        assert (tmp_path / "a" / name).read_text() == (tmp_path / "b" / name).read_text()


def test_bootstrap_creates_results_once(tmp_path):
    raw_dir = str(tmp_path / "raw")
    results_csv = str(tmp_path / "results" / "results.csv")
    assert not results_are_current(results_csv)

    assert ensure_demo_results(raw_dir, results_csv)
    assert results_are_current(results_csv)
    modified = os.path.getmtime(results_csv)

    # Current results are left alone
    assert ensure_demo_results(raw_dir, results_csv)
    assert os.path.getmtime(results_csv) == modified


def test_bootstrap_replaces_results_from_an_older_version(tmp_path):
    results_csv = tmp_path / "results" / "results.csv"
    results_csv.parent.mkdir()
    pd.DataFrame({"status": ["VALID"], "xml_size": [10], "processing_time": [11.0]}).to_csv(
        results_csv, index=False
    )
    assert not results_are_current(str(results_csv))
    assert ensure_demo_results(str(tmp_path / "raw"), str(results_csv))
    assert len(pd.read_csv(results_csv)) == DEFAULT_COUNT


def test_bootstrap_failure_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("a file where a directory should be")
    assert ensure_demo_results(str(blocker / "raw"), str(blocker / "results.csv")) is False
