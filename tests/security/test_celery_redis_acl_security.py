"""Security and ACL isolation tests for Celery Redis result backend per ADR 0003."""

from typing import Any

import pytest
import redis.asyncio as aioredis
from redis.exceptions import NoPermissionError

from db.redis import default_redis_client_manager
from shared.config import get_settings

settings = get_settings()


class TestCeleryRedisACLSecurity:
    """Validate strict least-privilege ACL boundary for mirage_celery on Redis DB 1."""

    @pytest.mark.asyncio
    async def test_celery_user_exact_commands_allowed_on_db1(self, live_redis_database: Any) -> None:
        """Verify mirage_celery can execute GET, SET, SETEX, EXPIRE, DEL, MGET on celery-task-meta keys in DB 1."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        # Connect as mirage_celery to DB 1
        client = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            username=settings.celery_redis_username,
            password=settings.celery_redis_password,
            db=1,
            decode_responses=True,
        )

        task_id = "test-task-uuid-001"
        key = f"celery-task-meta-{task_id}"

        try:
            # 1. SET / SETEX
            await client.set(key, '{"status": "SUCCESS", "result": 42}')
            await client.expire(key, 86400)

            # 2. GET
            val = await client.get(key)
            assert val is not None
            assert "SUCCESS" in val

            # 3. MGET
            m_vals = await client.mget([key])
            assert len(m_vals) == 1
            assert m_vals[0] == val

            # 4. DEL
            del_count = await client.delete(key)
            assert del_count == 1

            # 5. CLIENT & INFO
            info = await client.info("server")
            assert "redis_version" in info

        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_celery_user_denied_ratelimit_and_scs_on_db0(self, live_redis_database: Any) -> None:
        """Verify mirage_celery user is denied access to ratelimit:* and scs:* keys."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        client = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            username=settings.celery_redis_username,
            password=settings.celery_redis_password,
            db=0,
            decode_responses=True,
        )

        forbidden_keys = [
            "ratelimit:tenant_001:token_bucket",
            "scs:prompt_hash_1234",
            "config:tenant_001",
            "rav_embed:chunk_001",
        ]

        try:
            for key in forbidden_keys:
                with pytest.raises(NoPermissionError, match=r"(?i)(no permissions|has no permissions)"):
                    await client.set(key, "unauthorized")

                with pytest.raises(NoPermissionError, match=r"(?i)(no permissions|has no permissions)"):
                    await client.get(key)
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_app_user_denied_celery_keys_on_db1(self, live_redis_database: Any) -> None:
        """Verify standard application user mirage_app is strictly denied access to celery-task-meta keys."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        app_client = default_redis_client_manager.get_client()

        celery_keys = [
            "celery-task-meta-550e8400-e29b-41d4-a716-446655440000",
            "celery-chord-abc123",
        ]

        for key in celery_keys:
            with pytest.raises(NoPermissionError, match=r"(?i)(no permissions|has no permissions)"):
                await app_client.set(key, "unauthorized_payload")

            with pytest.raises(NoPermissionError, match=r"(?i)(no permissions|has no permissions)"):
                await app_client.get(key)

    @pytest.mark.asyncio
    async def test_administrative_commands_denied_for_celery_user(self, live_redis_database: Any) -> None:
        """Verify dangerous and administrative commands are denied to mirage_celery."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        client = aioredis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            username=settings.celery_redis_username,
            password=settings.celery_redis_password,
            db=1,
            decode_responses=True,
        )

        prohibited_commands = [
            ("FLUSHALL",),
            ("FLUSHDB",),
            ("SHUTDOWN",),
            ("CONFIG", "GET", "maxmemory"),
            ("KEYS", "*"),
            ("SAVE",),
        ]

        try:
            for cmd in prohibited_commands:
                with pytest.raises(NoPermissionError, match=r"(?i)(no permissions|has no permissions)"):
                    await client.execute_command(*cmd)
        finally:
            await client.aclose()
