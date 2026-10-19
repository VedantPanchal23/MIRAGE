# Runbook 01: Initial Secure Deployment

## 1. Overview and Architecture Context
This runbook details the initial deployment of the MIRAGE 3.0 AI Execution Assurance Platform using the production 13-service Docker Compose topology or equivalent container orchestrator.

### Service Inventory & Network Segmentation
- **frontend_net:** Edge network connecting `dashboard` (Nginx/React 18) and `gateway` (FastAPI).
- **backend_net:** Isolated internal network hosting `postgres`, `mongodb`, `redis`, `rabbitmq`, `qdrant`, `worker`, and `migration`. No host ports published.
- **observability_net:** Telemetry network hosting `tempo`, `otel-collector`, `prometheus`, and `grafana`.

## 2. Preflight Requirements
1. Docker Engine 24.0+ and Docker Compose v2.20+.
2. Dedicated filesystem volumes configured for persistent data:
   - `pgdata`: PostgreSQL database storage.
   - `audit_anchors`: Dedicated volume for append-only audit anchor hash chains (`/app/data/audit_anchors`).
   - `mongodata`, `qdrant_storage`, `rabbitmqdata`, `tempodata`, `prometheusdata`, `grafanadata`.
3. Secret material generated (minimum 48-char `SECRET_KEY`, strong passwords for databases, and 32-byte minimum `NOTARY_KEYS_JSON`).

## 3. Step-by-Step Deployment Procedure

### Step 1: Prepare Environment File
Copy `.env.example` to `.env` and populate strong, unique credentials:
```bash
cp .env.example .env
chmod 600 .env
```
Ensure that `ENVIRONMENT=production`, `DEBUG=false`, and default dev passwords are replaced.

### Step 2: Validate Configuration Settings
Run configuration validation using the python preflight:
```bash
python -c "from shared.config import get_settings; s = get_settings(); defects = s.validate_production_configuration(); exit(1) if defects else print('Config OK')"
```

### Step 3: Run Migration Preflight
Verify database connectivity and check migration head before launching application services:
```bash
python scripts/migration_preflight.py --check-only
```

### Step 4: Launch Core Services and Run Migrations
Start backing datastores and trigger the one-shot migration runner:
```bash
docker compose up -d postgres mongodb redis rabbitmq qdrant tempo otel-collector prometheus grafana
docker compose up --abort-on-container-exit migration
```
Verify that `mirage-migration` exited with code 0:
```bash
docker compose ps -a mirage-migration
```

### Step 5: Start Application Gateway and Workers
Start the edge gateway, Celery background worker, and React dashboard:
```bash
docker compose up -d gateway worker dashboard
```

## 4. Post-Deployment Verification
Check the readiness probe:
```bash
curl -f http://localhost:8000/v1/ready
```
Expected response: HTTP 200 `{"status": "ready", "degraded": false, "components": {...}}`.

Verify container security profiles:
```bash
docker inspect mirage-gateway --format '{{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}}'
```
Expected output: `true [ALL]`.
