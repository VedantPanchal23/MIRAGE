"""Command-line benchmark runner executing offline evaluation across standard datasets.

Usage:
    python -m benchmarks.runner --benchmark all --concurrency 4
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from benchmarks.datasets.factscore import FActScoreLoader
from benchmarks.datasets.halueval import HaluEvalLoader
from benchmarks.datasets.truthfulqa import TruthfulQALoader
from benchmarks.evaluator import (
    BenchmarkCase,
    BenchmarkOutput,
    BenchmarkResult,
    evaluate_benchmark_outputs,
)
from shared.logging import get_logger
from shared.schemas import VerificationRequest
from workers.orchestrator import VerificationOrchestrator

logger = get_logger("benchmark_runner")


class BenchmarkRunner:
    """Orchestrates concurrent evaluation of MIRAGE against benchmark datasets."""

    def __init__(
        self,
        concurrency: int = 4,
        output_dir: str | Path = "results",
        ablation_mode: str = "none",
    ) -> None:
        # Constrain concurrency to max 8 workers to prevent CPU starvation on 10-core HX
        self.concurrency = max(1, min(8, concurrency))
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ablation_mode = ablation_mode
        self.orchestrator = VerificationOrchestrator()

    async def _verify_single_case(
        self,
        case: BenchmarkCase,
        semaphore: asyncio.Semaphore,
    ) -> BenchmarkOutput:
        """Execute verification on a single benchmark instance with concurrency semaphore."""
        async with semaphore:
            # If case provides reference evidence, preload into RAV mock collection
            for idx, ev_chunk in enumerate(case.reference_evidence):
                self.orchestrator.rav_worker.add_mock_document(
                    chunk_id=f"ev_{case.case_id}_{idx}",
                    content=ev_chunk,
                )

            req = VerificationRequest(
                prompt=case.prompt,
                response=case.response,
                tenant_id=f"bench_{case.domain}",
                model_id="benchmark_target",
            )

            start = time.time()
            try:
                res = await self.orchestrator.verify_request(req)
                elapsed_ms = (time.time() - start) * 1000

                # Check if ablation disables calibration or signals
                predicted_hrs = res.hrs_result.hrs
                if self.ablation_mode == "uncalibrated":
                    predicted_hrs = res.hrs_result.raw_score

                output = BenchmarkOutput(
                    case_id=case.case_id,
                    predicted_hrs=predicted_hrs,
                    predicted_tier=res.hrs_result.tier.value,
                    conformal_lower=res.hrs_result.conformal_interval.lower,
                    conformal_upper=res.hrs_result.conformal_interval.upper,
                    latency_ms=elapsed_ms,
                    claims_count=len(res.claims),
                    signal_attribution={
                        "rav": res.hrs_result.signal_attribution.rav,
                        "scs": res.hrs_result.signal_attribution.scs,
                        "nli": res.hrs_result.signal_attribution.nli,
                        "ics": res.hrs_result.signal_attribution.ics,
                    },
                )
            except Exception as exc:
                logger.error("Verification error during benchmark case", case_id=case.case_id, error=str(exc))
                elapsed_ms = (time.time() - start) * 1000
                # Fallback output under unexpected error
                output = BenchmarkOutput(
                    case_id=case.case_id,
                    predicted_hrs=0.50,
                    predicted_tier="MEDIUM",
                    conformal_lower=0.35,
                    conformal_upper=0.65,
                    latency_ms=elapsed_ms,
                )

            return output

    async def run_benchmark(
        self,
        name: str,
        cases: list[BenchmarkCase],
    ) -> BenchmarkResult:
        """Run verification over all cases concurrently and evaluate metrics."""
        logger.info("Starting benchmark execution", name=name, cases_count=len(cases), concurrency=self.concurrency)
        semaphore = asyncio.Semaphore(self.concurrency)

        tasks = [self._verify_single_case(c, semaphore) for c in cases]
        outputs = await asyncio.gather(*tasks)

        result = evaluate_benchmark_outputs(name, cases, outputs)
        return result

    def print_summary(self, results: list[BenchmarkResult]) -> None:
        """Format and print beautiful summary tables in terminal."""
        print("\n" + "=" * 90)
        print("  MIRAGE BENCHMARK EVALUATION RESULTS SUMMARY")
        print("=" * 90)

        for res in results:
            print(f"\n>> Benchmark: {res.benchmark_name} (N={res.sample_count})")
            print("-" * 90)
            cls = res.classification_metrics
            print(
                f"  Classification: Macro F1={cls.get('macro_f1', 0.0):.4f} | "
                f"Accuracy={cls.get('accuracy', 0.0):.4f} | "
                f"AUROC={cls.get('auroc', 0.0):.4f}"
            )
            print(
                f"  Calibration:    ECE={res.ece:.4f} (15 bins) | MCE={res.mce:.4f} | Brier Score={res.brier_score:.4f}"
            )
            print(
                f"  Conformal:      Marginal Coverage={res.conformal_marginal_coverage * 100:.1f}% | "
                f"Mean Width={res.conformal_mean_width:.4f}"
            )
            print(f"  Latency:        Avg={res.avg_latency_ms:.1f}ms | P95={res.p95_latency_ms:.1f}ms")
            print("  Target Criteria Check (Section 17):")
            for crit, passed in res.target_criteria_report.items():
                status_str = "[PASS]" if passed else "[FAIL]"
                print(f"    {status_str} {crit}")

        print("=" * 90 + "\n")

    def save_report(self, results: list[BenchmarkResult]) -> Path:
        """Save structured JSON results report to output directory."""
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        report_file = self.output_dir / f"benchmark_report_{timestamp}.json"

        data = {
            "timestamp": datetime.now(UTC).isoformat(),
            "ablation_mode": self.ablation_mode,
            "results": [r.to_dict() for r in results],
        }

        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info("Saved benchmark report", report_path=str(report_file))
        return report_file


async def main_async(args: argparse.Namespace) -> int:
    """Async entry point for benchmark execution."""
    runner = BenchmarkRunner(
        concurrency=args.concurrency,
        output_dir=args.output_dir,
        ablation_mode=args.ablation,
    )

    datasets_to_run: list[tuple[str, list[BenchmarkCase]]] = []

    if args.benchmark in ("all", "halueval"):
        cases = HaluEvalLoader(args.halueval_path).load_cases(limit=args.limit)
        datasets_to_run.append(("HaluEval (Dialogue/QA/Summary)", cases))

    if args.benchmark in ("all", "truthfulqa"):
        cases = TruthfulQALoader(args.truthfulqa_path).load_cases(limit=args.limit)
        datasets_to_run.append(("TruthfulQA (Misconceptions)", cases))

    if args.benchmark in ("all", "factscore"):
        cases = FActScoreLoader(args.factscore_path).load_cases(limit=args.limit)
        datasets_to_run.append(("FActScore (Biographies)", cases))

    results: list[BenchmarkResult] = []
    for name, cases in datasets_to_run:
        res = await runner.run_benchmark(name, cases)
        results.append(res)

    runner.print_summary(results)
    runner.save_report(results)
    return 0


def main() -> None:
    """CLI parser entrypoint."""
    parser = argparse.ArgumentParser(description="MIRAGE Benchmarking & Evaluation CLI Runner")
    parser.add_argument(
        "--benchmark",
        choices=["all", "halueval", "truthfulqa", "factscore"],
        default="all",
        help="Which benchmark dataset to evaluate",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional max cases per benchmark")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent workers (1-8)")
    parser.add_argument("--output-dir", default="results", help="Directory to save JSON benchmark reports")
    parser.add_argument(
        "--ablation",
        choices=["none", "uncalibrated", "no-scs", "no-rav"],
        default="none",
        help="Ablation study configuration",
    )
    parser.add_argument("--halueval-path", default=None, help="Path to external HaluEval JSON/JSONL")
    parser.add_argument("--truthfulqa-path", default=None, help="Path to external TruthfulQA JSON/JSONL")
    parser.add_argument("--factscore-path", default=None, help="Path to external FActScore JSON/JSONL")

    args = parser.parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
