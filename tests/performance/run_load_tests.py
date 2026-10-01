"""Automated Runner and Orchestrator for MIRAGE Performance Testing (P3.1).

Executes k6 load testing scenarios (Scenario 1 Baseline, Scenario 2 Ramp-Up, Scenario 3 Sustained Load),
records git commit and environment metadata, checks gateway health, and aggregates structured results.

Usage:
    python tests/performance/run_load_tests.py --scenario baseline
    python tests/performance/run_load_tests.py --scenario ramp_up
    python tests/performance/run_load_tests.py --scenario sustained
    python tests/performance/run_load_tests.py --all --smoke
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shared.config import get_settings  # noqa: E402
from shared.logging import get_logger  # noqa: E402

logger = get_logger("performance_runner")

SCENARIOS: dict[str, str] = {
    "baseline": "tests/performance/scenarios/scenario1_baseline.js",
    "ramp_up": "tests/performance/scenarios/scenario2_ramp_up.js",
    "sustained": "tests/performance/scenarios/scenario3_sustained_load.js",
}


def find_k6_binary(custom_path: str | None = None) -> str:
    """Locate k6 executable on system PATH or default Windows installation directories."""
    if custom_path and Path(custom_path).is_file():
        return custom_path

    # Check system PATH
    found = shutil.which("k6")
    if found:
        return found

    # Check common Windows locations
    windows_paths: list[Path] = [
        Path(r"C:\Program Files\k6\k6.exe"),
        Path(r"C:\Program Files (x86)\k6\k6.exe"),
        Path.home() / "AppData" / "Local" / "Programs" / "k6" / "k6.exe",
    ]
    for p in windows_paths:
        if p.is_file():
            return str(p)

    raise FileNotFoundError(
        "k6 binary not found. Please install k6 (e.g. 'winget install GrafanaLabs.k6' or from https://k6.io)."
    )


def get_git_commit_hash() -> str:
    """Retrieve current Git HEAD commit hash for reproducible run recording."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown_commit"


def check_gateway_health(base_url: str) -> dict[str, Any] | None:
    """Probe /v1/health endpoint on target gateway to record pre-test system status."""
    try:
        with httpx.Client(base_url=base_url, timeout=5.0) as client:
            resp = client.get("/v1/health")
            if resp.status_code == 200:
                data: dict[str, Any] = resp.json()
                return data
            logger.warning("Gateway health check returned non-200", status=resp.status_code)
            return None
    except Exception as exc:
        logger.warning("Gateway health check failed or gateway not running", error=str(exc))
        return None


def run_scenario(
    k6_bin: str,
    scenario_key: str,
    base_url: str,
    output_dir: Path,
    smoke: bool = False,
    extra_env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Execute a specific k6 performance scenario and return structured metrics."""
    script_rel_path = SCENARIOS.get(scenario_key)
    if not script_rel_path:
        raise ValueError(f"Unknown scenario '{scenario_key}'. Choose from: {list(SCENARIOS.keys())}")

    script_path = PROJECT_ROOT / script_rel_path
    if not script_path.is_file():
        raise FileNotFoundError(f"Scenario script not found: {script_path}")

    report_json_path = output_dir / f"{scenario_key}_summary.json"
    output_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["MIRAGE_BASE_URL"] = base_url
    env["MIRAGE_REPORT_FILE"] = str(report_json_path)

    # Securely supply JWT signing secret from environment or shared app settings; never logged or printed
    if "MIRAGE_JWT_SECRET" not in env:
        env["MIRAGE_JWT_SECRET"] = get_settings().secret_key

    if smoke:
        # Fast smoke validation settings
        env["MIRAGE_ITERATIONS"] = "5"
        env["RAMP_DURATION"] = "5s"
        env["PLATEAU_DURATION"] = "5s"
        env["TARGET_VUS"] = "3"
        env["SUSTAINED_DURATION"] = "10s"
        env["SUSTAINED_VUS"] = "3"
        env["MIRAGE_PACING"] = "0.5"

    if extra_env:
        env.update(extra_env)

    cmd = [
        k6_bin,
        "run",
        str(script_path),
    ]

    logger.info("Starting k6 scenario execution", scenario=scenario_key, smoke=smoke)
    start_time = datetime.now(UTC)

    process = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    end_time = datetime.now(UTC)
    stdout = process.stdout
    stderr = process.stderr

    # Print live console output
    print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)

    result_data: dict[str, Any] = {
        "scenario": scenario_key,
        "exit_code": process.returncode,
        "started_at": start_time.isoformat(),
        "completed_at": end_time.isoformat(),
        "smoke_mode": smoke,
    }

    if report_json_path.is_file():
        try:
            with open(report_json_path, encoding="utf-8") as f:
                loaded: dict[str, Any] = json.load(f)
                result_data["metrics"] = loaded
        except Exception as exc:
            result_data["metrics_read_error"] = str(exc)

    return result_data


def generate_consolidated_report(
    results: list[dict[str, Any]],
    output_dir: Path,
    base_url: str,
    health: dict[str, Any] | None,
) -> Path:
    """Generate consolidated markdown summary report across all executed scenarios."""
    commit_hash = get_git_commit_hash()
    report_path = output_dir / "p3_1_performance_report.md"

    # Merge existing scenario summaries from output_dir if not present in current results
    seen_scenarios = {r.get("scenario") for r in results}
    all_results = list(results)
    for sc_key in ["baseline", "ramp_up", "sustained"]:
        if sc_key not in seen_scenarios:
            sum_path = output_dir / f"{sc_key}_summary.json"
            if sum_path.is_file():
                try:
                    with open(sum_path, encoding="utf-8") as f:
                        loaded: dict[str, Any] = json.load(f)
                        all_results.append(
                            {
                                "scenario": sc_key,
                                "metrics": loaded,
                                "exit_code": (
                                    0
                                    if loaded.get("reliability", {}).get("verification_success_rate", 0) >= 95
                                    else 1
                                ),
                            }
                        )
                except Exception:
                    pass

    order: dict[str, int] = {"baseline": 0, "ramp_up": 1, "sustained": 2}
    all_results.sort(key=lambda r: order.get(r.get("scenario", ""), 99))

    md_lines: list[str] = [
        "# MIRAGE Phase 3.1 Performance Benchmark Report",
        "",
        f"- **Execution Timestamp:** `{datetime.now(UTC).isoformat()}`",
        f"- **Git Commit:** `{commit_hash}`",
        f"- **Target URL:** `{base_url}`",
        f"- **Gateway Health Status:** `{health.get('status', 'unknown') if health else 'unreachable'}`",
        "",
        "## 1. Scenario Results Summary",
        "",
        "| Scenario | Target / Concurrency | Total Requests | Throughput (req/s) | "
        "P50 (ms) | P95 (ms) | P99 (ms) | Success Rate | Status |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in all_results:
        sc_name = r.get("scenario", "unknown")
        metrics = r.get("metrics", {})
        meta = metrics.get("metadata", {})
        latency = metrics.get("latency_ms", {})
        reliability = metrics.get("reliability", {})
        exit_code = r.get("exit_code", 1)

        status_badge = "PASSED" if exit_code == 0 else f"FAILED (exit {exit_code})"
        vus = meta.get("vus_max", "N/A")
        total_reqs = meta.get("total_requests", "N/A")
        rps = meta.get("throughput_rps", "N/A")
        p50 = latency.get("med_p50", "N/A")
        p95 = latency.get("p95", "N/A")
        p99 = latency.get("p99", "N/A")
        succ_rate = f"{reliability.get('verification_success_rate', 'N/A')}%"

        row = (
            f"| `{sc_name}` | {vus} VUs | {total_reqs} | {rps} | {p50} | {p95} | {p99} | "
            f"{succ_rate} | **{status_badge}** |"
        )
        md_lines.append(row)

    md_lines.extend(
        [
            "",
            "## 2. Governed Architecture Reconciliations",
            "",
            "1. **Scenario 7 Definition (`Testing_Strategy.md §8`):**",
            "   - Authoritative Scenario 7 is strictly **Model Cold Start** "
            "(hard restart of model serving / weight initialization).",
            "   - All 10 performance scenarios from Testing Strategy §8 are preserved in their authoritative ordering.",
            "",
            "2. **PostgreSQL Outage & Ambiguity Handling (`Testing_Strategy.md §9` vs P0.2 Architecture):**",
            "   - `Testing_Strategy.md §9` colloquially suggested buffering PostgreSQL writes during outages.",
            "   - **Approved P0.2 Architectural Contract:** PostgreSQL is the single authoritative source of truth "
            "for verification records and audit chaining.",
            "   - Verification transactions cannot commit without PostgreSQL. Dual-write failure triggers "
            "compensating cleanup and returns `503 SERVICE_DEGRADED`.",
            "   - No in-memory buffering is permitted in production verification paths.",
            "",
            "## 3. SLA Evaluation Target Reference",
            "",
            "- **P95 Latency:** `< 3000 ms` at 100 concurrent sessions",
            "- **Throughput:** `> 33 req/s` sustained",
            "- **Reliability:** `0%` unhandled 5xx errors; `< 1%` failure rate under standard conditions",
            "",
        ]
    )

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    return report_path


def main() -> None:
    """Parse CLI arguments and execute the requested load scenarios."""
    parser = argparse.ArgumentParser(description="MIRAGE Performance Test Runner (P3.1)")
    parser.add_argument(
        "--scenario",
        choices=["baseline", "ramp_up", "sustained"],
        help="Specific scenario to execute",
    )
    parser.add_argument("--all", action="store_true", help="Execute all P3.1 scenarios in sequence")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MIRAGE_BASE_URL", "http://localhost:8000"),
        help="Target base URL of MIRAGE gateway (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "results" / "performance"),
        help="Directory to store JSON and Markdown results",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run fast smoke validation (reduced VUs and durations) to verify harness integrity",
    )
    parser.add_argument("--k6-bin", default=None, help="Custom path to k6 binary")

    args = parser.parse_args()

    if not args.scenario and not args.all:
        parser.print_help()
        sys.exit(1)

    k6_bin = find_k6_binary(args.k6_bin)
    output_dir = Path(args.output_dir)

    print(f"MIRAGE Performance Harness initialized using k6 at: {k6_bin}")
    print(f"Target Gateway Base URL: {args.base_url}")

    health = check_gateway_health(args.base_url)
    if health:
        print(f"Gateway Health: OK (Status: {health.get('status', 'healthy')})")
    else:
        print("Note: Gateway not reachable or returned non-200. Ensure gateway is running if executing live load.")

    scenarios_to_run = list(SCENARIOS.keys()) if args.all else [args.scenario]
    results: list[dict[str, Any]] = []

    for sc in scenarios_to_run:
        res = run_scenario(
            k6_bin=k6_bin,
            scenario_key=sc,
            base_url=args.base_url,
            output_dir=output_dir,
            smoke=args.smoke,
        )
        results.append(res)

    report_file = generate_consolidated_report(results, output_dir, args.base_url, health)
    print(f"\nConsolidated Performance Report generated at: {report_file}")


if __name__ == "__main__":
    main()
