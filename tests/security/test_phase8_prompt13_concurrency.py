"""Dedicated adversarial test suite for MIRAGE Phase 8 Prompt 13 Concurrency and Fencing Validation.

Validates:
1. Real lease conflict matrix across all concurrency modes (SHARED vs SHARED, SHARED vs EXCLUSIVE,
   EXCLUSIVE vs SHARED, EXCLUSIVE vs EXCLUSIVE, inactive/expired/released, re-entrancy, cross-tenant).
2. Monotonic fencing token progression and propagation across lifecycle boundaries.
3. Stale token rejection and delayed-request protection.
4. Parent-resource lease protection of child-resource actions.
5. Adapter classification: ENFORCED (conditional writes) vs MEDIATED_ONLY / UNSUPPORTED (external targets).
6. PostgreSQL advisory lock serialization invariants and dialect fail-closed enforcement.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import (
    ActionContract,
    AITransaction,
    ResourceLease,
)
from services.action_governor import GovernedToolProxy
from services.concurrency_service import (
    ResourceConcurrencyService,
    are_resources_in_conflict,
    canonicalize_resource_uri,
    derive_resource_advisory_lock_key,
)
from shared.config import EnvironmentType
from shared.schemas.action import (
    ActionState,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.concurrency import (
    ConcurrencyMode,
    LeaseStatus,
    ResourceLeaseAcquireRequest,
)
from shared.schemas.control_plane import Decision


@pytest.fixture(autouse=True)
def mock_agent_eligibility() -> Any:
    with patch(
        "services.concurrency_service.agent_governance_service.evaluate_agent_eligibility",
        return_value=(True, "Eligible"),
    ):
        yield


def _build_mock_session() -> AsyncMock:
    """Build mock AsyncSession with synchronous Result mocks."""
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    mock_exec = MagicMock()
    mock_exec.scalar_one_or_none.return_value = None
    mock_exec.scalar_one.return_value = 0
    mock_exec.scalars.return_value.all.return_value = []
    mock_exec.scalars.return_value.first.return_value = None
    mock_exec.all.return_value = []
    mock_exec.first.return_value = None
    session.execute.return_value = mock_exec

    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested.return_value = nested_cm

    return session


def _sample_auth(tenant_id: str = "tenant_alpha", agent_id: str = "agent_worker_1") -> AuthContext:
    return AuthContext(
        tenant_id=tenant_id,
        role=Role.OPERATOR,
        user_id="user_admin",
        identity_id=f"usr_{agent_id}",
        principal_type="agent",
        agent_id=agent_id,
        capabilities=frozenset(),
        is_authenticated=True,
        token_type="jwt",
    )


def _sample_active_lease(
    *,
    lease_id: str = "lse_active_1",
    tenant_id: str = "tenant_alpha",
    resource_uri: str = "db://postgres/finance/ledger",
    agent_id: str = "agent_worker_1",
    txn_id: str = "txn_100",
    mode: ConcurrencyMode = ConcurrencyMode.EXCLUSIVE,
    token: int = 1,
    status: LeaseStatus = LeaseStatus.ACQUIRED,
    expires_in_seconds: int = 300,
) -> ResourceLease:
    now = datetime.now(UTC)
    return ResourceLease(
        id=lease_id,
        tenant_id=tenant_id,
        resource_uri=canonicalize_resource_uri(resource_uri),
        holder_agent_id=agent_id,
        holder_transaction_id=txn_id,
        holder_handoff_id=None,
        concurrency_mode=mode.value,
        fencing_token=token,
        status=status.value,
        expires_at=now + timedelta(seconds=expires_in_seconds),
        released_at=None if status != LeaseStatus.RELEASED else now,
        created_at=now,
        updated_at=now,
    )


def _sample_transaction(
    tenant_id: str = "tenant_alpha",
    txn_id: str = "txn_100",
    agent_id: str = "agent_worker_1",
) -> AITransaction:
    now = datetime.now(UTC)
    return AITransaction(
        id=txn_id,
        tenant_id=tenant_id,
        actor_identity_id=f"usr_{agent_id}",
        agent_id=agent_id,
        parent_transaction_id=None,
        idempotency_key=f"idem_{txn_id}",
        correlation_id=f"corr_{txn_id}",
        state="ACTIVE",
        max_turns=10,
        turn_count=1,
        taint_flags=[],
        context_sources=[],
        policy_id=None,
        budget_id=None,
        final_disposition=None,
        version=0,
        created_at=now,
        updated_at=now,
    )


class TestRealLeaseConflictMatrix:
    """Verifies the complete 7-part conflict matrix across all supported concurrency modes."""

    def test_shared_vs_shared_no_conflict(self) -> None:
        """SHARED request against active SHARED lease must NOT conflict."""
        uri = "db://postgres/reports/monthly"
        assert not are_resources_in_conflict(
            uri,
            ConcurrencyMode.SHARED,
            uri,
            ConcurrencyMode.SHARED,
        )

    def test_shared_vs_exclusive_conflicts(self) -> None:
        """SHARED request against active EXCLUSIVE lease MUST conflict."""
        uri = "db://postgres/reports/monthly"
        assert are_resources_in_conflict(
            uri,
            ConcurrencyMode.SHARED,
            uri,
            ConcurrencyMode.EXCLUSIVE,
        )

    def test_exclusive_vs_shared_conflicts(self) -> None:
        """EXCLUSIVE request against active SHARED lease MUST conflict."""
        uri = "db://postgres/reports/monthly"
        assert are_resources_in_conflict(
            uri,
            ConcurrencyMode.EXCLUSIVE,
            uri,
            ConcurrencyMode.SHARED,
        )

    def test_exclusive_vs_exclusive_conflicts(self) -> None:
        """EXCLUSIVE request against active EXCLUSIVE lease MUST conflict."""
        uri = "db://postgres/reports/monthly"
        assert are_resources_in_conflict(
            uri,
            ConcurrencyMode.EXCLUSIVE,
            uri,
            ConcurrencyMode.EXCLUSIVE,
        )

    @pytest.mark.asyncio
    async def test_acquire_lease_shared_vs_shared_succeeds(self) -> None:
        """Acquiring a SHARED lease when an active SHARED lease exists on another txn succeeds."""
        svc = ResourceConcurrencyService()
        auth = _sample_auth(agent_id="agent_reader_2")
        session = _build_mock_session()

        existing_shared = _sample_active_lease(
            lease_id="lse_shared_1",
            agent_id="agent_reader_1",
            txn_id="txn_read_1",
            mode=ConcurrencyMode.SHARED,
            token=1,
        )

        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(
            tenant_id="tenant_alpha",
            txn_id="txn_read_2",
            agent_id="agent_reader_2",
        )
        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = [existing_shared]
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 1
        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_txn, exec_leases, exec_token, exec_audit]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            req = ResourceLeaseAcquireRequest(
                resource_uri="db://postgres/reports/monthly",
                transaction_id="txn_read_2",
                agent_id="agent_reader_2",
                concurrency_mode=ConcurrencyMode.SHARED,
                duration_seconds=60,
            )
            resp = await svc.acquire_lease(auth=auth, request=req)
            assert resp.concurrency_mode == ConcurrencyMode.SHARED
            assert resp.fencing_token == 2

    @pytest.mark.asyncio
    async def test_acquire_lease_exclusive_vs_exclusive_raises_409(self) -> None:
        """Acquiring an EXCLUSIVE lease when an active EXCLUSIVE lease exists on another txn raises 409."""
        svc = ResourceConcurrencyService()
        auth = _sample_auth(agent_id="agent_writer_2")
        session = _build_mock_session()

        existing_exclusive = _sample_active_lease(
            lease_id="lse_excl_1",
            agent_id="agent_writer_1",
            txn_id="txn_write_1",
            mode=ConcurrencyMode.EXCLUSIVE,
            token=1,
        )

        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(
            tenant_id="tenant_alpha",
            txn_id="txn_write_2",
            agent_id="agent_writer_2",
        )
        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = [existing_exclusive]

        session.execute.side_effect = [exec_txn, exec_leases]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            req = ResourceLeaseAcquireRequest(
                resource_uri="db://postgres/finance/ledger",
                transaction_id="txn_write_2",
                agent_id="agent_writer_2",
                concurrency_mode=ConcurrencyMode.EXCLUSIVE,
                duration_seconds=60,
            )
            with pytest.raises(HTTPException) as exc_info:
                await svc.acquire_lease(auth=auth, request=req)
            assert exc_info.value.status_code == 409
            assert "Resource conflict" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_acquire_lease_inactive_released_allows_new_lease(self) -> None:
        """Released or inactive lease does NOT block a new acquisition."""
        svc = ResourceConcurrencyService()
        auth = _sample_auth(agent_id="agent_writer_2")
        session = _build_mock_session()

        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(
            tenant_id="tenant_alpha",
            txn_id="txn_write_2",
            agent_id="agent_writer_2",
        )
        # Active query only queries status=ACQUIRED, so released/inactive leases are not returned
        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = []
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 5  # Previous released lease had token 5
        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_txn, exec_leases, exec_token, exec_audit]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            req = ResourceLeaseAcquireRequest(
                resource_uri="db://postgres/finance/ledger",
                transaction_id="txn_write_2",
                agent_id="agent_writer_2",
                concurrency_mode=ConcurrencyMode.EXCLUSIVE,
                duration_seconds=60,
            )
            resp = await svc.acquire_lease(auth=auth, request=req)
            assert resp.fencing_token == 6

    @pytest.mark.asyncio
    async def test_acquire_lease_reentrant_renewal_extends_without_new_token(self) -> None:
        """Re-entrant acquisition by the same transaction extends duration without changing token."""
        svc = ResourceConcurrencyService()
        auth = _sample_auth(agent_id="agent_worker_1")
        session = _build_mock_session()

        existing_lease = _sample_active_lease(
            lease_id="lse_reentrant_1",
            agent_id="agent_worker_1",
            txn_id="txn_100",
            mode=ConcurrencyMode.EXCLUSIVE,
            token=3,
            expires_in_seconds=30,
        )

        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(
            tenant_id="tenant_alpha",
            txn_id="txn_100",
            agent_id="agent_worker_1",
        )
        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = [existing_lease]
        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_txn, exec_leases, exec_audit]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            req = ResourceLeaseAcquireRequest(
                resource_uri="db://postgres/finance/ledger",
                transaction_id="txn_100",
                agent_id="agent_worker_1",
                concurrency_mode=ConcurrencyMode.EXCLUSIVE,
                duration_seconds=300,
            )
            resp = await svc.acquire_lease(auth=auth, request=req)
            assert resp.id == "lse_reentrant_1"
            assert resp.fencing_token == 3  # Token does not change for re-entrant renewal

    @pytest.mark.asyncio
    async def test_cross_tenant_identical_resource_isolated(self) -> None:
        """Tenant B requesting the exact same resource URI as Tenant A is completely isolated."""
        svc = ResourceConcurrencyService()
        auth_b = _sample_auth(tenant_id="tenant_beta", agent_id="agent_beta_1")
        session_b = _build_mock_session()

        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(
            tenant_id="tenant_beta",
            txn_id="txn_beta_1",
            agent_id="agent_beta_1",
        )
        # In Tenant Beta's partition, there are no active leases
        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = []
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 0
        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session_b.execute.side_effect = [exec_txn, exec_leases, exec_token, exec_audit]

        with patch("services.concurrency_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session_b
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            req = ResourceLeaseAcquireRequest(
                resource_uri="db://postgres/finance/ledger",
                transaction_id="txn_beta_1",
                agent_id="agent_beta_1",
                concurrency_mode=ConcurrencyMode.EXCLUSIVE,
                duration_seconds=60,
            )
            resp = await svc.acquire_lease(auth=auth_b, request=req)
            assert resp.tenant_id == "tenant_beta"
            assert resp.fencing_token == 1


class TestFencingTokenMonotonicityAndPropagation:
    """Verifies fencing token enforcement, staleness rejection, and parent-child hierarchy."""

    @pytest.mark.asyncio
    async def test_stale_fencing_token_rejected_at_gate3(self) -> None:
        """Gate 3 rejects an action presenting an older fencing token than the current max."""
        svc = ResourceConcurrencyService()
        session = _build_mock_session()

        # Token query returns max=5
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 5

        # Hierarchical tokens query returns empty
        exec_hier = MagicMock()
        exec_hier.all.return_value = []

        session.execute.side_effect = [exec_token, exec_hier]

        decision = await svc.validate_lease_for_action(
            tenant_id="tenant_alpha",
            transaction_id="txn_100",
            target_resource="db://postgres/finance/ledger",
            fencing_token=3,  # Stale token 3 < max 5
            session=session,
        )

        assert decision.decision == Decision.BLOCK
        assert "Stale fencing token 3" in decision.reason
        assert "advanced to token 5" in decision.reason

    @pytest.mark.asyncio
    async def test_inactive_or_released_lease_token_rejected_at_gate3(self) -> None:
        """Gate 3 rejects an action presenting a token from a lease that is no longer active."""
        svc = ResourceConcurrencyService()
        session = _build_mock_session()

        # Token query returns max=1
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 1
        exec_hier = MagicMock()
        exec_hier.all.return_value = []

        # Active leases query returns empty (lease was released or expired)
        exec_active = MagicMock()
        exec_active.scalars.return_value.all.return_value = []

        session.execute.side_effect = [exec_token, exec_hier, exec_active]

        decision = await svc.validate_lease_for_action(
            tenant_id="tenant_alpha",
            transaction_id="txn_100",
            target_resource="db://postgres/finance/ledger",
            fencing_token=1,
            session=session,
        )

        assert decision.decision == Decision.BLOCK
        assert "no longer active or has expired" in decision.reason

    @pytest.mark.asyncio
    async def test_parent_resource_lease_protects_child_action(self) -> None:
        """Acquired lease on parent resource 'db://postgres/finance' protects action on 'db://postgres/finance/ledger'."""
        svc = ResourceConcurrencyService()
        session = _build_mock_session()

        # Max token for child is 0
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 0

        # Hierarchical leases query returns parent lease with token 2
        exec_hier = MagicMock()
        exec_hier.all.return_value = [("db://postgres/finance", "EXCLUSIVE", 2)]

        # Active leases query returns active parent lease owned by this txn
        parent_lease = _sample_active_lease(
            lease_id="lse_parent_1",
            resource_uri="db://postgres/finance",
            txn_id="txn_parent_100",
            token=2,
        )
        exec_active = MagicMock()
        exec_active.scalars.return_value.all.return_value = [parent_lease]

        session.execute.side_effect = [exec_token, exec_hier, exec_active]

        decision = await svc.validate_lease_for_action(
            tenant_id="tenant_alpha",
            transaction_id="txn_parent_100",
            target_resource="db://postgres/finance/ledger",
            fencing_token=2,
            session=session,
        )

        assert decision.decision == Decision.ALLOW
        assert "Resource lease verified" in decision.reason

    @pytest.mark.asyncio
    async def test_child_action_blocked_if_parent_lease_advanced(self) -> None:
        """Child action with token 1 is blocked if parent resource lease advanced to token 2."""
        svc = ResourceConcurrencyService()
        session = _build_mock_session()

        # Max token for child URI is 0
        exec_token = MagicMock()
        exec_token.scalar_one.return_value = 0

        # Hierarchical leases query detects parent lease at token 2
        exec_hier = MagicMock()
        exec_hier.all.return_value = [("db://postgres/finance", "EXCLUSIVE", 2)]

        session.execute.side_effect = [exec_token, exec_hier]

        decision = await svc.validate_lease_for_action(
            tenant_id="tenant_alpha",
            transaction_id="txn_parent_100",
            target_resource="db://postgres/finance/ledger",
            fencing_token=1,  # Stale against parent's token 2
            session=session,
        )

        assert decision.decision == Decision.BLOCK
        assert "Stale fencing token 1" in decision.reason
        assert "advanced to token 2" in decision.reason


class TestTargetAdapterFencingEnforcement:
    """Verifies target-side fencing capabilities: ENFORCED vs MEDIATED_ONLY / UNSUPPORTED."""

    @pytest.mark.asyncio
    async def test_enforced_adapter_rejects_mismatched_target_token(self) -> None:
        """ENFORCED adapter (db_query) fails execution when expected fencing token
        does not match active contract token.
        """
        proxy = GovernedToolProxy()
        auth = _sample_auth()

        contract = ActionContract(
            id="act_db_1",
            tenant_id="tenant_alpha",
            transaction_id="txn_100",
            tool_name="db_query",
            state=ActionState.EXECUTING.value,
            target_resource="db://postgres/finance/ledger",
            fencing_token=2,
            normalized_parameters={"query": "UPDATE ledger SET balance = 0", "expected_fencing_token": 1},
        )

        output, error = await proxy.dispatch(contract=contract, auth=auth)
        assert output["status"] == "error"
        assert "Target-side fencing check failed: expected token 1 != active token 2" in error

    @pytest.mark.asyncio
    async def test_enforced_adapter_succeeds_matching_target_token(self) -> None:
        """ENFORCED adapter (db_query) succeeds execution when expected fencing token matches active contract token."""
        proxy = GovernedToolProxy()
        auth = _sample_auth()

        contract = ActionContract(
            id="act_db_2",
            tenant_id="tenant_alpha",
            transaction_id="txn_100",
            tool_name="db_query",
            state=ActionState.EXECUTING.value,
            target_resource="db://postgres/finance/ledger",
            fencing_token=3,
            normalized_parameters={"query": "UPDATE ledger SET balance = 5000", "expected_fencing_token": 3},
        )

        output, error = await proxy.dispatch(contract=contract, auth=auth)
        assert error is None
        assert output["status"] == "ok"
        assert output["fencing_token"] == 3

    @pytest.mark.asyncio
    async def test_unsupported_adapter_relies_on_gate3_mediation(self) -> None:
        """UNSUPPORTED adapter (email_sender) records token in metadata but relies on Gate 3 mediation for safety."""
        proxy = GovernedToolProxy()
        auth = _sample_auth()

        contract = ActionContract(
            id="act_email_1",
            tenant_id="tenant_alpha",
            transaction_id="txn_100",
            tool_name="email_sender",
            state=ActionState.EXECUTING.value,
            target_resource="smtp://mail.internal:25/notifications",
            fencing_token=4,
            normalized_parameters={"recipient": "operator@example.com", "subject": "Alert"},
        )

        output, error = await proxy.dispatch(contract=contract, auth=auth)
        assert error is None
        assert output["status"] == "ok"
        assert output["delivered"] is True
        assert output["fencing_token"] == 4


class TestPostgresAdvisoryLockInvariants:
    """Verifies advisory lock serialization invariants and environment dialect enforcement."""

    def test_deterministic_key_derivation(self) -> None:
        """Advisory lock key must be deterministic for identical tenant and resource URI."""
        k1 = derive_resource_advisory_lock_key("tenant_1", "db://postgres/finance/ledger")
        k2 = derive_resource_advisory_lock_key("tenant_1", "db://postgres/finance/ledger")
        k3 = derive_resource_advisory_lock_key("tenant_1", "db://postgres/finance/accounts")
        assert k1 == k2
        assert k1 != k3

    def test_signed_64bit_bounds(self) -> None:
        """Advisory lock key must strictly fall within PostgreSQL signed 64-bit bounds (-2^63 to 2^63 - 1)."""
        key = derive_resource_advisory_lock_key("tenant_1", "db://postgres/finance/ledger")
        assert -9223372036854775808 <= key <= 9223372036854775807

    @pytest.mark.asyncio
    async def test_production_fails_closed_without_postgres(self) -> None:
        """In production environment, acquire_lease fails closed if dialect is not PostgreSQL."""
        svc = ResourceConcurrencyService()
        auth = _sample_auth()
        session = _build_mock_session()

        session.bind = MagicMock()
        session.bind.dialect.name = "sqlite"

        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = _sample_transaction(
            tenant_id="tenant_alpha",
            txn_id="txn_100",
            agent_id="agent_worker_1",
        )
        session.execute.return_value = exec_txn

        mock_settings = MagicMock()
        mock_settings.environment = EnvironmentType.PRODUCTION

        with patch("services.concurrency_service.get_settings", return_value=mock_settings):
            with patch("services.concurrency_service.get_tenant_session") as mock_ts:
                mock_cm = AsyncMock()
                mock_cm.__aenter__.return_value = session
                mock_cm.__aexit__.return_value = None
                mock_ts.return_value = mock_cm

                req = ResourceLeaseAcquireRequest(
                    resource_uri="db://postgres/finance/ledger",
                    transaction_id="txn_100",
                    agent_id="agent_worker_1",
                    concurrency_mode=ConcurrencyMode.EXCLUSIVE,
                    duration_seconds=60,
                )
                with pytest.raises(RuntimeError) as exc_info:
                    await svc.acquire_lease(auth=auth, request=req)
                assert "Production invariant violation" in str(exc_info.value)
                assert "requires PostgreSQL dialect" in str(exc_info.value)
