# MIRAGE 3.0 — Deployment, Operations & Incident Runbook

> **Status:** Authoritative | **Version:** 3.0.0  
> **Related:** [`ARCHITECTURE.md`](ARCHITECTURE.md) | [`deployment/aws-private-staging.md`](deployment/aws-private-staging.md) | [`ADRs/0004`](ADRs/0004-docker-compose-production-topology.md)

---

## 1. Local & Production Container Topology (Docker Compose)

[`docker-compose.yml`](../docker-compose.yml) defines a **13-service hardened topology** segmented across `frontend_net`, `backend_net`, and `observability_net`:

| Service | Image / Build | Host Port | Network(s) | Security Hardening |
| :--- | :--- | :--- | :--- | :--- |
| `dashboard` | `docker/Dockerfile.dashboard` | `3000` (`:8080` internal) | `frontend_net` | Non-root Nginx (`101:101`), `read_only`, `cap_drop: ALL`, tmpfs mounts |
| `gateway` | `docker/Dockerfile.gateway` | `8000` | `frontend_net`, `backend_net`, `observability_net` | Non-root (`1000:1000`), `read_only`, `cap_drop: ALL`, `/tmp` tmpfs, `audit_anchors` vol |
| `worker` | `docker/Dockerfile.worker` | *None* | `backend_net`, `observability_net` | Non-root (`1000:1000`), `read_only`, `cap_drop: ALL`, Celery heartbeat healthcheck |
| `migration` | `docker/Dockerfile.gateway` | *None* | `backend_net` | One-shot `alembic upgrade head` using DDL owner role `mirage` |
| `postgres` | `postgres:16.4-alpine3.20` | *Internal only* | `backend_net` | RLS enforced (`mirage_app` `NOBYPASSRLS` initialized via `docker/postgres-init.sql`) |
| `mongodb` | `mongo:7.0.12` | *Internal only* | `backend_net` | Least-privilege `mirage_app` user (`docker/mongo-init.js`), 90d trace TTL |
| `qdrant` | `qdrant/qdrant:v1.12.0` | *Internal only* | `backend_net` | API-key protected HNSW vector engine |
| `redis` | `redis:7.2.5-alpine3.20` | *Internal only* | `backend_net` | Split ACL users `mirage_app` & `mirage_celery` (`docker/redis-users.acl`) |
| `rabbitmq` | `rabbitmq:3.13.6-management-alpine` | *Internal only* | `backend_net` | Quorum queues & Dead-Letter Exchange (`docker/definitions.json`) |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.108.0` | *Internal only* | `observability_net` | Trace buffer & routing |
| `tempo` | `grafana/tempo:2.6.0` | *Internal only* | `observability_net` | Distributed trace storage |
| `prometheus` | `prom/prometheus:v2.54.1` | *Internal only* | `observability_net` | Scrapes Gateway `/metrics` internally |
| `grafana` | `grafana/grafana:11.2.0` | `3001` (`:3000` internal) | `observability_net` | Provisioned dashboards (`docker/grafana/`) |

> **Security Invariant:** Zero datastores, message brokers, or Prometheus endpoints publish host ports in production compose configurations.

### Quick Launch & Instant Public Demo Tunnel
```bash
cp .env.example .env                    # Review configuration (use strong secrets outside local dev)
docker compose up -d --build            # Build and boot full 13-service stack
docker compose ps                       # Verify healthy status across services
python scripts/verify_full_customer_journey.py
```
- **Platform Launchers:** `./start-mirage.ps1` (Windows PowerShell), `start-mirage.bat` (CMD), `./start-mirage.sh` (Linux/macOS).
- **Public HTTPS Tunnel (Zero-Cost Demo):** `.\scripts\start-public-tunnel.ps1` (exposes `http://127.0.0.1:3000` via Cloudflare Quick Tunnel).

---

## 2. Cloud, Staging & Kubernetes Deployment Options

1. **AWS Private Staging (Terraform + SSM):**
   See [`deployment/aws-private-staging.md`](deployment/aws-private-staging.md) for the zero-public-ingress `t3.large` architecture (`infra/terraform/`, `docker-compose.staging.yml`, `scripts/fetch_secrets.py`, and `scripts/verify_staging_release.py`). Note: Staging resources remain unprovisioned unless explicitly applied (`$0.00` idle cost).
2. **Kubernetes (Helm Chart — `k8s/helm/mirage/`):**
   Provides hardening-ready Deployments (`gateway`, `worker`, `dashboard` on container port `8080`), Services, Ingress, Secrets template, NetworkPolicy (egress scoped to PostgreSQL `5432`, Redis `6379`, RabbitMQ `5672`, Qdrant `6333`, MongoDB `27017`, OTel `4317`, DNS `53`, HTTP/HTTPS), `HorizontalPodAutoscaler` (`hpa.yaml`), `PodDisruptionBudget` (`pdb.yaml`), pre-upgrade Alembic migration hook Job (`migration-job.yaml`), and Prometheus alert rules (`prometheus-alerts.yaml` + [`docker/prometheus/alerts.yml`](../docker/prometheus/alerts.yml) & [`docker/alertmanager/alertmanager.yml`](../docker/alertmanager/alertmanager.yml)).
   ```bash
   helm upgrade --install mirage ./k8s/helm/mirage --namespace mirage --create-namespace
   ```
3. **Production Cloud VPS:**
   Provision Ubuntu 22.04/24.04 LTS with UFW (`22`, `80`, `443` only), Docker Engine + Compose plugin, strong `.env` keys (`chmod 600`), Certbot/Nginx TLS termination proxying `/` → `127.0.0.1:3000` and `/v1/` → `127.0.0.1:8000`, `docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d`, and scheduled daily backups.

---

## 3. Migrations, Health Probes & Disaster Recovery

### 3.1 Migration Preflight & Execution
The linear Alembic chain spans **26 revisions** ending at **`026_add_execution_trace`**:
```bash
python scripts/migration_preflight.py --database-url "${DATABASE_SYNC_URL}"
alembic upgrade head
```
Preflight verifies connectivity, single unbranched head, pending revision list, and unprivileged `mirage_app` (`NOBYPASSRLS`) role separation.

### 3.2 Liveness & Readiness Probes
- **`GET /v1/health` (Liveness):** Always returns HTTP `200` with version and circuit breaker status while the FastAPI event loop responds.
- **`GET /v1/ready` (Readiness):** Concurrently probes `postgres`, `redis`, `mongodb`, `rabbitmq`, `qdrant`, and `audit_anchor`.
  - **Degraded (`200`, `degraded: true`):** Only `qdrant` (or non-prod `audit_anchor`) unavailable; RAV bypassed while control/action/outcome gates hold.
  - **Unready (`503`):** Any failure of `postgres`, `redis`, `mongodb`, `rabbitmq` (or `audit_anchor` when `ENVIRONMENT=production`). Zero credentials are ever serialized.

### 3.3 Cryptographic Backup & Restore
```bash
python scripts/backup_restore.py backup --output-dir /var/backups/mirage
python scripts/backup_restore.py verify-backup --backup-dir /var/backups/mirage/<bundle_dir>
python scripts/backup_restore.py restore --backup-dir /var/backups/mirage/<bundle_dir> --confirm
```
> **Epistemic Rule:** Restoring Postgres tables does not prove ledger completeness; always run `GET /v1/audit/integrity` after restore to verify database heads against external `audit_anchors` proofs.

---

## 4. Consolidated Operational Runbooks

| Incident / Operation | Detection Signal | Immediate Fail-Closed Action & Recovery |
| :--- | :--- | :--- |
| **1. Production Startup Blocked** | Gateway exits during lifespan check | Inspect logs for `validate_environment_configuration()` defects: verify 48+ char `SECRET_KEY`, `amqps://` Celery broker, non-default passwords, valid `NOTARY_KEYS_JSON`, and `DEMO_AUTH_ENABLED=false`. |
| **2. Readiness `503` (`postgres`/`redis`/`mongo`/`rabbit`)** | `/v1/ready` returns `503` | Inspect `failed_components`; run `docker compose ps` & `docker compose logs <svc>`; restore unhealthy container before allowing traffic. |
| **3. Degraded Mode (`qdrant` down)** | `/v1/ready` `degraded: true` | Traffic continues with RAV bypassed; inspect `mirage-qdrant` memory/storage and re-sync KB documents if index state diverged. |
| **4. Audit Chain Tamper / Truncation Alert** | `GET /v1/audit/integrity` flags `INTEGRITY_FAILURE` | **Do not regenerate anchors.** Snapshot `pg_dump` + `/app/data/audit_anchors/*.anchors.jsonl` read-only immediately for forensic investigation. |
| **5. `EXECUTION_UNCERTAIN` Action** | Tool dispatch timed out; `GET /v1/actions/stranded` lists action | **Never blindly redispatch** (`HTTP 409`). Probe physical target via `OBS_DIRECT`/`IndependentObserverAdapter` and call `POST /v1/actions/{id}/reconcile` or `POST /v1/outcomes/{id}/escalate`. |
| **6. Compromised API Key / Tenant** | Unusual egress, abuse alerts, leaked credential | `POST /v1/auth/api-keys/{key_id}/revoke` for key-level cutoff, or `POST /v1/admin/tenants/{id}/suspend` to cut off all tenant auth at PostgreSQL immediately. |
| **7. Compromised MCP Server / Runaway Agent** | Prompt injection or SSRF triggers from MCP tool | `PUT /v1/mcp/servers/{id}/trust` → `REVOKED` (immediately deactivates child tools in `tool_registry`) or `POST /v1/agents/{id}/revoke`. |
| **8. Signing / Notary Key Rotation** | Scheduled rotation or key disclosure | Add new key ID to `NOTARY_KEYS_JSON` (multi-key validation), issue fresh checkpoints (`POST /v1/audit/anchor`), then retire old key ID. |
| **9. Failed Deployment / Bad Migration** | Container crashloop post-deploy | Run `migration_preflight.py`; prefer forward-fix migration over destructive downgrade unless verified cleanly on backup snapshot first. |
