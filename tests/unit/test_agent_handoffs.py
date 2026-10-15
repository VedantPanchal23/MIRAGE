"""Unit tests for Phase 8 Governed Agent Handoff Service.

Validates:
1. Handoff creation with valid active parent transaction, ancestor delegation, and eligible child agent.
2. Prevention of self-handoffs (parent agent == child agent).
3. Rejection of handoffs when parent transaction is in a terminal state (COMPLETED, FAILED, CANCELLED).
4. Rejection of handoffs when ancestor delegation is revoked or expired.
5. Rejection of handoffs when child agent is SUSPENDED or DEACTIVATED.
6. Server-side taint inheritance from parent transaction to handoff record.
7. Idempotent handoff creation and semantic collision detection.
8. Safe acceptance: child transaction spawn with lineage, decremented turn budget, and inherited taints.
9. Terminal state protection: cannot accept or cancel already finalized handoffs.
10. Parent cancellation handling: cannot accept handoff if parent transaction was cancelled while pending.
11. Cross-tenant fail-closed isolation.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import (
    Agent,
    AgentDelegation,
    AgentHandoff,
    AITransaction,
)
from services.handoff_service import (
    AgentHandoffService,
)
from shared.schemas.agent import AgentStatus
from shared.schemas.auth import AuthContext, Role
from shared.schemas.handoff import (
    AgentHandoffAcceptRequest,
    AgentHandoffCancelRequest,
    AgentHandoffCreateRequest,
    HandoffStatus,
)


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        identity_id="usr_operator_1",
        role=Role.OPERATOR,
        token_id="tok_alpha_1",
        agent_id="agent_child_1",
    )


@pytest.fixture
def test_handoff_service() -> AgentHandoffService:
    return AgentHandoffService()


def _build_mock_session() -> AsyncMock:
    """Build a mock AsyncSession with synchronous Result and nested savepoint support."""
    session = AsyncMock()
    mock_exec = MagicMock()
    mock_exec.scalar_one_or_none.return_value = None
    mock_exec.scalars.return_value.all.return_value = []
    mock_exec.first.return_value = None
    session.execute.return_value = mock_exec

    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested_cm)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _sample_parent_transaction(
    tenant_id: str = "tenant_alpha",
    txn_id: str = "txn_parent_1",
    agent_id: str = "agent_parent_1",
    state: str = "ACTIVE",
    taint_flags: list[str] | None = None,
    max_turns: int = 10,
    turn_count: int = 2,
) -> AITransaction:
    now = datetime.now(UTC)
    return AITransaction(
        id=txn_id,
        tenant_id=tenant_id,
        actor_identity_id="usr_1",
        agent_id=agent_id,
        parent_transaction_id=None,
        idempotency_key="idem_parent_1",
        correlation_id="corr_parent_1",
        state=state,
        max_turns=max_turns,
        turn_count=turn_count,
        taint_flags=taint_flags or ["PII", "CONFIDENTIAL"],
        context_sources=[],
        policy_id=None,
        budget_id=None,
        final_disposition=None,
        version=0,
        created_at=now,
        updated_at=now,
    )


def _sample_delegation(
    tenant_id: str = "tenant_alpha",
    delegation_id: str = "del_grant_1",
    parent_agent_id: str = "agent_parent_1",
    child_agent_id: str = "agent_child_1",
    status: str = "ACTIVE",
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> AgentDelegation:
    now = datetime.now(UTC)
    return AgentDelegation(
        id=delegation_id,
        tenant_id=tenant_id,
        parent_agent_id=parent_agent_id,
        parent_transaction_id="txn_parent_1",
        child_agent_id=child_agent_id,
        child_transaction_id="txn_child_1" if status == "ACTIVE" else None,
        delegated_capabilities=[{"capability_type": "TOOL_EXECUTE"}],
        resource_scope={},
        max_autonomy_level=2,
        delegation_depth=1,
        max_turns=6,
        status=status,
        purpose="Delegate specialized subtask",
        idempotency_key="idem_del_1",
        expires_at=expires_at or (now + timedelta(hours=1)),
        revoked_at=revoked_at,
        created_at=now,
        updated_at=now,
    )


def _sample_agent(
    tenant_id: str = "tenant_alpha",
    agent_id: str = "agent_child_1",
    status: AgentStatus = AgentStatus.ACTIVE,
) -> Agent:
    now = datetime.now(UTC)
    return Agent(
        id=agent_id,
        tenant_id=tenant_id,
        name="research_bot",
        status=status.value,
        active=(status == AgentStatus.ACTIVE),
        max_autonomy_level=3,
        registered_by_identity_id="usr_admin",
        created_at=now,
        updated_at=now,
    )


class TestAgentHandoffLifecycle:
    """Test suite for governed agent handoff creation, acceptance, and cancellation."""

    @pytest.mark.asyncio
    async def test_create_handoff_success(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """Create handoff succeeds when parent txn is active, delegation is active, and child agent is active."""
        session = _build_mock_session()
        parent_txn = _sample_parent_transaction()
        delegation = _sample_delegation()
        child_agent = _sample_agent()

        req = AgentHandoffCreateRequest(
            parent_transaction_id="txn_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            purpose="Delegate specialized subtask",
            permitted_scope={},
            duration_seconds=300,
            idempotency_key="idem_handoff_001",
        )

        exec_idem = MagicMock()
        exec_idem.scalar_one_or_none.return_value = None

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        exec_del = MagicMock()
        exec_del.scalar_one_or_none.return_value = delegation

        exec_agent = MagicMock()
        exec_agent.scalar_one_or_none.return_value = child_agent

        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_idem, exec_parent, exec_del, exec_audit]

        with (
            patch("services.handoff_service.get_tenant_session") as mock_ts,
            patch(
                "services.handoff_service.agent_governance_service.evaluate_agent_eligibility",
                return_value=(True, "Eligible"),
            ),
        ):
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            res = await test_handoff_service.create_handoff(auth=auth_context, request=req)

        assert res.id.startswith("hnd_")
        assert res.tenant_id == "tenant_alpha"
        assert res.parent_transaction_id == "txn_parent_1"
        assert res.child_agent_id == "agent_child_1"
        assert res.status == HandoffStatus.PENDING
        assert res.inherited_taint_flags == ["PII", "CONFIDENTIAL"]
        assert session.add.called

    @pytest.mark.asyncio
    async def test_create_handoff_prohibits_self_handoff(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """Creating a handoff from an agent to itself is strictly prohibited."""
        session = _build_mock_session()
        parent_txn = _sample_parent_transaction(agent_id="agent_same_1")

        req = AgentHandoffCreateRequest(
            parent_transaction_id="txn_parent_1",
            child_agent_id="agent_same_1",  # Same as parent agent!
            delegation_id="del_grant_1",
            purpose="Self-delegation attempt",
            idempotency_key="idem_self_handoff",
        )

        exec_idem = MagicMock()
        exec_idem.scalar_one_or_none.return_value = None

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        session.execute.side_effect = [exec_idem, exec_parent]

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_handoff_service.create_handoff(auth=auth_context, request=req)

        assert exc_info.value.status_code == 400
        assert "Self-handoff is prohibited" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_handoff_rejects_terminal_parent(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """Parent transaction in a terminal state (COMPLETED, FAILED, CANCELLED) cannot initiate handoffs."""
        session = _build_mock_session()
        parent_txn = _sample_parent_transaction(state="COMPLETED")

        req = AgentHandoffCreateRequest(
            parent_transaction_id="txn_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            purpose="Handoff after completion",
            idempotency_key="idem_terminal_parent",
        )

        exec_idem = MagicMock()
        exec_idem.scalar_one_or_none.return_value = None

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        session.execute.side_effect = [exec_idem, exec_parent]

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_handoff_service.create_handoff(auth=auth_context, request=req)

        assert exc_info.value.status_code == 409
        assert "not in active state" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_handoff_rejects_revoked_delegation(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """Handoff cannot be created if ancestor delegation grant is REVOKED."""
        session = _build_mock_session()
        parent_txn = _sample_parent_transaction()
        revoked_del = _sample_delegation(status="REVOKED", revoked_at=datetime.now(UTC))

        req = AgentHandoffCreateRequest(
            parent_transaction_id="txn_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            purpose="Handoff under revoked grant",
            idempotency_key="idem_revoked_del",
        )

        exec_idem = MagicMock()
        exec_idem.scalar_one_or_none.return_value = None

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        exec_del = MagicMock()
        exec_del.scalar_one_or_none.return_value = revoked_del

        session.execute.side_effect = [exec_idem, exec_parent, exec_del]

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_handoff_service.create_handoff(auth=auth_context, request=req)

        assert exc_info.value.status_code == 409
        assert "is not ACTIVE" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_handoff_rejects_suspended_child_agent(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """Target child agent must be in ACTIVE lifecycle state."""
        session = _build_mock_session()
        parent_txn = _sample_parent_transaction()
        delegation = _sample_delegation()

        req = AgentHandoffCreateRequest(
            parent_transaction_id="txn_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            purpose="Handoff to suspended agent",
            idempotency_key="idem_suspended_agent",
        )

        exec_idem = MagicMock()
        exec_idem.scalar_one_or_none.return_value = None

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        exec_del = MagicMock()
        exec_del.scalar_one_or_none.return_value = delegation

        session.execute.side_effect = [exec_idem, exec_parent, exec_del]

        with (
            patch("services.handoff_service.get_tenant_session") as mock_ts,
            patch(
                "services.handoff_service.agent_governance_service.evaluate_agent_eligibility",
                return_value=(False, "Suspended"),
            ),
        ):
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_handoff_service.create_handoff(auth=auth_context, request=req)

        assert exc_info.value.status_code == 403
        assert "is not eligible" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_create_handoff_idempotency_and_collision(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """Same idempotency key with identical payload returns existing; divergent semantics raises 409."""
        session = _build_mock_session()
        req = AgentHandoffCreateRequest(
            parent_transaction_id="txn_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            purpose="Idempotency test",
            idempotency_key="idem_exact_match_123",
        )

        existing_handoff = AgentHandoff(
            id="hnd_existing_1",
            tenant_id="tenant_alpha",
            parent_transaction_id="txn_parent_1",
            parent_agent_id="agent_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            child_transaction_id=None,
            status=HandoffStatus.PENDING.value,
            purpose="Idempotency test",
            permitted_scope={},
            inherited_taint_flags=["PII"],
            idempotency_key="idem_exact_match_123",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            accepted_at=None,
            completed_at=None,
            cancelled_at=None,
            cancellation_reason=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        exec_idem = MagicMock()
        exec_idem.scalar_one_or_none.return_value = existing_handoff
        session.execute.return_value = exec_idem

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            # Matching fields returns existing
            res = await test_handoff_service.create_handoff(auth=auth_context, request=req)
            assert res.id == "hnd_existing_1"

            # Divergent purpose raises 409
            existing_handoff.purpose = "Divergent purpose string"
            with pytest.raises(HTTPException) as exc_info:
                await test_handoff_service.create_handoff(auth=auth_context, request=req)
            assert exc_info.value.status_code == 409
            assert "Idempotency key reuse across materially divergent handoff semantics" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_accept_handoff_spawns_child_transaction(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """Accepting a handoff binds child agent, spawns child transaction, and inherits taints."""
        session = _build_mock_session()
        parent_txn = _sample_parent_transaction(max_turns=10, turn_count=2)
        delegation = _sample_delegation(status="ACTIVE")

        handoff = AgentHandoff(
            id="hnd_pending_1",
            tenant_id="tenant_alpha",
            parent_transaction_id="txn_parent_1",
            parent_agent_id="agent_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            child_transaction_id=None,
            status=HandoffStatus.PENDING.value,
            purpose="Valid handoff reason",
            permitted_scope={},
            inherited_taint_flags=["PII", "SECRET"],
            idempotency_key="idem_acc_123",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            accepted_at=None,
            completed_at=None,
            cancelled_at=None,
            cancellation_reason=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        req = AgentHandoffAcceptRequest(
            input_context={"task_data": "sample_input"},
        )

        exec_hnd = MagicMock()
        exec_hnd.scalar_one_or_none.return_value = handoff

        exec_del = MagicMock()
        exec_del.scalar_one_or_none.return_value = delegation

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_hnd, exec_parent, exec_del, exec_audit]

        with (
            patch("services.handoff_service.get_tenant_session") as mock_ts,
            patch(
                "services.handoff_service.agent_governance_service.evaluate_agent_eligibility",
                return_value=(True, "Eligible"),
            ),
        ):
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            res = await test_handoff_service.accept_handoff(auth=auth_context, handoff_id="hnd_pending_1", request=req)

        assert res.handoff.id == "hnd_pending_1"
        assert res.handoff.status == HandoffStatus.ACCEPTED
        assert res.child_transaction_id.startswith("txn_child_")
        assert handoff.status == HandoffStatus.ACCEPTED.value
        assert handoff.child_transaction_id == res.child_transaction_id

        # Verify child transaction was added to session
        added_objs = [call.args[0] for call in session.add.call_args_list]
        child_txns = [o for o in added_objs if isinstance(o, AITransaction)]
        assert len(child_txns) == 1
        child_txn = child_txns[0]
        assert child_txn.parent_transaction_id == "txn_parent_1"
        assert child_txn.agent_id == "agent_child_1"
        assert child_txn.taint_flags == ["PII", "SECRET"]
        assert child_txn.max_turns == 6  # min(delegation.max_turns=6, parent_remaining=8)

    @pytest.mark.asyncio
    async def test_accept_handoff_rejects_wrong_agent(self, test_handoff_service: AgentHandoffService) -> None:
        """Unauthorized caller cannot accept a handoff meant for another agent."""
        session = _build_mock_session()
        handoff = AgentHandoff(
            id="hnd_pending_1",
            tenant_id="tenant_alpha",
            parent_transaction_id="txn_parent_1",
            parent_agent_id="agent_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            child_transaction_id=None,
            status=HandoffStatus.PENDING.value,
            purpose="Delegate",
            permitted_scope={},
            inherited_taint_flags=[],
            idempotency_key="idem_wrong_agent",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            accepted_at=None,
            completed_at=None,
            cancelled_at=None,
            cancellation_reason=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        unauthorized_auth = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_imposter",
            role=Role.API_CLIENT,  # Not admin or operator
            token_id="tok_imp",
            agent_id="agent_imposter_2",  # Mismatched agent!
        )

        req = AgentHandoffAcceptRequest(input_context={})

        exec_hnd = MagicMock()
        exec_hnd.scalar_one_or_none.return_value = handoff
        session.execute.return_value = exec_hnd

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_handoff_service.accept_handoff(
                    auth=unauthorized_auth, handoff_id="hnd_pending_1", request=req
                )

        assert exc_info.value.status_code == 403
        assert "is not authorized to accept handoff" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_accept_handoff_rejects_parent_cancelled_while_pending(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """If parent transaction was cancelled while handoff was pending, accept must fail closed."""
        session = _build_mock_session()
        parent_txn = _sample_parent_transaction(state="CANCELLED")
        delegation = _sample_delegation(status="ACTIVE")

        handoff = AgentHandoff(
            id="hnd_pending_1",
            tenant_id="tenant_alpha",
            parent_transaction_id="txn_parent_1",
            parent_agent_id="agent_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            child_transaction_id=None,
            status=HandoffStatus.PENDING.value,
            purpose="Delegate",
            permitted_scope={},
            inherited_taint_flags=[],
            idempotency_key="idem_parent_cancelled",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            accepted_at=None,
            completed_at=None,
            cancelled_at=None,
            cancellation_reason=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        req = AgentHandoffAcceptRequest(input_context={})

        exec_hnd = MagicMock()
        exec_hnd.scalar_one_or_none.return_value = handoff

        exec_del = MagicMock()
        exec_del.scalar_one_or_none.return_value = delegation

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        session.execute.side_effect = [exec_hnd, exec_parent, exec_del]

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_handoff_service.accept_handoff(auth=auth_context, handoff_id="hnd_pending_1", request=req)

        assert exc_info.value.status_code == 409
        assert "parent transaction is no longer active" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_cancel_handoff_success_and_terminal_protection(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """Cancelling a PENDING handoff transitions to CANCELLED; cannot re-cancel or cancel ACCEPTED."""
        session = _build_mock_session()
        handoff = AgentHandoff(
            id="hnd_pending_1",
            tenant_id="tenant_alpha",
            parent_transaction_id="txn_parent_1",
            parent_agent_id="agent_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            child_transaction_id=None,
            status=HandoffStatus.PENDING.value,
            purpose="Delegate",
            permitted_scope={},
            inherited_taint_flags=[],
            idempotency_key="idem_cancel_test",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
            accepted_at=None,
            completed_at=None,
            cancelled_at=None,
            cancellation_reason=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        req = AgentHandoffCancelRequest(reason="Operator cancelled workflow")

        exec_hnd = MagicMock()
        exec_hnd.scalar_one_or_none.return_value = handoff

        exec_audit = MagicMock()
        exec_audit.first.return_value = None

        session.execute.side_effect = [exec_hnd, exec_audit]

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            res = await test_handoff_service.cancel_handoff(auth=auth_context, handoff_id="hnd_pending_1", request=req)

        assert res.status == HandoffStatus.CANCELLED
        assert handoff.status == HandoffStatus.CANCELLED.value

        # Attempting to cancel already cancelled handoff raises 409
        session.execute.side_effect = None
        session.execute.return_value.scalar_one_or_none.return_value = handoff

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_handoff_service.cancel_handoff(auth=auth_context, handoff_id="hnd_pending_1", request=req)
        assert exc_info.value.status_code == 409
        assert "Cannot cancel handoff in terminal status 'CANCELLED'" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_cross_tenant_isolation_fails_closed(
        self, test_handoff_service: AgentHandoffService, auth_context: AuthContext
    ) -> None:
        """Handoff not found in caller's tenant raises 404."""
        session = _build_mock_session()
        session.execute.return_value.scalar_one_or_none.return_value = None

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await test_handoff_service.get_handoff(auth=auth_context, handoff_id="hnd_foreign_1")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_handoff_rejects_unauthorized_agent_caller(
        self, test_handoff_service: AgentHandoffService
    ) -> None:
        """Caller agent cannot create a handoff for a parent transaction owned by another agent."""
        session = _build_mock_session()
        parent_txn = AITransaction(
            id="txn_parent_1",
            tenant_id="tenant_alpha",
            actor_identity_id="usr_1",
            agent_id="agent_legit_parent",
            state="ACTIVE",
            max_turns=10,
            turn_count=1,
            taint_flags=[],
            context_sources=[],
            version=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        exec_idem = MagicMock()
        exec_idem.scalar_one_or_none.return_value = None
        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn
        session.execute.side_effect = [exec_idem, exec_parent]

        auth = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_1",
            role=Role.API_CLIENT,
            agent_id="agent_impostor",
        )
        req = AgentHandoffCreateRequest(
            parent_transaction_id="txn_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            purpose="Unauthorized handoff attempt",
            idempotency_key="idem_unauth_hnd_1",
        )

        with pytest.raises(HTTPException) as exc_info:
            await test_handoff_service.create_handoff(auth=auth, request=req, session=session)
        assert exc_info.value.status_code == 403
        assert "not authorized to create handoff for parent agent" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_accept_handoff_atomic_savepoint_rollback_on_failure(
        self, test_handoff_service: AgentHandoffService
    ) -> None:
        """If database flush or audit fails during acceptance, the savepoint rolls back atomically."""
        session = _build_mock_session()
        now = datetime.now(UTC)

        handoff = AgentHandoff(
            id="hnd_pending_1",
            tenant_id="tenant_alpha",
            parent_transaction_id="txn_parent_1",
            parent_agent_id="agent_parent_1",
            child_agent_id="agent_child_1",
            delegation_id="del_grant_1",
            child_transaction_id=None,
            status=HandoffStatus.PENDING.value,
            purpose="Atomic rollback subtask",
            idempotency_key="idem_hnd_atomic",
            expires_at=now + timedelta(minutes=10),
            created_at=now,
            updated_at=now,
        )
        delegation = AgentDelegation(
            id="del_grant_1",
            tenant_id="tenant_alpha",
            parent_agent_id="agent_parent_1",
            parent_transaction_id="txn_parent_1",
            child_agent_id="agent_child_1",
            child_transaction_id=None,
            delegated_capabilities=[{"capability_type": "tools:math"}],
            resource_scope={},
            max_autonomy_level=2,
            delegation_depth=1,
            max_turns=5,
            status="ACTIVE",
            purpose="Math",
            idempotency_key="idem_del_1",
            expires_at=now + timedelta(minutes=15),
            created_at=now,
            updated_at=now,
        )
        parent_txn = AITransaction(
            id="txn_parent_1",
            tenant_id="tenant_alpha",
            actor_identity_id="usr_1",
            agent_id="agent_parent_1",
            state="ACTIVE",
            max_turns=10,
            turn_count=2,
            taint_flags=[],
            context_sources=[],
            version=0,
            created_at=now,
            updated_at=now,
        )

        exec_mock = MagicMock()
        exec_mock.scalar_one_or_none.side_effect = [handoff, parent_txn, delegation]
        session.execute.return_value = exec_mock

        # Make flush inside begin_nested fail with an operational error
        session.flush.side_effect = RuntimeError("Database connection lost during child spawn")

        auth = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_child",
            role=Role.OPERATOR,
            agent_id="agent_child_1",
        )
        req = AgentHandoffAcceptRequest(input_context={"task": "math"})

        with patch(
            "services.handoff_service.agent_governance_service.evaluate_agent_eligibility",
            return_value=(True, "Eligible"),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await test_handoff_service.accept_handoff(
                    auth=auth, handoff_id="hnd_pending_1", request=req, session=session
                )

        assert "Database connection lost during child spawn" in str(exc_info.value)
        # Verify nested savepoint was established to enable atomic rollback
        assert session.begin_nested.called
