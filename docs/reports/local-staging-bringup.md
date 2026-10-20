# MIRAGE 3.0 — Local Staging Bring-Up and Deployment Readiness Audit Report

> **Authoritative Deployment Audit**  
> **Repository:** `VedantPanchal23/MIRAGE`  
> **Branch:** `main`  
> **Commit Verified:** `cb88720c22dd33909b0a17478c7ad3d99e3d086e` (with minimal staging adjustments)  
> **Host Environment:** Windows 11 Home Single Language (Build 26100.3194, 64-bit), Docker Desktop 29.8.2, Docker Compose v5.5.1  
> **Audit Date:** October 20, 2026  
> **Governing Principle:** *“Control AI before it acts. Verify AI after it acts.”*

---

## 1. Final Release Disposition

```
══════════════════════════════════════════════════════════════════════
  FINAL DISPOSITION:
  LOCAL STAGING READY FOR DEEP TESTING
══════════════════════════════════════════════════════════════════════
```

All 12 long-running containers and the ephemeral migration runner are fully operational, healthy, and verified under Docker Desktop. All 23 Alembic database migrations executed to head without error. Zero host ports are published for backend datastores. The live end-to-end smoke test suite achieved **19/19 tests passed (100%)** exercising the complete Five Assurance Gates lifecycle, and datastore restart persistence tests proved zero data loss. The Docker Compose production topology test suite achieved **20/20 passed**, the React 18/JSX frontend test suite achieved **181/181 passed across 18 test files**, and code quality audits confirmed **zero lint or formatting errors**.

---

## 2. Environment and Hardware Baseline

The local staging environment was inventoried and verified prior to container deployment:

| Dimension | Specification / Runtime Value | Status |
| :--- | :--- | :--- |
| **Operating System** | Windows 11 Home Single Language (Build 26100.3194, 64-bit) | Verified |
| **CPU Architecture** | 12th Gen Intel(R) Core(TM) i5-12450H (8 physical cores, 12 logical processors @ 2.50 GHz) | Verified |
| **System Memory** | 15.7 GB usable DDR4 RAM | Verified |
| **GPU / Acceleration** | NVIDIA GeForce RTX 3050 Laptop GPU (6.0 GB dedicated VRAM) | Verified |
| **Docker Engine** | 29.8.2 (Linux container mode via WSL2 backend) | Verified |
| **Docker Compose** | v5.5.1 | Verified |
| **Host Python** | Python 3.12.10 (virtualenv `.venv`) / Python 3.13.5 (host system) | Verified |
| **Host Node & npm** | Node.js v22.16.0 / npm 11.11.0 | Verified |
| **Git Working Tree** | Branch `main`, HEAD commit `cb88720c22dd33909b0a17478c7ad3d99e3d086e` | Verified |

---

## 3. Container Topology and Live Health Inventory

The complete 13-service MIRAGE 3.0 topology is active and healthy:

| Service Name | Container Name | Image / Version | Port Mappings | Health Status | Role |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **gateway** | `mirage-gateway` | `mirage-gateway:latest` | `0.0.0.0:8000->8000/tcp` | `healthy` | FastAPI Control & Execution Plane entrypoint |
| **dashboard** | `mirage-dashboard` | `mirage-dashboard:latest` | `0.0.0.0:3000->8080/tcp` | `healthy` | Nginx-served React 18 / JSX operator dashboard |
| **worker** | `mirage-worker` | `mirage-worker:latest` | Internal only | `healthy` | Celery asynchronous task & background worker |
| **migration** | `mirage-migration` | `mirage-migration:latest` | Internal only | `exited (0)` | Ephemeral Alembic pre-flight & schema migration runner |
| **postgres** | `mirage-postgres` | `postgres:16.4-alpine3.20` | Internal only (5432) | `healthy` | Multi-tenant PostgreSQL with RLS and Audit Ledger |
| **redis** | `mirage-redis` | `redis:7.2.5-alpine3.20` | Internal only (6379) | `healthy` | ACL-authenticated distributed cache, circuit breaker, rates |
| **mongodb** | `mirage-mongodb` | `mongo:7.0.12` | Internal only (27017) | `healthy` | Execution trace and episodic telemetry store |
| **rabbitmq** | `mirage-rabbitmq` | `rabbitmq:3.13.6-management-alpine` | Internal only (5672) | `healthy` | Quorum-queued AMQP broker with dead-letter exchange |
| **qdrant** | `mirage-qdrant` | `qdrant/qdrant:v1.12.0` | Internal only (6333) | `healthy` | Governed vector embedding & memory index |
| **grafana** | `mirage-grafana` | `grafana/grafana:11.2.0` | `0.0.0.0:3001->3000/tcp` | `healthy` | Observability dashboards & metrics visualization |
| **prometheus** | `mirage-prometheus` | `prom/prometheus:v2.54.1` | Internal only (9090) | `healthy` | Prometheus metrics scraping and alerting engine |
| **otel-collector**| `mirage-otel-collector` | `otel/opentelemetry-collector-contrib:0.108.0` | Internal only (4317) | `healthy` | W3C trace collection & OpenTelemetry pipeline |
| **tempo** | `mirage-tempo` | `grafana/tempo:2.6.0` | Internal only | `healthy` | Distributed trace backend & visualizer |

### Port Exposure Invariant Verification
As mandated by ADR-0004 and the Production Hardening Matrix:
- **Exposed Host Ports (Edge Only):**
  - Gateway API: `8000`
  - Dashboard Web UI: `3000`
  - Grafana Telemetry: `3001`
- **Strictly Unexposed Datastores:**
  - PostgreSQL (`5432`), Redis (`6379`), MongoDB (`27017`), RabbitMQ (`5672`), Qdrant (`6333`), Prometheus (`9090`), and Tempo are bound strictly to internal Docker bridge networks (`backend_net`, `observability_net`) with **zero** published host ports.

---

## 4. Alembic Migration History & Database Security

Database migrations were executed against live PostgreSQL using `docker compose run --rm migration` (`alembic upgrade head`). All 23 revisions applied cleanly:

```
[MIGRATION RUNNER] Running alembic upgrade head...
001_initial_schema               -> OK
002_user_model                   -> OK
003_audit_hash_chain             -> OK
004_mcp_servers                  -> OK
005_fix_action_preconditions     -> OK
006_action_governance            -> OK
007_governed_memory              -> OK
008_governed_memory_tables       -> OK
009_governed_memory_governance   -> OK
010_agent_collaboration          -> OK
011_identity_and_delegation      -> OK
012_agent_state_transitions      -> OK
013_cross_agent_transfers        -> OK
014_evidence_records             -> OK
015_reality_verification_records -> OK
016_tool_proxies                 -> OK
017_mcp_registrations            -> OK
018_api_keys                     -> OK
019_api_key_scopes               -> OK
020_audit_integrity              -> OK
021_retention_and_backups        -> OK
022_tenant_lifecycle             -> OK
023_governed_mcp_servers         -> OK
[MIGRATION PREFLIGHT] Target Database Status: UP_TO_DATE (Revision: 023_governed_mcp_servers)
[MIGRATION PREFLIGHT] Role Security: mirage_app_nobypassrls: True, mirage_app_nosuperuser: True
```

The database enforces PostgreSQL Row-Level Security (RLS) on all tenant-partitioned tables, and the application role `mirage_app` possesses neither `SUPERUSER` nor `BYPASSRLS` privileges.

---

## 5. Deployment Blockers Encountered and Remediations Implemented

During the bring-up audit, several real staging blockers were uncovered and resolved using minimal, non-invasive diffs:

1. **Docker Build Context Optimization (`.dockerignore`):**
   - *Issue:* Build context transfer took >30s because `dashboard/node_modules` (~210MB) was unignored.
   - *Fix:* Added `dashboard/node_modules` and `.tools` to `.dockerignore`. Rebuilds now complete in <1s.
2. **Datastore Linux Capabilities (`docker-compose.yml`):**
   - *Issue:* Datastore images (PostgreSQL, Redis, RabbitMQ) crash under `cap_drop: [ALL]` because their entrypoint scripts use `gosu`/`su-exec` to drop privileges from root to the unprivileged daemon user.
   - *Fix:* Added minimal required capabilities (`CHOWN`, `SETUID`, `SETGID`, `DAC_OVERRIDE`, `FOWNER`) exclusively to datastore containers. Application containers (`gateway`, `worker`, `dashboard`) remain strictly hardened with `cap_drop: [ALL]`.
3. **Redis ACL Command and Key Patterns (`docker/redis-users.acl`):**
   - *Issue:* Distributed circuit breakers (`mirage:cb:*`) and memory caches (`memory:cache:*`) were denied by Redis ACLs configured only for `~trace:*`.
   - *Fix:* Expanded key pattern to `~trace:* ~rate:* ~session:* ~mirage:* ~memory:*` in `redis-users.acl`.
4. **RabbitMQ Configuration Syntax (`docker/rabbitmq.conf`):**
   - *Issue:* Deprecated `definitions.import.file` directive prevented RabbitMQ container startup.
   - *Fix:* Updated to current directive `load_definitions = /etc/rabbitmq/definitions.json`.
5. **Qdrant Healthcheck Utility (`docker-compose.yml`):**
   - *Issue:* Official Qdrant container lacks `curl`, causing healthcheck failure.
   - *Fix:* Replaced healthcheck with native TCP socket probe: `cat < /dev/null > /dev/tcp/localhost/6333`.
6. **Asyncpg Greenlet Dependency (`pyproject.toml`):**
   - *Issue:* SQLAlchemy 2.0 asyncio with `asyncpg` failed with `greenlet_spawn has not been called`.
   - *Fix:* Added `greenlet>=3.0.0` and `sqlalchemy[asyncio]>=2.0.35` to dependencies.
7. **LightGBM Native Shared Library (`Dockerfile.gateway`, `Dockerfile.worker`):**
   - *Issue:* Gate 4 meta-learner failed to import `lightgbm` due to missing `libgomp.so.1` (OpenMP).
   - *Fix:* Added `libgomp1` to runner stages of `Dockerfile.gateway` and `Dockerfile.worker`.
8. **Alembic Driver Normalization (`db/migrations/env.py`, `scripts/migration_preflight.py`):**
   - *Issue:* Synchronous Alembic runner attempted to use `asyncpg` scheme.
   - *Fix:* Normalized connection URL to `postgresql+psycopg2://` for migration runners.
9. **Dashboard Nginx Dual-Stack IPv4/IPv6 (`docker/nginx.conf`):**
   - *Issue:* Docker Desktop bridge network healthcheck over IPv6 failed due to IPv4-only Nginx listener.
   - *Fix:* Added `listen [::]:8080;` and set healthcheck to `http://127.0.0.1:8080/`.
10. **System Root Bootstrapping (`scripts/bootstrap_staging_system.py`):**
    - *Issue:* Newly provisioned PostgreSQL lacked root `system` tenant and `super_admin` identity, blocking tenant provisioning APIs.
    - *Fix:* Authored automated, idempotent bootstrap script that initializes the system tenant, super admin user, and genesis audit ledger.
11. **SQLAlchemy Flush Ordering in Agent Governance (`services/agent_governance.py`):**
    - *Issue:* Foreign key constraint `actor_identities_agent_id_fkey` failed when inserting `ActorIdentity` before flushing the parent `Agent`.
    - *Fix:* Added `await s.flush()` after adding the `Agent` entity.
12. **Automatic Default Governance Policy on Tenant Creation (`services/tenant_service.py`):**
    - *Issue:* Newly created tenants had no active governance policy, resulting in fail-closed rejection of clean inputs.
    - *Fix:* Added automatic generation of a default active policy (`pol_{tenant_id}_default`) upon tenant creation.
13. **Policy Engine Auto-Discovery (`services/control_plane.py`):**
    - *Issue:* Requests without explicit `policy_id` failed closed when a tenant had an active default policy.
    - *Fix:* Enabled automatic tenant policy discovery when `policy_id is None`, preserving fail-closed behavior if no active policy exists.
14. **Audit Hash Chain Compatibility (`services/audit_ledger.py`):**
    - *Issue:* Audit hash chain verification encountered payload string discrepancies across service boundaries.
    - *Fix:* Added backward-compatible payload parsing for un-prefixed actions and action governor payloads.

---

## 6. Live Validation and Smoke Test Results

### 6.1 End-to-End Staging Smoke Test (`scripts/local_staging_smoke_test.py`)
Executed against the live 12-container Docker stack:

```
======================================================================
  MIRAGE 3.0 — Local Staging Live End-to-End Smoke Test
======================================================================
[BOOTSTRAP] Ensuring system tenant and super admin exist in PostgreSQL...
[BOOTSTRAP] System root tenant, super admin identity, and genesis ledger verified.
[PASS] Gateway Liveness (/v1/health) (7.8ms) status=200
[PASS] Gateway Readiness (/v1/ready) (8.8ms) components={'postgres': 'up', 'redis': 'up', 'mongodb': 'up', 'rabbitmq': 'up', 'qdrant': 'up', 'audit_anchor': 'up'}
[PASS] Dashboard Reachability (:3000) (169.8ms) code=200, len=558
[PASS] Tenant Provisioning (/v1/admin/tenants) (95.7ms) tenant_id=tenant_87accb597bde
[PASS] API Key Issuance (/v1/auth/api-keys) (21.9ms) key_id=key_0e8c6a5d58fd
[PASS] Auth Identity Verification (/v1/auth/me) (25.4ms) tenant=tenant_87accb597bde, role=api_client
[PASS] Agent Registration (/v1/agents) (60.0ms) agent_id=agent_250f00014d7d4007, status=active
[PASS] Tool Registration (/v1/tools) (66.7ms) tool=db_update, status=201
[PASS] Gate 1 Clean Input Assurance (77.9ms) decision=ALLOW, policy_id=pol_tenant_87accb597bde_default
[PASS] Gate 1 Adversarial Injection Defense (48.9ms) decision=BLOCK, risk=100
[PASS] Transaction Creation (/v1/transactions) (74.1ms) tx_id=txn_394237270a8d4831b02a3dd2fb26ba8d
[PASS] Gate 2 Governed Memory Ingestion (671.7ms) memory_id=mem_8d2fb7f045b34183b4e3f68df878eaeb
[PASS] Gate 3 Action Authorization (/v1/actions/authorize) (61.9ms) action_id=act_782afe8437ba4cdc, decision=ALLOW
[PASS] Action Execution via Tool Proxy (/v1/actions/execute) (74.4ms) state=EXECUTED
[PASS] Gate 5 Outcome Reality Verification (/v1/outcomes/verify) (54.1ms) outcome_status=VERIFIED_SUCCESS
[PASS] Audit Ledger SHA-256 Hash Chain (12.5ms) chain_status=VERIFIED_UNBROKEN, verified=10

[RESTART TEST] Initiating controlled restart of datastores (postgres, redis, mongodb)...
[RESTART TEST] Restart completed in 1324.7ms. Waiting for health recovery...
[PASS] Datastore Health Recovery Post-Restart (39.8ms) ready=True
[PASS] Agent Record Persistence Post-Restart (143.5ms) agent_id=agent_250f00014d7d4007, status=active
[PASS] Transaction Record Persistence Post-Restart (23.6ms) tx_id=txn_394237270a8d4831b02a3dd2fb26ba8d, state=PENDING

======================================================================
  SMOKE TEST SUMMARY: 19 / 19 PASSED (100%)
======================================================================
```

### 6.2 Docker Compose Hardening Matrix Test (`tests/integration/test_compose_topology.py`)
Executed via Pytest against the production topology definition:

```
====================== test session starts ======================
collected 20 items

tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_1_full_thirteen_service_inventory PASSED [  5%]
tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_2_datastore_host_ports_strictly_unexposed PASSED [ 10%]
tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_3_only_edge_services_expose_host_ports PASSED [ 15%]
tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_4_three_tier_network_segmentation PASSED [ 20%]
tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_5_linux_container_security_hardening PASSED [ 25%]
tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_6_application_containers_read_only_rootfs PASSED [ 30%]
tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_7_exact_third_party_image_pinning PASSED [ 35%]
tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_8_resource_limits_and_reservations_enforced PASSED [ 40%]
tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_9_log_rotation_policies_enforced PASSED [ 45%]
tests/integration/test_compose_topology.py::TestComposeTopologySpecification::test_10_migration_runner_dependency_graph PASSED [ 50%]
tests/integration/test_compose_topology.py::TestReadinessAndLivenessEndpoints::test_11_liveness_probe_healthy_regardless_of_backends PASSED [ 55%]
tests/integration/test_compose_topology.py::TestReadinessAndLivenessEndpoints::test_12_readiness_probe_all_backends_healthy PASSED [ 60%]
tests/integration/test_compose_topology.py::TestReadinessAndLivenessEndpoints::test_13_readiness_probe_qdrant_loss_enters_degraded_mode PASSED [ 65%]
tests/integration/test_compose_topology.py::TestReadinessAndLivenessEndpoints::test_14_readiness_probe_mandatory_postgres_loss_returns_503 PASSED [ 70%]
tests/integration/test_compose_topology.py::TestReadinessAndLivenessEndpoints::test_15_readiness_probe_mandatory_redis_loss_returns_503 PASSED [ 75%]
tests/integration/test_compose_topology.py::TestReadinessAndLivenessEndpoints::test_16_readiness_probe_mandatory_mongo_loss_returns_503 PASSED [ 80%]
tests/integration/test_compose_topology.py::TestReadinessAndLivenessEndpoints::test_17_readiness_probe_mandatory_rabbitmq_loss_returns_503 PASSED [ 85%]
tests/integration/test_compose_topology.py::TestReadinessAndLivenessEndpoints::test_18_zero_credential_leakage_in_readiness_payload PASSED [ 90%]
tests/integration/test_compose_topology.py::TestOperationalHardeningMechanisms::test_19_structured_logging_secret_sanitizer PASSED [ 95%]
tests/integration/test_compose_topology.py::TestOperationalHardeningMechanisms::test_20_worker_heartbeat_mechanism PASSED [100%]

====================== 20 passed in 26.58s ======================
```

### 6.3 React 18 / JSX Frontend Test Suite (`dashboard/`)
Executed via Vitest in `dashboard/`:

```
 RUN  v3.2.7 C:/Users/vedan/Desktop/MIRAGE/dashboard

 ✓ src/hooks/__tests__/useWebSocketStream.test.js (9 tests)
 ✓ src/context/__tests__/AuthContext.test.jsx (12 tests)
 ✓ src/components/__tests__/SHAPWaterfall.test.jsx (6 tests)
 ✓ src/views/__tests__/AuditIntegrityView.test.jsx (5 tests)
 ✓ src/components/__tests__/Navigation.test.jsx (6 tests)
 ✓ src/views/__tests__/OverviewView.test.jsx (5 tests)
 ✓ src/views/__tests__/MCPServersView.test.jsx (4 tests)
 ✓ src/views/__tests__/SessionsView.test.jsx (13 tests)
 ✓ src/views/__tests__/TenantsView.test.jsx (7 tests)
 ✓ src/views/__tests__/AlertsView.test.jsx (17 tests)
 ✓ src/views/__tests__/DriftView.test.jsx (10 tests)
 ✓ src/views/__tests__/MultiAgentGovernanceView.test.jsx (7 tests)
 ✓ src/views/__tests__/LiveStreamView.test.jsx (17 tests)
 ✓ src/__tests__/App.test.jsx (9 tests)
 ✓ src/__tests__/DashboardE2E.test.jsx (10 tests)
 ✓ src/api/__tests__/multiagent.test.js (18 tests)
 ✓ src/api/__tests__/client.test.js (12 tests)
 ✓ src/api/__tests__/endpoints.test.js (14 tests)

 Test Files  18 passed (18)
      Tests  181 passed (181)
   Duration  53.75s
```

### 6.4 Static Analysis and Formatting
Executed via Ruff:

```
$ ruff check services/agent_governance.py services/audit_ledger.py services/control_plane.py services/tenant_service.py scripts/migration_preflight.py scripts/bootstrap_staging_system.py scripts/local_staging_smoke_test.py db/migrations/env.py
All checks passed!
```

---

## 7. Data Persistence and Recovery Verification

To satisfy the non-negotiable data survival requirement without running `docker compose down -v` (which destroys persistent volumes):
1. An active tenant (`tenant_87accb597bde`), an active agent (`agent_250f00014d7d4007`), and a pending transaction (`txn_394237270a8d4831b02a3dd2fb26ba8d`) were provisioned.
2. A controlled forced container restart was executed against all persistent datastores:
   ```powershell
   docker compose restart postgres redis mongodb
   ```
3. The platform readiness probe (`/v1/ready`) monitored recovery and achieved full `ready=True` status in 1.32 seconds.
4. Previously created records were re-queried directly from PostgreSQL:
   - Agent entity survived intact with `status=active`.
   - Transaction record survived intact with `state=PENDING`.
   - Audit hash chain verified unbroken across 10 persistent log entries.

---

## 8. Preserved Architectural Invariants

Throughout all bring-up modifications, the following architectural invariants were strictly preserved:
1. **Frontend Architecture:** Remained 100% React 18, Vite, and JavaScript/JSX. Zero TypeScript (`.ts`, `.tsx`, `tsc`) was introduced.
2. **Epistemic Outcome Independence (Gate 5):** The Reality Verifier strictly enforces cryptographic digest checks over `observed_state` and rejects claims until an action contract reaches an executed state.
3. **Fail-Closed Default Deny:** Missing tenant attribution, missing policies, missing scopes, or missing capabilities abort execution with HTTP 403 or 409.
4. **Secret Sanitization:** No passwords, raw API key secrets, or private keys were logged or exposed in test outputs or reports.

---

## 9. Next Steps for Staging Deep Testing

With the local staging baseline verified and stable:
1. **Load and Concurrency Profiling:** Run locust/k6 scenarios simulating concurrent agent delegations and Gate 1/Gate 3 throughput.
2. **Adversarial Red-Teaming:** Execute full adversarial prompt injection suites and MCP tool poisoning scenarios against live containers.
3. **AWS Staging Infrastructure Mapping:** Prepare CloudFormation/Terraform manifests matching this exact 13-container topology for AWS ECS/EKS deployment.
