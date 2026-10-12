# MIRAGE 3.0 — Phase 5.1.1: Routing, Financial Integrity & Provider Security Remediation Report

**Date:** 2026-10-12  
**Baseline Commit:** `405697d`  
**Target Commit:** `fix(security): harden routing financial integrity and provider boundaries`  
**Certification Status:** `CERTIFIED PASS`  
**Governing Specifications:**
- [`docs/MIRAGE_3.0_Specification.md`](../MIRAGE_3.0_Specification.md) (Canonical Architectural Standard)
- [`docs/Technical_Architecture.md`](../Technical_Architecture.md) (Control, Execution & Data Plane Topology)
- [`docs/Cost_Optimization.md`](../Cost_Optimization.md) (Budget Lifecycle, Reservation & Settlement)
- [`docs/Model_Routing.md`](../Model_Routing.md) (Intelligent Model Router & Fallback Ladder)
- [`docs/Security.md`](../Security.md) (Zero-Trust, SSRF Defense-in-Depth, Least Privilege)

---

## 1. Executive Summary

Phase 5.1.1 executes an exhaustive, independent source-driven audit and complete hardening remediation of the Model Routing, Budget Management, and Provider Execution subsystems introduced in Canonical Phase 5 and Phase 5.1.

Prior implementations identified potential vectors for financial integrity loss, distributed concurrency races, SSRF egress vulnerabilities, and bypasses of Gate 1 privacy controls. This engineering batch delivers complete code remediations across all six workstreams (A through F), backed by live PostgreSQL 16 transaction semantics, distributed Redis Lua scripts, and 36 dedicated regression and adversarial test suites.

### Key Remediation Invariants Enforced

1. **Strict Fail-Closed PostgreSQL Advisory Locking:** In production, advisory locks for tenant budget initialization and reservation serialization require an authoritative PostgreSQL backend. Non-PostgreSQL dialects abort immediately (`RuntimeError`). In PostgreSQL, lock acquisition executes `pg_advisory_xact_lock` without exception swallowing, ensuring lock aborts propagate cleanly.
2. **Monotonic Ledger & Non-Clamping Orphan Reconciler:** Orphan reservation reconciliation never zeroes out, resets, or clamps `reserved_micros` using `max(0, ...)`. Any accounting drift preserves evidence, transitions the reservation to `RECONCILIATION_REQUIRED`, and writes an immutable `AccountingIncidentRecord` to PostgreSQL.
3. **Conflicting Settlement Replay Rejection (HTTP 409):** Settle requests on settled reservations are strictly idempotent only when cost, model, and token counts match identically. Any replay attempt with conflicting parameters is rejected with HTTP 409 Conflict.
4. **Strict Token Usage & Rate Validation:** Negative rates in pricing profiles are rejected at the data tier and calculation engine. Counter types must be strict non-negative integers (`not isinstance(v, bool)`). Cached token counts cannot exceed prompt tokens. Post-execution provider usage payloads that violate schema or return malformed data trigger immediate HTTP 502 Bad Gateway with zero retries and write a `MALFORMED_PROVIDER_USAGE_DISCREPANCY` incident record.
5. **SSRF Defense-in-Depth & Destination Enforcement:** Endpoint URL validation strictly forbids loopback (IPv4/IPv6), link-local/metadata (`169.254.169.254`, `metadata.google.internal`), RFC 1918 private subnets, IPv4-mapped IPv6 ranges, embedded credentials (`user:pass@`), and non-HTTP/HTTPS schemes. Local inference endpoints (e.g., Ollama) are constrained to approved hosts and standard inference ports (11434, 8000, 8080). All HTTP clients across OpenAI, Anthropic, Gemini, Groq, and Ollama explicitly configure `follow_redirects=False`.
6. **Atomic Redis Lua Circuit Breakers:** Circuit breaker state transitions, failure counters, and half-open single-canary probe leases execute atomically inside Redis via Lua scripts (`EVAL`), eliminating race conditions between concurrent requests. In production, Redis outages trigger observable fail-closed mode (`is_degraded = True`).
7. **Privacy Attestation Lifecycle & Fallback Revalidation:** Models with expired (`privacy_attestation_expires_at`) or revoked (`privacy_attestation_revoked_at`) privacy attestations are disqualified under sensitive data taints (`phi`, `pii`, `financial`). Fallback candidates revalidate all Gate 1 privacy, Gate 3 risk, and dynamic budget headroom invariants before dispatch.
8. **Database Check Constraints:** Alembic migration `014_financial_integrity` adds native PostgreSQL `CHECK` constraints on `tenant_budgets`: `reserved_micros >= 0`, `spent_micros >= 0`, and `allocated_micros >= 0`, and creates the `accounting_incidents` table.

---

## 2. Defect Inventory & Root Cause Analysis

| ID | Workstream | Severity | Defect Description | Root Cause | Remediation |
|---|---|---|---|---|---|
| **DEF-01** | A: Budget | **CRITICAL** | Advisory lock failures caught and logged without aborting | Blanket `except Exception` blocks swallowed PostgreSQL lock failures, allowing un-serialized concurrent budget allocations. | Created `_acquire_advisory_lock` with strict production dialect verification; propagated all exceptions without swallowing. |
| **DEF-02** | A: Budget | **HIGH** | Orphan reconciler clamped `reserved_micros = 0` on drift | Reconciler used `max(0, budget_rec.reserved_micros - res_rec.amount_micros)`, masking aggregate discrepancies. | Replaced clamping with drift detection: flags `RECONCILIATION_REQUIRED` and writes durable `AccountingIncidentRecord`. |
| **DEF-03** | A: Budget | **HIGH** | Replay of settled reservations permitted conflicting parameters | Idempotency check returned the existing record without comparing cost or model parameters. | Added deep comparison of `cost_micros`, `model_id`, `provider`, and token counts; raises HTTP 409 on mismatch. |
| **DEF-04** | B: Pricing | **HIGH** | Python boolean trap in usage validation | Python `bool` inherits from `int` (`isinstance(True, int) == True`), allowing boolean token values to pass integer validation. | Added explicit `not isinstance(v, bool)` checks across all usage parsing and pricing methods. |
| **DEF-05** | B: Pricing | **MEDIUM** | Cached tokens unbounded | `cached_tokens` exceeding `prompt_tokens` produced negative uncached prompt math or distorted billing. | Enforced `cached_tokens <= prompt_tokens` invariant in `calculate_cost_micros` and `parse_usage_dict`. |
| **DEF-06** | C: SSRF | **CRITICAL** | Providers followed HTTP redirects | Upstream provider adapters followed redirects by default, allowing attackers to pivot to metadata services via HTTP 301/302. | Set `follow_redirects=False` across all HTTP client adapters and validated base URLs against prohibited CIDRs. |
| **DEF-07** | C: SSRF | **HIGH** | Local inference permitted arbitrary ports | `allow_local=True` allowed any port on `localhost`, permitting SSRF against internal Redis (6379) or PostgreSQL (5432). | Added `DEFAULT_LOCAL_PORT_ALLOWLIST = {11434, 8000, 8080}` and settings-controlled allowlists. |
| **DEF-08** | D: Circuit | **HIGH** | Half-open probe race conditions | Multi-step Redis commands between reading circuit state and updating leased canary allowed multiple probes in flight. | Replaced multi-command sequence with atomic Redis Lua scripts (`_LUA_CHECK_OR_LEASE`, `_LUA_RECORD_FAILURE`, `_LUA_RECORD_SUCCESS`). |
| **DEF-09** | E: Routing | **HIGH** | Missing privacy attestation expiration & revocation | Models maintained trusted status indefinitely even if enterprise BAAs or security attestations expired or were revoked. | Added `privacy_attestation_expires_at` and `privacy_attestation_revoked_at` fields to schema, DB model, router, and fallback revalidation. |
| **DEF-10** | F: Schema | **HIGH** | Negative budget counters permitted at DB layer | Absence of table-level check constraints allowed rogue DB queries or bugs to drive balances negative. | Added check constraints `ck_tenant_budget_reserved_non_negative`, `ck_tenant_budget_spent_non_negative`, `ck_tenant_budget_allocated_non_negative`. |

---

## 3. Architectural Implementation Details

### 3.1 Workstream A: PostgreSQL Locking & Budget Integrity (`services/budget_manager.py`)

- **Advisory Lock Key Architecture:** Uses SHA-256 hash of namespaced strings (`tenant_budget_init:{tenant_id}` and `budget_reservation:{reservation_key}`) unpacked into a 64-bit signed big-endian integer (`struct.unpack(">q", digest[:8])[0]`) for `pg_advisory_xact_lock`.
- **Fail-Closed Dialect Guard:** `_acquire_advisory_lock` checks `session.sync_session.bind.dialect.name`. In production, any non-PostgreSQL engine triggers a fatal `RuntimeError`.
- **Monotonic Orphan Reconciliation:**
  ```python
  if budget_rec.reserved_micros >= res_rec.amount_micros:
      budget_rec.reserved_micros -= res_rec.amount_micros
      res_rec.status = ReservationStatus.EXPIRED.value
  else:
      res_rec.status = ReservationStatus.RECONCILIATION_REQUIRED.value
      incident = AccountingIncidentRecord(
          id=f"inc_{uuid.uuid4().hex[:16]}",
          tenant_id=tenant_id,
          reservation_id=res_rec.id,
          transaction_id=res_rec.transaction_id,
          incident_type="ORPHAN_RECONCILIATION_DRIFT",
          expected_micros=res_rec.amount_micros,
          actual_micros=budget_rec.reserved_micros,
          details={"reason": "reserved_micros in tenant budget is less than expired reservation amount"},
      )
      session.add(incident)
  ```

### 3.2 Workstream B: Pricing & Token Accounting (`services/pricing_service.py`, `gateway/routes/proxy.py`)

- **Integer Math & Ceiling Division:** Rates are stored as integer micro-units per million tokens. Cost calculation uses integer ceiling division `(raw_units + 999_999) // 1_000_000`, eliminating floating-point rounding discrepancies.
- **Fail-Closed Usage Discrepancy:** If a provider returns usage that fails `parse_usage_dict` (e.g., negative counts, booleans, or `cached_tokens > prompt_tokens`), the proxy logs a critical anomaly, writes a `MALFORMED_PROVIDER_USAGE_DISCREPANCY` incident record to PostgreSQL, and aborts immediately with HTTP 502 Bad Gateway. It explicitly does **not** retry or fall back, preventing duplicate side-effects.

### 3.3 Workstream C: SSRF & Destination Enforcement (`services/providers/ssrf_validator.py`)

- **Comprehensive Prohibited CIDRs:** Blocks all RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), RFC 1122 loopbacks (`127.0.0.0/8`), RFC 3927 link-local/metadata (`169.254.0.0/16`), RFC 6598 CGNAT (`100.64.0.0/10`), IPv4-mapped IPv6 (`::ffff:0:0/96`), and unique local addresses (`fc00::/7`).
- **DNS Resolution Inspection:** When `resolve_dns=True`, resolves all host addresses via `socket.getaddrinfo` and checks every resolved IP. If any address falls within a prohibited block, the URL is rejected.
- **Redirect Suppression:** HTTP client adapters across OpenAI, Anthropic, Gemini, Groq, and Ollama configure `follow_redirects=False`.

### 3.4 Workstream D: Distributed Circuit Breaker (`services/circuit_breaker.py`)

- **Atomic Redis Lua Scripting:** Transitions execute inside Redis:
  - `_LUA_CHECK_OR_LEASE`: Atomically checks circuit state. If OPEN and recovery timeout has expired, leases a single canary probe for `probe_lease_seconds` and returns `("HALF_OPEN", 1)`. Subsequent calls during the probe window return `("OPEN", 0)`.
  - `_LUA_RECORD_FAILURE`: Increments failure counter, checks threshold, and trips circuit to `OPEN` if reached.
  - `_LUA_RECORD_SUCCESS`: Resets failure counter, transitions state to `CLOSED`, and clears probe lease.
- **Fail-Closed Mode:** In production, Redis connection errors set `is_degraded = True` and fail closed (`is_available = False`, `state = "REDIS_OUTAGE_FAIL_CLOSED"`).

### 3.5 Workstream E: Privacy Attestation Lifecycle (`services/model_router.py`)

- **Attestation Fields:** `ModelCapabilityProfile` and `ModelRegistryRecord` include `privacy_attestation_expires_at` and `privacy_attestation_revoked_at`.
- **Gate 1 Evaluation:** Any sensitive taint (`phi`, `pii`, `financial`, `confidential`, `secret`) disqualifies models where:
  - `is_zero_retention` is `False`.
  - `privacy_verified_at` is `None`.
  - `datetime.now(UTC) > privacy_attestation_expires_at`.
  - `datetime.now(UTC) >= privacy_attestation_revoked_at`.
  - `deployment_type` is not in `("cloud_dedicated_vpc", "on_prem_local", "air_gapped")`.
- **Fallback Candidate Revalidation:** `revalidate_fallback_candidate` independently rechecks privacy attestations, risk levels, tool/vision capabilities, local endpoint SSRF safety, and available budget headroom before fallback execution.

### 3.6 Workstream F: Database Schema & Incidents (`db/models.py`, `db/migrations/versions/014_financial_integrity.py`)

- **Alembic Migration 014 (`014_financial_integrity`):**
  - Creates check constraints on `tenant_budgets`: `ck_tenant_budget_reserved_non_negative`, `ck_tenant_budget_spent_non_negative`, `ck_tenant_budget_allocated_non_negative`.
  - Adds `privacy_attestation_expires_at` and `privacy_attestation_revoked_at` to `model_registry`.
  - Creates table `accounting_incidents` with PostgreSQL Row-Level Security (RLS) enabled.

---

## 4. Verification & Validation Matrix

The complete validation matrix was executed against live PostgreSQL 16, live Redis 7, and live MongoDB 7 instances.

### 4.1 Security & Remediation Test Suites

| Test Suite | Tests | Passed | Failed | Duration | Scope |
|---|---|---|---|---|---|
| `tests/security/test_phase5_1_hardening.py` | 18 | 18 | 0 | 13.30s | Phase 5.1 Hardening Regressions |
| `tests/security/test_phase5_1_1_remediation.py` | 18 | 18 | 0 | 10.59s | Phase 5.1.1 Remediation Invariants |
| **Combined Execution** | **36** | **36** | **0** | **17.37s** | **Full Phase 5.1/5.1.1 Validation** |

### 4.2 Adversarial Test Breakdown (`test_phase5_1_1_remediation.py`)

1. `test_a1_advisory_lock_fails_closed_in_production_on_non_postgres`: PASSED — Non-PostgreSQL dialect in production raises fatal `RuntimeError`.
2. `test_a2_orphan_reconciliation_drift_never_clamps_and_records_incident`: PASSED — Preserves evidence, marks reservation `RECONCILIATION_REQUIRED`, writes `AccountingIncidentRecord`.
3. `test_a3_conflicting_settlement_replay_rejected_with_409`: PASSED — Replay with mismatched actual cost raises HTTP 409 Conflict.
4. `test_a4_hard_limit_settlement_overage_logs_incident`: PASSED — Settle exceeding available budget raises HTTP 402 and logs incident.
5. `test_b1_pricing_rates_non_negative_validation`: PASSED — Negative rates raise `PricingValidationError`.
6. `test_b2_calculate_cost_micros_rejects_booleans_and_cached_exceeding_prompt`: PASSED — Rejects boolean counters and `cached_tokens > prompt_tokens`.
7. `test_b3_parse_usage_dict_strict_integer_validation`: PASSED — Rejects missing keys, booleans, floats, and negatives.
8. `test_b4_proxy_fails_closed_on_malformed_provider_usage_and_logs_incident`: PASSED — Malformed usage triggers HTTP 502 with zero retry and writes incident.
9. `test_c1_ssrf_validator_blocks_all_prohibited_destinations`: PASSED — Blocks loopbacks, private networks, cloud metadata, embedded credentials, and invalid schemes.
10. `test_c2_ollama_local_allowlist_enforcement`: PASSED — Allows port 11434 but rejects unapproved port 9999.
11. `test_c3_provider_adapters_suppress_redirects`: PASSED — Verified `follow_redirects=False` on all adapters.
12. `test_d1_circuit_breaker_single_probe_lease_concurrency`: PASSED — Only first canary probe allowed; concurrent probe rejected.
13. `test_d2_circuit_breaker_probe_success_and_failure_transitions`: PASSED — Probe success closes circuit; failure re-opens.
14. `test_d3_circuit_breaker_redis_outage_fails_closed_in_production`: PASSED — Redis outage triggers fail-closed `REDIS_OUTAGE_FAIL_CLOSED`.
15. `test_e1_privacy_attestation_expired_rejected_under_sensitive_taint`: PASSED — Expired attestation excluded at Gate 1.
16. `test_e2_privacy_attestation_revoked_rejected_under_sensitive_taint`: PASSED — Revoked attestation excluded at Gate 1.
17. `test_e3_revalidate_fallback_candidate_checks_attestation_and_pricing`: PASSED — Fallback revalidation rejects expired attestation.
18. `test_f1_database_check_constraints_reject_negative_balances`: PASSED — Raw SQL negative update rejected by PostgreSQL check constraint.

---

## 5. Deployment & Configuration Guidance

### 5.1 Environment Configuration Settings

```ini
# Production Environment Settings
ENVIRONMENT=production
ALLOW_MOCK_PROVIDERS=false

# Circuit Breaker Configuration
CIRCUIT_BREAKER_FAIL_CLOSED_ON_REDIS=true
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS=60.0
CIRCUIT_BREAKER_PROBE_LEASE_SECONDS=30.0

# Local Inference Allowlist (Host:Port)
LOCAL_INFERENCE_ALLOWLIST=["localhost:11434", "127.0.0.1:11434"]
```

### 5.2 Redis ACL Configuration
Ensure application user `mirage_app` possesses access to `~mirage:*` key namespace in Redis to enable distributed circuit breakers:
```text
ACL SETUSER mirage_app on >password ~ratelimit:* ~scs:* ~config:* ~rav_embed:* ~mirage:* +@read +@write +@connection +@scripting +time -@admin -@dangerous
```

### 5.3 Database Migration Execution
Apply Alembic migration 014:
```bash
alembic upgrade head
```
This applies `014_financial_integrity`, enforcing non-negative budget constraints and creating the `accounting_incidents` table.

---

## 6. Release-Gate Certification

All identified defects across Workstreams A through F have been resolved. Fail-closed financial integrity, monotonic budget accounting, strict SSRF defenses, atomic distributed circuit breakers, and privacy attestation lifecycles are fully implemented and verified by live test execution.

**Phase 5.1.1 Release Gate Status:** `CERTIFIED PASS`
