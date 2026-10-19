# MIRAGE 3.0 — Deployment and Operations

> **Status:** Authoritative | **Version:** 3.0.0 | **Date:** 2026-10-19

## 1. Introduction

MIRAGE 3.0 sits between AI systems and the real world to govern execution lifecycle, enforce identity, security, policy, reliability, and cost controls.
This document specifies the authoritative deployment topology, container security hardening, persistent storage architecture, database migration preflight, health and readiness probes, backup/disaster recovery procedures, and operational runbooks for running MIRAGE in production.

---

## 2. Deployment Topologies

### 2.1 Local Development
Optimized for rapid iteration, unit testing, and component debugging.
* **Mechanism:** Managed via `docker-compose.yml` and unified `Makefile` targets (`make up`, `make test`, `make logs`).
* **Configuration:** Local `.env` file (copied from `.env.example`, strictly excluded from version control).
* **Mock Providers:** Non-production environments permit local mock verifiers for offline testing.

### 2.2 Production 13-Service Container Topology (Docker Compose)
MIRAGE 3.0 implements a decoupled 13-service production topology adhering to ADR 0004:

```
                    +-----------------------------+
                    |  Host Port 3000 (Frontend)  |
                    |      mirage-dashboard       |
                    |   (React 18 / Nginx proxy)  |
                    +--------------+--------------+
                                   |
                             frontend_net
                                   |
                    +--------------v--------------+
                    |   Host Port 8000 (Gateway)  |
                    |        mirage-gateway       |
                    |       (FastAPI Engine)      |
                    +--------------+--------------+
                                   |
                                   +-----------------------+
                                   |                       |
                             backend_net           observability_net
                                   |                       |
          +------------------------+-----+                 |
          |                        |     |                 |
+---------v---------+    +---------v---+-v-------+   +-----v-------------+
|    PostgreSQL 16  |    |  Redis 7    | RabbitMQ|   |  OTel Collector   |
| (Control & RLS)   |    | (Limiting)  | (Celery)|   +---+----------+----+
+-------------------+    +-------------+---------+       |          |
|    MongoDB 7      |    |  Qdrant     | Worker  |   +---v---+  +---v----+
| (Traces & Spans)  |    | (Embeddings)| (Async) |   | Tempo |  |Prometh.|
+-------------------+    +-------------+---------+   +-------+  +---+----+
          |                        |                            |
          +------------------------+                 +----------v----+
                                                     |    Grafana    |
                                                     | (Host: 3001)  |
                                                     +---------------+
```

### 2.3 Network Segmentation
- **`frontend_net`:** Bridge network connecting edge clients to `mirage-dashboard` and `mirage-gateway`.
- **`backend_net`:** Internal, strictly unexposed bridge network hosting datastores (`postgres`, `mongodb`, `redis`, `qdrant`), queue brokers (`rabbitmq`), Celery `worker`, and one-shot `migration` runner. Host port mapping on backend datastores is strictly prohibited in production.
- **`observability_net`:** Isolated telemetry network connecting `gateway`, `worker`, and `tempo` to `otel-collector`, scraped by `prometheus` and visualized via `grafana`.

---

## 3. Container Security Hardening

Every production container in the MIRAGE topology enforces defense-in-depth Linux security controls:

### 3.1 Non-Root User Execution
- All application containers (`gateway`, `worker`, `migration`) execute as an unprivileged, non-login user `mirage` (`UID 1000:GID 1000`).
- Dashboard executes as unprivileged `nginx` (`UID 101:GID 101`) via `nginxinc/nginx-unprivileged:1.27.1-alpine3.20`.
- Root execution (`USER 0`) is strictly prohibited in production images.

### 3.2 Linux Capability Dropping & Privilege Escalation Prevention
- **`cap_drop: [ALL]`:** Dropped all Linux kernel capabilities.
- **`security_opt: ["no-new-privileges:true"]`:** Disables setuid binaries and prevents privilege escalation child processes.

### 3.3 Read-Only Root Filesystem (`read_only: true`)
- All application container root filesystems are mounted read-only to prevent malware persistence, unauthorized script execution, or tampering with code layers.
- Ephemeral writable storage is strictly limited to isolated `tmpfs` mounts:
  - Gateway / Worker: `/tmp:rw,noexec,nosuid,size=64m`
  - Dashboard: `/tmp`, `/var/cache/nginx`, `/var/run` (size-constrained tmpfs).

### 3.4 Persistent Volumes & Audit Anchor Storage
Writable persistent state is strictly confined to named volumes:
- `pgdata`: PostgreSQL database storage.
- `audit_anchors`: Mounts to `/app/data/audit_anchors` on `gateway` and `worker` to store immutable, append-only external audit anchor hash chains (`{tenant_id}.anchors.jsonl`).
- `mongodata`, `qdrant_storage`, `rabbitmqdata`, `tempodata`, `prometheusdata`, `grafanadata`.

---

## 4. Health, Readiness, and Safe Degradation

MIRAGE decouples process liveness from operational readiness:

### 4.1 Liveness Probe (`GET /v1/health`)
- Verifies that the FastAPI process and event loop are responsive.
- Always returns HTTP 200 as long as the process can serve HTTP traffic, preventing premature container churn during temporary upstream database failovers.
- Response includes uptime, circuit breaker statuses, and platform version `3.0.0`.

### 4.2 Readiness Probe (`GET /v1/ready`)
- Concurrently probes all required backing stores:
  - PostgreSQL database connection (`check_database_connection`)
  - Redis ping (`default_redis_client_manager.ping`)
  - MongoDB health (`default_mongo_trace_service.check_health`)
  - RabbitMQ broker socket (`_check_rabbitmq_ready`)
  - Qdrant vector database (`_check_qdrant_ready`)
  - Audit Anchor storage directory accessibility (`_check_audit_anchor_writable`)
- **Degraded Mode (HTTP 200, degraded=true):** If Qdrant is unreachable, the system enters degraded mode (bypassing RAV while preserving Gates 1, 3, 4, 5).
- **Unready Mode (HTTP 503):** If PostgreSQL, Redis, MongoDB, RabbitMQ, or in production mode, Audit Anchor storage is unavailable, the gateway marks itself unready.
- **Credential Sanitization:** Health probes strictly return status indicators (`"up"` or `"down"`). Passwords, hostnames, usernames, and connection strings are zero-exposed.

---

## 5. Database Migration Safety & Role Separation

### 5.1 Role Separation (PostgreSQL RLS Invariant)
1. **Migration Owner Role (`mirage`):** Database owner with DDL privileges (`CREATE TABLE`, `ALTER TABLE`, `DROP POLICY`). Used strictly by the one-shot `migration` container.
2. **Application Role (`mirage_app`):** Unprivileged runtime user with `NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOBYPASSRLS`. Application services (`gateway`, `worker`) connect strictly as `mirage_app`.
3. Because `mirage_app` has `NOBYPASSRLS`, PostgreSQL Row-Level Security policies are strictly enforced on all queries, guaranteeing multi-tenant isolation.

### 5.2 Migration Preflight Automation
Before running migrations or upgrading application versions, operators execute the preflight script:
```bash
python scripts/migration_preflight.py --database-url "${DATABASE_SYNC_URL}"
```
This script verifies:
- Database connectivity and PostgreSQL dialect.
- Presence of single, unbranched Alembic head.
- Current database revision vs target release head.
- Unprivileged role fencing (`mirage_app` with `NOBYPASSRLS`).

---

## 6. Backup, Verification, and Disaster Recovery

### 6.1 Cryptographic Backup Manifest
The backup utility (`scripts/backup_restore.py`) creates self-contained backup bundles:
- Relational database schema and data (`pg_dump`).
- External immutable audit anchor files (`data/audit_anchors/*.anchors.jsonl`).
- Deterministic cryptographic manifest (`manifest.json`) containing SHA-256 checksums across all captured files.

### 6.2 Backup Commands:
```bash
# Create backup bundle
python scripts/backup_restore.py backup --output-dir /var/backups/mirage

# Cryptographically verify backup bundle
python scripts/backup_restore.py verify-backup --backup-dir /var/backups/mirage/<bundle_name>

# Restore from verified backup bundle (fails closed if tampered)
python scripts/backup_restore.py restore --backup-dir /var/backups/mirage/<bundle_name> --confirm
```

### 6.3 Epistemic Reality Note
A successful database restore is NOT equivalent to cryptographic audit integrity. Restoring database tables does not prove the ledger has not been truncated or modified. Operators must run `verify_with_anchor` post-restore to verify ledger alignment against external anchors.

---

## 7. The 12 Operational Runbooks

Executable, step-by-step operational runbooks are located in `docs/runbooks/`:

| Runbook | Title | Focus Area |
|---------|-------|------------|
| [`01_initial_deployment.md`](runbooks/01_initial_deployment.md) | Initial Secure Deployment | 13-service Docker Compose topology, volume provisioning, initial boot. |
| [`02_configuration_and_secrets.md`](runbooks/02_configuration_and_secrets.md) | Configuration and Secrets | 12-Factor settings, Vault/KMS injection, production secret generation. |
| [`03_migration_execution_and_safety.md`](runbooks/03_migration_execution_and_safety.md) | Migration Preflight and Execution | Linear Alembic graph verification, role separation, rollback limits. |
| [`04_health_and_readiness_troubleshooting.md`](runbooks/04_health_and_readiness_troubleshooting.md) | Health and Readiness Troubleshooting | Liveness vs. readiness, degraded mode triage, backing store recovery. |
| [`05_database_backup_and_restore.md`](runbooks/05_database_backup_and_restore.md) | Database Backup and Restore | Scripted backup bundles, manifest checksum verification, safe restore. |
| [`06_audit_anchor_verification_and_recovery.md`](runbooks/06_audit_anchor_verification_and_recovery.md) | Audit-Anchor Verification & Recovery | Hash-chain verification, truncation detection, no automatic regeneration. |
| [`07_signing_key_rotation.md`](runbooks/07_signing_key_rotation.md) | Signing-Key Rotation and Recovery | JWT secret rotation, NotaryKeyRegistry multi-key rollout and retirement. |
| [`08_credential_compromise_and_tenant_suspension.md`](runbooks/08_credential_compromise_and_tenant_suspension.md) | Credential Compromise & Tenant Suspension | Instant API key revocation, tenant SUSPENDED status, fail-closed auth. |
| [`09_mcp_revocation_and_egress_incidents.md`](runbooks/09_mcp_revocation_and_egress_incidents.md) | MCP Revocation & Egress Incidents | GovernedToolProxy revocation, SSRF protection, agent delegation kill. |
| [`10_uncertain_action_investigation.md`](runbooks/10_uncertain_action_investigation.md) | Uncertain Action Investigation | Handling EXECUTION_UNCERTAIN, preventing blind redispatch, reality checks. |
| [`11_failed_deployment_recovery.md`](runbooks/11_failed_deployment_recovery.md) | Failed Deployment Recovery | Container crashloop triage, forward-repair vs. rollback decision tree. |
| [`12_incident_evidence_preservation.md`](runbooks/12_incident_evidence_preservation.md) | Incident Evidence Preservation | Exporting signed compliance evidence bundles, forensic anchor snapshots. |

---

## 8. Explicit Operational Limitations and Trust Boundaries

To maintain rigorous engineering honesty, operators must recognize the following platform boundaries:
1. **Single-Host Trust Boundary:** When PostgreSQL and the `audit_anchors` persistent volume share the same physical host operating system, an attacker with root OS access can tamper with both. True Byzantine fault tolerance requires remote append-only notary integration (e.g. Rekor/Sigstore, remote KMS, or WORM S3 Object Lock).
2. **External Protocol Fencing Limitations:** Internal database actions enforce conditional SQL mutations with fencing tokens. However, mutations dispatching to external third-party protocols (SMTP, arbitrary webhooks, remote REST APIs) cannot guarantee remote target-side fencing unless the remote target natively enforces conditional idempotency keys. External targets are mediated at Gate 3 and independently verified at Gate 5.
3. **Environment Demarcation:** Local Docker Compose validation verifies container security profiles, networking, volumes, and health probe contracts. It does NOT constitute certification against unprovisioned external cloud infrastructure (e.g. AWS EKS, managed RDS, or enterprise KMS).
