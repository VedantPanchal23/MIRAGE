"""Integration tests for Redis distributed caching.

Adheres to:
- PRD.md §FR-SCS-04, §14
- Technical_Architecture.md §7.4, §8.3, §8.4
- Security_Access.md §1.3 (Threat T-05c), §9.1
"""

import uuid
from typing import Any
from unittest.mock import patch

import pytest

from db.redis import RedisCacheService, default_redis_client_manager


@pytest.mark.integration
class TestRedisDistributedCache:
    """Validate Redis distributed SCS caching, TTLs, tenant isolation, and bypass semantics."""

    @pytest.mark.asyncio
    async def test_scs_cache_set_get_roundtrip(self, live_redis_database: Any) -> None:
        """Verify setting SCS evaluation results and reading them back with high fidelity."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        cache_service = RedisCacheService()
        tenant_id = f"tenant_cache_{uuid.uuid4().hex[:8]}"
        model_id = "llama-3.1-70b-versatile"
        prompt = "What is the speed of light in a vacuum?"
        score = 0.0425
        sample_count = 5
        clusters = [
            ["299,792,458 m/s", "Approximately 300,000 km/s"],
            ["Fastest speed in the universe"],
        ]

        # 1. Initial lookup is a miss
        cached_data, is_hit = await cache_service.get_scs(tenant_id, model_id, prompt)
        assert is_hit is False
        assert cached_data is None

        # 2. Store SCS results
        success = await cache_service.set_scs(
            tenant_id=tenant_id,
            model_id=model_id,
            prompt=prompt,
            score=score,
            sample_count=sample_count,
            clusters=clusters,
            ttl=3600,
        )
        assert success is True

        # 3. Second lookup is a hit with matching data
        cached_data, is_hit = await cache_service.get_scs(tenant_id, model_id, prompt)
        assert is_hit is True
        assert cached_data is not None
        assert cached_data["score"] == score
        assert cached_data["tenant_id"] == tenant_id
        assert cached_data["model_id"] == model_id
        assert cached_data["sample_count"] == sample_count
        assert len(cached_data["clusters"]) == 2

    @pytest.mark.asyncio
    async def test_scs_cache_ttl_and_expiration(self, live_redis_database: Any) -> None:
        """Verify that SCS cache entries are assigned the governing 1-hour (3600s) TTL."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        cache_service = RedisCacheService()
        tenant_id = f"tenant_ttl_{uuid.uuid4().hex[:8]}"
        model_id = "test-model"
        prompt = "Explain quantum entanglement in one sentence."

        await cache_service.set_scs(
            tenant_id=tenant_id,
            model_id=model_id,
            prompt=prompt,
            score=0.15,
            sample_count=5,
            clusters=[["entangled"]],
            ttl=3600,
        )

        client = default_redis_client_manager.get_client()
        key = cache_service.get_scs_cache_key(tenant_id, model_id, prompt)
        ttl = await client.ttl(key)

        # TTL must be active and <= 3600s
        assert 3500 <= ttl <= 3600, f"Expected TTL near 3600s, got {ttl}s"

    @pytest.mark.asyncio
    async def test_scs_cache_tenant_isolation(self, live_redis_database: Any) -> None:
        """Verify Tenant A's cached SCS result cannot be accessed by Tenant B on the identical prompt."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        cache_service = RedisCacheService()
        tenant_a = f"tenant_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:8]}"
        model_id = "shared-model"
        shared_prompt = "What is the capital of France?"

        # Tenant A populates cache
        await cache_service.set_scs(
            tenant_id=tenant_a,
            model_id=model_id,
            prompt=shared_prompt,
            score=0.01,
            sample_count=5,
            clusters=[["Paris"]],
        )

        # Tenant A gets cache hit
        data_a, hit_a = await cache_service.get_scs(tenant_a, model_id, shared_prompt)
        assert hit_a is True
        assert data_a is not None

        # Tenant B querying identical prompt/model must observe a MISS
        data_b, hit_b = await cache_service.get_scs(tenant_b, model_id, shared_prompt)
        assert hit_b is False
        assert data_b is None

    @pytest.mark.asyncio
    async def test_scs_cache_model_isolation(self, live_redis_database: Any) -> None:
        """Verify different models for the same tenant do not collide in cache."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        cache_service = RedisCacheService()
        tenant_id = f"tenant_model_{uuid.uuid4().hex[:8]}"
        prompt = "What is the capital of France?"

        await cache_service.set_scs(
            tenant_id=tenant_id,
            model_id="gpt-4o",
            prompt=prompt,
            score=0.02,
            sample_count=5,
            clusters=[["Paris"]],
        )

        # Query with llama-3.1-70b should miss
        data, hit = await cache_service.get_scs(tenant_id, "llama-3.1-70b", prompt)
        assert hit is False
        assert data is None

    @pytest.mark.asyncio
    async def test_malicious_tenant_id_namespace_injection(self) -> None:
        """Verify malicious tenant IDs with path traversal or glob characters are strictly rejected."""
        cache_service = RedisCacheService()

        malicious_tenants = [
            "tenant:with:colons",
            "tenant*with*globs",
            "tenant\r\nwith_newlines",
            "../traversal",
            "",
            "a" * 65,  # Exceeds max length of 64
        ]

        for mal_tenant in malicious_tenants:
            with pytest.raises(ValueError, match=r"(?i)(invalid tenant id|non-empty string)"):
                cache_service.get_scs_cache_key(mal_tenant, "model", "prompt")

    @pytest.mark.asyncio
    async def test_cache_circuit_breaker_bypass_on_failure(self) -> None:
        """Verify that when Redis is unreachable, cache get gracefully falls back to Cache-Bypass Mode."""
        cache_service = RedisCacheService()
        tenant_id = f"tenant_cb_{uuid.uuid4().hex[:8]}"

        with patch.object(
            default_redis_client_manager,
            "get_client",
            side_effect=ConnectionRefusedError("Redis down"),
        ):
            # Must NOT raise exception; must return (None, False) for Cache-Bypass Mode
            data, is_hit = await cache_service.get_scs(tenant_id, "model", "prompt")
            assert is_hit is False
            assert data is None
