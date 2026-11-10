"""
Reproducible processing-time benchmark for analyze_document(), the function behind
POST /api/analyze. It runs in process, with no network, and writes only to a
temporary directory (a generated synthetic batch used to train the risk model).

    python -m scripts.benchmark --warmup 1 --runs 5
"""

import argparse
import os
import platform
import statistics
import tempfile
import time
from datetime import date

import pandas as pd

from src.api.analysis import analyze_document
from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.synthetic import generate_dataset
from src.prediction.model import RiskPredictor

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "src", "api", "samples")
BATCH_SIZE = 20


def load_xml_dir(directory: str) -> list[tuple[str, bytes]]:
    files = []
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith(".xml"):
            with open(os.path.join(directory, name), "rb") as f:
                files.append((name, f.read()))
    return files


def percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in 0-100) of an ascending list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q / 100
    low = int(pos)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (pos - low)


def run_benchmark(warmup: int = 1, runs: int = 5, generated_limit: int | None = None) -> dict:
    """Times analyze_document() per invoice. warmup and runs are passes over every file."""
    if warmup < 0 or runs < 1:
        raise ValueError("warmup must be >= 0 and runs >= 1")
    with tempfile.TemporaryDirectory() as tmp:
        raw_dir = os.path.join(tmp, "raw_xml")
        generate_dataset(raw_dir)
        results_csv = os.path.join(tmp, "results", "results.csv")
        PipelineOrchestrator(raw_dir, results_csv).run()
        predictor = RiskPredictor()
        predictor.fit(pd.read_csv(results_csv))
        generated = load_xml_dir(raw_dir)
    if generated_limit is not None:
        generated = generated[:generated_limit]
    files = load_xml_dir(SAMPLES_DIR) + generated

    for _ in range(warmup):
        for name, content in files:
            analyze_document(name, content, predictor)

    per_invoice_ms = []
    wall = 0.0
    for _ in range(runs):
        for name, content in files:
            t0 = time.perf_counter()
            analyze_document(name, content, predictor)
            elapsed = time.perf_counter() - t0
            per_invoice_ms.append(elapsed * 1000)
            wall += elapsed
    per_invoice_ms.sort()

    # The batch endpoint checks its files one after another with this same function.
    batch = (files * BATCH_SIZE)[:BATCH_SIZE]
    batch_ms = []
    for _ in range(runs):
        t0 = time.perf_counter()
        for name, content in batch:
            analyze_document(name, content, predictor)
        batch_ms.append((time.perf_counter() - t0) * 1000)

    return {
        "files": len(files),
        "samples": len(files) - len(generated),
        "generated": len(generated),
        "warmup": warmup,
        "runs": runs,
        "count": len(per_invoice_ms),
        "invoices_per_second": len(per_invoice_ms) / wall,
        "p50_ms": percentile(per_invoice_ms, 50),
        "p95_ms": percentile(per_invoice_ms, 95),
        "max_ms": per_invoice_ms[-1],
        "batch_size": len(batch),
        "batch_median_ms": statistics.median(batch_ms),
    }


def machine_info() -> dict:
    return {
        "Python": platform.python_version(),
        "CPU": platform.processor() or "unknown",
        "OS": platform.platform(),
    }


def format_report(result: dict, command: str) -> str:
    rows = [
        ("Distinct files", result["files"]),
        ("Timed invoices (count)", result["count"]),
        ("Invoices per second", f"{result['invoices_per_second']:.1f}"),
        ("p50 ms per invoice", f"{result['p50_ms']:.2f}"),
        ("p95 ms per invoice", f"{result['p95_ms']:.2f}"),
        ("max ms per invoice", f"{result['max_ms']:.2f}"),
        (
            f"Batch of {result['batch_size']} files, median ms",
            f"{result['batch_median_ms']:.1f}",
        ),
    ]
    lines = ["| Metric | Value |", "|:--|--:|"] + [f"| {k} | {v} |" for k, v in rows]
    lines += [""] + [f"- {k}: {v}" for k, v in machine_info().items()]
    lines += [
        f"- Files: {result['samples']} bundled samples + {result['generated']} generated invoices",
        f"- Warm-up passes: {result['warmup']}, timed passes: {result['runs']}",
        f"- Date: {date.today().isoformat()}",
        f"- Command: `{command}`",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--warmup", type=int, default=1, help="warm-up passes (default 1)")
    parser.add_argument("--runs", type=int, default=5, help="timed passes (default 5)")
    args = parser.parse_args(argv)
    result = run_benchmark(args.warmup, args.runs)
    command = f"python -m scripts.benchmark --warmup {args.warmup} --runs {args.runs}"
    print(format_report(result, command))


if __name__ == "__main__":
    main()
