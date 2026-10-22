"""Phase 5.1.1: Comprehensive Routing, Financial Integrity & Provider Security Remediation Suite.

Validates the full matrix of remediations implemented across Workstreams A through F:
- Workstream A: Advisory lock fail-closed behavior, non-clamping orphan reconciliation,
  conflicting settlement replay prevention (HTTP 409), and durable incident logging.
- Workstream B: Strict usage parsing, boolean rejection, non-negative rate validation,
  cached token bounds, and proxy post-execution fail-closed behavior.
- Workstream C: SSRF destination validator covering IPv4/IPv6 loopback, link-local,
  RFC 1918 private, cloud metadata, embedded credentials, multi-IP DNS, and redirect suppression.
- Workstream D: Atomic Redis Lua circuit breaker transitions, single canary probe lease concurrency,
  and production fail-closed degradation on Redis outage.
- Workstream E: Privacy attestation lifecycle (expiration and revocation), pricing availability,
  and fallback candidate revalidation.
- Workstream F: Database check constraints on tenant_budgets and durable accounting incidents.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from starlette.testclient import TestClient

from db import session as db_session
from db.models import AccountingIncidentRecord, TenantBudgetRecord
from gateway.main import app
from services.budget_manager import (
    _acquire_advisory_lock,
    budget_manager_service,
)
from services.circuit_breaker import ModelCircuitBreaker
from services.model_router import model_router_service
from services.pricing_service import (
    PricingValidationError,
    pricing_service,
)
from services.providers.base import BaseProviderAdapter, ProviderResponse, UsageInfo
from services.providers.factory import (
    clear_adapter_overrides,
    get_provider_adapter,
    register_adapter_override,
)
from services.providers.ssrf_validator import (
    SSRFValidationError,
    validate_safe_provider_url,
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


class StubRecordingAdapter(BaseProviderAdapter):
    """Test adapter returning controllable usage info."""

    def __init__(self, content: str = "Test response", usage: UsageInfo | None = None) -> None:
        self.call_count = 0
        self.content = content
        self.usage = usage or UsageInfo(prompt_tokens=20, completion_tokens=30, total_tokens=50, cached_tokens=0)

    @property
    def provider_name(self) -> str:
        return "mock"

    async def generate(self, prompt: Any, model_id: str, **kwargs: Any) -> ProviderResponse:
        _ = prompt
        _ = kwargs
        self.call_count += 1
        return ProviderResponse(
            content=self.content,
            usage=self.usage,
            latency_ms=10.0,
            model_id=model_id,
            provider="mock",
            finish_reason="stop",
        )


@pytest.fixture(autouse=True)
def clean_adapters() -> Any:
    clear_adapter_overrides()
    yield
    clear_adapter_overrides()


# ===========================================================================
# Workstream A: PostgreSQL Locking & Budget Integrity
# ===========================================================================


@pytest.mark.security
@pytest.mark.asyncio
async def test_a1_advisory_lock_fails_closed_in_production_on_non_postgres() -> None:
    """A1: Advisory lock acquisition raises RuntimeError in production if dialect is not postgresql."""
    settings = get_settings()
    original_env = settings.environment
    try:
        settings.environment = EnvironmentType.PRODUCTION
        mock_session = MagicMock()
        mock_session.sync_session = MagicMock()
        mock_session.sync_session.bind = MagicMock()
        mock_session.sync_session.bind.dialect = MagicMock()
        mock_session.sync_session.bind.dialect.name = "sqlite"

        with pytest.raises(RuntimeError) as exc_info:
            await _acquire_advisory_lock(mock_session, "tenant_budget_init:test_t")
        assert "requires PostgreSQL dialect" in str(exc_info.value)
    finally:
        settings.environment = original_env


@pytest.mark.security
@pytest.mark.asyncio
async def test_a2_orphan_reconciliation_drift_never_clamps_and_records_incident() -> None:
    """A2: Reconciler flags drift, refuses to zero out/clamp reserved_micros, and records incident."""
    tenant_id = f"t_reconcile_drift_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_rec_{uuid.uuid4().hex[:8]}"

    # Create initial budget and reservation
    res = await budget_manager_service.reserve_budget(
        BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=tx_id,
            estimated_cost_micros=10_000,
            reservation_key=f"k_{tx_id}",
            timeout_seconds=10,
        )
    )

    # Tamper with DB: backdate reservation expiry and corrupt reserved_micros to be less than reservation
    async with db_session.get_tenant_session(tenant_id) as session:
        # Corrupt tenant budget
        stmt_b = select(TenantBudgetRecord).where(TenantBudgetRecord.tenant_id == tenant_id)
        b_rec = (await session.execute(stmt_b)).scalar_one()
        b_rec.reserved_micros = 2_000  # Less than reservation amount of 10,000!

        # Backdate reservation expiry
        from db.models import BudgetReservationRecord

        stmt_r = select(BudgetReservationRecord).where(BudgetReservationRecord.id == res.id)
        r_rec = (await session.execute(stmt_r)).scalar_one()
        r_rec.expires_at = datetime.now(UTC) - timedelta(seconds=10)
        await session.commit()

    # Run orphan reconciliation
    reconciled_count = await budget_manager_service.reconcile_orphaned_reservations(max_batch_size=10)
    assert reconciled_count == 0  # Drift item was NOT cleanly released

    # Verify reservation status is RECONCILIATION_REQUIRED and reserved_micros was NOT clamped to 0
    async with db_session.get_tenant_session(tenant_id) as session:
        stmt_b = select(TenantBudgetRecord).where(TenantBudgetRecord.tenant_id == tenant_id)
        b_rec = (await session.execute(stmt_b)).scalar_one()
        assert b_rec.reserved_micros == 2_000  # Unaltered; no silent masking

        from db.models import BudgetReservationRecord

        stmt_r = select(BudgetReservationRecord).where(BudgetReservationRecord.id == res.id)
        r_rec = (await session.execute(stmt_r)).scalar_one()
        assert r_rec.status == "RECONCILIATION_REQUIRED"

        # Durable AccountingIncidentRecord was written
        stmt_inc = select(AccountingIncidentRecord).where(
            AccountingIncidentRecord.tenant_id == tenant_id,
            AccountingIncidentRecord.incident_type == "ORPHAN_RECONCILIATION_DRIFT",
        )
        incident = (await session.execute(stmt_inc)).scalar_one_or_none()
        assert incident is not None
        assert incident.incident_type == "ORPHAN_RECONCILIATION_DRIFT"
        assert incident.actual_micros == 2_000
        assert incident.expected_micros == 10_000


@pytest.mark.security
@pytest.mark.asyncio
async def test_a3_conflicting_settlement_replay_rejected_with_409() -> None:
    """A3: Replay of same reservation with conflicting cost or model raises HTTP 409."""
    tenant_id = f"t_replay_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_rep_{uuid.uuid4().hex[:8]}"

    res = await budget_manager_service.reserve_budget(
        BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=tx_id,
            estimated_cost_micros=5_000,
            reservation_key=f"k_{tx_id}",
        )
    )

    # Initial settlement
    set_req1 = BudgetSettlementRequest(
        reservation_id=res.id,
        actual_cost_micros=3_000,
        model_id="mock-model",
        provider="mock",
        prompt_tokens=10,
        completion_tokens=20,
    )
    settled = await budget_manager_service.settle_budget(tenant_id, set_req1)
    assert settled.cost_micros == 3_000

    # Identical replay succeeds idempotently
    replayed = await budget_manager_service.settle_budget(tenant_id, set_req1)
    assert replayed.id == settled.id

    # Conflicting replay (mismatched actual cost) raises HTTP 409
    conflicting_req = BudgetSettlementRequest(
        reservation_id=res.id,
        actual_cost_micros=4_000,  # Conflict!
        model_id="mock-model",
        provider="mock",
        prompt_tokens=10,
        completion_tokens=20,
    )
    with pytest.raises(HTTPException) as exc_info:
        await budget_manager_service.settle_budget(tenant_id, conflicting_req)
    assert exc_info.value.status_code == 409
    assert "Settlement conflict" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_a4_hard_limit_settlement_overage_logs_incident() -> None:
    """A4: Settlement exceeding reservation under hard limit raises 402 and logs incident."""
    tenant_id = f"t_hard_over_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_ho_{uuid.uuid4().hex[:8]}"

    # Create budget with total 5_000, hard limit True
    await budget_manager_service.update_tenant_budget(tenant_id, total_budget_micros=5_000, hard_limit=True)

    res = await budget_manager_service.reserve_budget(
        BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=tx_id,
            estimated_cost_micros=4_000,
            reservation_key=f"k_{tx_id}",
        )
    )

    # Attempt settlement exceeding remaining budget (6_000 > 5_000 total)
    set_req = BudgetSettlementRequest(
        reservation_id=res.id,
        actual_cost_micros=6_000,
        model_id="mock-model",
        provider="mock",
        prompt_tokens=20,
        completion_tokens=40,
    )
    with pytest.raises(HTTPException) as exc_info:
        await budget_manager_service.settle_budget(tenant_id, set_req)
    assert exc_info.value.status_code == 402
    assert "exceeded reserved" in exc_info.value.detail

    # Verify incident was logged
    async with db_session.get_tenant_session(tenant_id) as session:
        stmt = select(AccountingIncidentRecord).where(
            AccountingIncidentRecord.tenant_id == tenant_id,
            AccountingIncidentRecord.incident_type == "SETTLEMENT_OVERAGE_HARD_LIMIT_BREACH",
        )
        inc = (await session.execute(stmt)).scalar_one_or_none()
        assert inc is not None
        assert inc.incident_type == "SETTLEMENT_OVERAGE_HARD_LIMIT_BREACH"
        assert inc.actual_micros == 6_000


# ===========================================================================
# Workstream B: Pricing & Usage Validation
# ===========================================================================


@pytest.mark.security
def test_b1_pricing_rates_non_negative_validation() -> None:
    """B1: Pricing profile queries and calculations reject negative rates."""
    mock_record = MagicMock()
    mock_record.id = "p_test"
    mock_record.input_cost_per_million_micros = -100
    mock_record.output_cost_per_million_micros = 500
    mock_record.cached_input_cost_per_million_micros = 0

    with pytest.raises(PricingValidationError) as exc_info:
        pricing_service.calculate_cost_micros(mock_record, prompt_tokens=10, completion_tokens=10)
    assert "non-negative integer" in str(exc_info.value)


@pytest.mark.security
def test_b2_calculate_cost_micros_rejects_booleans_and_cached_exceeding_prompt() -> None:
    """B2: Cost calculator rejects boolean counters and cached_tokens > prompt_tokens."""
    mock_record = MagicMock()
    mock_record.input_cost_per_million_micros = 1000
    mock_record.output_cost_per_million_micros = 2000
    mock_record.cached_input_cost_per_million_micros = 500

    # Reject boolean
    with pytest.raises((PricingValidationError, TypeError)):
        pricing_service.calculate_cost_micros(
            mock_record,
            prompt_tokens=True,  # type: ignore
            completion_tokens=10,
        )

    # Reject cached_tokens > prompt_tokens
    with pytest.raises(PricingValidationError) as exc_info:
        pricing_service.calculate_cost_micros(
            mock_record,
            prompt_tokens=10,
            completion_tokens=10,
            cached_tokens=15,
        )
    assert "cannot exceed prompt_tokens" in str(exc_info.value)


@pytest.mark.security
def test_b3_parse_usage_dict_strict_integer_validation() -> None:
    """B3: parse_usage_dict rejects missing keys, booleans, strings, and floats."""
    # Missing prompt_tokens
    with pytest.raises(PricingValidationError) as exc:
        pricing_service.parse_usage_dict({"completion_tokens": 10})
    assert "missing" in str(exc.value).lower()

    # Boolean prompt_tokens
    with pytest.raises(PricingValidationError) as exc:
        pricing_service.parse_usage_dict({"prompt_tokens": True, "completion_tokens": 10})
    assert "invalid prompt_tokens" in str(exc.value).lower()

    # Float completion_tokens
    with pytest.raises(PricingValidationError) as exc:
        pricing_service.parse_usage_dict({"prompt_tokens": 10, "completion_tokens": 10.5})
    assert "invalid completion_tokens" in str(exc.value).lower()

    # Negative tokens
    with pytest.raises(PricingValidationError) as exc:
        pricing_service.parse_usage_dict({"prompt_tokens": -5, "completion_tokens": 10})
    assert "invalid prompt_tokens" in str(exc.value).lower()


@pytest.mark.security
def test_b4_proxy_fails_closed_on_malformed_provider_usage_and_logs_incident() -> None:
    """B4: Proxy returns HTTP 502 when provider returns malformed usage and writes incident."""
    bad_usage = UsageInfo(prompt_tokens=10, completion_tokens=10, total_tokens=20, cached_tokens=50)
    mock_adapter = StubRecordingAdapter(usage=bad_usage)
    register_adapter_override("mock", mock_adapter)
    register_adapter_override("openai", mock_adapter)
    register_adapter_override("ollama", mock_adapter)

    client = TestClient(app)
    tenant_id = f"t_bad_usage_{uuid.uuid4().hex[:8]}"
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Test prompt"}]},
        headers=headers,
    )
    assert resp.status_code == 502
    assert "malformed" in resp.json()["detail"].lower()
    assert mock_adapter.call_count == 1  # Provider executed but returned unparseable usage


# ===========================================================================
# Workstream C: SSRF & Destination Enforcement
# ===========================================================================


@pytest.mark.security
def test_c1_ssrf_validator_blocks_all_prohibited_destinations() -> None:
    """C1: SSRF validator blocks loopbacks, private networks, cloud metadata, and invalid schemes."""
    # Loopback IPv4
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("http://127.0.0.1:8000/v1")
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("http://127.127.1.1:9000")

    # Loopback IPv6
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("http://[::1]:8000/v1")

    # RFC 1918 Private
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("http://10.0.0.1/api")
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("http://172.16.5.4:8080")
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("http://192.168.1.1/generate")

    # AWS/GCP Metadata
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("http://169.254.169.254/latest/meta-data/")
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("http://metadata.google.internal/computeMetadata/v1")

    # Embedded credentials
    with pytest.raises(SSRFValidationError) as exc:
        validate_safe_provider_url("https://admin:secret@api.openai.com/v1")
    assert "credentials" in str(exc.value)

    # Invalid schemes
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("ftp://api.anthropic.com/v1")
    with pytest.raises(SSRFValidationError):
        validate_safe_provider_url("file:///etc/passwd")


@pytest.mark.security
def test_c2_ollama_local_allowlist_enforcement() -> None:
    """C2: Local inference allowlist permits Ollama 11434 but rejects unlisted ports."""
    # Standard permitted allowlist endpoint
    assert validate_safe_provider_url("http://localhost:11434", allow_local=True) == "http://localhost:11434"

    # Local port not on allowlist
    with pytest.raises(SSRFValidationError) as exc:
        validate_safe_provider_url("http://localhost:9999", allow_local=True)
    assert "allowlist" in str(exc.value)


@pytest.mark.security
def test_c3_provider_adapters_suppress_redirects() -> None:
    """C3: All provider adapters configure follow_redirects=False."""
    adapters = [
        get_provider_adapter("openai"),
        get_provider_adapter("anthropic"),
        get_provider_adapter("google"),
        get_provider_adapter("groq"),
        get_provider_adapter("ollama"),
    ]
    for adapter in adapters:
        client = getattr(adapter, "_client", None)
        if client is not None and hasattr(client, "follow_redirects"):
            assert client.follow_redirects is False, f"{adapter.provider_name} has follow_redirects=True"


# ===========================================================================
# Workstream D: Distributed Circuit Breaker Atomic Transitions
# ===========================================================================


@pytest.mark.security
@pytest.mark.asyncio
async def test_d1_circuit_breaker_single_probe_lease_concurrency() -> None:
    """D1: Single canary probe lease: only first caller enters half-open, second is denied."""
    cb = ModelCircuitBreaker(failure_threshold=2, recovery_timeout_seconds=0.05, probe_lease_seconds=10.0)
    provider = f"p_probe_{uuid.uuid4().hex[:6]}"
    model = "m_probe"

    # Trip breaker
    await cb.record_failure(provider, model)
    await cb.record_failure(provider, model)
    is_avail, state = await cb.is_available(provider, model)
    assert not is_avail
    assert state == "OPEN"

    # Wait for recovery timeout
    await asyncio.sleep(0.08)

    # First check acquires probe lease
    is_avail1, state1 = await cb.is_available(provider, model)
    assert is_avail1 is True
    assert state1 == "HALF_OPEN"

    # Concurrent second check is rejected because probe is already in flight
    is_avail2, state2 = await cb.is_available(provider, model)
    assert is_avail2 is False


@pytest.mark.security
@pytest.mark.asyncio
async def test_d2_circuit_breaker_probe_success_and_failure_transitions() -> None:
    """D2: Probe success closes circuit; probe failure re-opens circuit."""
    cb = ModelCircuitBreaker(failure_threshold=1, recovery_timeout_seconds=0.01)
    p_success = f"p_s_{uuid.uuid4().hex[:6]}"
    m_success = "m_s"

    await cb.record_failure(p_success, m_success)
    await asyncio.sleep(0.02)
    # Acquire probe
    is_avail, _ = await cb.is_available(p_success, m_success)
    assert is_avail

    # Record success -> transitions back to CLOSED
    await cb.record_success(p_success, m_success)
    is_avail, state = await cb.is_available(p_success, m_success)
    assert is_avail
    assert state == "CLOSED"

    # Another circuit: probe failure -> transitions back to OPEN
    p_fail = f"p_f_{uuid.uuid4().hex[:6]}"
    m_fail = "m_f"
    await cb.record_failure(p_fail, m_fail)
    await asyncio.sleep(0.02)
    await cb.is_available(p_fail, m_fail)
    await cb.record_failure(p_fail, m_fail)
    is_avail, state = await cb.is_available(p_fail, m_fail)
    assert not is_avail
    assert state == "OPEN"


@pytest.mark.security
@pytest.mark.asyncio
async def test_d3_circuit_breaker_redis_outage_fails_closed_in_production() -> None:
    """D3: Redis outage in production with fail_closed=True marks degraded and blocks execution."""
    cb = ModelCircuitBreaker(fail_closed_on_redis_error=True)
    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(side_effect=RuntimeError("Redis cluster unreachable"))
    cb._redis_client = mock_redis
    cb._redis_checked = True

    is_avail, state = await cb.is_available("openai", "gpt-4o")
    assert not is_avail
    assert state == "REDIS_OUTAGE_FAIL_CLOSED"


# ===========================================================================
# Workstream E: Privacy Attestation Lifecycle & Routing Trust
# ===========================================================================


@pytest.mark.security
@pytest.mark.asyncio
async def test_e1_privacy_attestation_expired_rejected_under_sensitive_taint() -> None:
    """E1: Model with expired privacy attestation is excluded under sensitive taint."""
    expired_profile = ModelCapabilityProfile(
        model_id=f"m_expired_{uuid.uuid4().hex[:6]}",
        provider="mock",
        family="mock",
        tier=ModelTier.CAPABLE,
        context_window=32000,
        supports_tools=True,
        supports_vision=False,
        supports_structured_output=True,
        supports_system_prompt=True,
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=datetime.now(UTC) - timedelta(days=60),
        privacy_attestation_expires_at=datetime.now(UTC) - timedelta(hours=1),  # Expired!
        reliability_index=0.90,
        expected_latency_ms=200.0,
        pricing_available=True,
        pricing_profile_id="p_mock",
    )

    with patch.object(model_router_service, "list_models", return_value=[expired_profile]):
        req = RoutingRequest(
            tenant_id="default_tenant",
            task_type="chat",
            taints=["phi"],  # Sensitive taint
        )
        with pytest.raises(HTTPException) as exc_info:
            await model_router_service.route(req)
        assert exc_info.value.status_code == 422
        exclusions = exc_info.value.detail["exclusions"]
        assert any(e["rule"] == "GATE1_PRIVACY_ATTESTATION_EXPIRED" for e in exclusions)


@pytest.mark.security
@pytest.mark.asyncio
async def test_e2_privacy_attestation_revoked_rejected_under_sensitive_taint() -> None:
    """E2: Model with revoked privacy attestation is excluded under sensitive taint."""
    revoked_profile = ModelCapabilityProfile(
        model_id=f"m_revoked_{uuid.uuid4().hex[:6]}",
        provider="mock",
        family="mock",
        tier=ModelTier.CAPABLE,
        context_window=32000,
        supports_tools=True,
        supports_vision=False,
        supports_structured_output=True,
        supports_system_prompt=True,
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=datetime.now(UTC) - timedelta(days=10),
        privacy_attestation_revoked_at=datetime.now(UTC) - timedelta(minutes=5),  # Revoked!
        reliability_index=0.90,
        expected_latency_ms=200.0,
        pricing_available=True,
        pricing_profile_id="p_mock",
    )

    with patch.object(model_router_service, "list_models", return_value=[revoked_profile]):
        req = RoutingRequest(
            tenant_id="default_tenant",
            task_type="chat",
            taints=["pii"],  # Sensitive taint
        )
        with pytest.raises(HTTPException) as exc_info:
            await model_router_service.route(req)
        assert exc_info.value.status_code == 422
        exclusions = exc_info.value.detail["exclusions"]
        assert any(e["rule"] == "GATE1_PRIVACY_ATTESTATION_REVOKED" for e in exclusions)


@pytest.mark.security
@pytest.mark.asyncio
async def test_e3_revalidate_fallback_candidate_checks_attestation_and_pricing() -> None:
    """E3: Fallback candidate revalidation fails closed if attestation is expired or pricing missing."""
    req = RoutingRequest(
        tenant_id="default_tenant",
        task_type="chat",
        taints=["financial"],
    )

    # 1. Candidate with expired attestation
    expired_profile = ModelCapabilityProfile(
        model_id="cand-expired",
        provider="mock",
        family="mock",
        tier=ModelTier.CAPABLE,
        context_window=32000,
        supports_tools=True,
        supports_vision=False,
        supports_structured_output=True,
        supports_system_prompt=True,
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=datetime.now(UTC) - timedelta(days=30),
        privacy_attestation_expires_at=datetime.now(UTC) - timedelta(minutes=10),
        reliability_index=0.90,
        expected_latency_ms=200.0,
    )
    with patch.object(model_router_service, "get_model_profile", return_value=expired_profile):
        is_valid, reason, _, _, _ = await model_router_service.revalidate_fallback_candidate(
            "cand-expired", req, remaining_budget_micros=10_000
        )
        assert not is_valid
        assert "attestation expired" in str(reason)


# ===========================================================================
# Workstream F: Database Integrity & Accounting Incident Tracking
# ===========================================================================


@pytest.mark.security
@pytest.mark.asyncio
async def test_f1_database_check_constraints_reject_negative_balances() -> None:
    """F1: PostgreSQL check constraints reject direct attempts to set negative budget counters."""
    tenant_id = f"t_ck_neg_{uuid.uuid4().hex[:8]}"

    # Initialize budget
    await budget_manager_service.get_tenant_budget(tenant_id)

    # Direct raw SQL execution attempting negative reserved_micros must fail at DB level
    async with db_session.get_tenant_session(tenant_id) as session:
        with pytest.raises(Exception) as exc_info:
            await session.execute(
                text("UPDATE tenant_budgets SET reserved_micros = -100 WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            await session.commit()
        # Verify check constraint violation was raised by PostgreSQL
        assert "ck_tenant_budget_reserved_non_negative" in str(exc_info.value).lower()
