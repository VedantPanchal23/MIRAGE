"""Distributed and Concurrency-Safe Circuit Breaker for MIRAGE 3.0 Model Execution.

Supports Redis-backed shared state across replicas with single half-open probe leases,
and provides an explicitly labeled, thread-safe local fallback if Redis is unavailable.
"""

import threading
import time
from enum import StrEnum
from typing import Any

from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("circuit_breaker")


class CircuitState(StrEnum):
    """Lifecycle states of the circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class ModelCircuitBreaker:
    """Manages failure tracking, trips, and single-probe half-open canary recovery."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 60.0,
        probe_lease_seconds: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.probe_lease_seconds = probe_lease_seconds
        self._lock = threading.Lock()

        # Local fallback in-memory state
        self._local_failures: dict[str, int] = {}
        self._local_opened_at: dict[str, float] = {}
        self._local_probe_leased_until: dict[str, float] = {}
        self._redis_client: Any = None
        self._redis_checked = False

    async def _get_redis(self) -> Any:
        """Lazily initialize Redis connection if available."""
        if not self._redis_checked:
            self._redis_checked = True
            settings = get_settings()
            if getattr(settings, "redis_url", None):
                try:
                    import redis.asyncio as aioredis

                    client = aioredis.from_url(settings.redis_url, decode_responses=True)
                    await client.ping()
                    self._redis_client = client
                    logger.info("Distributed circuit breaker initialized with shared Redis state")
                except Exception as exc:
                    logger.warning(
                        "Redis unavailable for distributed circuit breaker; using local best-effort state",
                        error=str(exc),
                    )
                    self._redis_client = None
        return self._redis_client

    def _breaker_key(self, provider: str, model_id: str) -> str:
        """Canonical key scoped per provider and model deployment."""
        return f"mirage:cb:{provider.lower()}:{model_id.lower()}"

    async def is_available(self, provider: str, model_id: str) -> tuple[bool, str]:
        """Check if the model is currently available for traffic or probe execution.

        Returns (is_available, state_str).
        If state is OPEN and recovery timeout has passed, attempts to acquire the single
        half-open probe lease. Only the single caller that acquires the lease returns True (state='HALF_OPEN').
        All concurrent callers are rejected (state='OPEN').
        """
        key = self._breaker_key(provider, model_id)
        redis = await self._get_redis()

        if redis is not None:
            try:
                state_val = await redis.get(f"{key}:state") or CircuitState.CLOSED.value
                if state_val == CircuitState.CLOSED.value:
                    return True, CircuitState.CLOSED.value

                opened_at_str = await redis.get(f"{key}:opened_at")
                now = time.time()
                opened_at = float(opened_at_str) if opened_at_str else now

                if (now - opened_at) >= self.recovery_timeout_seconds:
                    # Attempt to acquire single half-open probe lease atomically
                    lease_acquired = await redis.set(
                        f"{key}:probe_lease",
                        "1",
                        ex=int(self.probe_lease_seconds),
                        nx=True,
                    )
                    if lease_acquired:
                        await redis.set(f"{key}:state", CircuitState.HALF_OPEN.value)
                        logger.info("Acquired single half-open probe lease", key=key)
                        return True, CircuitState.HALF_OPEN.value
                    else:
                        # Another replica or concurrent request is currently probing
                        return False, CircuitState.OPEN.value

                return False, CircuitState.OPEN.value
            except Exception as exc:
                logger.warning("Redis failure in circuit breaker check; falling back to local state", error=str(exc))

        # Local best-effort in-memory implementation
        with self._lock:
            opened_at = self._local_opened_at.get(key)
            if opened_at is None:
                return True, CircuitState.CLOSED.value

            now = time.time()
            if (now - opened_at) >= self.recovery_timeout_seconds:
                # Check probe lease
                lease_until = self._local_probe_leased_until.get(key, 0.0)
                if now >= lease_until:
                    # Acquire lease
                    self._local_probe_leased_until[key] = now + self.probe_lease_seconds
                    logger.info("Acquired local half-open probe lease", key=key)
                    return True, CircuitState.HALF_OPEN.value
                else:
                    # Already leased
                    return False, CircuitState.OPEN.value

            return False, CircuitState.OPEN.value

    async def record_failure(self, provider: str, model_id: str) -> None:
        """Record upstream error; trips breaker when threshold is reached."""
        key = self._breaker_key(provider, model_id)
        redis = await self._get_redis()

        if redis is not None:
            try:
                state_val = await redis.get(f"{key}:state") or CircuitState.CLOSED.value
                now = time.time()

                if state_val == CircuitState.HALF_OPEN.value:
                    # Probe failed: immediately trip back to OPEN and release lease
                    await redis.set(f"{key}:state", CircuitState.OPEN.value)
                    await redis.set(f"{key}:opened_at", str(now))
                    await redis.delete(f"{key}:probe_lease")
                    logger.warning("Half-open canary probe failed; circuit tripped back to OPEN", key=key)
                    return

                new_count = await redis.incr(f"{key}:failures")
                if new_count >= self.failure_threshold:
                    await redis.set(f"{key}:state", CircuitState.OPEN.value)
                    await redis.set(f"{key}:opened_at", str(now))
                    logger.warning(
                        "Circuit breaker tripped to OPEN (distributed)",
                        key=key,
                        failure_count=new_count,
                    )
                return
            except Exception as exc:
                logger.warning("Redis failure recording circuit failure; using local", error=str(exc))

        with self._lock:
            now = time.time()
            opened_at = self._local_opened_at.get(key)
            if opened_at is not None:
                # In probe or open state, extend opened_at
                self._local_opened_at[key] = now
                self._local_probe_leased_until.pop(key, None)
                logger.warning("Probe failed; circuit reset to OPEN (local)", key=key)
                return

            count = self._local_failures.get(key, 0) + 1
            self._local_failures[key] = count
            if count >= self.failure_threshold:
                self._local_opened_at[key] = now
                logger.warning(
                    "Circuit breaker tripped to OPEN (local best-effort)",
                    key=key,
                    failure_count=count,
                )

    async def record_success(self, provider: str, model_id: str) -> None:
        """Record upstream success; resets failures and closes breaker."""
        key = self._breaker_key(provider, model_id)
        redis = await self._get_redis()

        if redis is not None:
            try:
                await redis.delete(f"{key}:failures", f"{key}:state", f"{key}:opened_at", f"{key}:probe_lease")
                return
            except Exception as exc:
                logger.warning("Redis failure resetting circuit breaker", error=str(exc))

        with self._lock:
            self._local_failures.pop(key, None)
            self._local_opened_at.pop(key, None)
            self._local_probe_leased_until.pop(key, None)


circuit_breaker_service = ModelCircuitBreaker()
