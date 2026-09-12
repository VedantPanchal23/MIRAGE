"""Unit tests for the MIRAGE benchmarking and statistical evaluation engine."""

import pytest

from benchmarks.datasets.factscore import FActScoreLoader
from benchmarks.datasets.halueval import HaluEvalLoader
from benchmarks.datasets.truthfulqa import TruthfulQALoader
from benchmarks.evaluator import (
    BenchmarkCase,
    BenchmarkOutput,
    evaluate_benchmark_outputs,
)
from benchmarks.metrics import (
    compute_calibration_metrics,
    compute_classification_metrics,
    compute_conformal_coverage,
    compute_mondrian_coverage,
    mcnemar_test,
    paired_bootstrap_test,
)


@pytest.mark.unit
class TestClassificationMetrics:
    """Test accuracy, macro F1, and ranking discrimination metrics."""

    def test_perfect_classification(self) -> None:
        y_true = [0, 0, 1, 1]
        y_pred = [0, 0, 1, 1]
        y_prob = [0.1, 0.2, 0.8, 0.9]

        res = compute_classification_metrics(y_true, y_pred, y_prob)
        assert res["accuracy"] == 1.0
        assert res["macro_f1"] == 1.0
        assert res["auroc"] == 1.0

    def test_imperfect_classification_f1(self) -> None:
        y_true = [0, 0, 1, 1]
        y_pred = [0, 1, 1, 1]  # 1 false positive
        res = compute_classification_metrics(y_true, y_pred)
        assert res["accuracy"] == 0.75
        assert 0.60 < res["macro_f1"] < 1.0


@pytest.mark.unit
class TestCalibrationMetrics:
    """Test ECE (15 bins), MCE, and Brier score."""

    def test_perfect_calibration_ece_near_zero(self) -> None:
        # Create perfectly calibrated predictions
        y_true = [0] * 50 + [1] * 50
        y_prob = [0.0] * 50 + [1.0] * 50
        ece, mce, brier, bins = compute_calibration_metrics(y_true, y_prob, num_bins=15)

        assert ece == 0.0
        assert mce == 0.0
        assert brier == 0.0
        assert len(bins) == 15

    def test_uncalibrated_severe_ece(self) -> None:
        # Model predicts 0.99 for negative labels and 0.01 for positive labels
        y_true = [0] * 20 + [1] * 20
        y_prob = [0.99] * 20 + [0.01] * 20
        ece, mce, brier, _ = compute_calibration_metrics(y_true, y_prob, num_bins=15)

        assert ece > 0.80
        assert mce > 0.80
        assert brier > 0.80


@pytest.mark.unit
class TestConformalPredictionMetrics:
    """Test marginal and Mondrian group-conditional empirical coverage."""

    def test_conformal_coverage_continuous(self) -> None:
        y_true = [0.10, 0.50, 0.85]
        intervals = [
            (0.05, 0.15),  # covers 0.10
            (0.40, 0.60),  # covers 0.50
            (0.80, 0.90),  # covers 0.85
        ]
        res = compute_conformal_coverage(y_true, intervals)
        assert res["empirical_coverage"] == 1.0
        assert res["mean_interval_width"] == 0.1333

    def test_conformal_coverage_binary_labels(self) -> None:
        y_true = [0, 0, 1]
        intervals = [
            (0.05, 0.15),  # low <= 0.20 -> covered for 0
            (0.08, 0.18),  # low <= 0.20 -> covered for 0
            (0.80, 0.95),  # high >= 0.80 -> covered for 1
        ]
        res = compute_conformal_coverage(y_true, intervals, tolerance=0.20)
        assert res["empirical_coverage"] == 1.0

    def test_mondrian_group_coverage(self) -> None:
        y_true = [0.1, 0.8]
        intervals = [(0.0, 0.2), (0.7, 0.9)]
        groups = ["tier:LOW", "tier:HIGH"]
        res = compute_mondrian_coverage(y_true, intervals, groups)
        assert res["tier:LOW"] == 1.0
        assert res["tier:HIGH"] == 1.0


@pytest.mark.unit
class TestSignificanceTesting:
    """Test Paired Bootstrap and McNemar tests."""

    def test_paired_bootstrap_distinct_models(self) -> None:
        y_true = [1] * 50 + [0] * 50
        # Model A is perfect
        prob_a = [0.9] * 50 + [0.1] * 50
        # Model B is random
        prob_b = [0.5] * 100

        res = paired_bootstrap_test(y_true, prob_a, prob_b, n_bootstrap=500, seed=42)
        assert res["macro_f1_a"] > res["macro_f1_b"]
        assert res["p_value"] < 0.01
        assert res["is_significant_p01"] == 1.0

    def test_mcnemar_test_identical_models(self) -> None:
        y_true = [0, 1, 0, 1]
        pred_a = [0, 1, 0, 1]
        pred_b = [0, 1, 0, 1]
        res = mcnemar_test(y_true, pred_a, pred_b)
        assert res["chi2"] == 0.0
        assert res["p_value"] == 1.0


@pytest.mark.unit
class TestDatasetLoaders:
    """Test HaluEval, TruthfulQA, and FActScore loaders."""

    def test_halueval_curated_loader(self) -> None:
        loader = HaluEvalLoader()
        cases = loader.load_cases(limit=4)
        assert len(cases) == 4
        assert all(isinstance(c, BenchmarkCase) for c in cases)
        assert cases[0].ground_truth_label in (0, 1)

    def test_truthfulqa_curated_loader(self) -> None:
        loader = TruthfulQALoader()
        cases = loader.load_cases()
        assert len(cases) >= 4
        assert any(c.domain == "misconceptions" for c in cases)

    def test_factscore_curated_loader(self) -> None:
        loader = FActScoreLoader()
        cases = loader.load_cases()
        assert len(cases) >= 4
        assert any("Turing" in c.response for c in cases)


@pytest.mark.unit
class TestBenchmarkEvaluator:
    """Test evaluate_benchmark_outputs against target criteria."""

    def test_evaluate_benchmark_outputs_summary(self) -> None:
        cases = [
            BenchmarkCase(case_id="c1", prompt="q1", response="r1", ground_truth_label=0),
            BenchmarkCase(case_id="c2", prompt="q2", response="r2", ground_truth_label=1),
        ]
        outputs = [
            BenchmarkOutput(
                case_id="c1",
                predicted_hrs=0.10,
                predicted_tier="LOW",
                conformal_lower=0.05,
                conformal_upper=0.15,
                latency_ms=15.0,
            ),
            BenchmarkOutput(
                case_id="c2",
                predicted_hrs=0.90,
                predicted_tier="CRITICAL",
                conformal_lower=0.85,
                conformal_upper=0.95,
                latency_ms=20.0,
            ),
        ]

        result = evaluate_benchmark_outputs("TestBench", cases, outputs)
        assert result.benchmark_name == "TestBench"
        assert result.sample_count == 2
        assert result.classification_metrics["accuracy"] == 1.0
        assert result.ece <= 0.10
        assert result.conformal_marginal_coverage == 1.0
        assert result.avg_latency_ms == 17.5
        d = result.to_dict()
        assert "target_criteria_report" in d
