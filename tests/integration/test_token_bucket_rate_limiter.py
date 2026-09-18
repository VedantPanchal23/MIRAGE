"""Integration and high-concurrency tests for Redis atomic token-bucket rate limiter.

Adheres to:
- Security_Access.md §1.3 (Threat T-06), §7.2, §9.1
- ADR 0002: Atomic Token Bucket with Redis Server Time
- Testing_Strategy.md §7 (Security & Concurrency Testing)
"""

import asyncio
import time
import uuid
from typing import Any

import pytest
import redis.asyncio as aioredis
from fastapi import HTTPException

from db.redis import (
    TokenBucketRateLimiter,
    default_redis_client_manager,
)
from gateway.middleware.rate_limiter import AsyncRateLimiter


@pytest.mark.integration
class TestTokenBucketRateLimiter:
    """Validate atomic token-bucket consumption, tier limits, refill rates, and concurrency."""

    @pytest.mark.asyncio
    async def test_initial_capacity_across_tiers(self, live_redis_database: Any) -> None:
        """Verify initial capacity and refill rates for Free (60), Pro (300), and Enterprise (1000)."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        limiter = TokenBucketRateLimiter()

        # Free tier: capacity 60
        tenant_free = f"tenant_cap_free_{uuid.uuid4().hex[:8]}"
        res_free = await limiter.consume(tenant_free, tier="free", cost=1)
        assert res_free.allowed is True
        assert res_free.limit == 60
        assert res_free.remaining == 59

        # Pro tier: capacity 300
        tenant_pro = f"tenant_cap_pro_{uuid.uuid4().hex[:8]}"
        res_pro = await limiter.consume(tenant_pro, tier="pro", cost=1)
        assert res_pro.allowed is True
        assert res_pro.limit == 300
        assert res_pro.remaining == 299

        # Enterprise tier: capacity 1000
        tenant_ent = f"tenant_cap_ent_{uuid.uuid4().hex[:8]}"
        res_ent = await limiter.consume(tenant_ent, tier="enterprise", cost=1)
        assert res_ent.allowed is True
        assert res_ent.limit == 1000
        assert res_ent.remaining == 999

    @pytest.mark.asyncio
    async def test_bucket_exhaustion_and_retry_after(self, live_redis_database: Any) -> None:
        """Verify that consuming all available tokens rejects further requests with positive retry_after."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        limiter = TokenBucketRateLimiter()
        tenant_id = f"tenant_exhaust_{uuid.uuid4().hex[:8]}"

        # Consume 60 tokens sequentially
        for i in range(60):
            res = await limiter.consume(tenant_id, tier="free", cost=1)
            assert res.allowed is True
            assert res.remaining == 59 - i

        # 61st request must be rejected
        res_rejected = await limiter.consume(tenant_id, tier="free", cost=1)
        assert res_rejected.allowed is False
        assert res_rejected.remaining == 0
        assert res_rejected.retry_after >= 1
        assert res_rejected.reset_time > int(time.time())

    @pytest.mark.asyncio
    async def test_refill_dynamics_over_time(self, live_redis_database: Any) -> None:
        """Verify tokens refill according to configured refill rate over real time."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        limiter = TokenBucketRateLimiter()
        tenant_id = f"tenant_refill_{uuid.uuid4().hex[:8]}"

        # Exhaust all 60 tokens
        for _ in range(60):
            await limiter.consume(tenant_id, tier="free", cost=1)

        res_exhausted = await limiter.consume(tenant_id, tier="free", cost=1)
        assert res_exhausted.allowed is False

        # Wait 2.1 seconds (Free tier refills 1.0 token/sec -> at least 2 tokens refilled)
        await asyncio.sleep(2.1)

        # Next request should succeed
        res_refilled = await limiter.consume(tenant_id, tier="free", cost=1)
        assert res_refilled.allowed is True
        assert res_refilled.remaining >= 1

    @pytest.mark.asyncio
    async def test_gateway_rate_limiter_middleware_headers(self, live_redis_database: Any) -> None:
        """Verify AsyncRateLimiter raises HTTP 429 with required specification headers upon exhaustion."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        middleware_limiter = AsyncRateLimiter()
        tenant_id = f"tenant_headers_{uuid.uuid4().hex[:8]}"

        # Exhaust free tier capacity
        for _ in range(60):
            await middleware_limiter.check_rate_limit(tenant_id, tier="free")

        # 61st call raises HTTPException(429) with all 4 mandatory headers
        with pytest.raises(HTTPException) as exc_info:
            await middleware_limiter.check_rate_limit(tenant_id, tier="free")

        exc = exc_info.value
        assert exc.status_code == 429
        assert "X-RateLimit-Limit" in exc.headers
        assert exc.headers["X-RateLimit-Limit"] == "60"
        assert "X-RateLimit-Remaining" in exc.headers
        assert exc.headers["X-RateLimit-Remaining"] == "0"
        assert "X-RateLimit-Reset" in exc.headers
        assert int(exc.headers["X-RateLimit-Reset"]) > 0
        assert "Retry-After" in exc.headers
        assert int(exc.headers["Retry-After"]) >= 1

    @pytest.mark.asyncio
    async def test_concurrent_consumption_zero_double_spending(self, live_redis_database: Any) -> None:
        """MANDATORY: 50 concurrent async workers across 3 client pools consume from capacity=10.

        Proves: successful_consumptions == 10 with zero double-spending caused by race conditions.
        """
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        # Create 3 independent Redis client connections simulating multiple gateway instances
        url = default_redis_client_manager.redis_url
        client1 = aioredis.from_url(url, decode_responses=True)
        client2 = aioredis.from_url(url, decode_responses=True)
        client3 = aioredis.from_url(url, decode_responses=True)
        clients = [client1, client2, client3]

        tenant_id = f"tenant_race_{uuid.uuid4().hex[:8]}"
        key = f"ratelimit:{tenant_id}:verify"

        # Pre-seed key with capacity=10 and refill_rate=0.0 to prevent refill during test
        from db.redis import TOKEN_BUCKET_LUA_SCRIPT

        sha = await client1.script_load(TOKEN_BUCKET_LUA_SCRIPT)
        # Execute once to initialize bucket with capacity 10
        await client1.evalsha(sha, 1, key, 10, 0.0, 1, 60)

        # 9 remaining tokens left. Launch 50 concurrent requests simultaneously across all 3 clients
        async def worker(worker_idx: int) -> int:
            cli = clients[worker_idx % len(clients)]
            res = await cli.evalsha(sha, 1, key, 10, 0.0, 1, 60)
            return int(res[0])

        results = await asyncio.gather(*(worker(i) for i in range(50)))
        successful_consumptions = sum(results)

        # 1 pre-seed consumption + 9 successful concurrent consumptions = exactly 10
        assert successful_consumptions == 9, (
            f"Expected exactly 9 additional concurrent successes, got {successful_consumptions}!"
        )

        # Verify remaining is exactly 0
        res_final = await client1.evalsha(sha, 1, key, 10, 0.0, 1, 60)
        assert res_final[0] == 0
        assert res_final[1] == 0

        for c in clients:
            await c.aclose()

    @pytest.mark.asyncio
    async def test_concurrent_multi_tenant_isolation(self, live_redis_database: Any) -> None:
        """Verify concurrent requests across distinct tenants do not interfere or contend."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        limiter = TokenBucketRateLimiter()
        tenant_a = f"tenant_iso_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"tenant_iso_b_{uuid.uuid4().hex[:8]}"

        # Launch 70 requests to Tenant A and 70 requests to Tenant B simultaneously
        async def request_task(tenant: str) -> bool:
            res = await limiter.consume(tenant, tier="free", cost=1)
            return res.allowed

        tasks_a = [request_task(tenant_a) for _ in range(70)]
        tasks_b = [request_task(tenant_b) for _ in range(70)]

        results = await asyncio.gather(*tasks_a, *tasks_b)
        results_a = results[:70]
        results_b = results[70:]

        # Both tenants have Free capacity of 60 -> exactly 60 successes each
        assert sum(results_a) == 60, f"Tenant A expected 60 successes, got {sum(results_a)}"
        assert sum(results_b) == 60, f"Tenant B expected 60 successes, got {sum(results_b)}"

    @pytest.mark.asyncio
    async def test_exact_exhaustion_boundary_condition(self, live_redis_database: Any) -> None:
        """Verify that when exactly 1 token remains, only 1 of N concurrent requests gets through."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        limiter = TokenBucketRateLimiter()
        tenant_id = f"tenant_one_left_{uuid.uuid4().hex[:8]}"

        # Consume 59 tokens leaving exactly 1 token
        for _ in range(59):
            await limiter.consume(tenant_id, tier="free", cost=1)

        # 10 concurrent requests arrive simultaneously
        tasks = [limiter.consume(tenant_id, tier="free", cost=1) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        allowed_count = sum(1 for r in results if r.allowed)
        rejected_count = sum(1 for r in results if not r.allowed)

        assert allowed_count == 1, f"Expected exactly 1 success for the last token, got {allowed_count}"
        assert rejected_count == 9, f"Expected 9 rejections, got {rejected_count}"
