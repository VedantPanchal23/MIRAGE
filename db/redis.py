"""Redis distributed caching and atomic token-bucket rate limiting service.

Adheres to:
- PRD.md §FR-SCS-04, §14
- Technical_Architecture.md §7.4, §8.3, §8.4, §9.1
- Security_Access.md §1.3 (Threats T-05c, T-06), §7.2, §9.1
- Testing_Strategy.md §7, §9
- ADR 0002: Atomic Token Bucket with Redis Server Time
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnError
from redis.exceptions import NoPermissionError, RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from gateway.middleware.circuit_breaker import call_async_with_circuit, redis_circuit
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.telemetry.metrics import SCS_CACHE_HITS_TOTAL, SCS_CACHE_MISSES_TOTAL

logger = get_logger("redis_service")
settings = get_settings()

TENANT_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")

# ------------------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------------------


class RedisServiceError(RuntimeError):
    """Base exception for Redis infrastructure and coordination failures."""

    pass


class RedisConnectionError(RedisServiceError):
    """Raised when Redis host/port is unreachable or connection reset."""

    pass


class RedisOperationTimeoutError(RedisServiceError):
    """Raised when a Redis command exceeds configured socket timeout."""

    pass


class RateLimitExceededError(RedisServiceError):
    """Raised when tenant exceeds tier token bucket capacity."""

    def __init__(
        self,
        tenant_id: str,
        tier: str,
        limit: int,
        remaining: int,
        retry_after: int,
        reset_time: int,
    ) -> None:
        msg = f"Rate limit exceeded for tenant '{tenant_id}' on '{tier}' tier. Max {limit} req/min allowed."
        super().__init__(msg)
        self.tenant_id = tenant_id
        self.tier = tier
        self.limit = limit
        self.remaining = remaining
        self.retry_after = retry_after
        self.reset_time = reset_time


# ------------------------------------------------------------------------------
# Connection & Client Manager
# ------------------------------------------------------------------------------


class RedisClientManager:
    """Manages bounded connection pools and lifecycle for redis.asyncio clients."""

    def __init__(
        self,
        redis_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        max_connections: int | None = None,
        socket_timeout: float | None = None,
        socket_connect_timeout: float | None = None,
    ) -> None:
        self.redis_url = redis_url or settings.redis_url
        self.username = username if username is not None else settings.redis_username
        self.password = password if password is not None else settings.redis_password
        self.max_connections = max_connections or settings.redis_max_connections
        self.socket_timeout = socket_timeout or settings.redis_socket_timeout
        self.socket_connect_timeout = socket_connect_timeout or settings.redis_socket_connect_timeout
        self._pool: aioredis.ConnectionPool[Any] | None = None
        self._client: aioredis.Redis[Any] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_connection_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "max_connections": self.max_connections,
            "timeout": 5.0,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
            "decode_responses": True,
        }
        if self.username:
            kwargs["username"] = self.username
        if self.password:
            kwargs["password"] = self.password
        return kwargs

    def get_pool(self) -> aioredis.ConnectionPool[Any]:
        """Return or lazily initialize the connection pool bound to current event loop."""
        current_loop: asyncio.AbstractEventLoop | None = None
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        need_new_pool = self._pool is None or (
            self._loop is not None
            and (self._loop.is_closed() or (current_loop is not None and self._loop != current_loop))
        )

        if need_new_pool:
            self._loop = current_loop
            self._pool = aioredis.BlockingConnectionPool.from_url(
                self.redis_url,
                **self._get_connection_kwargs(),
            )
            self._client = None
        assert self._pool is not None
        return self._pool

    def get_client(self) -> aioredis.Redis[Any]:
        """Return an async Redis client instance bound to current event loop."""
        pool = self.get_pool()
        if self._client is None:
            self._client = aioredis.Redis(connection_pool=pool)
        return self._client

    async def ping(self) -> bool:
        """Check live Redis connectivity via PING command."""
        try:
            client = self.get_client()
            res = await client.ping()
            return bool(res)
        except Exception as exc:
            logger.warning("Redis ping check failed", error=str(exc))
            return False

    async def close(self) -> None:
        """Gracefully close active Redis client connections and disconnect pool."""
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
        if self._pool is not None:
            try:
                await self._pool.disconnect()
            except Exception:
                pass
            self._pool = None
        self._loop = None

    def reset(
        self,
        redis_url: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        """Rebind client manager to a new Redis instance (used by test fixtures)."""
        self.redis_url = redis_url
        if username is not None:
            self.username = username
        if password is not None:
            self.password = password
        self._pool = None
        self._client = None
        self._loop = None


default_redis_client_manager = RedisClientManager()


def reset_default_redis_client(
    url: str,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Convenience helper to reset the global default client manager for tests."""
    default_redis_client_manager.reset(url, username=username, password=password)


# ------------------------------------------------------------------------------
# Token Bucket Rate Limiter (ADR 0002)
# ------------------------------------------------------------------------------

# Atomic Token Bucket Lua script querying authoritative Redis server TIME
TOKEN_BUCKET_LUA_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

-- 1. Retrieve authoritative microsecond timestamp from Redis server clock
local t = redis.call('TIME')
local now = tonumber(t[1]) + (tonumber(t[2]) / 1000000.0)

-- 2. Fetch current token balance and timestamp
local data = redis.call('HMGET', key, 'tokens', 'last_updated')
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if tokens == nil or last_updated == nil then
    tokens = capacity
    last_updated = now
else
    local delta = math.max(0.0, now - last_updated)
    tokens = math.min(capacity, tokens + (delta * refill_rate))
    last_updated = now
end

local allowed = 0
local retry_after = 0

if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
else
    local missing = requested - tokens
    retry_after = math.ceil(missing / refill_rate)
end

-- 3. Atomically persist updated state and set expiration
redis.call('HMSET', key, 'tokens', tostring(tokens), 'last_updated', tostring(last_updated))
redis.call('EXPIRE', key, ttl)

local remaining = math.max(0, math.floor(tokens))
local reset_seconds = math.ceil((capacity - tokens) / refill_rate)
local reset_time = math.ceil(now + reset_seconds)

return {allowed, remaining, retry_after, reset_time}
"""


@dataclass(frozen=True)
class TokenBucketResult:
    """Result of an atomic token bucket consumption evaluation."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_time: int


class TokenBucketRateLimiter:
    """Distributed token-bucket rate limiter with atomic Lua execution and Redis server-time synchronization."""

    TIER_LIMITS: dict[str, tuple[int, float]] = {
        # tier: (capacity, refill_tokens_per_second)
        "free": (60, 1.0),  # 60 req / 60s
        "pro": (300, 5.0),  # 300 req / 60s
        "enterprise": (1000, 16.6667),  # 1000 req / 60s
    }

    def __init__(self, client_manager: RedisClientManager | None = None) -> None:
        self.client_manager = client_manager or default_redis_client_manager
        self._script_sha: str | None = None

    def _validate_tenant_id(self, tenant_id: str) -> None:
        if not tenant_id or not isinstance(tenant_id, str):
            raise ValueError("Tenant ID must be a non-empty string")
        if len(tenant_id) > 64 or not TENANT_ID_REGEX.match(tenant_id):
            raise ValueError(f"Invalid tenant ID '{tenant_id}': Must match ^[a-zA-Z0-9_-]+$ and length <= 64")

    def get_rate_limit_key(self, tenant_id: str, scope: str = "verify") -> str:
        """Construct namespaced rate limit key."""
        self._validate_tenant_id(tenant_id)
        return f"ratelimit:{tenant_id}:{scope}"

    async def _eval_token_bucket(
        self,
        key: str,
        capacity: int,
        refill_rate: float,
        requested: int,
        ttl: int,
    ) -> list[int]:
        client = self.client_manager.get_client()
        try:
            if self._script_sha is None:
                self._script_sha = await client.script_load(TOKEN_BUCKET_LUA_SCRIPT)  # type: ignore[no-untyped-call]
            try:
                raw_res = await client.evalsha(  # type: ignore[no-untyped-call]
                    self._script_sha,
                    1,
                    key,
                    capacity,
                    refill_rate,
                    requested,
                    ttl,
                )
            except RedisError as script_err:
                if "NOSCRIPT" in str(script_err):
                    self._script_sha = await client.script_load(TOKEN_BUCKET_LUA_SCRIPT)  # type: ignore[no-untyped-call]
                    raw_res = await client.evalsha(  # type: ignore[no-untyped-call]
                        self._script_sha,
                        1,
                        key,
                        capacity,
                        refill_rate,
                        requested,
                        ttl,
                    )
                else:
                    raise
            return [int(v) for v in raw_res]
        except (RedisConnError, ConnectionRefusedError) as conn_err:
            logger.error("Redis connection failure during rate limit check", key=key, error=str(conn_err))
            raise RedisConnectionError(f"Redis rate limiter connection failed: {conn_err}") from conn_err
        except RedisTimeoutError as time_err:
            logger.error("Redis timeout during rate limit check", key=key, error=str(time_err))
            raise RedisOperationTimeoutError(f"Redis rate limiter timed out: {time_err}") from time_err
        except NoPermissionError as perm_err:
            logger.critical("Redis ACL permission denied during rate limit check", key=key, error=str(perm_err))
            raise RedisServiceError(f"Redis rate limiter ACL violation: {perm_err}") from perm_err
        except Exception as exc:
            logger.error("Redis unexpected error during rate limit check", key=key, error=str(exc))
            raise RedisServiceError(f"Redis rate limiter failed: {exc}") from exc

    async def consume(
        self,
        tenant_id: str,
        tier: str = "free",
        cost: int = 1,
        scope: str = "verify",
    ) -> TokenBucketResult:
        """Atomically consume tokens for the authenticated tenant."""
        self._validate_tenant_id(tenant_id)
        tier_clean = tier.lower() if tier else "free"
        capacity, refill_rate = self.TIER_LIMITS.get(tier_clean, self.TIER_LIMITS["free"])

        key = self.get_rate_limit_key(tenant_id, scope=scope)
        ttl = max(120, math.ceil(capacity / refill_rate) + 60)

        res = await self._eval_token_bucket(
            key=key,
            capacity=capacity,
            refill_rate=refill_rate,
            requested=cost,
            ttl=ttl,
        )

        allowed = bool(res[0] == 1)
        remaining = res[1]
        retry_after = res[2]
        reset_time = res[3]

        return TokenBucketResult(
            allowed=allowed,
            limit=capacity,
            remaining=remaining,
            retry_after=retry_after,
            reset_time=reset_time,
        )

    async def check_rate_limit(
        self,
        tenant_id: str,
        tier: str = "free",
        cost: int = 1,
        scope: str = "verify",
    ) -> TokenBucketResult:
        """Check rate limit and raise RateLimitExceededError if capacity exhausted."""
        res = await self.consume(tenant_id, tier=tier, cost=cost, scope=scope)
        if not res.allowed:
            logger.warning(
                "Rate limit exceeded for tenant",
                tenant_id=tenant_id,
                tier=tier,
                limit=res.limit,
                retry_after=res.retry_after,
            )
            raise RateLimitExceededError(
                tenant_id=tenant_id,
                tier=tier,
                limit=res.limit,
                remaining=res.remaining,
                retry_after=res.retry_after,
                reset_time=res.reset_time,
            )
        return res


# ------------------------------------------------------------------------------
# Distributed SCS Cache Service
# ------------------------------------------------------------------------------


class RedisCacheService:
    """Distributed cache for Self-Consistency Sampling (SCS) and model variance states."""

    def __init__(self, client_manager: RedisClientManager | None = None) -> None:
        self.client_manager = client_manager or default_redis_client_manager

    def _validate_tenant_id(self, tenant_id: str) -> None:
        if not tenant_id or not isinstance(tenant_id, str):
            raise ValueError("Tenant ID must be a non-empty string")
        if len(tenant_id) > 64 or not TENANT_ID_REGEX.match(tenant_id):
            raise ValueError(f"Invalid tenant ID '{tenant_id}': Must match ^[a-zA-Z0-9_-]+$ and length <= 64")

    def get_scs_cache_key(self, tenant_id: str, model_id: str, prompt: str) -> str:
        """Generate deterministic cache key: scs:{sha256(prompt:model_id:tenant_id)}."""
        self._validate_tenant_id(tenant_id)
        raw = f"{prompt}:{model_id}:{tenant_id}"
        return f"scs:{compute_sha256(raw)}"

    async def get_scs(
        self,
        tenant_id: str,
        model_id: str,
        prompt: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Retrieve cached SCS evaluation.

        Returns (cached_payload, is_hit).
        If Redis is unreachable or circuit is OPEN, fails open to Cache-Bypass Mode (returns None, False).
        """
        cache_key = self.get_scs_cache_key(tenant_id, model_id, prompt)

        async def _do_get() -> str | None:
            client = self.client_manager.get_client()
            res = await client.get(cache_key)
            return str(res) if res is not None else None

        try:
            cached_val = await call_async_with_circuit(redis_circuit, _do_get)
            if cached_val is not None:
                SCS_CACHE_HITS_TOTAL.labels(tenant_id=tenant_id).inc()
                logger.debug("SCS cache hit", cache_key=cache_key, tenant_id=tenant_id)
                data = json.loads(cached_val)
                return data, True

            SCS_CACHE_MISSES_TOTAL.labels(tenant_id=tenant_id).inc()
            return None, False
        except Exception as exc:
            # Cache-Bypass Mode (Technical_Architecture.md §8.4)
            SCS_CACHE_MISSES_TOTAL.labels(tenant_id=tenant_id).inc()
            logger.warning(
                "SCS cache lookup failed or circuit open; falling back to Cache-Bypass Mode",
                cache_key=cache_key,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return None, False

    async def set_scs(
        self,
        tenant_id: str,
        model_id: str,
        prompt: str,
        score: float,
        sample_count: int,
        clusters: list[list[str]],
        ttl: int = 3600,  # PRD FR-SCS-04: TTL 1 hour
    ) -> bool:
        """Store SCS evaluation results with 1-hour TTL. Non-fatal on Redis failure."""
        cache_key = self.get_scs_cache_key(tenant_id, model_id, prompt)
        payload = {
            "score": score,
            "tenant_id": tenant_id,
            "model_id": model_id,
            "sample_count": sample_count,
            "clusters": clusters,
            "cached_at": datetime.now(UTC).isoformat(),
        }
        json_data = json.dumps(payload)

        async def _do_set() -> bool:
            client = self.client_manager.get_client()
            await client.set(cache_key, json_data, ex=ttl)
            return True

        try:
            await call_async_with_circuit(redis_circuit, _do_set)
            logger.debug("SCS cache write succeeded", cache_key=cache_key, tenant_id=tenant_id)
            return True
        except Exception as exc:
            logger.warning(
                "SCS cache write failed; proceeding without caching",
                cache_key=cache_key,
                tenant_id=tenant_id,
                error=str(exc),
            )
            return False

    async def check_health(self) -> dict[str, Any]:
        """Report live Redis component health status."""
        is_alive = await self.client_manager.ping()
        circuit_state = redis_circuit.current_state
        return {
            "status": "healthy" if is_alive else "degraded",
            "alive": is_alive,
            "circuit_breaker": circuit_state,
            "host": settings.redis_host,
            "port": settings.redis_port,
        }


default_redis_cache_service = RedisCacheService()
default_token_bucket_rate_limiter = TokenBucketRateLimiter()
