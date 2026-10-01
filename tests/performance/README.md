# MIRAGE Performance & Distributed Load Testing Harness (Phase P3.1)

This directory contains the authoritative performance, latency, and load-testing test harness for the **MIRAGE Autonomous Multimodal Hallucination Detection & Verification System**, implementing **Phase P3.1** per [`Testing_Strategy.md §8`](../../Testing_Strategy.md#8-performance-testing).

---

## 1. Authoritative Scenario Catalog & Reconciliations

Per `Testing_Strategy.md §8`, MIRAGE performance validation is structured across **10 canonical scenarios**:

| Scenario # | Canonical Scenario Name | Target Execution & Methodology | P3 Phase Scope |
| :--- | :--- | :--- | :--- |
| **Scenario 1** | **Baseline Latency Profile** | 1 concurrent user, 100 requests. Captures stable P50/P95/P99 latency without contention. | **P3.1 (Current)** |
| **Scenario 2** | **Concurrency Ramp-Up** | 1 → 100 concurrent users over 5 minutes. Identifies throughput and latency inflection points. | **P3.1 (Current)** |
| **Scenario 3** | **Sustained Load** | 100 concurrent users held for 10 minutes. Validates stability, memory leak freedom, and persistence consistency. | **P3.1 (Current)** |
| **Scenario 4** | **Spike / Burst** | 10 → 200 → 10 concurrent users. Validates rapid connection pool surge recovery. | P3.2 |
| **Scenario 5** | **Noisy Neighbor** | Single-tenant 10x volume burst. Verifies tenant token-bucket isolation without degrading neighboring tenants. | P3.2 |
| **Scenario 6** | **SCS Cache Warm Load** | Repeated prompt patterns. Measures latency reduction and cache hit rate (> 90%). | P3.2 |
| **Scenario 7** | **Model Cold Start** | Hard restart of model serving / weight initialization. Measures cold-start weights loading times. | P3.2 |
| **Scenario 8** | **DB Pool Exhaustion** | 200 concurrent write operations. Verifies graceful queueing without data loss. | P3.2 |
| **Scenario 9** | **RabbitMQ Backpressure** | Async logging and task queue flooding. Verifies queue depth limits and rejection without OOM. | P3.2 |
| **Scenario 10** | **Correction Loop Latency** | High-HRS verification triggering autonomous rewrite. Verifies correction turnaround < 2.0s. | P3.2 |

### Governed Architectural Reconciliations

1. **Scenario 7 Definition (`Testing_Strategy.md §8`):**
   - The authoritative Scenario 7 is strictly **Model Cold Start** (hard restart of model serving / weight initialization). All 10 scenarios and their numbering are preserved exactly as defined in `Testing_Strategy.md §8`.
2. **PostgreSQL Outage & Ambiguity Handling (`Testing_Strategy.md §9` vs P0.2 Architecture):**
   - `Testing_Strategy.md §9` colloquially suggested buffering PostgreSQL writes during outages.
   - **Authoritative Approved Contract (P0.2 & ADR 0001):** PostgreSQL is the single authoritative source of truth for verification persistence and audit hash chaining. Verification transactions *cannot* commit without PostgreSQL. Dual-write failure triggers compensating cleanup and returns `503 SERVICE_DEGRADED`. No in-memory buffering is permitted in production verification paths.

---

## 2. Test Harness Architecture & Modular Design

The P3.1 harness is written for **Grafana k6** and organized modularly:

```
tests/performance/
├── README.md                      # Comprehensive execution and metrics guide
├── config.js                      # Centralized configuration, thresholds, URLs, and validation logic
├── auth.js                        # Multi-tenant JWT generation (k6 native crypto HMAC-SHA256) & API keys
├── payloads.js                    # Deterministic, realistic verification payloads across multiple domains
├── metrics.js                     # Custom k6 Trends, Rates, Counters, and handleSummary JSON/ASCII exporter
├── baseline.js                    # Scenario 1 entrypoint (k6 run tests/performance/baseline.js)
├── ramp_up.js                     # Scenario 2 entrypoint (k6 run tests/performance/ramp_up.js)
├── sustained_load.js              # Scenario 3 entrypoint (k6 run tests/performance/sustained_load.js)
├── scenarios/
│   ├── scenario1_baseline.js      # Explicit modular implementation for Scenario 1
│   ├── scenario2_ramp_up.js       # Explicit modular implementation for Scenario 2
│   └── scenario3_sustained_load.js# Explicit modular implementation for Scenario 3
└── run_load_tests.py              # Automated Python CLI orchestrator with health checks & reporting
```

### Security & Multi-Tenancy Invariants Enforced
- **Zero Client Header Tampering:** The harness never injects spoofed client headers (`X-Role`, `X-Tenant-ID`), which are stripped at the ASGI boundary by `HeaderSanitizationMiddleware`.
- **Cryptographic JWT Minting:** Authentic HMAC-SHA256 JWT tokens are generated on-the-fly via k6's native `k6/crypto` and `k6/encoding` using the configured secret key.
- **Tenant Isolation:** When `MIRAGE_MULTI_TENANT=true`, virtual users are mapped to discrete tenants (`perf_tenant_${__VU}`), exercising true isolated token buckets and database row partitions.

---

## 3. Execution Instructions

### Option A: Using the Automated Python Runner (Recommended)

The Python runner auto-detects `k6`, checks gateway health, runs scenarios, records Git commit metadata, and writes JSON + Markdown reports:

```bash
# 1. Run quick smoke validation across all 3 scenarios (5 iterations, short durations)
python tests/performance/run_load_tests.py --all --smoke

# 2. Run Scenario 1 (Baseline: 1 VU, 100 requests)
python tests/performance/run_load_tests.py --scenario baseline

# 3. Run Scenario 2 (Ramp-Up: 1 -> 100 VUs over 5 minutes)
python tests/performance/run_load_tests.py --scenario ramp_up

# 4. Run Scenario 3 (Sustained Load: 100 VUs for 10 minutes)
python tests/performance/run_load_tests.py --scenario sustained

# 5. Run against custom gateway URL
python tests/performance/run_load_tests.py --all --base-url http://127.0.0.1:8000
```

### Option B: Running k6 Directly

```bash
# Scenario 1 — Baseline
k6 run tests/performance/baseline.js

# Scenario 2 — Ramp-Up
k6 run tests/performance/ramp_up.js

# Scenario 3 — Sustained Load
k6 run tests/performance/sustained_load.js
```

### Environment Variable Overrides

| Environment Variable | Default Value | Description |
| :--- | :--- | :--- |
| `MIRAGE_BASE_URL` | `http://localhost:8000` | Target MIRAGE Gateway base URL |
| `MIRAGE_JWT_SECRET` | *(from settings)* | Secret key for signing test JWT tokens |
| `MIRAGE_TENANT_ID` | `perf_tenant_default` | Default tenant ID for single-tenant tests |
| `MIRAGE_MULTI_TENANT`| `true` | Enabled by default; assigns each VU an isolated tenant (`perf_tenant_${__VU}`) |
| `MIRAGE_AUTH_TOKEN` | `""` | Static Bearer token override |
| `MIRAGE_API_KEY` | `""` | Static API Key override (`X-API-Key`) |
| `RAMP_DURATION` | `5m` | Duration for Scenario 2 concurrency ramp |
| `SUSTAINED_DURATION`| `10m` | Duration for Scenario 3 sustained plateau |
| `MIRAGE_REPORT_FILE`| `results/<scenario>_summary.json` | Path to output JSON summary |

---

## 4. Interpreting Results & Target SLA Metrics

The harness collects and reports:

1. **Latency Profile (`http_req_duration` & `mirage_verification_duration`):**
   - **P50 (Median):** Typical verification latency under target load.
   - **P95:** 95th percentile latency. Target SLA: `< 3000 ms` at 100 concurrent sessions (per `Testing_Strategy.md §8`).
   - **P99:** Extreme tail latency (informational metric recorded for telemetry).
2. **System Throughput (`http_reqs` rate):**
   - Measured requests per second. Target SLA: `> 33 req/s` sustained under 100 VUs.
3. **Reliability & Degradation Breakdown:**
   - **Verification Success Rate (`mirage_verification_success`):** Percentage of 200 OK responses with complete `hrs_result` and extracted propositions.
   - **Rate Limited (`mirage_http_429_rate`):** Measures token bucket exhaustion.
   - **Service Degraded (`mirage_service_degraded_rate`):** Measures 503 responses when underlying persistence (PostgreSQL/Redis) is unavailable or circuit is open.
   - **Unhandled Errors (`mirage_http_5xx_rate`):** Target: `0.0%` under normal operating conditions.
4. **Application Telemetry:**
   - **Mean Calibrated HRS (`mirage_hrs_score`):** Average calibrated risk score computed by the pipeline.
   - **Claims Evaluated (`mirage_claims_extracted`):** Total propositions decomposed and checked against knowledge bases.

> [!NOTE]
> Phase P3.1 establishes the measurement capability and executes initial verification. Full end-to-end SLA signoff across all 10 scenarios is completed in **Phase P3.6**.
