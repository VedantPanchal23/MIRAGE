# Runbook 11: Failed Deployment Recovery

## 1. Overview and Incident Classification
A deployment failure can occur due to:
1. Migration failure or divergence.
2. Missing secret configuration or validation failure on container boot.
3. Persistent volume mount failure (e.g. read-only audit anchor storage).
4. Container crashloops / OOM kills due to insufficient memory limits.

## 2. Emergency Triage Checklist

### Step 1: Inspect Container Lifecycle States
```bash
docker compose ps -a
```
Identify containers in `Restarting`, `Exit 1`, or `unhealthy` states.

### Step 2: Read Container Logs
Check the gateway or failing container output:
```bash
docker compose logs --tail=100 gateway
```
Look for specific error signatures:
- `ValueError: Production security policy violation: CELERY_BROKER_URL must use AMQPS`
  -> Update `.env` with `amqps://` broker URL.
- `PermissionError: [Errno 30] Read-only file system: 'data/audit_anchors'`
  -> Ensure `audit_anchors` volume is declared and mounted to `/app/data/audit_anchors`.
- `ModuleNotFoundError` or migration error -> Check migration preflight.

## 3. Rollback Procedure (Forward-Repair vs Rollback)

### Decision Tree:
- **Case 1: Schema migration has NOT been run:**
  Roll back image tags in `docker-compose.yml` to the previous stable release commit. Restart services.
- **Case 2: Schema migration ran, but application failed boot:**
  Fix configuration or secret values without rolling back schema if the schema is backward-compatible.
- **Case 3: Schema migration failed mid-way:**
  Run `python scripts/migration_preflight.py` to identify current database revision.
  Fix the underlying DDL error and re-run `alembic upgrade head`.
  Never manually delete rows from `alembic_version` without verifying table structure.

## 4. Post-Recovery Verification
Verify all 13 services are healthy:
```bash
pytest tests/integration/test_compose_topology.py
```
And verify system readiness:
```bash
curl -f http://localhost:8000/v1/ready
```
