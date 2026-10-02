"""Unit and contract tests for rate limiter middleware alignment and fail-closed error handling."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from db.redis import (
    RateLimitExceededError,
    RedisConnectionError,
    RedisOperationTimeoutError,
    TokenBucketRateLimiter,
    TokenBucketResult,
)
from gateway.main import create_app
from gateway.middleware.rate_limiter import AsyncRateLimiter
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory


@pytest.mark.unit
class TestRateLimiterAlignment:
    """Verify rate limiter middleware behavior, contract headers, and centralized fail-closed handling."""

    @pytest.mark.asyncio
    async def test_middleware_raises_http_429_with_standard_headers_on_exhaustion(self) -> None:
        """Verify middleware translates RateLimitExceededError to HTTPException(429) with all 4 headers."""
        mock_backend = AsyncMock(spec=TokenBucketRateLimiter)
        mock_backend.check_rate_limit.side_effect = RateLimitExceededError(
            tenant_id="tenant_exh_123",
            tier="free",
            limit=60,
            remaining=0,
            retry_after=15,
            reset_time=1700000060,
        )

        limiter = AsyncRateLimiter(backend=mock_backend)

        with pytest.raises(HTTPException) as exc_info:
            await limiter.check_rate_limit("tenant_exh_123", tier="free")

        exc = exc_info.value
        assert exc.status_code == 429
        assert exc.headers is not None
        assert exc.headers["X-RateLimit-Limit"] == "60"
        assert exc.headers["X-RateLimit-Remaining"] == "0"
        assert exc.headers["X-RateLimit-Reset"] == "1700000060"
        assert exc.headers["Retry-After"] == "15"

    @pytest.mark.asyncio
    async def test_middleware_propagates_redis_connection_error(self) -> None:
        """Verify middleware propagates RedisConnectionError directly for centralized gateway handling."""
        mock_backend = AsyncMock(spec=TokenBucketRateLimiter)
        mock_backend.check_rate_limit.side_effect = RedisConnectionError("Connection refused on port 6379")

        limiter = AsyncRateLimiter(backend=mock_backend)

        with pytest.raises(RedisConnectionError) as exc_info:
            await limiter.check_rate_limit("tenant_conn_err_123")

        assert "Connection refused on port 6379" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_middleware_propagates_redis_timeout_error(self) -> None:
        """Verify middleware propagates RedisOperationTimeoutError directly for centralized gateway handling."""
        mock_backend = AsyncMock(spec=TokenBucketRateLimiter)
        mock_backend.check_rate_limit.side_effect = RedisOperationTimeoutError("Socket read timeout")

        limiter = AsyncRateLimiter(backend=mock_backend)

        with pytest.raises(RedisOperationTimeoutError) as exc_info:
            await limiter.check_rate_limit("tenant_timeout_123")

        assert "Socket read timeout" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_middleware_returns_token_bucket_result_on_success(self) -> None:
        """Verify middleware returns TokenBucketResult intact when tokens are consumed."""
        mock_backend = AsyncMock(spec=TokenBucketRateLimiter)
        mock_backend.check_rate_limit.return_value = TokenBucketResult(
            allowed=True,
            limit=60,
            remaining=59,
            retry_after=0,
            reset_time=1700000060,
        )

        limiter = AsyncRateLimiter(backend=mock_backend)
        result = await limiter.check_rate_limit("tenant_ok_123")

        assert result.allowed is True
        assert result.remaining == 59
        assert result.limit == 60

    def test_centralized_gateway_handler_produces_http_503_service_degraded(self) -> None:
        """Verify gateway's centralized RedisServiceError handler produces HTTP 503 SERVICE_DEGRADED."""
        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_rl_failclosed_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        payload = {
            "prompt": "What is the speed of light?",
            "response": "The speed of light is 299,792,458 m/s.",
            "tenant_id": tenant_id,
        }

        with patch(
            "gateway.routes.verify.rate_limiter.check_rate_limit",
            side_effect=RedisConnectionError("Redis cluster unreachable during rate limit evaluation"),
        ):
            resp = client.post("/v1/verify", json=payload, headers=headers)

            assert resp.status_code == 503
            assert resp.headers.get("Retry-After") == "10"
            data = resp.json()
            assert "error" in data
            assert data["error"]["code"] == "SERVICE_DEGRADED"
            assert "Rate limiting service is unavailable" in data["error"]["message"]
