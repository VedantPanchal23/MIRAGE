"""Component-level health check endpoint."""

import time
from typing import Any

from fastapi import APIRouter

from gateway.middleware.circuit_breaker import get_all_circuit_statuses
from shared.config import get_settings

router = APIRouter(prefix="/v1", tags=["Health"])
start_time = time.time()
settings = get_settings()


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Component-level health check endpoint returning dependency status and uptime."""
    uptime_seconds = round(time.time() - start_time, 2)
    circuit_statuses = get_all_circuit_statuses()

    # Determine overall status
    is_degraded = any(c["state"] == "open" for c in circuit_statuses.values())
    status_str = "degraded" if is_degraded else "healthy"

    return {
        "status": status_str,
        "version": "2.1.0",
        "environment": settings.environment.value,
        "uptime_seconds": uptime_seconds,
        "circuit_breakers": circuit_statuses,
        "components": {
            "gateway": {"status": "healthy"},
            "postgres": {"status": "configured", "host": settings.postgres_host},
            "redis": {"status": "configured", "host": settings.redis_host},
            "qdrant": {"status": "configured", "host": settings.qdrant_host},
            "rabbitmq": {"status": "configured", "host": settings.rabbitmq_host},
        },
    }
