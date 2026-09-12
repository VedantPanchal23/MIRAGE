"""MIRAGE Benchmarking & Evaluation Suite."""

from benchmarks.evaluator import BenchmarkCase, BenchmarkOutput, BenchmarkResult, evaluate_benchmark_outputs
from benchmarks.metrics import (
    compute_calibration_metrics,
    compute_classification_metrics,
    compute_conformal_coverage,
    compute_mondrian_coverage,
    mcnemar_test,
    paired_bootstrap_test,
)

__all__ = [
    "BenchmarkCase",
    "BenchmarkOutput",
    "BenchmarkResult",
    "compute_calibration_metrics",
    "compute_classification_metrics",
    "compute_conformal_coverage",
    "compute_mondrian_coverage",
    "evaluate_benchmark_outputs",
    "mcnemar_test",
    "paired_bootstrap_test",
]
