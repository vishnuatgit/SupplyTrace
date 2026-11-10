from scripts.benchmark import format_report, run_benchmark


def test_benchmark_returns_sane_fields():
    result = run_benchmark(warmup=1, runs=2, generated_limit=10)
    assert result["samples"] >= 1
    assert result["generated"] == 10
    assert result["count"] == 2 * result["files"]
    assert result["invoices_per_second"] > 0
    assert 0 < result["p50_ms"] <= result["p95_ms"] <= result["max_ms"]
    assert result["batch_size"] == 20 and result["batch_median_ms"] > 0
    report = format_report(result, "cmd")
    assert "| Invoices per second |" in report and "Python" in report
