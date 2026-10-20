"""MIRAGE 3.0 Local Staging Bounded Performance Baseline.

Executes a controlled, repeatable performance benchmark against the live
MIRAGE 3.0 gateway running in Docker Desktop on Windows 11.

Parameters:
- Workload: 8 concurrent async worker tasks
- Total Requests per Endpoint:
  - GET  /v1/health (Liveness Probe): 100 requests
  - GET  /v1/ready (Full Readiness Probe: Postgres, Redis, Mongo, Rabbit, Qdrant): 50 requests
  - POST /v1/input-assurance (Gate 1 Assurance & Policy Evaluation): 50 requests
- Captured Metrics:
  - Throughput (req/sec)
  - Latency distributions (Min, p50, p95, p99, Max, Mean)
  - Error rate (%)
  - Host & Container resource consumption via docker stats
"""

from __future__ import annotations

import asyncio
import json
import statistics
import subprocess
import time
import uuid
from typing import Any

import httpx

from gateway.middleware.auth import create_access_token
from shared.schemas.auth import Role

GATEWAY_URL = "http://localhost:8000"


def get_docker_stats() -> dict[str, dict[str, str]]:
    """Capture snapshot of container CPU and Memory utilization."""
    cmd = [
        "docker", "stats", "--no-stream",
        "--format", "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    stats: dict[str, dict[str, str]] = {}
    for line in proc.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            stats[parts[0]] = {
                "cpu": parts[1],
                "mem_usage": parts[2],
                "mem_perc": parts[3],
            }
    return stats


async def benchmark_endpoint(
    name: str,
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: dict[str, Any] | None,
    total_requests: int,
    concurrency: int,
) -> dict[str, Any]:
    print(f"\n[BENCHMARK] Running '{name}': {total_requests} requests (concurrency={concurrency})...")
    latencies: list[float] = []
    status_codes: list[int] = []
    errors: list[str] = []

    sem = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_keepalive_connections=concurrency * 2, max_connections=concurrency * 2)

    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=15.0, limits=limits) as client:
        async def _single_request() -> None:
            async with sem:
                t0 = time.perf_counter()
                try:
                    if method == "GET":
                        r = await client.get(url, headers=headers)
                    else:
                        r = await client.post(url, headers=headers, json=json_body)
                    dur_ms = (time.perf_counter() - t0) * 1000
                    latencies.append(dur_ms)
                    status_codes.append(r.status_code)
                    if r.status_code >= 400:
                        errors.append(f"HTTP {r.status_code}: {r.text[:100]}")
                except Exception as exc:
                    dur_ms = (time.perf_counter() - t0) * 1000
                    latencies.append(dur_ms)
                    errors.append(str(exc))

        t_start = time.perf_counter()
        tasks = [asyncio.create_task(_single_request()) for _ in range(total_requests)]
        await asyncio.gather(*tasks)
        total_time_sec = time.perf_counter() - t_start

    sorted_lats = sorted(latencies)
    n = len(sorted_lats)
    p50 = statistics.median(sorted_lats) if n else 0.0
    p95 = sorted_lats[int(n * 0.95)] if n else 0.0
    p99 = sorted_lats[int(n * 0.99)] if n else 0.0
    min_lat = sorted_lats[0] if n else 0.0
    max_lat = sorted_lats[-1] if n else 0.0
    mean_lat = statistics.mean(sorted_lats) if n else 0.0
    rps = n / total_time_sec if total_time_sec > 0 else 0.0
    err_rate = (len(errors) / n * 100.0) if n else 0.0

    result = {
        "endpoint": name,
        "method": method,
        "url": url,
        "concurrency": concurrency,
        "total_requests": n,
        "duration_sec": round(total_time_sec, 2),
        "rps": round(rps, 1),
        "error_count": len(errors),
        "error_rate_pct": round(err_rate, 2),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "min_ms": round(min_lat, 2),
        "max_ms": round(max_lat, 2),
        "mean_ms": round(mean_lat, 2),
    }

    print(f"  Throughput : {result['rps']} req/sec ({result['duration_sec']}s total)")
    print(f"  Latency p50: {result['p50_ms']} ms | p95: {result['p95_ms']} ms | p99: {result['p99_ms']} ms")
    print(f"  Error Rate : {result['error_rate_pct']}% ({result['error_count']} errors)")
    return result


async def run_baseline() -> dict[str, Any]:
    print("=" * 70)
    print("  MIRAGE 3.0 Local Staging Bounded Performance Baseline")
    print("=" * 70)

    # 1. Capture initial resource stats
    stats_before = get_docker_stats()

    # 2. Setup synthetic tenant and credentials for Gate 1 testing
    sys_token = create_access_token(
        tenant_id="system",
        role=Role.SUPER_ADMIN,
        user_id="staging_super_admin",
    )
    async with httpx.AsyncClient(base_url=GATEWAY_URL, timeout=10.0) as client:
        r = await client.post(
            "/v1/admin/tenants",
            headers={"Authorization": f"Bearer {sys_token}"},
            json={"name": f"Perf Tenant {uuid.uuid4().hex[:6]}", "admin_user_id": "perf_admin"},
        )
        assert r.status_code == 201, f"Failed to provision perf tenant: {r.text}"
        tenant_id = r.json()["id"]

    tenant_jwt = create_access_token(
        tenant_id=tenant_id,
        role=Role.TENANT_ADMIN,
        user_id="perf_admin",
    )
    tenant_headers = {"Authorization": f"Bearer {tenant_jwt}"}

    results: list[dict[str, Any]] = []

    # Benchmark 1: Liveness Probe (/v1/health) - 100 requests, 8 concurrency
    res_health = await benchmark_endpoint(
        name="Liveness Probe (/v1/health)",
        method="GET",
        url="/v1/health",
        headers={},
        json_body=None,
        total_requests=100,
        concurrency=8,
    )
    results.append(res_health)

    # Benchmark 2: Full Readiness Probe (/v1/ready) - 50 requests, 8 concurrency
    res_ready = await benchmark_endpoint(
        name="Full Readiness Probe (/v1/ready)",
        method="GET",
        url="/v1/ready",
        headers={},
        json_body=None,
        total_requests=50,
        concurrency=8,
    )
    results.append(res_ready)

    # Benchmark 3: Gate 1 Input Assurance & Policy Evaluation - 50 requests, 8 concurrency
    res_gate1 = await benchmark_endpoint(
        name="Gate 1 Input Assurance (/v1/input-assurance)",
        method="POST",
        url="/v1/input-assurance",
        headers=tenant_headers,
        json_body={
            "content": "Verify customer account balance and eligibility for upgrade.",
            "initial_risk": 15,
        },
        total_requests=50,
        concurrency=8,
    )
    results.append(res_gate1)

    # 3. Capture post-run resource stats
    stats_after = get_docker_stats()

    summary = {
        "benchmarks": results,
        "resource_snapshots": {
            "before": stats_before,
            "after": stats_after,
        },
    }

    print("\n" + "=" * 70)
    print("  PERFORMANCE BASELINE SUMMARY")
    print("=" * 70)
    for r in results:
        ep = r['endpoint']
        print(
            f"{ep:<45} | RPS: {r['rps']:>5.1f} | p50: {r['p50_ms']:>6.1f}ms | "
            f"p95: {r['p95_ms']:>6.1f}ms | Err: {r['error_rate_pct']}%"
        )

    with open("data/perf_baseline_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


if __name__ == "__main__":
    asyncio.run(run_baseline())
