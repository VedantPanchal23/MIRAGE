"""Security and least-privilege access tests for Redis 7 infrastructure.

Adheres to:
- Security_Access.md §1.3, §9.1
- Development_Workflow.md §13 (Security Gates)
"""

import ast
import inspect
from typing import Any

import pytest
import redis.asyncio as aioredis
from redis.exceptions import AuthenticationError, NoPermissionError

import gateway.middleware.rate_limiter as rate_limiter_module
from db.redis import default_redis_client_manager
from shared.config import get_settings

settings = get_settings()


@pytest.mark.security
class TestRedisSecurity:
    """Validate Redis authentication, ACL command restrictions, keyspace boundaries, and codebase AST invariants."""

    @pytest.mark.asyncio
    async def test_invalid_credentials_rejected(self, live_redis_database: Any) -> None:
        """Verify connecting with invalid password or bad username raises AuthenticationError."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        host = live_redis_database.get_container_host_ip()
        port = int(live_redis_database.get_exposed_port(6379))
        bad_client = aioredis.Redis(
            host=host,
            port=port,
            username="mirage_app",
            password="wrong_password_12345",
        )

        with pytest.raises(AuthenticationError):
            await bad_client.ping()

        await bad_client.aclose()

    @pytest.mark.asyncio
    async def test_application_identity_allowed_commands(self, live_redis_database: Any) -> None:
        """Verify the configured mirage_app ACL identity can execute required commands."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        client = default_redis_client_manager.get_client()

        # 1. PING
        assert await client.ping() is True

        # 2. Key write in permitted keyspace
        key = "scs:security_test_key"
        await client.set(key, "valid_data", ex=60)

        # 3. Key read in permitted keyspace
        val = await client.get(key)
        assert val == "valid_data"

        # 4. Key delete in permitted keyspace
        await client.delete(key)

    @pytest.mark.asyncio
    async def test_administrative_commands_prohibited_for_app_user(self, live_redis_database: Any) -> None:
        """Verify mirage_app identity cannot execute prohibited administrative commands."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        client = default_redis_client_manager.get_client()

        # Commands prohibited under -@admin -@dangerous
        prohibited_commands = [
            ("FLUSHALL",),
            ("FLUSHDB",),
            ("SHUTDOWN", "NOSAVE"),
            ("CONFIG", "GET", "maxmemory"),
            ("ACL", "LIST"),
            ("SAVE",),
        ]

        for cmd in prohibited_commands:
            with pytest.raises(NoPermissionError, match=r"(?i)(no permissions|has no permissions)"):
                await client.execute_command(*cmd)

    @pytest.mark.asyncio
    async def test_keyspace_boundary_denies_celery_and_unrelated_keys(self, live_redis_database: Any) -> None:
        """Verify mirage_app cannot read or write keys outside permitted ~ratelimit:* and ~scs:* patterns."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        client = default_redis_client_manager.get_client()

        unrelated_keys = [
            "celery-task-meta-550e8400-e29b-41d4-a716-446655440000",
            "unrelated_root_key",
            "admin:credentials",
            "user_session:123",
        ]

        for key in unrelated_keys:
            # Write must be denied
            with pytest.raises(NoPermissionError, match=r"(?i)(no permissions|has no permissions)"):
                await client.set(key, "unauthorized")

            # Read must be denied
            with pytest.raises(NoPermissionError, match=r"(?i)(no permissions|has no permissions)"):
                await client.get(key)

    def test_ast_safeguard_zero_in_memory_rate_limiter_fallback(self) -> None:
        """Verify gateway.middleware.rate_limiter contains NO in-memory dictionaries or lists."""
        source = inspect.getsource(rate_limiter_module)
        tree = ast.parse(source)

        for node in ast.walk(tree):
            # Check for defaultdict usage
            if isinstance(node, ast.Name) and node.id == "defaultdict":
                pytest.fail(
                    "Found banned 'defaultdict' in gateway.middleware.rate_limiter; "
                    "in-memory fallback is strictly forbidden!"
                )
            # Check for class SlidingWindowRateLimiter
            if isinstance(node, ast.ClassDef) and node.name == "SlidingWindowRateLimiter":
                pytest.fail("Found banned 'SlidingWindowRateLimiter' class in gateway.middleware.rate_limiter!")
