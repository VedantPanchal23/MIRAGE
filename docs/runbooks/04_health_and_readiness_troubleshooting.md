# Runbook 04: Health and Readiness Troubleshooting

## 1. Overview and Probe Distinction
MIRAGE separates liveness from readiness to avoid cascading container restarts:
- **Liveness Probe (`GET /v1/health`):** Verifies that the FastAPI process and event loop are alive. Does not fail if backing datastores are temporarily degraded.
- **Readiness Probe (`GET /v1/ready`):** Verifies that the instance can safely process incoming AI transactions. Probes PostgreSQL, Redis, MongoDB, RabbitMQ, Qdrant, and Audit Anchor storage concurrently.

## 2. Readiness Probe Status Codes and Failure Modes

### HTTP 200 (Ready)
All mandatory and degraded-capable backends are healthy:
```json
{
  "status": "ready",
  "degraded": false,
  "degraded_components": [],
  "uptime_seconds": 1245.2,
  "components": {
    "postgres": "up",
    "redis": "up",
    "mongodb": "up",
    "rabbitmq": "up",
    "qdrant": "up",
    "audit_anchor": "up"
  }
}
```

### HTTP 200 with degraded=true (Degraded RAV-less Mode)
When Qdrant (vector database) is unavailable, MIRAGE falls back to degraded mode:
- Retrieval-Augmented Verification (RAV) is bypassed or falls back to lexical/exact search.
- Gates 1, 3, 4 (NLI/ICS), and 5 remain fully functional.
- Incident response: Inspect `mirage-qdrant` container logs and storage mount.

### HTTP 503 (Service Unavailable / Unready)
Triggered when any mandatory backend fails:
- `postgres`: Control-plane, RLS identity resolution, or transaction logging inaccessible.
- `redis`: Distributed rate limiter or circuit breaker lock broker inaccessible.
- `mongodb`: Execution span and trace recorder unavailable.
- `rabbitmq`: Asynchronous Celery verification worker queue broker unreachable.
- `audit_anchor`: External anchor volume unmounted or filesystem read-only in production.

## 3. Triage Procedures for Failed Components

### PostgreSQL DOWN:
1. Verify database process status: `docker compose ps postgres`
2. Test network connectivity: `docker compose exec gateway pg_isready -h postgres -p 5432`
3. Inspect PostgreSQL logs: `docker compose logs --tail=100 postgres`

### Audit Anchor DOWN:
1. Check if the `/app/data/audit_anchors` directory exists and is writable:
```bash
docker compose exec gateway test -w /app/data/audit_anchors && echo "Writable" || echo "Read-only or missing"
```
2. Verify volume mount in `docker-compose.yml`:
Ensure `audit_anchors:/app/data/audit_anchors` is mounted.

### Zero Credential Leakage Guarantee:
Readiness probes strictly output status strings (`"up"` or `"down"`). Passwords, hostnames, usernames, or connection URLs are never emitted in probe output.
