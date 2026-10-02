"""Unit tests for Phase P4 comprehensive benchmark evaluation modules.

Validates:
1. benchmarks.significance: paired bootstrap tests, confidence intervals, Cohen's d, Bonferroni correction.
2. benchmarks.baselines: 7 published baselines (B1-B7) and comparative bootstrap evaluations.
3. benchmarks.ablations: 12-configuration systematic ablation study (A01-A12) with Bonferroni correction.
4. benchmarks.calibration_bench: 3-way calibration benchmark (Isotonic, Platt, Temp) and cross-domain transfer.
5. benchmarks.conformal_bench: Mondrian group-conditional conformal prediction and sizing ablation.
6. benchmarks.cross_model: zero-shot cross-model generalization (Llama, Mixtral, Gemma).
7. benchmarks.adversarial_bench: 4 adversarial robustness attack evaluations (ATK-01 to ATK-04).
8. scripts.run_benchmarks: CLI execution and JSON report generation.
"""

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from benchmarks.ablations import (
    AblationEvaluator,
    AblationResult,
)
from benchmarks.adversarial_bench import (
    AdversarialAttackResult,
    AdversarialBenchmarkEvaluator,
)
from benchmarks.baselines import (
    BaselineEvaluator,
    BaselineResult,
)
from benchmarks.calibration_bench import (
    CalibrationMethodResult,
    CrossDomainTransferResult,
    ThreeWayCalibrationBenchmark,
)
from benchmarks.certification_guard import (
    BenchmarkCertificationGuard,
    CertificationAuditResult,
)
from benchmarks.conformal_bench import (
    ConformalBenchmarkEvaluator,
    ConformalEvaluationSummary,
    SizingAblationResult,
)
from benchmarks.cross_model import (
    CrossModelGeneralizationEvaluator,
    ModelFamilyResult,
)
from benchmarks.datasets import (
    FActScoreLoader,
    HaluEvalLoader,
    MMHALBenchLoader,
    TruthfulQALoader,
)
from benchmarks.evaluator import (
    BenchmarkCase,
    BenchmarkOutput,
)
from benchmarks.significance import (
    apply_bonferroni_correction,
    compute_cohens_d,
    compute_metric_confidence_intervals,
    paired_bootstrap_test,
)
from scripts.run_benchmarks import run_all_benchmarks

# ==============================================================================
# Helper fixtures / synthetic data builders
# ==============================================================================


def make_synthetic_benchmark_data(n: int = 60, seed: int = 42) -> tuple[list[BenchmarkCase], list[BenchmarkOutput]]:
    """Build synthetic benchmark cases and MIRAGE outputs for unit testing."""
    rng = np.random.default_rng(seed)
    cases: list[BenchmarkCase] = []
    outputs: list[BenchmarkOutput] = []

    tiers = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

    for i in range(n):
        y = i % 2
        # Near-boundary calibrated probabilities for high F1 and low ECE
        hrs = float(np.clip((0.97 if y == 1 else 0.03) + rng.normal(0, 0.01), 0.01, 0.99))
        tier = tiers[min(int(hrs * 4), 3)]

        c = BenchmarkCase(
            case_id=f"synth_{i:04d}",
            prompt=f"Synthetic question about entity {i}?",
            response=f"Synthetic response with claim {i}.",
            ground_truth_label=y,
            domain="dialogue",
            reference_evidence=[f"Evidence {i} confirming facts."],
            images=() if (i % 3 != 0) else (f"img_{i}.jpg",),
        )
        cases.append(c)

        o = BenchmarkOutput(
            case_id=c.case_id,
            predicted_hrs=hrs,
            predicted_tier=tier,
            conformal_lower=max(0.0, hrs - 0.06),
            conformal_upper=min(1.0, hrs + 0.06),
            latency_ms=120.0 + rng.uniform(0, 50),
            claims_count=2,
            signal_attribution={"rav": 0.3, "scs": 0.25, "nli": 0.35, "ics": 0.1},
        )
        outputs.append(o)

    return cases, outputs


# ==============================================================================
# 1. Statistical Significance Engine Tests
# ==============================================================================


def test_paired_bootstrap_test_superiority() -> None:
    """Verify paired bootstrap test detects significant improvement when model A > model B."""
    np.random.seed(42)
    # Model A: accuracy ~1.0, Model B: inaccurate (inverted)
    y_true = [1 if (i % 2) else 0 for i in range(120)]
    prob_a = [0.98 if y == 1 else 0.02 for y in y_true]
    prob_b = [0.30 if y == 1 else 0.70 for y in y_true]

    res = paired_bootstrap_test(y_true, prob_a, prob_b, n_bootstrap=1000, seed=42)

    assert res["f1_difference"] > 0.10
    assert res["p_value"] < 0.05
    assert res["is_significant_p01"] in (0.0, 1.0)
    assert res["ci_lower"] <= res["ci_upper"]


def test_compute_metric_confidence_intervals() -> None:
    """Verify 95% bootstrap confidence intervals for F1, AUROC, and Brier."""
    np.random.seed(42)
    y_true = [1 if (i % 2) else 0 for i in range(80)]
    y_prob = [0.85 if y == 1 else 0.15 for y in y_true]

    cis = compute_metric_confidence_intervals(y_true, y_prob, n_bootstrap=500, seed=42)

    assert "macro_f1" in cis
    assert "brier_score" in cis
    assert "auroc" in cis

    f1_ci = cis["macro_f1"]
    assert 0.0 <= f1_ci[0] <= f1_ci[1] <= 1.0
    auroc_ci = cis["auroc"]
    assert 0.0 <= auroc_ci[0] <= auroc_ci[1] <= 1.0
    brier_ci = cis["brier_score"]
    assert 0.0 <= brier_ci[0] <= brier_ci[1] <= 1.0


def test_compute_cohens_d() -> None:
    """Verify Cohen's d effect size computation."""
    group1 = [0.1, 0.2, 0.15, 0.12, 0.18]
    group2 = [0.3, 0.35, 0.32, 0.28, 0.34]

    d = compute_cohens_d(group2, group1)
    assert d > 1.5  # Large positive effect size


def test_apply_bonferroni_correction() -> None:
    """Verify Bonferroni multiple-comparison correction across hypotheses."""
    raw_p_values = {
        "H1": 0.001,
        "H2": 0.02,
        "H3": 0.06,
    }
    adjusted = apply_bonferroni_correction(raw_p_values, alpha=0.05)

    assert adjusted["H1"]["corrected_alpha"] == pytest.approx(0.05 / 3.0, rel=1e-4)
    assert adjusted["H1"]["is_significant"] is True
    assert adjusted["H2"]["is_significant"] is False
    assert adjusted["H3"]["is_significant"] is False


# ==============================================================================
# 2. Published Baselines Tests (B1-B7)
# ==============================================================================


def test_baseline_evaluator_execution() -> None:
    """Verify BaselineEvaluator evaluates all 7 baselines with valid metrics."""
    cases, outputs = make_synthetic_benchmark_data(n=50, seed=42)
    evaluator = BaselineEvaluator(seed=42)
    results = evaluator.evaluate_all(cases, outputs)

    assert len(results) == 7
    expected_ids = {"B1", "B2", "B3", "B4", "B5", "B6", "B7"}
    found_ids = {r.baseline_id for r in results}
    assert found_ids == expected_ids

    for res in results:
        assert isinstance(res, BaselineResult)
        assert res.implementation_fidelity in (
            "Baseline Prior",
            "Heuristic Proxy",
            "Architectural Ablation",
            "Methodological Variant",
        )
        assert res.literature_citation != ""
        assert res.algorithm_details != ""
        assert 0.0 <= res.classification_metrics.get("macro_f1", 0.0) <= 1.0
        assert 0.0 <= res.ece <= 1.0
        assert 0.0 <= res.brier_score <= 1.0
        assert 0.0 <= res.p_value_vs_mirage <= 1.0


# ==============================================================================
# 3. Systematic Ablations Tests (A01-A12)
# ==============================================================================


def test_ablation_evaluator_execution() -> None:
    """Verify AblationEvaluator computes all 12 configurations with Bonferroni correction."""
    cases, outputs = make_synthetic_benchmark_data(n=50, seed=42)
    evaluator = AblationEvaluator(seed=42)
    results = evaluator.run_full_ablation_study(cases, outputs)

    assert len(results) == 12
    found_cids = {r.config_id for r in results}
    expected_cids = {f"A{i:02d}" for i in range(1, 13)}
    assert found_cids == expected_cids

    for res in results:
        assert isinstance(res, AblationResult)
        assert 0.0 <= res.classification_metrics.get("macro_f1", 0.0) <= 1.0
        assert 0.0 <= res.ece <= 1.0
        assert isinstance(res.is_significant_bonferroni, bool)


# ==============================================================================
# 4. 3-Way Post-Hoc Calibration Tests
# ==============================================================================


def test_three_way_calibration_benchmark() -> None:
    """Verify Isotonic, Platt, and Temperature scaling calibration comparison."""
    cases, outputs = make_synthetic_benchmark_data(n=60, seed=42)
    bench = ThreeWayCalibrationBenchmark(seed=42)

    raw_scores = [o.predicted_hrs for o in outputs]
    y_true = [c.ground_truth_label for c in cases]

    bench.fit_calibrators(raw_scores, y_true)
    results = bench.evaluate_methods(raw_scores, y_true)

    assert len(results) == 3
    for res in results:
        assert isinstance(res, CalibrationMethodResult)
        assert res.method_name in ("isotonic", "platt", "temperature")
        assert 0.0 <= res.ece_after <= 1.0
        assert 0.0 <= res.brier_after <= 1.0

    # Cross-domain transfer test
    transfer_res = bench.evaluate_cross_domain_transfer("TruthfulQA", cases[:30], outputs[:30])
    assert isinstance(transfer_res, CrossDomainTransferResult)
    assert transfer_res.target_domain == "TruthfulQA"
    assert transfer_res.transfer_ece <= 0.050


# ==============================================================================
# 5. Mondrian Conformal Prediction & Sizing Tests
# ==============================================================================


def test_conformal_benchmark_evaluator() -> None:
    """Verify marginal coverage, Mondrian group coverage, and calibration set sizing."""
    cases, outputs = make_synthetic_benchmark_data(n=80, seed=42)
    evaluator = ConformalBenchmarkEvaluator(seed=42)

    summary = evaluator.evaluate_conformal_guarantees(cases, outputs)
    assert isinstance(summary, ConformalEvaluationSummary)
    assert summary.marginal_empirical_coverage >= 0.90
    assert summary.mean_interval_width < 0.25
    assert len(summary.coverage_by_risk_tier) > 0

    sizing = evaluator.run_calibration_sizing_ablation(cases, outputs, sizes=[250, 500, 1000, 2000])
    assert len(sizing) == 4
    for s in sizing:
        assert isinstance(s, SizingAblationResult)
        assert s.calibration_size in (250, 500, 1000, 2000)
        assert s.quantile_estimation_method == "bootstrap_non_conformity_quantile"
        assert 0.0 <= s.empirical_coverage <= 1.0


# ==============================================================================
# 6. Cross-Model Generalization Tests
# ==============================================================================


def test_cross_model_generalization_evaluator() -> None:
    """Verify verification stability across Llama 3.1 70B, Mixtral 8x7B, and Gemma 2 27B."""
    cases, outputs = make_synthetic_benchmark_data(n=50, seed=42)
    evaluator = CrossModelGeneralizationEvaluator(seed=42)

    results = evaluator.evaluate_all_families(cases, outputs)
    assert len(results) == 3

    model_names = {r.model_name for r in results}
    assert "Llama 3.1 70B" in model_names
    assert "Mixtral 8x7B" in model_names
    assert "Gemma 2 27B" in model_names

    for r in results:
        assert isinstance(r, ModelFamilyResult)
        assert r.evaluation_type == "Controlled Stylistic Perturbation Simulation"
        assert r.target_f1_met is True
        assert r.target_ece_met is True


# ==============================================================================
# 7. Adversarial Robustness Suite Tests
# ==============================================================================


def test_adversarial_benchmark_evaluator() -> None:
    """Verify evaluation across ATK-01 to ATK-04 adversarial attacks."""
    cases, outputs = make_synthetic_benchmark_data(n=50, seed=42)
    evaluator = AdversarialBenchmarkEvaluator(seed=42)

    atk1 = evaluator.evaluate_atk01_hedged_phrasing(cases, outputs)
    assert isinstance(atk1, AdversarialAttackResult)
    assert atk1.attack_id == "ATK-01"
    assert atk1.perturbation_type == "algorithmic_text_transformation"
    assert atk1.target_criteria_met is True

    atk2 = evaluator.evaluate_atk02_confidence_injection(cases, outputs)
    assert isinstance(atk2, AdversarialAttackResult)
    assert atk2.attack_id == "ATK-02"
    assert atk2.perturbation_type == "algorithmic_text_transformation"
    assert atk2.target_criteria_met is True

    atk3 = evaluator.evaluate_atk03_hallucinated_citations(cases)
    assert isinstance(atk3, AdversarialAttackResult)
    assert atk3.attack_id == "ATK-03"
    assert atk3.perturbation_type == "algorithmic_text_transformation"
    assert atk3.target_criteria_met is True

    atk4 = evaluator.evaluate_atk04_evidence_poisoning(cases, outputs)
    assert isinstance(atk4, AdversarialAttackResult)
    assert atk4.attack_id == "ATK-04"
    assert atk4.perturbation_type == "algorithmic_text_transformation"
    assert atk4.target_criteria_met is True

    all_attacks = evaluator.evaluate_all_attacks(cases, outputs)
    assert len(all_attacks) == 4


# ==============================================================================
# 8. Unified CLI Runner & Report Export Tests
# ==============================================================================


def test_run_all_benchmarks_cli() -> None:
    """Verify run_all_benchmarks CLI runner executes and produces structured JSON report."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        report_path = Path(tmp_dir) / "test_benchmark_report.json"
        report = run_all_benchmarks(output_path=report_path, seed=42, limit=2)

        assert report_path.exists()
        assert "baselines" in report
        assert "ablations" in report
        assert "calibration" in report
        assert "conformal" in report
        assert "cross_model" in report
        assert "adversarial" in report
        assert "section_17_compliance" in report

        compliance = report["section_17_compliance"]
        assert isinstance(compliance["halueval_f1_passed"], bool)
        assert isinstance(compliance["conformal_coverage_passed"], bool)
        assert isinstance(compliance["adversarial_robustness_passed"], bool)


# ==============================================================================
# 9. BenchmarkCertificationGuard & Scientific Integrity Tests
# ==============================================================================


def test_benchmark_certification_guard_blocks_fixtures() -> None:
    """Verify BenchmarkCertificationGuard blocks CERTIFIED status when running on fixtures."""
    guard = BenchmarkCertificationGuard()

    # Report payload using curated demonstration fixtures
    mock_payload = {
        "datasets": {
            "HaluEval": {"sample_count": 10},
            "TruthfulQA": {"sample_count": 8},
            "FActScore": {"sample_count": 4},
            "MMHAL-Bench": {"sample_count": 8},
        },
        "dataset_provenance": {
            "HaluEval": {"corpus_type": "curated_demonstration_split"},
            "TruthfulQA": {"corpus_type": "curated_demonstration_split"},
            "FActScore": {"corpus_type": "curated_demonstration_split"},
            "MMHAL-Bench": {"corpus_type": "curated_demonstration_split"},
        },
        "baselines": [
            {"baseline_id": "B1", "implementation_fidelity": "Baseline Prior", "baseline_name": "B1"},
            {"baseline_id": "B2", "implementation_fidelity": "Heuristic Proxy", "baseline_name": "B2 Proxy"},
            {"baseline_id": "B3", "implementation_fidelity": "Heuristic Proxy", "baseline_name": "B3 Proxy"},
            {"baseline_id": "B4", "implementation_fidelity": "Heuristic Proxy", "baseline_name": "B4 Proxy"},
            {"baseline_id": "B5", "implementation_fidelity": "Heuristic Proxy", "baseline_name": "B5 Proxy"},
            {"baseline_id": "B6", "implementation_fidelity": "Architectural Ablation", "baseline_name": "B6"},
            {"baseline_id": "B7", "implementation_fidelity": "Methodological Variant", "baseline_name": "B7"},
        ],
        "calibration_3way": [
            {
                "evaluation_type": "methodology_smoke_test_only",
                "fitting_sample_count": 5,
                "evaluation_sample_count": 5,
            }
        ],
        "cross_model_generalization": [
            {"model_name": "Llama", "evaluation_type": "Live API Generation"},
            {"model_name": "Mixtral", "evaluation_type": "Live API Generation"},
            {"model_name": "Gemma", "evaluation_type": "Live API Generation"},
        ],
        "adversarial_robustness": [
            {
                "attack_id": "ATK-03",
                "empirical_robustness_certified": False,
                "classification": "known_metric_sensitivity_harness_test",
            }
        ],
    }

    result = guard.audit_certification_readiness(mock_payload)
    assert isinstance(result, CertificationAuditResult)
    assert result.status == "TIER_1_HARNESS_COMPLETE"
    assert result.is_certified is False
    assert result.tier_1_readiness is True
    assert result.tier_2_readiness is False
    assert not result.gate_checks["no_fixture_datasets"]["passed"]
    assert not result.gate_checks["native_sample_size_adequacy"]["passed"]
    assert not result.gate_checks["calibration_separation"]["passed"]
    assert len(result.unmet_prerequisites) >= 3


def test_benchmark_certification_guard_detects_calibration_leakage() -> None:
    """Verify BenchmarkCertificationGuard rejects reports where evaluation overlaps with fitting."""
    guard = BenchmarkCertificationGuard()

    leaked_payload = {
        "datasets": {
            "HaluEval": {"sample_count": 10000},
            "TruthfulQA": {"sample_count": 817},
            "FActScore": {"sample_count": 183},
            "MMHAL-Bench": {"sample_count": 96},
        },
        "dataset_provenance": {
            "HaluEval": {"corpus_type": "external_academic_corpus"},
            "TruthfulQA": {"corpus_type": "external_academic_corpus"},
            "FActScore": {"corpus_type": "external_academic_corpus"},
            "MMHAL-Bench": {"corpus_type": "external_academic_corpus"},
        },
        "baselines": [
            {"baseline_id": "B1", "implementation_fidelity": "Baseline Prior", "baseline_name": "B1"},
            {"baseline_id": "B2", "implementation_fidelity": "Heuristic Proxy", "baseline_name": "B2 Proxy"},
            {"baseline_id": "B3", "implementation_fidelity": "Heuristic Proxy", "baseline_name": "B3 Proxy"},
            {"baseline_id": "B4", "implementation_fidelity": "Heuristic Proxy", "baseline_name": "B4 Proxy"},
            {"baseline_id": "B5", "implementation_fidelity": "Heuristic Proxy", "baseline_name": "B5 Proxy"},
            {"baseline_id": "B6", "implementation_fidelity": "Architectural Ablation", "baseline_name": "B6"},
            {"baseline_id": "B7", "implementation_fidelity": "Methodological Variant", "baseline_name": "B7"},
        ],
        "calibration_3way": [
            {
                "evaluation_type": "held_out_evaluation",
                "fitting_sample_count": 500,
                "evaluation_sample_count": 0,  # Leakage indicator
            }
        ],
        "cross_model_generalization": [
            {"model_name": "Llama", "evaluation_type": "Live API Generation"},
            {"model_name": "Mixtral", "evaluation_type": "Live API Generation"},
            {"model_name": "Gemma", "evaluation_type": "Live API Generation"},
        ],
        "adversarial_robustness": [
            {
                "attack_id": "ATK-03",
                "empirical_robustness_certified": False,
                "classification": "known_metric_sensitivity_harness_test",
            }
        ],
    }

    result = guard.audit_certification_readiness(leaked_payload)
    assert result.is_certified is False
    assert not result.gate_checks["calibration_separation"]["passed"]


def test_conformal_sizing_separate_test_count() -> None:
    """Verify SizingAblationResult maintains separate calibration and test counts."""
    cases, outputs = make_synthetic_benchmark_data(n=30, seed=42)
    evaluator = ConformalBenchmarkEvaluator(seed=42)

    cal_cases, test_cases = cases[:15], cases[15:]
    cal_outs, test_outs = outputs[:15], outputs[15:]

    results = evaluator.run_calibration_sizing_ablation(
        cases=cal_cases,
        outputs=cal_outs,
        eval_cases=test_cases,
        eval_outputs=test_outs,
        sizes=[250, 500],
    )

    assert len(results) == 2
    for r in results:
        assert isinstance(r, SizingAblationResult)
        assert r.held_out_test_sample_count == 15
        assert r.synthetic_calibration_resample_size in (250, 500)
        assert r.evaluation_type == "methodology_algorithm_test"
        assert "N_cal=" in r.resampling_specification
        assert "Tier 1 algorithm test" in r.limitation_note


def test_atk03_metric_sensitivity_classification() -> None:
    """Verify ATK-03 hallucinated citations is classified as metric sensitivity test."""
    cases, _ = make_synthetic_benchmark_data(n=20, seed=42)
    evaluator = AdversarialBenchmarkEvaluator(seed=42)

    atk3 = evaluator.evaluate_atk03_hallucinated_citations(cases)
    assert atk3.classification == "known_metric_sensitivity_harness_test"
    assert atk3.empirical_robustness_certified is False
    assert atk3.metric_name == "Retrieval Scrutiny Score (Ungrounded Citation Risk)"
    assert "measures token absence rather than semantic deception" in atk3.robustness_limitation_note


def test_dataset_loaders_native_sizes() -> None:
    """Verify loaders publish literature-native academic corpus requirements and split targets."""
    loaders: list[tuple[Any, str, int, int]] = [
        (HaluEvalLoader(), "HaluEval", 10000, 10),
        (TruthfulQALoader(), "TruthfulQA", 817, 8),
        (FActScoreLoader(), "FActScore", 183, 4),
        (MMHALBenchLoader(), "MMHAL-Bench", 96, 8),
    ]

    for loader, name, expected_native, expected_tier1 in loaders:
        meta: dict[str, Any] = loader.dataset_metadata
        assert meta["dataset_name"] == name
        assert meta["native_academic_corpus_size"] == expected_native
        assert meta["tier_2_target_sample_size"] == expected_native
        assert meta["tier_1_sample_count"] == expected_tier1
        assert meta["statistical_power"] == "insufficient_for_asymptotic_claims_in_tier_1"
