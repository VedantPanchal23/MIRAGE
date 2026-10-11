"""Security, concurrency, and cost-bounds enforcement tests for Phase 5."""

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from gateway.main import app
from services.budget_manager import budget_manager_service
from services.model_router import model_router_service
from services.providers.base import ProviderError, ProviderErrorType
from services.providers.mock_adapter import MockProviderAdapter
from shared.schemas.auth import Role
from shared.schemas.budget import (
    BudgetReservationRequest,
)
from shared.schemas.model_router import ModelTier, RoutingRequest
from tests.auth_factory import AuthTestFactory


@pytest.mark.security
@pytest.mark.asyncio
async def test_concurrent_budget_reservations_race_condition_defense() -> None:
    """PostgreSQL row-level locking strictly prevents concurrent overspend races."""
    tenant_id = f"t_race_{uuid.uuid4().hex[:8]}"

    # Set total budget to 10,000 micros ($0.01)
    await budget_manager_service.update_tenant_budget(
        tenant_id=tenant_id,
        total_budget_micros=10_000,
        hard_limit=True,
    )

    # Launch 10 concurrent reservation attempts of 2,000 micros each
    # Exactly 5 should succeed, and exactly 5 should fail with 402
    async def _attempt_reserve(idx: int) -> bool:
        req = BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=f"tx_race_{idx}",
            estimated_cost_micros=2_000,
            reservation_key=f"key_race_{idx}",
        )
        try:
            await budget_manager_service.reserve_budget(req)
            return True
        except HTTPException as exc:
            if exc.status_code == 402:
                return False
            raise

    results = await asyncio.gather(*[_attempt_reserve(i) for i in range(10)])
    succeeded = sum(1 for r in results if r is True)
    failed = sum(1 for r in results if r is False)

    assert succeeded == 5
    assert failed == 5

    # Check that durable ledger invariant holds exactly
    budget = await budget_manager_service.get_tenant_budget(tenant_id)
    assert budget.reserved_micros == 10_000
    assert budget.spent_micros == 0
    assert budget.available_micros == 0
    assert budget.spent_micros + budget.reserved_micros <= budget.total_budget_micros


@pytest.mark.security
def test_cross_tenant_budget_isolation() -> None:
    """Tenants cannot read or mutate budgets belonging to other tenants."""
    tenant_a = f"t_iso_a_{uuid.uuid4().hex[:8]}"
    tenant_b = f"t_iso_b_{uuid.uuid4().hex[:8]}"

    client = TestClient(app)
    headers_a = AuthTestFactory.auth_headers(tenant_id=tenant_a, role=Role.TENANT_ADMIN)

    # 1. Tenant A tries to read Tenant B's budget -> 403 Forbidden
    resp = client.get(f"/v1/budgets/tenant?tenant_id={tenant_b}", headers=headers_a)
    assert resp.status_code == 403

    # 2. Tenant A tries to modify Tenant B's budget -> 403 Forbidden
    update_payload = {"total_budget_micros": 999_999, "hard_limit": False}
    resp = client.put(f"/v1/budgets/tenant?tenant_id={tenant_b}", json=update_payload, headers=headers_a)
    assert resp.status_code == 403


@pytest.mark.security
@pytest.mark.asyncio
async def test_fallback_ladder_reauthorization_integrity() -> None:
    """Fallback candidates must strictly satisfy the original security and risk constraints."""
    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="reasoning",
        taints=["phi"],  # Strict healthcare taint
        risk_level=3,  # High risk action
        allow_fallbacks=True,
    )

    decision = await model_router_service.route(req)
    all_models = await model_router_service.list_models()
    models_by_id = {m.model_id: m for m in all_models}

    # Selected model must be zero-retention and FRONTIER
    sel_profile = models_by_id[decision.selected_model_id]
    assert sel_profile.is_zero_retention is True or sel_profile.provider in ("ollama", "mock")
    assert sel_profile.tier == ModelTier.FRONTIER
    assert sel_profile.reliability_index >= 0.85

    # Every model in the fallback ladder MUST ALSO strictly satisfy the same security invariants
    for fb_id in decision.fallback_ladder:
        fb_profile = models_by_id[fb_id]
        # Invariant 1: Zero retention for PHI taint
        assert fb_profile.is_zero_retention is True or fb_profile.provider in ("ollama", "mock")
        # Invariant 2: FRONTIER tier for L3 risk
        assert fb_profile.tier == ModelTier.FRONTIER
        assert fb_profile.reliability_index >= 0.85


@pytest.mark.security
@pytest.mark.asyncio
async def test_negative_cost_and_overflow_defense() -> None:
    """Negative budget or reservation parameters must be rejected."""
    tenant_id = f"t_neg_{uuid.uuid4().hex[:8]}"

    # Negative budget update rejected
    with pytest.raises(HTTPException) as exc_info:
        await budget_manager_service.update_tenant_budget(
            tenant_id=tenant_id,
            total_budget_micros=-1000,
        )
    assert exc_info.value.status_code == 400

    # Negative reservation amount rejected by schema validation
    with pytest.raises((HTTPException, ValueError)):
        BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id="tx_neg",
            estimated_cost_micros=-50,
            reservation_key="key_neg",
        )


@pytest.mark.security
@pytest.mark.asyncio
async def test_offline_mock_provider_deterministic_execution_and_error_simulation() -> None:
    """Mock adapter provides deterministic token counts and simulates provider errors."""
    adapter = MockProviderAdapter(fixed_latency_ms=5.0)

    # 1. Normal deterministic execution
    resp = await adapter.generate("Hello world, this is a test prompt.", "mock-frontier")
    assert resp.provider == "mock"
    assert resp.model_id == "mock-frontier"
    assert resp.usage.prompt_tokens > 0
    assert resp.usage.completion_tokens > 0
    assert resp.latency_ms >= 5.0
    assert "Verified execution" in resp.content

    # 2. Rate limit 429 simulation
    with pytest.raises(ProviderError) as exc_info:
        await adapter.generate("Test prompt", "mock-frontier_rate_limit_fail")
    assert exc_info.value.error_type == ProviderErrorType.RATE_LIMIT_EXCEEDED
    assert exc_info.value.status_code == 429
    assert exc_info.value.retryable is True

    # 3. Timeout simulation
    with pytest.raises(ProviderError) as exc_info:
        await adapter.generate("Test prompt", "mock-frontier_timeout_fail")
    assert exc_info.value.error_type == ProviderErrorType.TIMEOUT
    assert exc_info.value.status_code == 504
    assert exc_info.value.retryable is True

    # 4. Upstream 500 error simulation
    with pytest.raises(ProviderError) as exc_info:
        await adapter.generate("Test prompt", "mock-frontier_upstream_fail")
    assert exc_info.value.error_type == ProviderErrorType.UPSTREAM_UNAVAILABLE
    assert exc_info.value.status_code == 500
    assert exc_info.value.retryable is True
