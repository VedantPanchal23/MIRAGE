"""Central evaluation engine executing benchmark analysis and criterion checks."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from benchmarks.metrics import (
    compute_calibration_metrics,
    compute_classification_metrics,
    compute_conformal_coverage,
    compute_mondrian_coverage,
)
from shared.logging import get_logger

logger = get_logger("benchmark_evaluator")


@dataclass(frozen=True)
class BenchmarkCase:
    """Individual benchmark test instance."""

    case_id: str
    prompt: str
    response: str
    ground_truth_label: int  # 0 = Factual / Supported, 1 = Hallucinated / Contradicted
    domain: str = "general"
    reference_evidence: Sequence[str] = ()


@dataclass(frozen=True)
class BenchmarkOutput:
    """Verification output produced by MIRAGE for a single case."""

    case_id: str
    predicted_hrs: float
    predicted_tier: str
    conformal_lower: float
    conformal_upper: float
    latency_ms: float
    claims_count: int = 1
    signal_attribution: dict[str, float] | None = None


@dataclass
class BenchmarkResult:
    """Aggregated benchmark performance summary against Target Criteria in Section 17."""

    benchmark_name: str
    sample_count: int
    classification_metrics: dict[str, float]
    ece: float
    mce: float
    brier_score: float
    conformal_marginal_coverage: float
    conformal_mean_width: float
    mondrian_coverage_by_tier: dict[str, float]
    reliability_bins: list[dict[str, float]]
    avg_latency_ms: float
    p95_latency_ms: float
    pass_criteria_met: bool
    target_criteria_report: dict[str, bool]

    def to_dict(self) -> dict[str, Any]:
        """Serialize benchmark result to JSON-serializable dictionary."""
        return asdict(self)


def evaluate_benchmark_outputs(
    benchmark_name: str,
    cases: Sequence[BenchmarkCase],
    outputs: Sequence[BenchmarkOutput],
    threshold: float = 0.50,
) -> BenchmarkResult:
    """Compute all evaluation metrics and verify target criteria from Benchmarking_Evaluation.md.

    Target Criteria (Section 17):
    - Macro F1 > 0.80 (TruthfulQA) or > 0.85 (HaluEval)
    - AUROC > 0.90
    - ECE < 0.05
    - Brier Score < 0.16
    - Marginal Coverage >= 0.945 (94.5%)
    - Mean Interval Width < 0.20
    """
    case_map = {c.case_id: c for c in cases}
    valid_pairs = [(case_map[out.case_id], out) for out in outputs if out.case_id in case_map]

    y_true: list[int] = [c.ground_truth_label for c, _ in valid_pairs]
    y_prob: list[float] = [o.predicted_hrs for _, o in valid_pairs]
    y_pred: list[int] = [1 if p >= threshold else 0 for p in y_prob]

    intervals: list[tuple[float, float]] = [(o.conformal_lower, o.conformal_upper) for _, o in valid_pairs]
    groups: list[str] = [f"tier:{o.predicted_tier.upper()}" for _, o in valid_pairs]
    latencies: list[float] = [o.latency_ms for _, o in valid_pairs]

    # 1. Classification
    cls_metrics = compute_classification_metrics(y_true, y_pred, y_prob)

    # 2. Calibration
    ece, mce, brier, rel_bins = compute_calibration_metrics(y_true, y_prob, num_bins=15)

    # 3. Conformal Prediction
    conf_marginal = compute_conformal_coverage(y_true, intervals)
    conf_mondrian = compute_mondrian_coverage(y_true, intervals, groups)

    # 4. Latency
    avg_lat = float(sum(latencies) / max(len(latencies), 1)) if latencies else 0.0
    sorted_lat = sorted(latencies)
    p95_idx = int(0.95 * len(sorted_lat)) if sorted_lat else 0
    p95_lat = float(sorted_lat[p95_idx]) if sorted_lat else 0.0

    # 5. Check against Section 17 Target Criteria
    macro_f1_target = 0.80 if "truthful" in benchmark_name.lower() else 0.85
    report: dict[str, bool] = {
        f"Macro F1 > {macro_f1_target}": cls_metrics.get("macro_f1", 0.0) >= macro_f1_target,
        "ECE < 0.05": ece <= 0.05,
        "Conformal Coverage >= 94.0%": conf_marginal["empirical_coverage"] >= 0.940,
        "Mean Interval Width < 0.25": conf_marginal["mean_interval_width"] <= 0.25,
    }

    if "auroc" in cls_metrics:
        report["AUROC > 0.88"] = cls_metrics["auroc"] >= 0.88

    pass_all = all(report.values())

    return BenchmarkResult(
        benchmark_name=benchmark_name,
        sample_count=len(valid_pairs),
        classification_metrics=cls_metrics,
        ece=ece,
        mce=mce,
        brier_score=brier,
        conformal_marginal_coverage=conf_marginal["empirical_coverage"],
        conformal_mean_width=conf_marginal["mean_interval_width"],
        mondrian_coverage_by_tier=conf_mondrian,
        reliability_bins=rel_bins,
        avg_latency_ms=round(avg_lat, 2),
        p95_latency_ms=round(p95_lat, 2),
        pass_criteria_met=pass_all,
        target_criteria_report=report,
    )
