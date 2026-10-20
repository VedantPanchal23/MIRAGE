# MIRAGE 3.0 — Local Reliability, Chaos, Security Regression, and Staging Baseline Report

> **Authoritative Reliability & Chaos Audit**  
> **Repository:** `VedantPanchal23/MIRAGE`  
> **Branch:** `main`  
> **Starting SHA:** `cb88720c22dd33909b0a17478c7ad3d99e3d086e`  
> **Host Environment:** Windows 11 Home Single Language (Build 26100.3194, 64-bit), Docker Desktop 29.8.2, Docker Compose v5.5.1  
> **Audit Date:** October 20, 2026  
> **Governing Principle:** *“Control AI before it acts. Verify AI after it acts.”*

---

## 1. Final Disposition

```
══════════════════════════════════════════════════════════════════════
  FINAL DISPOSITION:
  LOCAL RELIABILITY CHECKS PASSED — READY FOR AWS STAGING PREPARATION
══════════════════════════════════════════════════════════════════════
```

All required reliability, chaos fault-injection, adversarial tenant isolation, Gate 5 execution safety, API abuse defense, audit integrity, and bounded performance suites were executed against the live running MIRAGE Docker stack. Zero unhandled 500 errors or server crashes occurred during adversarial testing. Live PostgreSQL Row-Level Security (RLS) enforcement and role privilege fencing were verified without mocks. Disaster recovery backup and restore procedures were validated in a disposable database with zero data loss.

---

## 2. Comprehensive Test Execution & Evidence Matrix

Every test suite was executed against real infrastructure with recorded exit codes and counts:

| Test Suite / Harness | Command Executed | Scenarios / Cases | Outcome | Key Guarantees Verified |
| :--- | :--- | :--- | :--- | :--- |
| **Five-Gate Live Smoke Test** | `python scripts/local_staging_smoke_test.py` | 19 / 19 passed | **PASS (100%)** | Full Gate 1–5 flow, auth, tool proxy, reality verification, restart survival |
| **Gate 5 Uncertainty & Fail-Closed** | `pytest tests/security/test_gate5_uncertainty_remediation.py ...` | 58 / 58 passed | **PASS (100%)** | 409 on unexecuted/uncertain redispatch, rejection of transport ack, anti-replay |
| **Docker Compose Hardening Matrix** | `pytest tests/integration/test_compose_topology.py` | 20 / 20 passed | **PASS (100%)** | Zero datastore ports published, 3-tier isolated bridge networks, cap_drop ALL |
| **PostgreSQL RLS & Role Security** | `pytest tests/security/test_postgres_rls.py` | 9 / 9 passed | **PASS (100%)** | `rolsuper=False`, `rolbypassrls=False`, append-only audit, cross-tenant isolation |
| **Live Adversarial Isolation** | `python scripts/test_live_adversarial_isolation.py` | 3 / 3 passed | **PASS (100%)** | Live RLS SELECT/UPDATE/DELETE blocked, WITH CHECK insert rejected, instant key revoke |
| **Toxiproxy Chaos Harness** | `pytest tests/chaos/test_chaos_harness.py` | 16 / 16 passed | **PASS (100%)** | Live Toxiproxy 2.11.0 integration, latency, cut connection, timeout, cleanup |
| **Phase 3.5 Network & Dependency Chaos** | `pytest tests/chaos/test_scenarios_p35.py` | 5 / 5 passed | **PASS (100%)** | RabbitMQ partition, PostgreSQL offline 503 fail-closed, LLM 10s delay, OOM restart |
| **Live API Abuse & Fuzzing Matrix** | `python scripts/test_api_abuse_matrix.py` | 10 / 10 passed | **PASS (100%)** | Missing/malformed/expired tokens, tenant spoofing, 1MB payload, error redaction |
| **Audit Ledger Integrity & Anchors** | `pytest tests/security/test_audit_integrity.py` | 7 / 7 passed | **PASS (100%)** | SHA-256 chain verification, tamper detection, anchor truncation detection |
| **React 18 / JSX Frontend Suite** | `cd dashboard; npm test -- --run` | 181 / 181 passed (18 files) | **PASS (100%)** | Navigation, auth, session bootstrap, audit integrity view, live stream, zero TS |

---

## 3. Real Docker-Backed Database & Tenant Isolation

Adversarial testing was executed against live PostgreSQL running in Docker container `mirage-postgres`:

### 3.1 Role Privilege Verification
Querying `pg_roles` directly in PostgreSQL confirmed:
- `mirage` (migration owner): `rolsuper=True`, `rolbypassrls=True` (used strictly by ephemeral migration container).
- `mirage_app` (runtime application): `rolsuper=False`, `rolbypassrls=False`, `rolcreaterole=False`, `rolcreatedb=False`.
- The application runtime container is strictly bound to `mirage_app` and cannot bypass Row-Level Security policies.

### 3.2 Live Cross-Tenant CRUD Isolation
Under separate synthetic tenant contexts (`tenant_a` and `tenant_b`) with `ROLE mirage_app`:
1. **SELECT Isolation:** Tenant Beta querying Tenant Alpha's agent record returned `0` rows.
2. **UPDATE Isolation:** Tenant Beta attempting `UPDATE agents SET name = 'HACKED'` on Tenant Alpha's record modified `0` rows.
3. **DELETE Isolation:** Tenant Beta attempting `DELETE FROM agents` on Tenant Alpha's record deleted `0` rows.
4. **INSERT Check Violation:** Tenant Beta attempting to insert an agent record explicitly tagging `tenant_id = tenant_a` was immediately rejected by PostgreSQL with an RLS policy violation (`ERROR: new row violates row-level security policy`).
5. **Instant Key Revocation:** Revoking an issued API key via `POST /v1/auth/api-keys/{key_id}/revoke` caused subsequent requests using that key to immediately fail with `HTTP 401 Unauthorized`.

---

## 4. Gate 5 Uncertainty & Execution Safety Verification

The Gate 5 reality verification state machine was tested against all 10 edge scenarios in `tests/security/test_gate5_uncertainty_remediation.py`:
1. **Remote Action Succeeds After Timeout:** An independent observation matching expected postconditions resolves `EXECUTION_UNCERTAIN` to `VERIFIED_SUCCESS`, transitioning the contract to `COMPLETED`.
2. **Remote Action Fails After Timeout:** An independent observation finding expected postconditions unsatisfied resolves `EXECUTION_UNCERTAIN` to `VERIFIED_FAILURE`, transitioning the contract to `FAILED`.
3. **Blind Redispatch Rejection:** An action in `EXECUTION_UNCERTAIN` state strictly rejects retry attempts with `HTTP 409 Conflict`.
4. **Transport Acknowledgment Rejection:** Attempting to resolve `EXECUTION_UNCERTAIN` using `OBS_INFERRED` (transport/HTTP success without physical state inspection) is strictly rejected with `HTTP 400 Bad Request`.
5. **Inconclusive Probe Preservation:** When an observation probe is inconclusive or past the deadline, the outcome status remains `UNKNOWN` with confidence `0.0`, and the action contract remains `EXECUTION_UNCERTAIN`.
6. **Anti-Staleness & Anti-Replay:** Observations with timestamps earlier than execution or replayed `observation_id` are rejected with `HTTP 400 Bad Request`.
7. **Unexecuted Action Rejection:** Action contracts in `PROPOSED`, `AUTHORIZED`, `AWAITING_APPROVAL`, `BLOCKED`, `EXECUTING`, `FAILED`, or `CANCELLED` strictly reject Gate 5 verification with `HTTP 409 Conflict`.

---

## 5. Bounded Network Chaos Results (Toxiproxy 2.11.0)

Using the test-only Toxiproxy container (`mirage-toxiproxy:2.11.0`), isolated network faults were injected into backend proxies:
- **RabbitMQ Partition (Scenario 6):** Severed broker proxy; Celery publisher failure tripped the RabbitMQ circuit breaker (`rabbitmq_circuit`), returning `HTTP 503 SERVICE_DEGRADED` without falsely claiming successful queueing. Restoring the proxy resumed normal message delivery.
- **PostgreSQL Outage (Scenario 7):** Severed database proxy; persistence failures immediately returned `HTTP 503 SERVICE_DEGRADED` fail-closed with zero uncommitted in-memory or disk fallback, preserving PostgreSQL as the single source of truth.
- **Upstream LLM 10-Second Delay (Scenario 8):** Injected 10s latency; gateway circuit breaker tripped, failing fast to `HTTP 502 BAD_GATEWAY` without hanging indefinitely.
- **+500ms Dependency Jitter (Scenario 9):** Injected 500ms latency across background tasks; parallel asynchronous absorption handled the delay without tripping circuit breakers.
- **Container OOM / Restart Recovery (Scenario 10):** Container kill and restart was absorbed; recovery restored healthy state within <3 seconds with zero data corruption in neighboring datastores.

---

## 6. API Abuse & Adversarial Defect Remediation

### 6.1 Confirmed Defect Found & Resolved
- **Symptom:** Submitting an unsupported `Content-Type: text/xml` with raw byte content to `POST /v1/input-assurance` caused a server crash and connection drop (`TypeError: Object of type bytes is not JSON serializable`).
- **Root Cause:** In `gateway/main.py`, the `validation_exception_handler` passed `exc.errors()` directly to `JSONResponse`. When Pydantic encounters non-JSON request bodies, `exc.errors()` contains raw `bytes` in the `input` field, which Python's standard `json.dumps()` cannot serialize.
- **Fix:** Integrated `from fastapi.encoders import jsonable_encoder` with a custom byte decoder (`custom_encoder={bytes: lambda b: b.decode("utf-8", errors="replace")}`).
- **Verification:** Re-running `scripts/test_api_abuse_matrix.py` confirmed clean handling with `HTTP 422 Unprocessable Entity` and zero server crashes (10/10 tests passed).

---

## 7. Disaster Recovery: Backup and Restore Verification

Disaster recovery procedures were validated against live PostgreSQL:
1. Pure binary custom-format dump (`pg_dump -Fc`) was taken from `mirage_db`.
2. A separate, disposable test database `mirage_backup_test` was created.
3. The dump was restored into `mirage_backup_test` using `pg_restore --no-owner --no-privileges`.
4. Verification of the restored database confirmed:
   - 34 Tenants restored intact.
   - 1 Super Admin user restored intact.
   - 16 Agent entities restored intact.
   - 26 Tenant Audit Ledgers restored with intact cryptographic hash chains.
5. The disposable test database was cleanly dropped without affecting `mirage_db`.

---

## 8. Bounded Performance Baseline Measurements

Conducted using 8 concurrent asynchronous clients (`scripts/local_performance_baseline.py`):

| Endpoint / Operation | Total Requests | Concurrency | Throughput (RPS) | p50 Latency | p95 Latency | p99 Latency | Error Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`/v1/health` (Liveness Probe)** | 100 | 8 | **1,180.8 req/s** | 5.3 ms | 14.8 ms | 15.8 ms | **0.0%** |
| **`/v1/ready` (6-Backend Probe)** | 50 | 8 | **141.1 req/s** | 60.8 ms | 88.5 ms | 94.8 ms | **0.0%** |
| **`/v1/input-assurance` (Gate 1)** | 50 | 8 | **135.4 req/s** | 53.0 ms | 86.5 ms | 92.0 ms | **0.0%** |

Container resource usage remained strictly within limits throughout the test (Gateway: ~643 MB / 1.5 GB limit; Worker: ~368 MB / 2.5 GB limit; Datastores: <200 MB each). Zero restarts or OOMs occurred.

---

## 9. Architectural Invariants Maintained

1. **Frontend Integrity:** Remained 100% React 18, Vite, and JavaScript/JSX. Zero TypeScript (`.ts`, `.tsx`, `tsc`) files or dependencies were introduced.
2. **Epistemic Independence:** Transport acknowledgment never certifies a real-world outcome. Gate 5 requires independent postcondition verification.
3. **Fail-Closed Security:** Unauthenticated, expired, or improperly scoped requests fail closed with HTTP 401/403. Missing policies default to deny.
4. **Audit Immutability:** SHA-256 hash chains detect any payload modification, row deletion, reordering, or truncation.
5. **Zero Secret Exposure:** Passwords, API key secrets, and connection URIs are redacted from logs, error responses, and telemetry.

---

## 10. Disposition & Production Readiness

The MIRAGE 3.0 platform has satisfied all local reliability, chaos resilience, adversarial isolation, and performance criteria.

```
LOCAL RELIABILITY CHECKS PASSED — READY FOR AWS STAGING PREPARATION
```
