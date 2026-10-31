# ADR 0004: Docker Compose Multi-Container Production Topology & Worker Deployment Architecture

## Status
Ratified

## Context
Phase P0.6 requires hardening the containerized multi-service deployment topology for MIRAGE. Previous phases (P0.1–P0.5) established strict tenant authentication, PostgreSQL row-level security, MongoDB trace persistence, Redis token-bucket rate limiting with DB 0/DB 1 ACL isolation, and RabbitMQ durable Quorum queue task execution.

However, the existing `docker-compose.yml` deployment topology suffered from multiple critical defects:
1. The Celery worker daemon was absent from Compose, and `docker/Dockerfile.worker` executed a one-shot Python module that immediately exited.
2. All datastores and message brokers exposed plaintext ports to the host interface (`0.0.0.0`), bypassing perimeter security and tenant isolation.
3. No `.dockerignore` existed, causing massive build context leakage.
4. Database migrations (`alembic upgrade head`) were never executed in Compose, causing fresh deployments to fail on missing tables.
5. The gateway healthcheck was misleading, pinging only Redis and returning HTTP 200 even when core databases were disconnected.
6. The OpenTelemetry Collector was omitted despite being required by `Technical_Architecture.md` §10.1 and `Security_Access.md` §17.1.
7. RabbitMQ quorum queues were described without distinguishing single-node Compose durability from multi-node Raft clustering.

## Decisions

### 1. Consolidated Multi-Queue Celery Worker Container
Rather than deploying separate micro-worker containers for each internal signal (`rav_worker`, `scs_worker`, `visual_worker`, `ics_worker`), background tasks are organized into pipeline stages mapped to durable RabbitMQ Quorum queues:
- `mirage.verify` $\to$ `async_verify_task` (runs full multi-signal `VerificationOrchestrator`)
- `mirage.drift` $\to$ `recompute_drift_task` (runs `LongitudinalDriftTracker`)
- `mirage.ingest` $\to$ `ingest_document_task` (runs `KnowledgeBaseIngestionService`)

A consolidated worker daemon container is deployed executing:
```bash
celery -A workers.celery_app worker \
    --loglevel=INFO \
    -Q mirage.verify,mirage.drift,mirage.ingest \
    --concurrency=2 \
    -n mirage_worker@%h
```
This minimizes container overhead while fully processing all background queues with `task_acks_late=True` and `task_reject_on_worker_lost=True`.

### 2. Single-Node RabbitMQ Durability Boundary
In the Docker Compose profile, RabbitMQ runs as a single broker node. Quorum queue declarations (`x-queue-type: quorum`, `x-delivery-limit: 5`) provide:
- On-disk write-ahead logging (WAL) commits before delivery acknowledgements.
- Delivery limit tracking and dead-letter routing (`mirage.dlx`) for poison messages.
- Durability across container restarts via the `rabbitmqdata` volume.
It is explicitly recognized that single-node Compose does **NOT** provide multi-node Raft consensus quorum or High Availability (HA), which is an enterprise cloud profile (Month 6).

### 3. Standalone MongoDB Single-Document Write Atomicity
Inspection of `db/mongo.py` confirms that verification pipeline trace persistence relies on single-document operations (`insert_one`, `delete_one`, `find_one`) on `traces_{tenant_id}`. In MongoDB, single-document operations are atomic by default. Standalone MongoDB (`mongo:7.0.12`) fully satisfies all existing runtime requirements without requiring a multi-node replica set.

### 4. Three-Tier Network Segmentation & Zero Host Port Exposure for Datastores
Three isolated Docker bridge networks are created:
- `frontend_net`: Connects `mirage-dashboard` to `mirage-gateway`.
- `backend_net`: Connects `mirage-gateway`, `mirage-worker`, and `mirage-migration` to internal datastores (`mirage-postgres`, `mirage-mongodb`, `mirage-redis`, `mirage-rabbitmq`, `mirage-qdrant`).
- `observability_net`: Connects `mirage-gateway` and `mirage-worker` to `mirage-otel-collector`, `mirage-tempo`, `mirage-prometheus`, and `mirage-grafana`.

Zero datastores, caches, or message brokers publish ports to the host interface. Only the gateway (`8000`), dashboard (`3000`), and Grafana (`3001`) are exposed on the host for local development and staging verification.

### 5. One-Shot Migration Runner Pattern
A dedicated `mirage-migration` service executes `alembic upgrade head` synchronously with `restart: "no"`. Downstream services (`mirage-gateway`, `mirage-worker`) configure:
```yaml
depends_on:
  migration:
    condition: service_completed_successfully
```
This guarantees that schema migrations and RLS policies are applied exactly once before application containers start, eliminating startup race conditions across replicas.

### 6. Decoupled Liveness vs. Multi-Tier Readiness
- **Liveness (`/v1/health`)**: Lightweight event loop check returning basic status without touching dependencies.
- **Readiness (`/v1/ready`)**: Actively probes PostgreSQL (`SELECT 1`), Redis (`PING`), MongoDB (`adminCommand('ping')`), RabbitMQ (TCP connection), and Qdrant (`/readyz`).
  - Mandatory backends (Postgres, Redis, Mongo, RabbitMQ) UP $\to$ HTTP 200.
  - Qdrant DOWN $\to$ HTTP 200 with `degraded: true` (enters RAV-less mode).
  - Any mandatory backend DOWN $\to$ HTTP 503 `UNREADY`.
  - Zero sensitive connection parameters or credentials are exposed in responses.

### 7. Telemetry Routing via OpenTelemetry Collector
The OpenTelemetry Collector (`mirage-otel-collector`) is formally integrated matching TAD §10.1 and Security §17.1:
`mirage-gateway` & `mirage-worker` $\to$ `mirage-otel-collector` (port 4317 gRPC) $\to$ `mirage-tempo` (port 4317 gRPC).

### 8. Deterministic Worker Health Heartbeat Probe
To avoid self-referential deadlock and broker flakiness associated with `celery inspect ping`, worker liveness is validated via a lightweight timestamp probe on `/tmp/worker_heartbeat` updated periodically by the worker process.

### 9. Strict Container Hardening
All containers enforce:
- Non-root user execution (`USER 1000:1000` for custom containers).
- Capability dropping (`cap_drop: [ALL]`).
- Privilege escalation prevention (`security_opt: [no-new-privileges:true]`).
- Read-only root filesystem (`read_only: true`) with writable `tmpfs: /tmp`.
- Exact third-party image patch pinning.

## Consequences
- Clean, repeatable, multi-tier container orchestration via Docker Compose.
- Complete elimination of datastore exposure to host interfaces.
- Zero startup race conditions for database migrations.
- High resilience during runtime dependency outages without falling back to in-memory state.
- Trace routing conforms to governing OpenTelemetry architecture.
