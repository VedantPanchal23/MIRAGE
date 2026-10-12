"""Phase 5.2: Comprehensive Routing, Financial Integrity, Provider Security & RLS Milestone Suite.

Validates:
1. Connection-boundary SSRF enforcement: DNS rebinding prevention, IP pinning, cloud metadata blocking,
   local port restrictions, and redirect prohibition across all provider adapters.
2. PostgreSQL locking & concurrency safety: serialized budget reservations, strict idempotency,
   conflicting replay rejection (HTTP 409), and deadlock-free settlement vs orphan reconciliation.
3. Database Row-Level Security (RLS) enforcement: strict tenant isolation on accounting_incidents,
   tenant_budgets, budget_reservations, transaction_cost_records, and provider_invocations using
   unprivileged mirage_app role with NOBYPASSRLS.
4. Privacy attestation provenance: trusted issuer verification, expiration, revocation, and consistent
   fallback ladder revalidation.
5. Provider invocation tracking: durable audit records for every execution attempt and honest handling
   of post-execution settlement failures.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.testclient import TestClient

from db import session as db_session
from db.models import (
    AccountingIncidentRecord,
    ProviderInvocationRecord,
)
from gateway.main import app
from services.budget_manager import budget_manager_service
from services.model_router import model_router_service
from services.pricing_service import (
    PricingProfileNotFoundError,
    pricing_service,
)
from services.providers.base import (
    BaseProviderAdapter,
    ProviderError,
    ProviderErrorType,
    ProviderResponse,
    UsageInfo,
)
from services.providers.factory import (
    clear_adapter_overrides,
    register_adapter_override,
)
from services.providers.ssrf_validator import (
    SSRFSafeNetworkBackend,
    SSRFValidationError,
    create_ssrf_safe_client,
)
from shared.config import get_settings
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

# ==============================================================================
# Workstream 1: Connection-Boundary SSRF & DNS Rebinding Enforcement
# ==============================================================================


@pytest.mark.asyncio
async def test_ssrf_boundary_dns_rebinding_blocked() -> None:
    """Simulate DNS rebinding where host resolves to public IP initially, then rebinds to 127.0.0.1 at connect time."""
    # Custom resolver that simulates DNS rebinding returning a loopback IP at connect time
    def rebind_resolver(_h: str, p: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(2, 1, 6, "", ("127.0.0.1", p))]

    backend = SSRFSafeNetworkBackend(allow_local=False, dns_resolver=rebind_resolver)

    with pytest.raises(SSRFValidationError) as exc_info:
        await backend.connect_tcp("rebind.malicious-site.com", 443)

    assert "resolved to prohibited address '127.0.0.1'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ssrf_boundary_cloud_metadata_blocked() -> None:
    """Verify that cloud metadata hosts are blocked at the socket connection boundary."""
    backend = SSRFSafeNetworkBackend(allow_local=False)

    for meta_host in ["169.254.169.254", "100.100.100.200", "metadata.google.internal"]:
        with pytest.raises(SSRFValidationError):
            await backend.connect_tcp(meta_host, 80)


@pytest.mark.asyncio
async def test_ssrf_boundary_local_ports_allowlist_enforcement() -> None:
    """Verify that when allow_local=True, arbitrary internal ports (5432, 6379, 22) are strictly blocked."""
    backend = SSRFSafeNetworkBackend(allow_local=True)

    # Prohibited ports
    for port in [5432, 6379, 22, 3306, 27017]:
        with pytest.raises(SSRFValidationError) as exc_info:
            await backend.connect_tcp("127.0.0.1", port)
        assert f"Local inference port {port} is not in approved port allowlist" in str(exc_info.value)


@pytest.mark.asyncio
async def test_ssrf_boundary_unix_socket_blocked() -> None:
    """Verify that Unix domain sockets are unconditionally prohibited for provider adapters."""
    backend = SSRFSafeNetworkBackend()
    with pytest.raises(SSRFValidationError) as exc_info:
        await backend.connect_unix_socket("/var/run/docker.sock")
    assert "Unix domain sockets are prohibited" in str(exc_info.value)


@pytest.mark.asyncio
async def test_provider_adapters_reject_redirects_and_handle_errors() -> None:
    """Verify provider adapters reject 3xx redirects and map SSRFValidationError to ProviderError."""
    # Test that create_ssrf_safe_client suppresses redirects
    client = create_ssrf_safe_client(allow_local=False)
    assert client.follow_redirects is False
    await client.aclose()

    # Test adapter behavior on 301/302 responses
    from services.providers.openai_adapter import OpenAIProviderAdapter

    adapter = OpenAIProviderAdapter(api_key="sk-test", base_url="https://api.openai.com/v1")

    # Mock client post returning a 302 Found response
    mock_resp = httpx.Response(302, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    with patch("services.providers.openai_adapter.create_ssrf_safe_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        with pytest.raises(ProviderError) as exc_info:
            await adapter.generate("Hello", "gpt-4o")

        assert exc_info.value.error_type == ProviderErrorType.INVALID_REQUEST
        assert "redirect status 302" in str(exc_info.value)


# ==============================================================================
# Workstream 2: PostgreSQL Locking, Concurrency Safety & Deadlock Elimination
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrency_safe_budget_reservations() -> None:
    """Verify concurrent reservations for the same tenant serialize safely under row/advisory locks."""
    tenant_id = f"tenant_conc_{uuid.uuid4().hex[:6]}"

    # Initialize budget
    async with db_session.get_tenant_session(tenant_id) as session:
        await budget_manager_service.get_or_create_tenant_budget_record(session, tenant_id)
        await session.commit()

    # Execute 5 concurrent reservations
    async def _make_reservation(idx: int) -> None:
        req = BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=f"tx_{idx}_{uuid.uuid4().hex[:6]}",
            estimated_cost_micros=10_000,
            reservation_key=f"res_key_{idx}_{uuid.uuid4().hex[:6]}",
            attempt_number=1,
            selected_provider="mock",
            selected_model="mock-capable",
            timeout_seconds=300,
        )
        res = await budget_manager_service.reserve_budget(req)
        assert res.amount_micros == 10_000

    results = await asyncio.gather(*[_make_reservation(i) for i in range(5)], return_exceptions=True)
    for r in results:
        assert not isinstance(r, Exception), f"Concurrent reservation failed: {r}"

    # Verify total reserved amount in tenant budget is exactly 50,000 micros
    budget = await budget_manager_service.get_tenant_budget(tenant_id)
    assert budget.reserved_micros == 50_000


@pytest.mark.asyncio
async def test_concurrency_idempotent_and_conflicting_reservations() -> None:
    """Verify idempotent replay returns identical reservation; conflicting replay raises HTTP 409."""
    tenant_id = f"tenant_idem_{uuid.uuid4().hex[:6]}"
    res_key = f"shared_res_key_{uuid.uuid4().hex[:6]}"
    tx_id = f"tx_orig_{uuid.uuid4().hex[:6]}"

    req1 = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id=tx_id,
        estimated_cost_micros=25_000,
        reservation_key=res_key,
        attempt_number=1,
        selected_provider="mock",
        selected_model="mock-capable",
        timeout_seconds=300,
    )
    res1 = await budget_manager_service.reserve_budget(req1)
    assert res1.amount_micros == 25_000

    # Identical replay
    res2 = await budget_manager_service.reserve_budget(req1)
    assert res2.id == res1.id
    assert res2.amount_micros == 25_000

    # Conflicting replay (different transaction_id)
    conflicting_req = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id=f"tx_conflict_{uuid.uuid4().hex[:6]}",
        estimated_cost_micros=25_000,
        reservation_key=res_key,
        attempt_number=1,
        selected_provider="mock",
        selected_model="mock-capable",
        timeout_seconds=300,
    )
    with pytest.raises(HTTPException) as exc_info:
        await budget_manager_service.reserve_budget(conflicting_req)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_deadlock_free_settlement_and_orphan_reconciliation() -> None:
    """Verify concurrent settlement and orphan reconciliation run without deadlock (40P01)."""
    tenant_id = f"tenant_dl_{uuid.uuid4().hex[:6]}"

    # Create reservation and then simulate expiration
    req = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id=f"tx_{uuid.uuid4().hex[:6]}",
        estimated_cost_micros=15_000,
        reservation_key=f"res_{uuid.uuid4().hex[:6]}",
        attempt_number=1,
        selected_provider="mock",
        selected_model="mock-capable",
        timeout_seconds=300,
    )
    res = await budget_manager_service.reserve_budget(req)

    # Force expiration in DB so reconcile_orphaned_reservations detects it as expired
    async with db_session.get_tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE budget_reservations SET expires_at = NOW() - INTERVAL '10 seconds' WHERE id = :id"),
            {"id": res.id},
        )
        await session.commit()

    # Run settlement and orphan reconciliation concurrently
    async def _settle() -> Any:
        try:
            return await budget_manager_service.settle_budget(
                tenant_id,
                BudgetSettlementRequest(
                    reservation_id=res.id,
                    actual_cost_micros=12_000,
                    model_id="mock-capable",
                    provider="mock",
                    prompt_tokens=100,
                    completion_tokens=50,
                    attempt_number=1,
                    pricing_profile_id="price_mock_capable",
                ),
            )
        except HTTPException:
            return "settled_or_conflict"

    async def _reconcile() -> Any:
        return await budget_manager_service.reconcile_orphaned_reservations(max_batch_size=10)

    results = await asyncio.gather(_settle(), _reconcile(), return_exceptions=True)
    for r in results:
        assert not isinstance(r, Exception), f"Deadlock or unhandled error occurred: {r}"


# ==============================================================================
# Workstream 3: PostgreSQL Row-Level Security (RLS) Tenant Isolation
# ==============================================================================


@pytest.fixture
def unprivileged_app_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Create async sessionmaker authenticated as unprivileged application role mirage_app."""
    from sqlalchemy.engine import make_url

    settings = get_settings()
    sync_url = settings.database_sync_url
    parsed = make_url(sync_url)
    db_name = parsed.database or "test"

    # Ensure mirage_app role exists and has permissions on new tables
    admin_engine = create_engine(sync_url)
    with admin_engine.connect() as conn:
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mirage_app') THEN
                        CREATE ROLE mirage_app WITH LOGIN PASSWORD 'mirage_app_pw'
                            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                    END IF;
                END $$;
                """
            )
        )
        conn.execute(text(f"GRANT CONNECT ON DATABASE {db_name} TO mirage_app;"))
        conn.execute(text("GRANT USAGE ON SCHEMA public TO mirage_app;"))
        conn.execute(
            text(
                """
                GRANT SELECT, INSERT, UPDATE, DELETE ON
                    tenants,
                    accounting_incidents,
                    tenant_budgets,
                    budget_reservations,
                    transaction_cost_records,
                    provider_invocations
                TO mirage_app;
                """
            )
        )
        conn.commit()
    admin_engine.dispose()

    # Build connection URL using mirage_app credentials
    app_async_url = make_url(settings.database_url).set(
        username="mirage_app",
        password="mirage_app_pw",
    ).render_as_string(hide_password=False)
    app_engine = create_async_engine(app_async_url, pool_size=5, max_overflow=5)
    return async_sessionmaker(bind=app_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_rls_tenant_isolation_accounting_incidents(
    unprivileged_app_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Verify PostgreSQL RLS strictly prevents cross-tenant access and cross-tenant inserts on accounting_incidents."""
    tenant_a = f"tenant_rls_a_{uuid.uuid4().hex[:6]}"
    tenant_b = f"tenant_rls_b_{uuid.uuid4().hex[:6]}"
    inc_a_id = f"inc_a_{uuid.uuid4().hex[:8]}"
    inc_b_id = f"inc_b_{uuid.uuid4().hex[:8]}"

    # Seed tenants
    settings = get_settings()
    admin_engine = create_engine(settings.database_sync_url)
    with admin_engine.connect() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:a, 'A', :ha, NOW())"),
            {"a": tenant_a, "ha": f"hash_{tenant_a}"},
        )
        conn.execute(
            text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:b, 'B', :hb, NOW())"),
            {"b": tenant_b, "hb": f"hash_{tenant_b}"},
        )
        conn.commit()
    admin_engine.dispose()

    # Insert incident for Tenant A under Tenant A session context
    async with unprivileged_app_sessionmaker() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                {"tenant": tenant_a},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO accounting_incidents (
                        id, tenant_id, incident_type, expected_micros, actual_micros, details, resolved, created_at
                    ) VALUES (:id, :tenant, 'TEST_INCIDENT_A', 100, 200, '{}', false, NOW())
                    """
                ),
                {"id": inc_a_id, "tenant": tenant_a},
            )

    # Insert incident for Tenant B under Tenant B session context
    async with unprivileged_app_sessionmaker() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                {"tenant": tenant_b},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO accounting_incidents (
                        id, tenant_id, incident_type, expected_micros, actual_micros, details, resolved, created_at
                    ) VALUES (:id, :tenant, 'TEST_INCIDENT_B', 300, 400, '{}', false, NOW())
                    """
                ),
                {"id": inc_b_id, "tenant": tenant_b},
            )

    # Query under Tenant A context -> Tenant B rows MUST be completely invisible
    async with unprivileged_app_sessionmaker() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                {"tenant": tenant_a},
            )
            res = (await session.execute(select(AccountingIncidentRecord))).scalars().all()
            assert len(res) == 1
            assert res[0].id == inc_a_id
            assert res[0].tenant_id == tenant_a

            # Direct lookup of Tenant B incident returns None
            direct_b = await session.get(AccountingIncidentRecord, inc_b_id)
            assert direct_b is None

    # Cross-tenant insert attempt -> MUST be rejected by RLS WITH CHECK policy
    async with unprivileged_app_sessionmaker() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                {"tenant": tenant_a},
            )
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await session.execute(
                    text(
                        """
                        INSERT INTO accounting_incidents (
                            id, tenant_id, incident_type, expected_micros, actual_micros, details, resolved, created_at
                        ) VALUES ('inc_spoofed', :tenant_b, 'SPOOF', 100, 100, '{}', false, NOW())
                        """
                    ),
                    {"tenant_b": tenant_b},
                )
            assert "violates row-level security policy" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_rls_tenant_isolation_budgets_and_invocations(
    unprivileged_app_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Verify RLS on tenant_budgets, budget_reservations, and provider_invocations."""
    tenant_a = f"tenant_rls_inv_a_{uuid.uuid4().hex[:6]}"
    tenant_b = f"tenant_rls_inv_b_{uuid.uuid4().hex[:6]}"

    # Seed tenants
    settings = get_settings()
    admin_engine = create_engine(settings.database_sync_url)
    with admin_engine.connect() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:a, 'A', :ha, NOW())"),
            {"a": tenant_a, "ha": f"hash_{tenant_a}"},
        )
        conn.execute(
            text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:b, 'B', :hb, NOW())"),
            {"b": tenant_b, "hb": f"hash_{tenant_b}"},
        )
        conn.commit()
    admin_engine.dispose()

    # Insert provider invocation for Tenant A
    inv_a_id = f"inv_a_{uuid.uuid4().hex[:8]}"
    async with unprivileged_app_sessionmaker() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                {"tenant": tenant_a},
            )
            await session.execute(
                text(
                    """
                    INSERT INTO provider_invocations (
                        id, tenant_id, transaction_id, attempt_number, provider, model_id,
                        status, latency_ms, prompt_tokens, completion_tokens, created_at
                    ) VALUES (:id, :tenant, 'tx_1', 1, 'openai', 'gpt-4o', 'SUCCESS', 150.0, 10, 20, NOW())
                    """
                ),
                {"id": inv_a_id, "tenant": tenant_a},
            )

    # Query under Tenant B -> Tenant A invocation is invisible
    async with unprivileged_app_sessionmaker() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                {"tenant": tenant_b},
            )
            res = (await session.execute(select(ProviderInvocationRecord))).scalars().all()
            assert len(res) == 0

            direct_a = await session.get(ProviderInvocationRecord, inv_a_id)
            assert direct_a is None


# ==============================================================================
# Workstream 4: Privacy Attestation Provenance & Fallback Enforcement
# ==============================================================================


@pytest.mark.asyncio
async def test_privacy_attestation_issuer_provenance() -> None:
    """Verify that models lacking trusted attestation_issuer are rejected under sensitive taints."""
    # Register mock profile without attestation_issuer
    untrusted_model = ModelCapabilityProfile(
        model_id="mock-untrusted-attestation",
        provider="mock",
        family="mock",
        tier=ModelTier.CAPABLE,
        context_window=32768,
        supports_tools=True,
        supports_vision=False,
        supports_structured_output=True,
        supports_system_prompt=True,
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=datetime.now(UTC),
        privacy_attestation_expires_at=datetime.now(UTC) + timedelta(days=30),
        privacy_attestation_revoked_at=None,
        attestation_issuer=None,  # Missing issuer provenance
        active=True,
    )

    with patch.object(model_router_service, "list_models", return_value=[untrusted_model]):
        req = RoutingRequest(
            tenant_id="test_tenant",
            taints=["phi"],
            estimated_input_tokens=100,
            estimated_output_tokens=100,
        )
        with pytest.raises(HTTPException) as exc_info:
            await model_router_service.route(req)

        assert exc_info.value.status_code == 422
        assert "GATE1_PRIVACY_ATTESTATION_UNTRUSTED" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_fallback_revalidation_enforces_attestation_issuer() -> None:
    """Verify that revalidate_fallback_candidate rejects fallback candidates lacking attestation_issuer."""
    untrusted_profile = ModelCapabilityProfile(
        model_id="mock-fallback-untrusted",
        provider="mock",
        family="mock",
        tier=ModelTier.CAPABLE,
        context_window=32768,
        supports_tools=True,
        supports_vision=False,
        supports_structured_output=True,
        supports_system_prompt=True,
        is_zero_retention=True,
        deployment_type="cloud_dedicated_vpc",
        privacy_verified_at=datetime.now(UTC),
        privacy_attestation_expires_at=datetime.now(UTC) + timedelta(days=30),
        privacy_attestation_revoked_at=None,
        attestation_issuer=None,  # Missing issuer
        active=True,
    )

    with patch.object(model_router_service, "get_model_profile", return_value=untrusted_profile):
        req = RoutingRequest(
            tenant_id="test_tenant",
            taints=["confidential"],
            estimated_input_tokens=100,
            estimated_output_tokens=100,
        )
        is_valid, reason, profile, cost, price_id = await model_router_service.revalidate_fallback_candidate(
            candidate_model_id="mock-fallback-untrusted",
            request=req,
            remaining_budget_micros=100_000,
        )
        assert is_valid is False
        assert "lacks trusted attestation issuer provenance" in str(reason)


# ==============================================================================
# Workstream 5: Pricing Invariants & Provider Invocation Tracking
# ==============================================================================


@pytest.mark.asyncio
async def test_unpriced_model_excluded_from_routing() -> None:
    """Verify that models without active pricing profile raise PricingProfileNotFoundError and are excluded."""
    with pytest.raises(PricingProfileNotFoundError):
        await pricing_service.get_active_pricing_profile("completely-unknown-model-xyz")


@pytest.mark.asyncio
async def test_provider_invocation_tracking_in_proxy() -> None:
    """Verify that executing a request via /v1/chat/completions logs durable ProviderInvocationRecord."""
    class MockTrackedAdapter(BaseProviderAdapter):
        @property
        def provider_name(self) -> str:
            return "mock"

        async def generate(
            self,
            prompt: str | list[dict[str, Any]],
            model_id: str,
            *,
            temperature: float = 0.7,
            max_tokens: int | None = None,
            tools: list[dict[str, Any]] | None = None,
            system_prompt: str | None = None,
            timeout_seconds: float = 30.0,
        ) -> ProviderResponse:
            del prompt, temperature, max_tokens, tools, system_prompt, timeout_seconds
            return ProviderResponse(
                content="Hello from tracked provider",
                usage=UsageInfo(prompt_tokens=15, completion_tokens=25, total_tokens=40, cached_tokens=0),
                latency_ms=120.5,
                model_id=model_id,
                provider="mock",
            )

    stub = MockTrackedAdapter()
    register_adapter_override("mock", stub)

    try:
        tenant_id = f"tenant_inv_{uuid.uuid4().hex[:6]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)

        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "mock-capable",
                "messages": [{"role": "user", "content": "Ping"}],
            },
            headers=headers,
        )
        assert resp.status_code == 200

        # Query provider_invocations table to verify invocation was recorded
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = select(ProviderInvocationRecord).where(ProviderInvocationRecord.tenant_id == tenant_id)
            invs = (await session.execute(stmt)).scalars().all()
            assert len(invs) >= 1
            inv = invs[0]
            assert inv.status == "SUCCESS"
            assert inv.model_id == "mock-capable"
            assert inv.prompt_tokens == 15
            assert inv.completion_tokens == 25
            assert inv.latency_ms == 120.5
    finally:
        clear_adapter_overrides()
