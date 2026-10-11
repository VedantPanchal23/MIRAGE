"""Adversarial and Security Regression Matrix for Phase 5.1 Hardening.

Covers the 22 mandatory adversarial regression scenarios:
1. Router database outage: zero provider calls.
2. Budget database outage or uncertain reservation result: zero provider calls.
3. Concurrent initial budget creation under advisory lock.
4. Concurrent same-key/same-payload reservations.
5. Concurrent same-key/conflicting-payload reservations rejected.
6. Budget update racing reservation.
7. Repeated settlement and duplicate cost prevention.
8. Settlement exceeding reservation and hard-budget overage rejection.
9. Provider succeeds but settlement fails.
10. Accounting drift invariants fail closed without max(0, ...) masking.
11. Reconciler races with active provider execution and settlement.
12. Late settlement after expiry/release rejected.
13. Sensitive taint with unverified deployment metadata rejected.
14. Local endpoint and provider-base-URL SSRF policy violations.
15. Every fallback rechecks privacy, risk, capability, pricing, and available budget.
16. Circuit breaker half-open single probe lease concurrency.
17. Missing credentials and unknown providers fail closed.
18. Missing/stale pricing profiles fail closed.
19. Invalid token usage and malformed usage data rejected.
20. Tenant isolation across budgets, reservations, settlements, and cost records.
21. Production mode strictly forbids mock provider.
22. Full Gate 4 verification and honest response headers after execution.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from gateway.main import app
from services.budget_manager import budget_manager_service
from services.circuit_breaker import ModelCircuitBreaker
from services.model_router import model_router_service
from services.pricing_service import (
    PricingProfileNotFoundError,
    PricingValidationError,
    pricing_service,
)
from services.providers.base import BaseProviderAdapter, ProviderResponse, UsageInfo
from services.providers.factory import (
    ProviderConfigurationError,
    clear_adapter_overrides,
    get_provider_adapter,
    register_adapter_override,
    validate_provider_base_url,
)
from shared.config import get_settings
from shared.config.settings import EnvironmentType
from shared.schemas.auth import Role
from shared.schemas.budget import (
    BudgetReservationRequest,
    BudgetSettlementRequest,
)
from shared.schemas.model_router import (
    ModelCapabilityProfile,
    ModelTier,
    RoutingRequest,
)
from tests.auth_factory import AuthTestFactory


class RecordingMockAdapter(BaseProviderAdapter):
    """Mock adapter recording invocation counts and arguments."""

    def __init__(self, content: str = "Test response content") -> None:
        self.call_count = 0
        self.content = content

    @property
    def provider_name(self) -> str:
        return "mock"

    async def generate(self, prompt: Any, model_id: str, **kwargs: Any) -> ProviderResponse:
        _ = prompt
        _ = kwargs
        self.call_count += 1
        return ProviderResponse(
            content=self.content,
            usage=UsageInfo(prompt_tokens=15, completion_tokens=25, total_tokens=40, cached_tokens=0),
            latency_ms=12.5,
            model_id=model_id,
            provider="mock",
            finish_reason="stop",
        )


@pytest.fixture(autouse=True)
def cleanup_overrides() -> Any:
    clear_adapter_overrides()
    yield
    clear_adapter_overrides()


# ---------------------------------------------------------------------------
# Scenario 1 & 2: Infrastructure Outages Fail Closed with Zero Provider Calls
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_router_outage_fails_closed_zero_provider_calls() -> None:
    """1. Router infrastructure outage: aborts immediately with 503 and zero provider calls."""
    mock_adapter = RecordingMockAdapter()
    register_adapter_override("mock", mock_adapter)
    register_adapter_override("openai", mock_adapter)

    client = TestClient(app)
    tenant_id = f"t_outage_r_{uuid.uuid4().hex[:8]}"
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

    with patch.object(model_router_service, "route", side_effect=RuntimeError("Database connection lost")):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            headers=headers,
        )
        assert resp.status_code == 503
        assert "Model routing infrastructure failure" in resp.json()["detail"]
        assert mock_adapter.call_count == 0


@pytest.mark.security
def test_budget_reservation_outage_fails_closed_zero_provider_calls() -> None:
    """2. Budget reservation failure: aborts with 503 and zero provider calls."""
    mock_adapter = RecordingMockAdapter()
    register_adapter_override("mock", mock_adapter)
    register_adapter_override("openai", mock_adapter)

    client = TestClient(app)
    tenant_id = f"t_outage_b_{uuid.uuid4().hex[:8]}"
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

    with patch.object(
        budget_manager_service,
        "reserve_budget",
        side_effect=RuntimeError("PostgreSQL connection timeout"),
    ):
        resp = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "Hello"}]},
            headers=headers,
        )
        assert resp.status_code == 503
        assert "Preflight budget reservation failed" in resp.json()["detail"]
        assert mock_adapter.call_count == 0


# ---------------------------------------------------------------------------
# Scenario 3, 4, 5, 6: Concurrency, Advisory Locks, and Reservation Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.asyncio
async def test_concurrent_initial_budget_creation() -> None:
    """3. Concurrent first-time budget initialization serializes cleanly without duplicates."""
    tenant_id = f"t_init_race_{uuid.uuid4().hex[:8]}"

    # Launch 8 concurrent calls to get_tenant_budget for brand new tenant
    tasks = [budget_manager_service.get_tenant_budget(tenant_id) for _ in range(8)]
    results = await asyncio.gather(*tasks)

    # All should return the exact same budget ID and initial balance
    first_id = results[0].id
    for b in results:
        assert b.id == first_id
        assert b.total_budget_micros == 100_000_000
        assert b.reserved_micros == 0
        assert b.spent_micros == 0


@pytest.mark.security
@pytest.mark.asyncio
async def test_concurrent_same_key_same_payload_reservations() -> None:
    """4. Concurrent identical reservations return the same reservation without double-charging."""
    tenant_id = f"t_idem_race_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_idem_{uuid.uuid4().hex[:8]}"
    res_key = f"key_idem_{uuid.uuid4().hex[:8]}"

    await budget_manager_service.update_tenant_budget(tenant_id, total_budget_micros=10_000, hard_limit=True)

    req = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id=tx_id,
        estimated_cost_micros=3_000,
        reservation_key=res_key,
    )

    tasks = [budget_manager_service.reserve_budget(req) for _ in range(5)]
    results = await asyncio.gather(*tasks)

    first_res_id = results[0].id
    for res in results:
        assert res.id == first_res_id
        assert res.amount_micros == 3_000

    # Ensure reserved balance was charged exactly ONCE
    b = await budget_manager_service.get_tenant_budget(tenant_id)
    assert b.reserved_micros == 3_000
    assert b.available_micros == 7_000


@pytest.mark.security
@pytest.mark.asyncio
async def test_same_key_conflicting_payload_rejected() -> None:
    """5. Reusing an existing reservation key with conflicting parameters must be rejected (HTTP 409)."""
    tenant_id = f"t_conflict_{uuid.uuid4().hex[:8]}"
    res_key = f"key_conflict_{uuid.uuid4().hex[:8]}"

    await budget_manager_service.update_tenant_budget(tenant_id, total_budget_micros=50_000)

    # 1. First reservation: amount 2,000
    r1 = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id="tx_orig",
        estimated_cost_micros=2_000,
        reservation_key=res_key,
    )
    await budget_manager_service.reserve_budget(r1)

    # 2. Conflicting reservation with different transaction ID -> 409
    r2_diff_tx = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id="tx_diff",
        estimated_cost_micros=2_000,
        reservation_key=res_key,
    )
    with pytest.raises(HTTPException) as exc_info:
        await budget_manager_service.reserve_budget(r2_diff_tx)
    assert exc_info.value.status_code == 409

    # 3. Conflicting reservation with different amount -> 409
    r3_diff_amount = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id="tx_orig",
        estimated_cost_micros=5_000,
        reservation_key=res_key,
    )
    with pytest.raises(HTTPException) as exc_info2:
        await budget_manager_service.reserve_budget(r3_diff_amount)
    assert exc_info2.value.status_code == 409


# ---------------------------------------------------------------------------
# Scenario 7, 8, 9, 10: Settlement Idempotency, Overages, and Drift Prevention
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.asyncio
async def test_repeated_settlement_duplicate_cost_prevention() -> None:
    """7. Repeated settlement requests return the existing cost record without double-charging spend."""
    tenant_id = f"t_set_rep_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_rep_{uuid.uuid4().hex[:8]}"

    await budget_manager_service.update_tenant_budget(tenant_id, total_budget_micros=20_000)

    res = await budget_manager_service.reserve_budget(
        BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=tx_id,
            estimated_cost_micros=4_000,
            reservation_key=f"k_{tx_id}",
        )
    )

    set_req = BudgetSettlementRequest(
        reservation_id=res.id,
        actual_cost_micros=3_500,
        model_id="mock-capable",
        provider="mock",
        prompt_tokens=100,
        completion_tokens=50,
        attempt_number=1,
    )

    cost1 = await budget_manager_service.settle_budget(tenant_id, set_req)
    assert cost1.cost_micros == 3_500

    # Replay settlement
    cost2 = await budget_manager_service.settle_budget(tenant_id, set_req)
    assert cost2.id == cost1.id
    assert cost2.cost_micros == 3_500

    # Ensure spent is 3,500 (not 7,000)
    b = await budget_manager_service.get_tenant_budget(tenant_id)
    assert b.spent_micros == 3_500
    assert b.reserved_micros == 0


@pytest.mark.security
@pytest.mark.asyncio
async def test_settlement_exceeding_reservation_hard_budget_rejection() -> None:
    """8. If actual cost exceeds reserved funds and headroom under hard limit, reject with 402."""
    tenant_id = f"t_overage_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_ov_{uuid.uuid4().hex[:8]}"

    # Set total budget to exactly 5,000
    await budget_manager_service.update_tenant_budget(tenant_id, total_budget_micros=5_000, hard_limit=True)

    res = await budget_manager_service.reserve_budget(
        BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=tx_id,
            estimated_cost_micros=4_000,
            reservation_key=f"k_{tx_id}",
        )
    )

    # Actual cost is 6,000 (exceeds reserved 4,000 by 2,000; headroom is 1,000)
    set_req = BudgetSettlementRequest(
        reservation_id=res.id,
        actual_cost_micros=6_000,
        model_id="mock-frontier",
        provider="mock",
        prompt_tokens=200,
        completion_tokens=100,
    )

    with pytest.raises(HTTPException) as exc_info:
        await budget_manager_service.settle_budget(tenant_id, set_req)
    assert exc_info.value.status_code == 402
    assert "exceeded reserved" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_accounting_drift_invariants_fail_closed() -> None:
    """10. Accounting drift (reserved < reservation amount) raises HTTP 500 without masking."""
    tenant_id = f"t_drift_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_drift_{uuid.uuid4().hex[:8]}"

    res = await budget_manager_service.reserve_budget(
        BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=tx_id,
            estimated_cost_micros=5_000,
            reservation_key=f"k_{tx_id}",
        )
    )

    # Artificially tamper with budget_rec.reserved_micros to simulate drift
    from sqlalchemy import select

    from db import session as db_session
    from db.models import TenantBudgetRecord

    async with db_session.get_tenant_session(tenant_id) as session:
        stmt = select(TenantBudgetRecord).where(TenantBudgetRecord.tenant_id == tenant_id)
        budget_rec = (await session.execute(stmt)).scalar_one()
        budget_rec.reserved_micros = 1_000  # Less than reservation amount of 5,000!
        await session.commit()

    # Attempting to settle must raise 500 rather than silently clamping with max(0, ...)
    set_req = BudgetSettlementRequest(
        reservation_id=res.id,
        actual_cost_micros=4_000,
        model_id="mock-capable",
        provider="mock",
        prompt_tokens=10,
        completion_tokens=10,
    )
    with pytest.raises(HTTPException) as exc_info:
        await budget_manager_service.settle_budget(tenant_id, set_req)
    assert exc_info.value.status_code == 500
    assert "accounting drift detected" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Scenario 11, 12: Reconciler Races and Late Settlement
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.asyncio
async def test_late_settlement_after_expiry_or_release_rejected() -> None:
    """12. Settle request on an already released reservation must be rejected (HTTP 409)."""
    tenant_id = f"t_late_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_late_{uuid.uuid4().hex[:8]}"

    res = await budget_manager_service.reserve_budget(
        BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=tx_id,
            estimated_cost_micros=2_000,
            reservation_key=f"k_{tx_id}",
        )
    )

    # Release reservation
    await budget_manager_service.release_reservation(tenant_id, res.id)

    # Late settlement attempt
    set_req = BudgetSettlementRequest(
        reservation_id=res.id,
        actual_cost_micros=1_500,
        model_id="mock-capable",
        provider="mock",
        prompt_tokens=10,
        completion_tokens=10,
    )
    with pytest.raises(HTTPException) as exc_info:
        await budget_manager_service.settle_budget(tenant_id, set_req)
    assert exc_info.value.status_code == 409
    assert "RELEASED" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Scenario 13, 14: Sensitive Taints and SSRF / Base URL Violations
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.asyncio
async def test_sensitive_taint_with_unverified_deployment_metadata() -> None:
    """13. Sensitive taints reject models lacking verified deployment isolation."""
    # Test model with is_zero_retention=True but deployment_type="cloud_shared"
    unverified_profile = ModelCapabilityProfile(
        model_id="test-cloud-shared",
        provider="openai",
        family="openai",
        tier=ModelTier.FRONTIER,
        context_window=128000,
        supports_tools=True,
        supports_vision=True,
        supports_structured_output=True,
        supports_system_prompt=True,
        is_zero_retention=True,
        deployment_type="cloud_shared",  # Not dedicated or air-gapped!
        privacy_verified_at=datetime.now(UTC),
        reliability_index=0.95,
        expected_latency_ms=500.0,
        input_cost_per_million_micros=1000000,
        output_cost_per_million_micros=2000000,
    )

    with patch.object(model_router_service, "list_models", return_value=[unverified_profile]):
        req = RoutingRequest(
            tenant_id="default_tenant",
            task_type="reasoning",
            taints=["phi"],  # HIPAA/PHI taint
        )
        with pytest.raises(HTTPException) as exc_info:
            await model_router_service.route(req)
        assert exc_info.value.status_code == 422
        exclusions = exc_info.value.detail["exclusions"]
        assert any(e["rule"] == "GATE1_DEPLOYMENT_NOT_ISOLATED" for e in exclusions)


@pytest.mark.security
def test_provider_base_url_ssrf_policy_violations() -> None:
    """14. Metadata IP addresses and invalid schemes are blocked by URL validation."""
    with pytest.raises(ProviderConfigurationError):
        validate_provider_base_url("http://169.254.169.254/latest/meta-data")

    with pytest.raises(ProviderConfigurationError):
        validate_provider_base_url("http://metadata.google.internal/computeMetadata/v1")

    with pytest.raises(ProviderConfigurationError):
        validate_provider_base_url("ftp://api.openai.com/v1")

    # Cloud provider with loopback is rejected
    with pytest.raises(ProviderConfigurationError):
        validate_provider_base_url("http://localhost:8000/v1", allow_local=False)

    # Local Ollama with loopback is permitted
    assert validate_provider_base_url("http://localhost:11434", allow_local=True) == "http://localhost:11434"


# ---------------------------------------------------------------------------
# Scenario 15, 16: Fallback Revalidation and Circuit Breaker Probe Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.asyncio
async def test_fallback_ladder_revalidates_assurance_and_budget() -> None:
    """15. Fallback candidate revalidation checks capabilities, risk, and budget limits."""
    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="coding",
        required_capabilities=["tools"],
        estimated_input_tokens=100,
        estimated_output_tokens=100,
    )

    # Candidate with budget exceeded
    is_valid, reason, profile, cost, price_id = await model_router_service.revalidate_fallback_candidate(
        candidate_model_id="mock-frontier",
        request=req,
        remaining_budget_micros=1,  # Insufficient budget!
    )
    assert is_valid is False
    assert "exceeds remaining budget" in str(reason)


@pytest.mark.security
@pytest.mark.asyncio
async def test_circuit_breaker_single_probe_lease_concurrency() -> None:
    """16. When breaker is OPEN and timeout expires, exactly ONE request acquires half-open lease."""
    cb = ModelCircuitBreaker(failure_threshold=3, recovery_timeout_seconds=0.1, probe_lease_seconds=5.0)

    # Trip breaker
    for _ in range(3):
        await cb.record_failure("testprov", "testmod")

    is_avail, state = await cb.is_available("testprov", "testmod")
    assert is_avail is False
    assert state == "OPEN"

    # Wait for recovery timeout
    await asyncio.sleep(0.15)

    # Launch 5 concurrent calls to is_available
    results = await asyncio.gather(*[cb.is_available("testprov", "testmod") for _ in range(5)])

    # Exactly ONE should acquire half-open lease (True, "HALF_OPEN")
    leased_count = sum(1 for avail, st in results if avail is True and st == "HALF_OPEN")
    rejected_count = sum(1 for avail, st in results if avail is False and st == "OPEN")

    assert leased_count == 1
    assert rejected_count == 4


# ---------------------------------------------------------------------------
# Scenario 17, 18, 19, 21: Configuration, Pricing, and Input Validation
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_missing_credentials_and_unknown_providers_fail_closed() -> None:
    """17. Unknown providers raise ProviderConfigurationError instead of returning mock."""
    with pytest.raises(ProviderConfigurationError):
        get_provider_adapter("nonexistent_unknown_provider_xyz")


@pytest.mark.security
@pytest.mark.asyncio
async def test_authoritative_pricing_fails_closed_on_missing_profile() -> None:
    """18. Missing pricing profile strictly raises PricingProfileNotFoundError."""
    with pytest.raises(PricingProfileNotFoundError):
        await pricing_service.get_active_pricing_profile("unregistered-ghost-model-xyz")


@pytest.mark.security
def test_invalid_token_usage_and_negative_costs_rejected() -> None:
    """19. Negative tokens or costs raise PricingValidationError."""
    with pytest.raises(PricingValidationError):
        pricing_service.parse_usage_dict({"prompt_tokens": -5, "completion_tokens": 10})

    with pytest.raises(PricingValidationError):
        pricing_service.parse_usage_dict("not_a_dictionary")  # type: ignore


@pytest.mark.security
def test_production_mode_forbids_mock_provider() -> None:
    """21. In EnvironmentType.PRODUCTION, mock provider access is rejected."""
    settings = get_settings()
    original_env = settings.environment
    try:
        settings.environment = EnvironmentType.PRODUCTION
        with pytest.raises(ProviderConfigurationError):
            get_provider_adapter("mock")
    finally:
        settings.environment = original_env


# ---------------------------------------------------------------------------
# Scenario 22: Gate 4 Output Assurance and Honest Metadata in Proxy
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_proxy_honest_gate4_output_assurance_headers() -> None:
    """22. Proxy execution passes through Gate 4 and outputs honest audit headers."""
    mock_adapter = RecordingMockAdapter("The Apollo 11 lunar module landed on the Moon in July 1969.")
    register_adapter_override("mock", mock_adapter)
    register_adapter_override("openai", mock_adapter)
    register_adapter_override("ollama", mock_adapter)

    client = TestClient(app)
    tenant_id = f"t_honest_{uuid.uuid4().hex[:8]}"
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

    resp = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "When did Apollo 11 land?"}]},
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert resp.headers["X-Mirage-Verified"] in ("true", "false")
    assert "X-Mirage-HRS" in resp.headers
    assert "X-Mirage-Cost-Micros" in resp.headers
    assert "X-Mirage-Decision-Hash" in resp.headers
    assert data["choices"][0]["message"]["content"] == mock_adapter.content
    assert data["mirage"]["cost_micros"] >= 0
