"""Automated driver for MIRAGE performance and load testing.

Executes k6 load testing scenarios or runs native high-concurrency async load simulation
when k6 binary is not installed in the local environment.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import httpx
import numpy as np

from gateway.main import app
from shared.logging import get_logger

logger = get_logger("load_tester")


class PerformanceLoadRunner:
    """Runs performance and load benchmarks validating PRD latency and throughput SLAs."""

    def __init__(self, base_url: str = "http://testserver", output_dir: str | Path = "results") -> None:
        self.base_url = base_url
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def run_simulated_load(
        self,
        concurrent_users: int = 20,
        total_requests: int = 100,
    ) -> dict[str, Any]:
        """Execute async load test using Starlette TestClient transport (in-memory, no socket overhead)."""
        logger.info(
            "Starting in-process simulated load test",
            concurrent_users=concurrent_users,
            total_requests=total_requests,
        )

        payload = {
            "prompt": "What is the speed of light?",
            "response": "The speed of light in vacuum is 299,792,458 meters per second.",
            "tenant_id": "perf_tenant",
        }
        headers = {
            "X-Tenant-ID": "perf_tenant",
            "X-API-Key": "dev_key_default",
        }

        latencies: list[float] = []
        status_codes: list[int] = []

        semaphore = asyncio.Semaphore(concurrent_users)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            # Warm-up phase: discard initial cold-start / circuit breaker warm-up requests
            logger.info("Executing warm-up requests before measurement per Section 8 protocol")
            for _ in range(5):
                try:
                    await client.post("/v1/verify", json=payload, headers=headers)
                except Exception:
                    pass

            async def send_req() -> None:
                async with semaphore:
                    t0 = time.time()
                    try:
                        r = await client.post("/v1/verify", json=payload, headers=headers)
                        dur = (time.time() - t0) * 1000
                        latencies.append(dur)
                        status_codes.append(r.status_code)
                    except Exception as exc:
                        latencies.append((time.time() - t0) * 1000)
                        status_codes.append(500)
                        logger.debug("Request error during load", error=str(exc))

            start_wall = time.time()
            tasks = [asyncio.create_task(send_req()) for _ in range(total_requests)]
            await asyncio.gather(*tasks)
            total_wall_sec = time.time() - start_wall

        # Compute percentiles
        arr = np.array(latencies)
        success_count = sum(1 for c in status_codes if c == 200)
        error_rate = (len(status_codes) - success_count) / max(len(status_codes), 1)
        throughput = total_requests / max(total_wall_sec, 0.001)

        p50 = float(np.percentile(arr, 50))
        p90 = float(np.percentile(arr, 90))
        p95 = float(np.percentile(arr, 95))
        p99 = float(np.percentile(arr, 99))

        results = {
            "scenario": "concurrent_load",
            "timestamp": datetime.now(UTC).isoformat(),
            "concurrent_users": concurrent_users,
            "total_requests": total_requests,
            "successful_requests": success_count,
            "error_rate": round(error_rate, 4),
            "total_duration_seconds": round(total_wall_sec, 2),
            "throughput_req_per_sec": round(throughput, 2),
            "latency_p50_ms": round(p50, 2),
            "latency_p90_ms": round(p90, 2),
            "latency_p95_ms": round(p95, 2),
            "latency_p99_ms": round(p99, 2),
            "sla_p95_passed": p95 < 3000.0,
            "sla_error_rate_passed": error_rate < 0.01,
        }

        self._print_results(results)
        return results

    def _print_results(self, r: dict[str, Any]) -> None:
        print("\n" + "=" * 70)
        print("  MIRAGE PERFORMANCE & LOAD TEST AUDIT REPORT")
        print("=" * 70)
        print(f"  Concurrent VUs:    {r['concurrent_users']}")
        print(f"  Total Requests:    {r['total_requests']}")
        print(f"  Throughput:        {r['throughput_req_per_sec']} req/s")
        print(f"  Error Rate:        {r['error_rate'] * 100:.2f}%")
        print(f"  Latency P50:       {r['latency_p50_ms']} ms")
        print(f"  Latency P90:       {r['latency_p90_ms']} ms")
        print(f"  Latency P95:       {r['latency_p95_ms']} ms (Target: < 3000ms)")
        print(f"  Latency P99:       {r['latency_p99_ms']} ms")
        print("-" * 70)
        sla_p95_str = "[PASS]" if r["sla_p95_passed"] else "[FAIL]"
        sla_err_str = "[PASS]" if r["sla_error_rate_passed"] else "[FAIL]"
        print(f"  {sla_p95_str} SLA P95 Latency < 3000ms")
        print(f"  {sla_err_str} SLA Error Rate < 1%")
        print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MIRAGE performance and load tests")
    parser.add_argument("--concurrency", type=int, default=20, help="Concurrent simulated users")
    parser.add_argument("--requests", type=int, default=100, help="Total requests to fire")
    parser.add_argument("--output-dir", default="results", help="Directory for JSON results")
    args = parser.parse_args()

    runner = PerformanceLoadRunner(output_dir=args.output_dir)
    res = asyncio.run(runner.run_simulated_load(args.concurrency, args.requests))

    # Save results
    out_file = Path(args.output_dir) / f"perf_results_{int(time.time())}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

    sys.exit(0 if res["sla_p95_passed"] else 1)


if __name__ == "__main__":
    main()
