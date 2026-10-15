"""Unit tests for ActionGovernorService cross-agent delegation and lifecycle integration."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import (
    ActionContract,
    AgentDelegation,
    AITransaction,
    ToolDefinition,
)
from services.action_governor import ActionGovernorService
from shared.schemas.action import (
    ActionExecutionRequest,
    ActionProposal,
    ActionState,
    ActionType,
    EgressType,
    PostconditionRule,
    ToolTrustLevel,
    ToolType,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import Decision, PolicyDecision
from shared.schemas.delegation import DelegationStatus
from shared.schemas.outcome import OutcomeStatus


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_gamma",
        identity_id="usr_tester_1",
        role=Role.OPERATOR,
        token_id="tok_gamma_1",
    )


@pytest.fixture
def governor_service() -> ActionGovernorService:
    return ActionGovernorService()


def _build_mock_session() -> AsyncMock:
    """Build a mock AsyncSession with synchronous Result and nested savepoint support."""
    session = AsyncMock()
    mock_exec = MagicMock()
    mock_exec.scalar_one_or_none.return_value = None
    mock_exec.scalar_one.return_value = 0
    mock_exec.scalars.return_value.all.return_value = []
    mock_exec.one.return_value = (0, 0)
    mock_exec.first.return_value = None
    session.execute.return_value = mock_exec

    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested_cm)
    session.add = MagicMock()
    session.delete = MagicMock()
    session.flush = AsyncMock()
    return session


def _make_tool(
    name: str = "db_query",
    req_cap: str = "database:read",
    active: bool = True,
) -> ToolDefinition:
    now = datetime.now(UTC)
    return ToolDefinition(
        id=f"tool_{name}",
        tenant_id="tenant_gamma",
        name=name,
        description="Governed tool for testing",
        tool_type=ToolType.NATIVE.value,
        egress_type=EgressType.INTERNAL_ISOLATED.value,
        trust_level=ToolTrustLevel.VERIFIED.value,
        required_capability=req_cap,
        parameters_schema={"type": "object"},
        config={},
        active=active,
        created_at=now,
        updated_at=now,
    )


def _make_txn(
    txn_id: str = "txn_parent_1",
    agent_id: str | None = "agent_child_1",
    parent_txn_id: str | None = None,
    state: str = "ACTIVE",
    final_disposition: str | None = None,
) -> AITransaction:
    now = datetime.now(UTC)
    return AITransaction(
        id=txn_id,
        tenant_id="tenant_gamma",
        actor_identity_id="usr_tester_1",
        agent_id=agent_id,
        parent_transaction_id=parent_txn_id,
        idempotency_key=f"idem_{txn_id}",
        correlation_id=f"corr_{txn_id}",
        state=state,
        max_turns=10,
        turn_count=1,
        final_disposition=final_disposition,
        taint_flags=[],
        context_sources=[],
        created_at=now,
        updated_at=now,
    )


def _make_delegation(
    delegation_id: str = "del_grant_1",
    parent_agent_id: str = "agent_parent_1",
    child_agent_id: str = "agent_child_1",
    parent_txn_id: str = "txn_parent_1",
    child_txn_id: str = "txn_child_1",
    status: str = DelegationStatus.ACTIVE.value,
    caps: list[dict[str, Any]] | None = None,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
    max_autonomy: int = 2,
) -> AgentDelegation:
    now = datetime.now(UTC)
    if caps is None:
        caps = [
            {
                "capability_type": "database:read",
                "resource_scope": {"allowed_prefixes": ["db://finance"]},
                "constraints": {"max_amount": 5000},
                "max_autonomy_level": 2,
            }
        ]
    return AgentDelegation(
        id=delegation_id,
        tenant_id="tenant_gamma",
        parent_agent_id=parent_agent_id,
        parent_transaction_id=parent_txn_id,
        child_agent_id=child_agent_id,
        child_transaction_id=child_txn_id,
        delegated_capabilities=caps,
        resource_scope={},
        max_autonomy_level=max_autonomy,
        delegation_depth=1,
        max_turns=4,
        status=status,
        purpose="Delegated subtask",
        idempotency_key=f"idem_{delegation_id}",
        expires_at=expires_at or (now + timedelta(hours=1)),
        revoked_at=revoked_at,
        created_at=now,
        updated_at=now,
    )


class TestIdempotencySemantics:
    """Verify idempotency key reuse rejects semantic collisions."""

    @pytest.mark.asyncio
    async def test_idempotent_replay_success(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        txn = _make_txn(txn_id="txn_1")
        existing_contract = ActionContract(
            id="act_existing_1",
            tenant_id=auth_context.tenant_id,
            transaction_id="txn_1",
            actor_identity_id=auth_context.identity_id,
            agent_id=txn.agent_id,
            tool_id="tool_calc",
            tool_name="calculator",
            action_type=ActionType.READ.value,
            target_resource="calc://basic",
            parameters={"expression": "2+2"},
            normalized_parameters={"expression": "2+2"},
            parameters_hash="hash_123",
            required_capability="compute:math",
            taint_flags=[],
            risk_score=10,
            blast_radius={},
            state=ActionState.AUTHORIZED.value,
            idempotency_key="idem_calc_1",
            preconditions=[],
            postconditions=[],
            requires_outcome_assurance=False,
            created_at=datetime.now(UTC),
        )

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = txn
            elif "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = existing_contract
            return res

        session.execute.side_effect = mock_exec

        req = ActionProposal(
            transaction_id="txn_1",
            tool_name="calculator",
            action_type=ActionType.READ,
            target_resource="calc://basic",
            parameters={"expression": "2+2"},
            idempotency_key="idem_calc_1",
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                decision = await governor_service.propose_and_authorize_action(auth=auth_context, req=req)

        assert decision.action_id == "act_existing_1"
        assert decision.decision == Decision.ALLOW
        assert decision.state == ActionState.AUTHORIZED
        assert "Idempotent replay" in decision.reason

    @pytest.mark.asyncio
    async def test_idempotency_semantic_mismatch_rejected(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        txn = _make_txn(txn_id="txn_1")
        existing_contract = ActionContract(
            id="act_existing_1",
            tenant_id=auth_context.tenant_id,
            transaction_id="txn_1",
            actor_identity_id=auth_context.identity_id,
            agent_id=txn.agent_id,
            tool_id="tool_calc",
            tool_name="calculator",
            action_type=ActionType.READ.value,
            target_resource="calc://basic",
            parameters={"expression": "2+2"},
            normalized_parameters={"expression": "2+2"},
            parameters_hash="hash_123",
            required_capability="compute:math",
            taint_flags=[],
            risk_score=10,
            blast_radius={},
            state=ActionState.AUTHORIZED.value,
            idempotency_key="idem_reused_key",
            preconditions=[],
            postconditions=[],
            requires_outcome_assurance=False,
            created_at=datetime.now(UTC),
        )

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = txn
            elif "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = existing_contract
            return res

        session.execute.side_effect = mock_exec

        # Reusing the SAME key but with different tool and action type
        req = ActionProposal(
            transaction_id="txn_1",
            tool_name="db_query",
            action_type=ActionType.WRITE,
            target_resource="db://finance",
            parameters={"query": "DELETE"},
            idempotency_key="idem_reused_key",
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                decision = await governor_service.propose_and_authorize_action(auth=auth_context, req=req)

        assert decision.decision == Decision.BLOCK
        assert decision.state == ActionState.BLOCKED
        assert "materially different action semantics" in decision.reason


class TestInitiatingAgentLifecycleProposal:
    """Verify that initiating agent status blocks proposal when suspended or revoked."""

    @pytest.mark.asyncio
    async def test_suspended_initiating_agent_blocked_at_proposal(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        txn = _make_txn(txn_id="txn_1", agent_id="agent_suspended_1")

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = txn
            elif "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = None
            return res

        session.execute.side_effect = mock_exec

        req = ActionProposal(
            transaction_id="txn_1",
            tool_name="calculator",
            action_type=ActionType.READ,
            target_resource="calc://basic",
            parameters={"expression": "100"},
            idempotency_key="idem_susp_prop",
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=False,
            ):
                decision = await governor_service.propose_and_authorize_action(auth=auth_context, req=req)

        assert decision.decision == Decision.BLOCK
        assert decision.state == ActionState.BLOCKED
        assert "not eligible to propose actions" in decision.reason


class TestChildTransactionDelegationProposal:
    """Verify cross-agent delegation enforcement on child transactions at proposal time."""

    @pytest.mark.asyncio
    async def test_child_transaction_missing_delegation_blocked(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        child_txn = _make_txn(txn_id="txn_child_1", parent_txn_id="txn_parent_1")
        tool = _make_tool()

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = child_txn
            elif "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = None
            elif "tool_registry" in entity_str:
                res.scalar_one_or_none.return_value = tool
            elif "agent_delegations" in entity_str:
                res.scalar_one_or_none.return_value = None  # No delegation grant bound!
            return res

        session.execute.side_effect = mock_exec

        req = ActionProposal(
            transaction_id="txn_child_1",
            tool_name="db_query",
            action_type=ActionType.READ,
            target_resource="db://finance",
            parameters={},
            idempotency_key="idem_child_missing",
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                decision = await governor_service.propose_and_authorize_action(auth=auth_context, req=req)

        assert decision.decision == Decision.BLOCK
        assert decision.state == ActionState.BLOCKED
        assert "has no bound delegation grant" in decision.reason

    @pytest.mark.asyncio
    async def test_child_transaction_pending_delegation_blocked(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        child_txn = _make_txn(txn_id="txn_child_1", parent_txn_id="txn_parent_1")
        tool = _make_tool()
        pending_grant = _make_delegation(status=DelegationStatus.PENDING.value)

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = child_txn
            elif "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = None
            elif "tool_registry" in entity_str:
                res.scalar_one_or_none.return_value = tool
            elif "agent_delegations" in entity_str:
                res.scalar_one_or_none.return_value = pending_grant
            return res

        session.execute.side_effect = mock_exec

        req = ActionProposal(
            transaction_id="txn_child_1",
            tool_name="db_query",
            action_type=ActionType.READ,
            target_resource="db://finance",
            parameters={},
            idempotency_key="idem_child_pending",
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                decision = await governor_service.propose_and_authorize_action(auth=auth_context, req=req)

        assert decision.decision == Decision.BLOCK
        assert decision.state == ActionState.BLOCKED
        assert "is not ACTIVE" in decision.reason

    @pytest.mark.asyncio
    async def test_child_transaction_expired_delegation_blocked(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        child_txn = _make_txn(txn_id="txn_child_1", parent_txn_id="txn_parent_1")
        tool = _make_tool()
        expired_grant = _make_delegation(
            expires_at=datetime.now(UTC) - timedelta(minutes=10),
        )

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = child_txn
            elif "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = None
            elif "tool_registry" in entity_str:
                res.scalar_one_or_none.return_value = tool
            elif "agent_delegations" in entity_str:
                res.scalar_one_or_none.return_value = expired_grant
            return res

        session.execute.side_effect = mock_exec

        req = ActionProposal(
            transaction_id="txn_child_1",
            tool_name="db_query",
            action_type=ActionType.READ,
            target_resource="db://finance",
            parameters={},
            idempotency_key="idem_child_expired",
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                decision = await governor_service.propose_and_authorize_action(auth=auth_context, req=req)

        assert decision.decision == Decision.BLOCK
        assert decision.state == ActionState.BLOCKED
        assert "expired or is revoked" in decision.reason

    @pytest.mark.asyncio
    async def test_child_transaction_delegation_policy_denial(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        child_txn = _make_txn(txn_id="txn_child_1", parent_txn_id="txn_parent_1")
        tool = _make_tool(name="privileged_exec", req_cap="exec:root")
        grant = _make_delegation()

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = child_txn
            elif "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = None
            elif "tool_registry" in entity_str:
                res.scalar_one_or_none.return_value = tool
            elif "agent_delegations" in entity_str:
                res.scalar_one_or_none.return_value = grant
            return res

        session.execute.side_effect = mock_exec

        req = ActionProposal(
            transaction_id="txn_child_1",
            tool_name="privileged_exec",
            action_type=ActionType.EXECUTE,
            target_resource="system://kernel",
            parameters={},
            idempotency_key="idem_child_denied",
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                with patch(
                    "services.delegation_service.delegation_service.validate_delegation_for_operation",
                    new_callable=AsyncMock,
                    return_value=PolicyDecision(
                        decision=Decision.DENY,
                        reason="Capability 'exec:root' not granted by delegation",
                    ),
                ):
                    decision = await governor_service.propose_and_authorize_action(auth=auth_context, req=req)

        assert decision.decision == Decision.DENY
        assert decision.state == ActionState.BLOCKED
        assert "Capability 'exec:root' not granted by delegation" in decision.reason

    @pytest.mark.asyncio
    async def test_child_transaction_valid_delegation_authorized(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        child_txn = _make_txn(txn_id="txn_child_1", parent_txn_id="txn_parent_1")
        tool = _make_tool(name="db_query", req_cap="database:read")
        grant = _make_delegation(max_autonomy=2)

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            res.scalar_one_or_none.return_value = None
            entity_str = str(stmt)
            if "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = child_txn
            elif "action_contracts" in entity_str:
                if "idempotency_key" in entity_str:
                    res.scalar_one_or_none.return_value = None
                elif "count" in entity_str:
                    res.one.return_value = (1, 10)
                else:
                    res.scalars.return_value.all.return_value = [{"estimated_dollar_cost": 0.0}]
            elif "tool_registry" in entity_str:
                res.scalar_one_or_none.return_value = tool
            elif "agent_delegations" in entity_str:
                res.scalar_one_or_none.return_value = grant
            elif "capabilities" in entity_str:
                res.scalars.return_value.all.return_value = []
            elif "audit_log_records" in entity_str:
                res.first.return_value = ("0" * 64, 1)
            return res

        session.execute.side_effect = mock_exec

        req = ActionProposal(
            transaction_id="txn_child_1",
            tool_name="db_query",
            action_type=ActionType.READ,
            target_resource="db://finance/ledger",
            parameters={"amount": 100},
            idempotency_key="idem_child_valid",
            postconditions=[PostconditionRule(assertion="EQUALS", target="status", expected_value="ok")],
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                with patch(
                    "services.delegation_service.delegation_service.validate_delegation_for_operation",
                    new_callable=AsyncMock,
                    return_value=PolicyDecision(decision=Decision.ALLOW, reason="Delegation valid"),
                ):
                    decision = await governor_service.propose_and_authorize_action(auth=auth_context, req=req)

        assert decision.decision == Decision.ALLOW, f"Decision was {decision.decision}, reason: {decision.reason}"
        assert decision.state == ActionState.AUTHORIZED
        assert "Action authorized" in decision.reason


class TestExecutionBoundaryRevalidation:
    """Verify execution-boundary checks prevent unauthorized side effects."""

    @pytest.mark.asyncio
    async def test_principal_mismatch_rejected(
        self,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        auth_different_user = AuthContext(
            tenant_id="tenant_gamma",
            identity_id="usr_hijacker",
            role=Role.OPERATOR,
            token_id="tok_hacked",
        )
        contract = ActionContract(
            id="act_contract_1",
            tenant_id="tenant_gamma",
            transaction_id="txn_1",
            actor_identity_id="usr_original_owner",
            agent_id="agent_1",
            tool_id="tool_calc",
            tool_name="calculator",
            action_type=ActionType.READ.value,
            target_resource="calc://basic",
            parameters={"expression": "1+1"},
            normalized_parameters={"expression": "1+1"},
            parameters_hash="hash_1",
            required_capability="compute:math",
            taint_flags=[],
            risk_score=10,
            blast_radius={},
            state=ActionState.AUTHORIZED.value,
            idempotency_key="idem_1",
            preconditions=[],
            postconditions=[],
            requires_outcome_assurance=False,
            created_at=datetime.now(UTC),
        )
        session.execute.return_value.scalar_one_or_none.return_value = contract

        req = ActionExecutionRequest(action_id="act_contract_1")

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with pytest.raises(HTTPException) as exc:
                await governor_service.execute_action(auth=auth_different_user, req=req)

        assert exc.value.status_code == 403
        assert "Principal mismatch" in exc.value.detail

    @pytest.mark.asyncio
    async def test_agent_suspended_between_proposal_and_execution_blocked(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        contract = ActionContract(
            id="act_contract_2",
            tenant_id=auth_context.tenant_id,
            transaction_id="txn_1",
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_suspended_later",
            tool_id="tool_calc",
            tool_name="calculator",
            action_type=ActionType.READ.value,
            target_resource="calc://basic",
            parameters={"expression": "1+1"},
            normalized_parameters={"expression": "1+1"},
            parameters_hash="hash_1",
            required_capability="compute:math",
            taint_flags=[],
            risk_score=10,
            blast_radius={},
            state=ActionState.AUTHORIZED.value,
            idempotency_key="idem_2",
            preconditions=[],
            postconditions=[],
            requires_outcome_assurance=False,
            created_at=datetime.now(UTC),
        )
        txn = _make_txn(txn_id="txn_1", agent_id="agent_suspended_later")

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = contract
            elif "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = txn
            return res

        session.execute.side_effect = mock_exec

        req = ActionExecutionRequest(action_id="act_contract_2")

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=False,
            ):
                with pytest.raises(HTTPException) as exc:
                    await governor_service.execute_action(auth=auth_context, req=req)

        assert exc.value.status_code == 403
        assert "is suspended, revoked, or inactive at execution time" in exc.value.detail

    @pytest.mark.asyncio
    async def test_delegation_revoked_between_proposal_and_execution_blocked(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        contract = ActionContract(
            id="act_contract_3",
            tenant_id=auth_context.tenant_id,
            transaction_id="txn_child_1",
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child_1",
            tool_id="tool_db",
            tool_name="db_query",
            action_type=ActionType.READ.value,
            target_resource="db://finance",
            parameters={},
            normalized_parameters={},
            parameters_hash="hash_1",
            required_capability="database:read",
            taint_flags=[],
            risk_score=10,
            blast_radius={},
            state=ActionState.AUTHORIZED.value,
            idempotency_key="idem_3",
            preconditions=[],
            postconditions=[],
            requires_outcome_assurance=False,
            created_at=datetime.now(UTC),
        )
        child_txn = _make_txn(txn_id="txn_child_1", parent_txn_id="txn_parent_1")
        tool = _make_tool(name="db_query", req_cap="database:read")
        revoked_grant = _make_delegation(
            status=DelegationStatus.REVOKED.value,
            revoked_at=datetime.now(UTC),
        )

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = contract
            elif "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = child_txn
            elif "tool_registry" in entity_str:
                res.scalar_one_or_none.return_value = tool
            elif "agent_delegations" in entity_str:
                res.scalar_one_or_none.return_value = revoked_grant
            return res

        session.execute.side_effect = mock_exec

        req = ActionExecutionRequest(action_id="act_contract_3")

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                with pytest.raises(HTTPException) as exc:
                    await governor_service.execute_action(auth=auth_context, req=req)

        assert exc.value.status_code == 403
        assert "is not ACTIVE (current: REVOKED)" in exc.value.detail

    @pytest.mark.asyncio
    async def test_uncertain_outcome_remains_pending_verification(
        self,
        auth_context: AuthContext,
        governor_service: ActionGovernorService,
    ) -> None:
        session = _build_mock_session()
        contract = ActionContract(
            id="act_contract_4",
            tenant_id=auth_context.tenant_id,
            transaction_id="txn_child_1",
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child_1",
            tool_id="tool_db",
            tool_name="db_query",
            action_type=ActionType.WRITE.value,
            target_resource="db://finance/ledger",
            parameters={"query": "INSERT INTO accounts VALUES (1)"},
            normalized_parameters={"query": "INSERT INTO accounts VALUES (1)"},
            parameters_hash="hash_1",
            required_capability="database:read",
            taint_flags=[],
            risk_score=50,
            blast_radius={"estimated_dollar_cost": 0.0},
            state=ActionState.AUTHORIZED.value,
            idempotency_key="idem_4",
            preconditions=[],
            postconditions=[{"assertion": "EQUALS", "target": "status", "expected_value": "ok"}],
            requires_outcome_assurance=True,
            outcome_contract={
                "requires_outcome_assurance": True,
                "verification_deadline_seconds": 30.0,
            },
            outcome_status=OutcomeStatus.PENDING_VERIFICATION.value,
            created_at=datetime.now(UTC),
        )
        child_txn = _make_txn(txn_id="txn_child_1", parent_txn_id="txn_parent_1")
        tool = _make_tool(name="db_query", req_cap="database:read")
        grant = _make_delegation()

        def mock_exec(stmt: Any) -> MagicMock:
            res = MagicMock()
            entity_str = str(stmt)
            if "action_contracts" in entity_str:
                res.scalar_one_or_none.return_value = contract
            elif "ai_transactions" in entity_str:
                res.scalar_one_or_none.return_value = child_txn
            elif "tool_registry" in entity_str:
                res.scalar_one_or_none.return_value = tool
            elif "agent_delegations" in entity_str:
                res.scalar_one_or_none.return_value = grant
            elif "capabilities" in entity_str:
                res.scalars.return_value.all.return_value = []
            elif "audit_log_records" in entity_str:
                res.first.return_value = ("0" * 64, 1)
            return res

        session.execute.side_effect = mock_exec

        req = ActionExecutionRequest(action_id="act_contract_4")

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with patch(
                "services.agent_governance.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                with patch(
                    "services.delegation_service.delegation_service.validate_delegation_for_operation",
                    new_callable=AsyncMock,
                    return_value=PolicyDecision(
                        decision=Decision.ALLOW,
                        reason="Delegation valid",
                    ),
                ):
                    result = await governor_service.execute_action(auth=auth_context, req=req)

        # Invariant: A tool HTTP 200 / success is NOT proof of real-world outcome!
        # State transitions to EXECUTED, outcome remains PENDING_VERIFICATION awaiting
        # Gate 5 Reality Verifier observation.
        assert result.action_id == "act_contract_4"
        assert result.state == ActionState.EXECUTED
        assert result.outcome_status == OutcomeStatus.PENDING_VERIFICATION
        assert result.postconditions_satisfied is False
        assert contract.state == ActionState.EXECUTED.value
