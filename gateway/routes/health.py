"""Component-level liveness and readiness check endpoints."""

import asyncio
import socket
import time
from typing import Any

from fastapi import APIRouter, Response, status

from db.mongo import default_mongo_trace_service
from db.redis import default_redis_client_manager
from db.session import check_database_connection
from gateway.middleware.circuit_breaker import get_all_circuit_statuses
from shared.config import get_settings

router = APIRouter(prefix="/v1", tags=["Health"])
start_time = time.time()
settings = get_settings()


def _check_tcp_port(host: str, port: int, timeout_sec: float = 1.0) -> bool:
    """Check whether a TCP socket connection succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


async def _check_qdrant_ready(host: str, port: int, timeout_sec: float = 1.0) -> bool:
    """Check Qdrant readiness via socket check to avoid blocking external HTTP libraries."""
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _check_tcp_port, host, port, timeout_sec)
    except Exception:
        return False


async def _check_rabbitmq_ready(host: str, port: int, timeout_sec: float = 1.0) -> bool:
    """Check RabbitMQ broker socket accessibility within timeout."""
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _check_tcp_port, host, port, timeout_sec)
    except Exception:
        return False


def _check_audit_anchor_writable() -> bool:
    """Verify that the external audit anchor storage directory is accessible and writable."""
    try:
        from services.audit_anchor import FileAuditAnchorBackend, get_anchor_backend

        backend = get_anchor_backend()
        if isinstance(backend, FileAuditAnchorBackend):
            target_dir = backend.anchor_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            probe_file = target_dir / ".probe_check"
            probe_file.write_text("ready", encoding="utf-8")
            probe_file.unlink(missing_ok=True)
        return True
    except Exception:
        return False


@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Lightweight liveness probe verifying that the FastAPI event loop is alive and responsive."""
    uptime_seconds = round(time.time() - start_time, 2)
    circuit_statuses = get_all_circuit_statuses()

    # Determine overall status based on circuit breakers
    is_degraded = any(c["state"] == "open" for c in circuit_statuses.values())
    status_str = "degraded" if is_degraded else "healthy"

    return {
        "status": status_str,
        "version": "2.1.0",
        "platform_version": "3.0.0",
        "environment": settings.environment.value,
        "uptime_seconds": uptime_seconds,
        "circuit_breakers": circuit_statuses,
        "circuits": circuit_statuses,
        "components": {
            "gateway": {"status": "healthy"},
            "postgres": {"status": "configured"},
            "redis": {"status": "configured"},
            "qdrant": {"status": "configured"},
            "rabbitmq": {"status": "configured"},
        },
    }


@router.get("/ready")
async def readiness_check(response: Response) -> dict[str, Any]:
    """Comprehensive readiness probe verifying all mandatory and degraded-capable backing stores.

    Mandatory backends (PostgreSQL, Redis, MongoDB, RabbitMQ, and in production, Audit Anchor storage)
    must be healthy.
    If mandatory backends are UP and Qdrant is DOWN, returns HTTP 200 (Degraded RAV-less mode).
    If any mandatory backend is DOWN, returns HTTP 503 (Unready).
    Zero credentials, internal URLs, or connection strings are exposed in the output.
    """
    uptime_seconds = round(time.time() - start_time, 2)

    # 1. Probe all backends concurrently
    loop = asyncio.get_running_loop()
    pg_task = asyncio.create_task(check_database_connection())
    redis_task = asyncio.create_task(default_redis_client_manager.ping())
    mongo_task = asyncio.create_task(default_mongo_trace_service.check_health())
    rabbit_task = asyncio.create_task(_check_rabbitmq_ready(settings.rabbitmq_host, settings.rabbitmq_port))
    qdrant_task = asyncio.create_task(_check_qdrant_ready(settings.qdrant_host, settings.qdrant_port))
    anchor_task = loop.run_in_executor(None, _check_audit_anchor_writable)

    pg_ok, redis_ok, mongo_res, rabbit_ok, qdrant_ok, anchor_ok = await asyncio.gather(
        pg_task, redis_task, mongo_task, rabbit_task, qdrant_task, anchor_task
    )
    mongo_ok = bool(mongo_res.get("status") == "pass")

    components: dict[str, str] = {
        "postgres": "up" if pg_ok else "down",
        "redis": "up" if redis_ok else "down",
        "mongodb": "up" if mongo_ok else "down",
        "rabbitmq": "up" if rabbit_ok else "down",
        "qdrant": "up" if qdrant_ok else "down",
        "audit_anchor": "up" if anchor_ok else "down",
    }

    is_prod = settings.environment.value == "production"
    mandatory_keys = ["postgres", "redis", "mongodb", "rabbitmq"]
    if is_prod:
        mandatory_keys.append("audit_anchor")

    mandatory_failures = [k for k in mandatory_keys if components.get(k) != "up"]
    degraded_failures = [
        k for k in ("qdrant", "audit_anchor") if components.get(k) != "up" and k not in mandatory_failures
    ]

    if mandatory_failures:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "unready",
            "degraded": False,
            "uptime_seconds": uptime_seconds,
            "failed_components": mandatory_failures,
            "components": components,
        }

    is_degraded = bool(degraded_failures)
    return {
        "status": "ready",
        "degraded": is_degraded,
        "degraded_components": degraded_failures if is_degraded else [],
        "uptime_seconds": uptime_seconds,
        "components": components,
    }
