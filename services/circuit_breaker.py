"""Distributed and Concurrency-Safe Circuit Breaker for MIRAGE 3.0 Model Execution.

Supports Redis-backed shared state across replicas with atomic single half-open probe leases via Lua scripts,
enforces explicit fail-closed semantics in production when Redis is unreachable,
and provides an observable, thread-safe degraded local fallback when explicitly allowed.
"""

import threading
import time
from enum import StrEnum
from typing import Any

from shared.config import get_settings
from shared.config.settings import EnvironmentType
from shared.logging import get_logger

logger = get_logger("circuit_breaker")


class CircuitState(StrEnum):
    """Lifecycle states of the circuit breaker."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerRedisError(Exception):
    """Raised when Redis fails while operating in strict fail-closed distributed mode."""

    pass


# Atomic Lua script for state inspection and single-probe lease acquisition
_LUA_CHECK_OR_LEASE = """
local state = redis.call('GET', KEYS[1])
if not state or state == 'CLOSED' then
    return {'CLOSED', 1}
end
local opened_at = tonumber(redis.call('GET', KEYS[2]) or '0')
local now = tonumber(ARGV[3])
if (now - opened_at) >= tonumber(ARGV[1]) then
    local acquired = redis.call('SET', KEYS[3], '1', 'EX', tonumber(ARGV[2]), 'NX')
    if acquired then
        redis.call('SET', KEYS[1], 'HALF_OPEN')
        return {'HALF_OPEN', 1}
    else
        return {'OPEN', 0}
    end
end
return {'OPEN', 0}
"""

# Atomic Lua script for recording failure and tripping to OPEN
_LUA_RECORD_FAILURE = """
local state = redis.call('GET', KEYS[1])
local now = ARGV[2]
if state == 'HALF_OPEN' then
    redis.call('SET', KEYS[1], 'OPEN')
    redis.call('SET', KEYS[2], now)
    redis.call('DEL', KEYS[3])
    return 'TRIPPED_BACK_TO_OPEN'
end
local count = redis.call('INCR', KEYS[4])
if tonumber(count) >= tonumber(ARGV[1]) then
    redis.call('SET', KEYS[1], 'OPEN')
    redis.call('SET', KEYS[2], now)
    return 'TRIPPED_TO_OPEN'
end
return 'FAILURE_RECORDED'
"""

# Atomic Lua script for closing breaker on probe/execution success
_LUA_RECORD_SUCCESS = """
redis.call('DEL', KEYS[1], KEYS[2], KEYS[3], KEYS[4])
return 'RESET_CLOSED'
"""


class ModelCircuitBreaker:
    """Manages failure tracking, trips, and single-probe half-open canary recovery."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 60.0,
        probe_lease_seconds: float = 30.0,
        fail_closed_on_redis_error: bool | None = None,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.probe_lease_seconds = probe_lease_seconds
        self.fail_closed_on_redis_error = fail_closed_on_redis_error
        self._lock = threading.Lock()

        # Local fallback in-memory state
        self._local_failures: dict[str, int] = {}
        self._local_opened_at: dict[str, float] = {}
        self._local_probe_leased_until: dict[str, float] = {}
        self._redis_client: Any = None
        self._redis_checked = False
        self._is_degraded = False

    @property
    def is_degraded(self) -> bool:
        """Returns True if the circuit breaker is operating in replica-local degraded mode."""
        return self._is_degraded

    def _should_fail_closed_on_redis(self) -> bool:
        """Evaluate whether Redis unavailability requires strict fail-closed protection."""
        if self.fail_closed_on_redis_error is not None:
            return self.fail_closed_on_redis_error
        settings = get_settings()
        if settings.environment == EnvironmentType.PRODUCTION:
            return True
        return getattr(settings, "circuit_breaker_fail_closed_on_redis", False)

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
                    self._is_degraded = False
                    logger.info("Distributed circuit breaker initialized with shared Redis state")
                except Exception as exc:
                    if self._should_fail_closed_on_redis():
                        logger.critical(
                            "Redis unavailable for distributed circuit breaker in fail-closed mode",
                            error=str(exc),
                        )
                    else:
                        self._is_degraded = True
                        logger.warning(
                            "CIRCUIT_BREAKER_DEGRADED_MODE: Redis unavailable; using local best-effort state",
                            extra={"degraded_mode": True, "error": str(exc)},
                        )
                    self._redis_client = None
        return self._redis_client

    def _breaker_key(self, provider: str, model_id: str) -> str:
        """Canonical key scoped per provider and model deployment."""
        return f"mirage:cb:{provider.strip().lower()}:{model_id.strip().lower()}"

    async def is_available(self, provider: str, model_id: str) -> tuple[bool, str]:
        """Check if the model is currently available for traffic or probe execution.

        Returns (is_available, state_str).
        Under distributed Redis, atomically checks state and acquires the single
        half-open probe lease via Lua script.
        If Redis is unreachable and fail-closed is active, returns (False, 'REDIS_OUTAGE_FAIL_CLOSED').
        """
        key = self._breaker_key(provider, model_id)
        redis = await self._get_redis()

        if redis is not None:
            try:
                res = await redis.eval(
                    _LUA_CHECK_OR_LEASE,
                    3,
                    f"{key}:state",
                    f"{key}:opened_at",
                    f"{key}:probe_lease",
                    str(self.recovery_timeout_seconds),
                    str(int(self.probe_lease_seconds)),
                    str(time.time()),
                )
                state_str = res[0]
                is_avail = bool(res[1])
                if state_str == CircuitState.HALF_OPEN.value and is_avail:
                    logger.info("Acquired single distributed half-open probe lease", key=key)
                elif state_str == CircuitState.OPEN.value and not is_avail:
                    logger.debug("Rejected concurrent probe during OPEN state", key=key)
                return is_avail, state_str
            except Exception as exc:
                if self._should_fail_closed_on_redis():
                    logger.critical(
                        "Circuit breaker Redis failure in fail-closed mode: rejecting model execution",
                        key=key,
                        error=str(exc),
                    )
                    return False, "REDIS_OUTAGE_FAIL_CLOSED"
                self._is_degraded = True
                logger.warning(
                    "CIRCUIT_BREAKER_DEGRADED_MODE: Redis failure during availability check; "
                    "falling back to local state",
                    extra={"degraded_mode": True, "error": str(exc)},
                )

        # Fallback path (only reached in non-fail-closed mode)
        if self._should_fail_closed_on_redis():
            return False, "REDIS_OUTAGE_FAIL_CLOSED"

        with self._lock:
            opened_at = self._local_opened_at.get(key)
            if opened_at is None:
                return True, CircuitState.CLOSED.value

            now = time.time()
            if (now - opened_at) >= self.recovery_timeout_seconds:
                lease_until = self._local_probe_leased_until.get(key, 0.0)
                if now >= lease_until:
                    self._local_probe_leased_until[key] = now + self.probe_lease_seconds
                    logger.info("Acquired local half-open probe lease", key=key)
                    return True, CircuitState.HALF_OPEN.value
                else:
                    return False, CircuitState.OPEN.value

            return False, CircuitState.OPEN.value

    async def record_failure(self, provider: str, model_id: str) -> None:
        """Record upstream error; trips breaker when threshold is reached."""
        key = self._breaker_key(provider, model_id)
        redis = await self._get_redis()

        if redis is not None:
            try:
                now_str = str(time.time())
                res = await redis.eval(
                    _LUA_RECORD_FAILURE,
                    4,
                    f"{key}:state",
                    f"{key}:opened_at",
                    f"{key}:probe_lease",
                    f"{key}:failures",
                    str(self.failure_threshold),
                    now_str,
                )
                if res in ("TRIPPED_TO_OPEN", "TRIPPED_BACK_TO_OPEN"):
                    logger.warning(
                        "Circuit breaker tripped to OPEN (distributed)",
                        key=key,
                        reason=res,
                    )
                return
            except Exception as exc:
                if self._should_fail_closed_on_redis():
                    logger.critical(
                        "Circuit breaker Redis failure in fail-closed mode while recording failure",
                        key=key,
                        error=str(exc),
                    )
                    raise CircuitBreakerRedisError(f"Redis unavailable to record failure in production: {exc}") from exc
                self._is_degraded = True
                logger.warning(
                    "CIRCUIT_BREAKER_DEGRADED_MODE: Redis failure recording circuit failure; using local",
                    extra={"degraded_mode": True, "error": str(exc)},
                )

        if self._should_fail_closed_on_redis():
            raise CircuitBreakerRedisError("Redis unavailable to record failure in fail-closed mode")

        with self._lock:
            now = time.time()
            opened_at = self._local_opened_at.get(key)
            if opened_at is not None:
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
                await redis.eval(
                    _LUA_RECORD_SUCCESS,
                    4,
                    f"{key}:state",
                    f"{key}:opened_at",
                    f"{key}:probe_lease",
                    f"{key}:failures",
                )
                logger.info("Circuit breaker reset to CLOSED (distributed)", key=key)
                return
            except Exception as exc:
                if self._should_fail_closed_on_redis():
                    logger.critical(
                        "Circuit breaker Redis failure in fail-closed mode while recording success",
                        key=key,
                        error=str(exc),
                    )
                    raise CircuitBreakerRedisError(f"Redis unavailable to record success in production: {exc}") from exc
                self._is_degraded = True
                logger.warning(
                    "CIRCUIT_BREAKER_DEGRADED_MODE: Redis failure resetting circuit breaker; using local",
                    extra={"degraded_mode": True, "error": str(exc)},
                )

        if self._should_fail_closed_on_redis():
            raise CircuitBreakerRedisError("Redis unavailable to record success in fail-closed mode")

        with self._lock:
            self._local_failures.pop(key, None)
            self._local_opened_at.pop(key, None)
            self._local_probe_leased_until.pop(key, None)
            logger.info("Circuit breaker reset to CLOSED (local)", key=key)


circuit_breaker_service = ModelCircuitBreaker()
