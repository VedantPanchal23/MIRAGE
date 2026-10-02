"""One-click reproducibility CLI runner for MIRAGE comprehensive benchmark evaluation.

Implements the official reproducibility runner specified in Benchmarking_Evaluation.md §14:
    python scripts/run_benchmarks.py --benchmark all --seed 42

Executes offline evaluation across all academic benchmarks, baselines, ablations,
calibrations, conformal bounds, cross-model testing, and adversarial attack suites,
producing structured JSON reports matching the Section 17 Target Criteria table.
"""

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.ablations import AblationEvaluator
from benchmarks.adversarial_bench import AdversarialBenchmarkEvaluator
from benchmarks.baselines import BaselineEvaluator
from benchmarks.calibration_bench import ThreeWayCalibrationBenchmark
from benchmarks.conformal_bench import ConformalBenchmarkEvaluator
from benchmarks.cross_model import CrossModelGeneralizationEvaluator
from benchmarks.datasets import (
    FActScoreLoader,
    HaluEvalLoader,
    MMHALBenchLoader,
    TruthfulQALoader,
)
from benchmarks.evaluator import (
    BenchmarkOutput,
    BenchmarkResult,
    evaluate_benchmark_outputs,
)
from benchmarks.runner import BenchmarkRunner
from shared.logging import get_logger

logger = get_logger("run_benchmarks_cli")


def set_reproducible_seed(seed: int = 42) -> None:
    """Set global random seeds for deterministic benchmark execution."""
    random.seed(seed)
    np.random.seed(seed)


def format_table_row(cols: list[str], widths: list[int]) -> str:
    """Format string columns into aligned table row."""
    padded = [col.ljust(w)[:w] for col, w in zip(cols, widths, strict=False)]
    return "| " + " | ".join(padded) + " |"


async def execute_phase4_benchmarks(args: argparse.Namespace) -> dict[str, Any]:
    """Execute all requested Phase P4 benchmark suites and assemble structured report."""
    set_reproducible_seed(args.seed)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_payload: dict[str, Any] = {
        "mirage_version": "2.1.0",
        "phase": "Phase P4: Comprehensive Benchmark Evaluation",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": args.seed,
        "concurrency": args.concurrency,
        "datasets": {},
        "baselines": [],
        "ablations": [],
        "calibration_3way": [],
        "cross_domain_transfer": {},
        "conformal_guarantees": {},
        "calibration_sizing_ablation": [],
        "cross_model_generalization": [],
        "adversarial_robustness": [],
        "overall_status": "PENDING",
    }

    # 1. Load Datasets
    logger.info("Loading academic benchmark datasets...")
    halueval_cases = HaluEvalLoader(args.halueval_path).load_cases(limit=args.limit)
    truthfulqa_cases = TruthfulQALoader(args.truthfulqa_path).load_cases(limit=args.limit)
    factscore_cases = FActScoreLoader(args.factscore_path).load_cases(limit=args.limit)
    mmhal_cases = MMHALBenchLoader(args.mmhal_path).load_cases(limit=args.limit)

    all_cases = halueval_cases + truthfulqa_cases + factscore_cases + mmhal_cases
    logger.info(
        "Loaded benchmark cases",
        halueval=len(halueval_cases),
        truthfulqa=len(truthfulqa_cases),
        factscore=len(factscore_cases),
        mmhal=len(mmhal_cases),
        total=len(all_cases),
    )

    runner = BenchmarkRunner(concurrency=args.concurrency, output_dir=output_dir)

    # 2. Execute MIRAGE Full Pipeline Verification
    logger.info("Executing MIRAGE full pipeline verification...")
    dataset_results: dict[str, BenchmarkResult] = {}
    dataset_outputs: dict[str, list[BenchmarkOutput]] = {}

    for d_name, d_cases in [
        ("HaluEval", halueval_cases),
        ("TruthfulQA", truthfulqa_cases),
        ("FActScore", factscore_cases),
        ("MMHAL-Bench", mmhal_cases),
    ]:
        if args.benchmark in ("all", d_name.lower().replace("-", "")):
            logger.info("Evaluating benchmark dataset", dataset=d_name, count=len(d_cases))
            # Verify cases using runner semaphore
            semaphore = asyncio.Semaphore(args.concurrency)
            tasks = [runner._verify_single_case(c, semaphore) for c in d_cases]
            outs = await asyncio.gather(*tasks)

            res = evaluate_benchmark_outputs(d_name, d_cases, outs)
            dataset_results[d_name] = res
            dataset_outputs[d_name] = outs
            report_payload["datasets"][d_name] = res.to_dict()

    # Aggregate primary test outputs
    primary_cases = halueval_cases
    primary_outputs = dataset_outputs.get("HaluEval", [])
    if not primary_outputs and all_cases:
        tasks = [runner._verify_single_case(c, asyncio.Semaphore(args.concurrency)) for c in all_cases]
        primary_outputs = await asyncio.gather(*tasks)
        primary_cases = all_cases

    # 3. Baseline Comparisons (B1 - B7)
    if args.benchmark in ("all", "baselines"):
        logger.info("Running Baseline Comparisons (B1-B7)...")
        b_evaluator = BaselineEvaluator(seed=args.seed)
        b_results = b_evaluator.evaluate_all(primary_cases, primary_outputs)
        report_payload["baselines"] = [b.to_dict() for b in b_results]

    # 4. 12-Configuration Systematic Ablation Study (A01 - A12)
    if args.benchmark in ("all", "ablation"):
        logger.info("Running 12-Configuration Systematic Ablation Study (A01-A12)...")
        a_evaluator = AblationEvaluator(seed=args.seed)
        a_results = a_evaluator.run_full_ablation_study(primary_cases, primary_outputs)
        report_payload["ablations"] = [a.to_dict() for a in a_results]

    # 5. 3-Way Calibration Benchmark & Cross-Domain Transfer
    if args.benchmark in ("all", "calibration"):
        logger.info("Running 3-Way Post-Hoc Calibration Benchmark...")
        c_bench = ThreeWayCalibrationBenchmark(seed=args.seed)
        raw_scores = [o.predicted_hrs for o in primary_outputs]
        y_true = [c.ground_truth_label for c in primary_cases]
        c_bench.fit_calibrators(raw_scores, y_true)

        cal_results = c_bench.evaluate_methods(raw_scores, y_true)
        report_payload["calibration_3way"] = [c.to_dict() for c in cal_results]

        # Transfer to TruthfulQA zero-shot
        if "TruthfulQA" in dataset_outputs:
            tqa_transfer = c_bench.evaluate_cross_domain_transfer(
                "TruthfulQA", truthfulqa_cases, dataset_outputs["TruthfulQA"]
            )
            report_payload["cross_domain_transfer"] = tqa_transfer.to_dict()

    # 6. Mondrian Conformal Prediction & Calibration Sizing Ablation
    if args.benchmark in ("all", "conformal"):
        logger.info("Evaluating Mondrian Conformal Prediction Guarantees & Sizing Ablation...")
        cp_evaluator = ConformalBenchmarkEvaluator(seed=args.seed)
        cp_summary = cp_evaluator.evaluate_conformal_guarantees(primary_cases, primary_outputs)
        report_payload["conformal_guarantees"] = cp_summary.to_dict()

        sizing_res = cp_evaluator.run_calibration_sizing_ablation(primary_cases, primary_outputs)
        report_payload["calibration_sizing_ablation"] = [s.to_dict() for s in sizing_res]

    # 7. Cross-Model Generalization Testing
    if args.benchmark in ("all", "cross_model", "crossmodel"):
        logger.info("Evaluating Cross-Model Generalization (Llama 3.1, Mixtral, Gemma 2)...")
        cm_evaluator = CrossModelGeneralizationEvaluator(seed=args.seed)
        cm_results = cm_evaluator.evaluate_all_families(primary_cases, primary_outputs)
        report_payload["cross_model_generalization"] = [m.to_dict() for m in cm_results]

    # 8. Adversarial Robustness Testing (ATK-01 to ATK-04)
    if args.benchmark in ("all", "adversarial"):
        logger.info("Evaluating Adversarial Robustness Suite (ATK-01 to ATK-04)...")
        adv_evaluator = AdversarialBenchmarkEvaluator(seed=args.seed)
        adv_results = adv_evaluator.evaluate_all_attacks(primary_cases, primary_outputs)
        report_payload["adversarial_robustness"] = [a.to_dict() for a in adv_results]

    # 9. Verify Section 17 Target Criteria Acceptance
    all_targets_passed = True
    for d_name, d_res in dataset_results.items():
        if not d_res.pass_criteria_met:
            all_targets_passed = False
            logger.warning("Dataset benchmark failed target criteria", dataset=d_name)

    report_payload["overall_status"] = "PASSED" if all_targets_passed else "FAILED"

    # Convenient aliases & Section 17 Target Compliance Summary
    report_payload["calibration"] = report_payload["calibration_3way"]
    report_payload["conformal"] = report_payload["conformal_guarantees"]
    report_payload["cross_model"] = report_payload["cross_model_generalization"]
    report_payload["adversarial"] = report_payload["adversarial_robustness"]
    report_payload["section_17_compliance"] = {
        "halueval_f1_passed": report_payload.get("datasets", {}).get("HaluEval", {}).get("pass_criteria_met", True),
        "conformal_coverage_passed": report_payload.get("conformal_guarantees", {}).get("marginal_target_met", True),
        "calibration_generalization_passed": report_payload.get("cross_domain_transfer", {}).get(
            "transfer_generalization_target_met", True
        ),
        "cross_model_invariance_passed": all(
            m.get("target_f1_met", True) for m in report_payload.get("cross_model_generalization", [])
        ),
        "adversarial_robustness_passed": all(
            a.get("target_criteria_met", True) for a in report_payload.get("adversarial_robustness", [])
        ),
    }

    # Save output report
    report_file = output_dir / "benchmark_report_p4.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    logger.info("Phase P4 Benchmark Evaluation report written", report_file=str(report_file))
    return report_payload


def run_all_benchmarks(
    output_path: Path | None = None,
    seed: int = 42,
    limit: int | None = 20,
    concurrency: int = 4,
) -> dict[str, Any]:
    """Synchronous programmatic wrapper to execute all benchmarks and return the report."""
    args = argparse.Namespace(
        benchmark="all",
        limit=limit,
        concurrency=concurrency,
        seed=seed,
        output_dir=str(output_path.parent) if output_path else "results",
        halueval_path=None,
        truthfulqa_path=None,
        factscore_path=None,
        mmhal_path=None,
    )
    report = asyncio.run(execute_phase4_benchmarks(args))
    if output_path and output_path != Path(args.output_dir) / "benchmark_report_p4.json":
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    return report


def print_cli_summary_tables(report: dict[str, Any]) -> None:
    """Print clean formatted markdown tables in terminal for human inspection."""
    print("\n" + "=" * 95)
    print("  MIRAGE PHASE P4: COMPREHENSIVE BENCHMARK EVALUATION RESULTS")
    print(f"  Status: {report['overall_status']} | Timestamp: {report['timestamp']}")
    print("=" * 95)

    # 1. Dataset Benchmarks Table
    print("\n### 1. Primary Benchmark Datasets Evaluation (Section 2 & 17)")
    col_names = ["Benchmark", "Samples", "Macro F1", "AUROC", "ECE (15 bins)", "Brier", "Coverage", "Target"]
    widths = [18, 9, 10, 8, 14, 8, 10, 8]
    print(format_table_row(col_names, widths))
    print("|" + "|".join(["-" * (w + 2) for w in widths]) + "|")

    for d_name, d_data in report.get("datasets", {}).items():
        cls = d_data.get("classification_metrics", {})
        row = [
            d_name,
            str(d_data.get("sample_count", 0)),
            f"{cls.get('macro_f1', 0.0):.4f}",
            f"{cls.get('auroc', 0.0):.4f}",
            f"{d_data.get('ece', 0.0):.4f}",
            f"{d_data.get('brier_score', 0.0):.4f}",
            f"{d_data.get('conformal_marginal_coverage', 0.0) * 100:.1f}%",
            "PASS" if d_data.get("pass_criteria_met") else "FAIL",
        ]
        print(format_table_row(row, widths))

    # 2. Baselines Comparison Table
    if report.get("baselines"):
        print("\n### 2. Baseline Comparisons vs MIRAGE (Section 4)")
        col_names = ["ID", "Baseline Name", "Signal Family", "Macro F1", "ECE", "Brier", "p-value", "Verdict"]
        widths = [4, 28, 14, 10, 8, 8, 10, 8]
        print(format_table_row(col_names, widths))
        print("|" + "|".join(["-" * (w + 2) for w in widths]) + "|")

        for b in report["baselines"]:
            cls = b.get("classification_metrics", {})
            row = [
                b.get("baseline_id", ""),
                b.get("baseline_name", ""),
                b.get("signal_family", ""),
                f"{cls.get('macro_f1', 0.0):.4f}",
                f"{b.get('ece', 0.0):.4f}",
                f"{b.get('brier_score', 0.0):.4f}",
                f"{b.get('p_value_vs_mirage', 1.0):.5f}",
                "PASS" if b.get("is_mirage_significantly_better") else "TIE",
            ]
            print(format_table_row(row, widths))

    # 3. Ablation Study Table
    if report.get("ablations"):
        print("\n### 3. Systematic Ablation Study (Section 5)")
        col_names = ["ID", "Configuration", "Signals", "Meta-Learner", "Macro F1", "ECE", "Delta F1", "Sig."]
        widths = [4, 30, 16, 14, 10, 8, 10, 6]
        print(format_table_row(col_names, widths))
        print("|" + "|".join(["-" * (w + 2) for w in widths]) + "|")

        for a in report["ablations"]:
            cls = a.get("classification_metrics", {})
            row = [
                a.get("config_id", ""),
                a.get("description", ""),
                "+".join(a.get("active_signals", [])),
                a.get("meta_learner", ""),
                f"{cls.get('macro_f1', 0.0):.4f}",
                f"{a.get('ece', 0.0):.4f}",
                f"{a.get('delta_f1_vs_full', 0.0):+.4f}",
                "YES" if a.get("is_significant_bonferroni") else "NO",
            ]
            print(format_table_row(row, widths))

    # 4. Calibration Benchmark Table
    if report.get("calibration_3way"):
        print("\n### 4. 3-Way Calibration Benchmark (Section 6)")
        col_names = ["Calibration Method", "ECE Before", "ECE After", "MCE After", "Brier After", "Target Met"]
        widths = [22, 12, 12, 12, 12, 12]
        print(format_table_row(col_names, widths))
        print("|" + "|".join(["-" * (w + 2) for w in widths]) + "|")

        for c in report["calibration_3way"]:
            row = [
                c.get("method_name", "").title(),
                f"{c.get('ece_before', 0.0):.4f}",
                f"{c.get('ece_after', 0.0):.4f}",
                f"{c.get('mce_after', 0.0):.4f}",
                f"{c.get('brier_after', 0.0):.4f}",
                "PASS" if c.get("target_ece_met") else "FAIL",
            ]
            print(format_table_row(row, widths))

    # 5. Adversarial Robustness Table
    if report.get("adversarial_robustness"):
        print("\n### 5. Adversarial Robustness Suite (Section 11)")
        col_names = ["Attack ID", "Attack Name", "Clean Metric", "Attacked", "Delta", "Target", "Status"]
        widths = [10, 28, 14, 10, 8, 8, 8]
        print(format_table_row(col_names, widths))
        print("|" + "|".join(["-" * (w + 2) for w in widths]) + "|")

        for adv in report["adversarial_robustness"]:
            row = [
                adv.get("attack_id", ""),
                adv.get("attack_name", ""),
                f"{adv.get('clean_metric', 0.0):.4f}",
                f"{adv.get('attacked_metric', 0.0):.4f}",
                f"{adv.get('metric_delta', 0.0):.4f}",
                f"{adv.get('target_threshold', 0.0):.2f}",
                "PASS" if adv.get("target_criteria_met") else "FAIL",
            ]
            print(format_table_row(row, widths))

    print("\n" + "=" * 95 + "\n")


def main() -> None:
    """CLI entry point for running Phase P4 benchmarks."""
    parser = argparse.ArgumentParser(description="MIRAGE Phase P4: Comprehensive Benchmark Evaluation CLI")
    parser.add_argument(
        "--benchmark",
        choices=[
            "all",
            "halueval",
            "truthfulqa",
            "factscore",
            "mmhal",
            "baselines",
            "ablation",
            "calibration",
            "conformal",
            "cross_model",
            "adversarial",
        ],
        default="all",
        help="Evaluation suite to execute (default: all)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional case limit per benchmark")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrency workers (1-8)")
    parser.add_argument("--seed", type=int, default=42, help="Deterministic random seed (default: 42)")
    parser.add_argument("--output-dir", default="results", help="Directory for JSON evaluation reports")
    parser.add_argument("--halueval-path", default=None, help="Optional external HaluEval path")
    parser.add_argument("--truthfulqa-path", default=None, help="Optional external TruthfulQA path")
    parser.add_argument("--factscore-path", default=None, help="Optional external FActScore path")
    parser.add_argument("--mmhal-path", default=None, help="Optional external MMHAL-Bench path")

    args = parser.parse_args()
    report = asyncio.run(execute_phase4_benchmarks(args))
    print_cli_summary_tables(report)


if __name__ == "__main__":
    main()
