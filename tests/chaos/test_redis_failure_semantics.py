"""Failure mode, chaos, and circuit breaker tests for Redis infrastructure.

Adheres to:
- Technical_Architecture.md §8.3, §8.4
- Security_Access.md §1.3 (Threat T-06)
- Testing_Strategy.md §9 (Chaos Testing Scenarios)
"""

import asyncio
import uuid
from typing import Any
from unittest.mock import patch

import pybreaker
import pytest
from starlette.testclient import TestClient

from db.redis import (
    RedisConnectionError,
    default_redis_client_manager,
    default_token_bucket_rate_limiter,
)
from gateway.main import create_app
from gateway.middleware.circuit_breaker import (
    call_async_with_circuit,
    reset_all_circuits,
)
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory
from workers.scs.worker import SCSWorker


@pytest.mark.chaos
class TestRedisFailureSemantics:
    """Validate failure modes, circuit breaker tripping, Cache-Bypass Mode, and fail-closed rate limiting."""

    def test_rate_limiter_fails_closed_with_http_503_when_redis_down(self) -> None:
        """Verify that when Redis is unreachable, rate limiter fails closed with HTTP 503 SERVICE_DEGRADED."""
        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_redis_down_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        payload = {
            "prompt": "What is the boiling point of water?",
            "response": "The boiling point of water is 100 degrees Celsius.",
            "tenant_id": tenant_id,
        }

        with patch.object(
            default_token_bucket_rate_limiter,
            "consume",
            side_effect=RedisConnectionError("Connection to Redis lost on port 6379"),
        ):
            response = client.post("/v1/verify", json=payload, headers=headers)

            # Security Invariant: Must fail closed with 503, NEVER 200
            assert response.status_code == 503
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "SERVICE_DEGRADED"
            assert "Rate limiting service is unavailable" in data["error"]["message"]

    @pytest.mark.asyncio
    async def test_scs_cache_bypasses_smoothly_on_redis_down(self) -> None:
        """Verify that when Redis is unreachable, SCSWorker enters Cache-Bypass Mode and computes score live."""
        worker = SCSWorker()
        tenant_id = f"tenant_bypass_{uuid.uuid4().hex[:8]}"
        prompt = "What is the speed of sound?"

        # Simulate Redis connection failure during cache lookup and write
        with patch.object(
            worker.cache_service,
            "get_scs",
            return_value=(None, False),  # Simulates Cache-Bypass Mode
        ):
            score, is_hit = await worker.compute_scs_score(prompt, model_id="llama-3.1", tenant_id=tenant_id)
            assert is_hit is False
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_async_circuit_breaker_trips_and_recovers(self) -> None:
        """Verify AsyncCircuitBreaker trips to OPEN after fail_max errors and recovers after reset_timeout."""
        reset_all_circuits()
        test_cb = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=2, name="test_async_redis_circuit")

        async def failing_operation() -> None:
            raise ConnectionError("Simulated Redis socket failure")

        async def successful_operation() -> str:
            return "recovered_ok"

        # 1. First 3 failures trip the circuit
        for _ in range(3):
            try:
                await call_async_with_circuit(test_cb, failing_operation)
            except (ConnectionError, pybreaker.CircuitBreakerError):
                pass

        assert test_cb.current_state == "open"

        # 2. Immediate 4th call is fast-rejected by open circuit
        with pytest.raises(pybreaker.CircuitBreakerError):
            await call_async_with_circuit(test_cb, failing_operation)

        # 3. Wait for reset_timeout (2.1s)
        await asyncio.sleep(2.1)

        # 4. Next successful call closes circuit
        res = await call_async_with_circuit(test_cb, successful_operation)
        assert res == "recovered_ok"
        assert test_cb.current_state == "closed"

    @pytest.mark.asyncio
    async def test_redis_restart_reconstruction(self, live_redis_database: Any) -> None:
        """Verify application reconstructs safely after Redis restart / key flush without errors."""
        if live_redis_database is None:
            pytest.skip("Live Redis container not available")

        worker = SCSWorker()
        tenant_id = f"tenant_reconstruct_{uuid.uuid4().hex[:8]}"
        prompt = "Explain photosynthesis in one sentence."

        # 1. Warm up SCS cache
        score1, hit1 = await worker.compute_scs_score(prompt, model_id="model_x", tenant_id=tenant_id)
        assert hit1 is False

        score2, hit2 = await worker.compute_scs_score(prompt, model_id="model_x", tenant_id=tenant_id)
        assert hit2 is True
        assert score1 == score2

        # 2. Simulate Redis restart / key flush by deleting tenant keys
        client = default_redis_client_manager.get_client()
        key = worker.get_cache_key(prompt, "model_x", tenant_id)
        await client.delete(key)

        # 3. Request after restart cleanly misses cache, recomputes, and repopulates
        score3, hit3 = await worker.compute_scs_score(prompt, model_id="model_x", tenant_id=tenant_id)
        assert hit3 is False  # Reconstructed from scratch
        assert isinstance(score3, float)
