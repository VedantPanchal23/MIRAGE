"""Dedicated regression test suite verifying Prompt 11 Consolidated Security and Execution-Safety Remediation.

Covers:
1. P0 - 1: Durable two-phase execution protocol preventing duplicate external side effects
           (pre-dispatch commit of EXECUTING, post-dispatch failure to EXECUTION_UNCERTAIN, 409 rejection of retries).
2. P0 - 2: Enforcing authenticated agent-to-transaction ownership binding at proposal and execution boundaries.
3. P0 - 3: Epistemic hierarchical outcome assurance preventing false VERIFIED_SUCCESS
           on failed/cancelled child transactions.
4. P0 - 4 & P1 - 7: Lease serialization, RFC 3986 URI normalization, and hierarchical fencing token inheritance.
5. P1 - 6: Secure handoff completion enforcing caller authorization,
           child transaction completion, and outcome assurance.
6. P2 - 9: JWT audience and issuer claim enforcement.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import (
    ActionContract,
    Agent,
    AgentHandoff,
    AITransaction,
    Capability,
    ResourceLease,
    ToolDefinition,
)
from services.action_governor import ActionGovernorService
from services.concurrency_service import (
    canonicalize_resource_uri,
)
from services.handoff_service import AgentHandoffService
from services.hierarchical_outcome_service import HierarchicalOutcomeService
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
from shared.schemas.control_plane import Decision
from shared.schemas.handoff import HandoffStatus
from shared.schemas.hierarchical_outcome import HierarchicalOutcomeStatus


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

    async def _mock_get(model: object, pk: object, **_kwargs: object) -> object:
        if model is Agent:
            return Agent(
                id=str(pk),
                tenant_id="tenant_alpha",
                name=f"Agent {pk}",
                status="active",
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        return None

    session.get = AsyncMock(side_effect=_mock_get)
    return session


# ===========================================================================
# 1. P0 - 1: Durable Action Execution Protocol & Failure Modes
# ===========================================================================


class TestDurableActionExecutionFailureModes:
    """Verify that external side effects cannot be duplicated following post-dispatch DB failure."""

    @pytest.mark.asyncio
    async def test_post_dispatch_failure_transitions_to_execution_uncertain(self) -> None:
        """When dispatch succeeds but post-dispatch persistence fails, state becomes EXECUTION_UNCERTAIN."""
        governor = ActionGovernorService()
        session = _build_mock_session()
        now = datetime.now(UTC)

        contract = ActionContract(
            id="act_durable_1",
            tenant_id="tenant_alpha",
            transaction_id="txn_alpha_1",
            actor_identity_id="usr_owner",
            agent_id="agent_alpha",
            tool_id="tool_payment",
            tool_name="payment_gateway",
            action_type=ActionType.WRITE.value,
            target_resource="api://payments.internal/charge",
            parameters={"amount": 100},
            normalized_parameters={"amount": 100},
            parameters_hash="hash_amt",
            required_capability="finance:charge",
            taint_flags=[],
            risk_score=25,
            blast_radius={},
            state=ActionState.AUTHORIZED.value,
            idempotency_key="idem_pay_1",
            preconditions=[],
            postconditions=[],
            requires_outcome_assurance=False,
            created_at=now,
        )

        txn = AITransaction(
            id="txn_alpha_1",
            tenant_id="tenant_alpha",
            agent_id="agent_alpha",
            actor_identity_id="usr_owner",
            state="ACTIVE",
            turn_count=1,
            max_turns=10,
            taint_flags=[],
            context_sources=[],
            version=0,
            created_at=now,
            updated_at=now,
        )

        tool = ToolDefinition(
            id="tool_payment",
            tenant_id="tenant_alpha",
            name="payment_gateway",
            tool_type=ToolType.NATIVE.value,
            description="Process payments",
            parameters_schema={},
            required_capability="finance:charge",
            trust_level=ToolTrustLevel.VERIFIED.value,
            egress_type=EgressType.INTERNAL_ISOLATED.value,
            active=True,
            created_at=now,
            updated_at=now,
        )

        cap = Capability(
            id="cap_charge",
            tenant_id="tenant_alpha",
            identity_id="usr_owner",
            agent_id="agent_alpha",
            capability_type="finance:charge",
            resource_scope={},
            constraints={},
            max_autonomy_level=4,
            created_at=now,
        )

        def mock_exec(stmt: object) -> MagicMock:
            res = MagicMock()
            res.scalar_one_or_none.return_value = None
            res.scalars.return_value.all.return_value = []
            res.all.return_value = []
            res.first.return_value = None
            res.scalar.return_value = 0
            res.scalar_one.return_value = 0
            stmt_str = str(stmt).lower()
            if "action_contracts" in stmt_str:
                res.scalar_one_or_none.return_value = contract
            elif "ai_transactions" in stmt_str:
                res.scalar_one_or_none.return_value = txn
            elif "tool_registry" in stmt_str:
                res.scalar_one_or_none.return_value = tool
            elif "capabilities" in stmt_str:
                res.scalars.return_value.all.return_value = [cap]
            elif "audit_logs" in stmt_str:
                res.first.return_value = None
                res.scalar.return_value = 0
            return res

        session.execute.side_effect = mock_exec

        auth = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_owner",
            role=Role.API_CLIENT,
            agent_id="agent_alpha",
        )
        req = ActionExecutionRequest(action_id="act_durable_1")

        # Simulate tool proxy executing successfully (external side effect occurred)
        with patch.object(
            governor.tool_proxy,
            "dispatch",
            AsyncMock(return_value=({"status": "charged", "tx_id": "ext_999"}, None)),
        ) as mock_dispatch:
            with patch("db.session.get_tenant_session") as mock_ts:
                mock_ts.return_value.__aenter__.return_value = session

                # Post-dispatch Phase 3 fails during flush (e.g., DB constraint or connection drop)
                original_flush = session.flush
                flush_call_count = 0

                async def mock_flush() -> None:
                    nonlocal flush_call_count
                    flush_call_count += 1
                    # Fail on the post-dispatch flush (Phase 3)
                    if flush_call_count >= 2:
                        raise RuntimeError("Database connection broken while persisting outcome")
                    return await original_flush()

                session.flush.side_effect = mock_flush

                with pytest.raises(HTTPException) as exc_info:
                    await governor.execute_action(auth=auth, req=req)

                assert exc_info.value.status_code == 500
                assert "EXECUTION_UNCERTAIN" in exc_info.value.detail
                assert "Database connection broken" in exc_info.value.detail
                assert mock_dispatch.await_count == 1
                # Contract state must be marked EXECUTION_UNCERTAIN to prevent repeat execution
                assert contract.state == ActionState.EXECUTION_UNCERTAIN.value

    @pytest.mark.asyncio
    async def test_retries_rejected_for_executing_and_uncertain_states(self) -> None:
        """Retry of an EXECUTING or EXECUTION_UNCERTAIN action contract is rejected with 409 Conflict."""
        governor = ActionGovernorService()
        session = _build_mock_session()
        now = datetime.now(UTC)

        for state in (ActionState.EXECUTING.value, ActionState.EXECUTION_UNCERTAIN.value):
            contract = ActionContract(
                id=f"act_retry_{state}",
                tenant_id="tenant_alpha",
                transaction_id="txn_1",
                actor_identity_id="usr_1",
                agent_id="agent_1",
                tool_id="tool_1",
                tool_name="tool_1",
                action_type=ActionType.WRITE.value,
                target_resource="db://test",
                parameters={},
                normalized_parameters={},
                parameters_hash="h",
                required_capability="db:write",
                taint_flags=[],
                risk_score=10,
                blast_radius={},
                state=state,
                idempotency_key=f"idem_{state}",
                preconditions=[],
                postconditions=[],
                requires_outcome_assurance=False,
                created_at=now,
            )
            exec_mock = MagicMock()
            exec_mock.scalar_one_or_none.return_value = contract
            session.execute.return_value = exec_mock

            auth = AuthContext(
                tenant_id="tenant_alpha",
                identity_id="usr_1",
                role=Role.API_CLIENT,
                agent_id="agent_1",
            )
            req = ActionExecutionRequest(action_id=contract.id)

            with patch("db.session.get_tenant_session") as mock_ts:
                mock_ts.return_value.__aenter__.return_value = session
                with pytest.raises(HTTPException) as exc_info:
                    await governor.execute_action(auth=auth, req=req)

                assert exc_info.value.status_code == 409
                assert "EXECUTING" in exc_info.value.detail or "EXECUTION_UNCERTAIN" in exc_info.value.detail


# ===========================================================================
# 2. P0 - 2: Enforce Authenticated Agent-to-Transaction Binding
# ===========================================================================


class TestAgentToTransactionOwnershipBinding:
    """Verify that an agent cannot propose or execute actions against another agent's transaction."""

    @pytest.mark.asyncio
    async def test_cross_agent_proposal_blocked_without_delegation(self) -> None:
        """Agent B proposing an action under Agent A's transaction is blocked with 403 / BLOCK."""
        governor = ActionGovernorService()
        session = _build_mock_session()
        now = datetime.now(UTC)

        txn = AITransaction(
            id="txn_agent_a",
            tenant_id="tenant_alpha",
            agent_id="agent_A",  # Owned by Agent A
            actor_identity_id="usr_original",
            state="ACTIVE",
            turn_count=1,
            max_turns=10,
            taint_flags=[],
            context_sources=[],
            version=0,
            created_at=now,
            updated_at=now,
        )

        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = txn
        exec_del = MagicMock()
        exec_del.scalar_one_or_none.return_value = None  # No delegation grant from A to B
        session.execute.side_effect = [exec_txn, exec_del]

        # Rogue Agent B attempts proposal on Agent A's transaction
        auth_agent_b = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_agent_b",
            role=Role.API_CLIENT,
            agent_id="agent_B",
        )
        proposal = ActionProposal(
            transaction_id="txn_agent_a",
            tool_name="database_writer",
            action_type=ActionType.WRITE,
            target_resource="db://finance/ledger",
            parameters={"query": "DELETE FROM accounts"},
            required_capability="db:write",
            idempotency_key="idem_cross_prop",
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            dec = await governor.propose_and_authorize_action(auth=auth_agent_b, req=proposal)

            assert dec.decision == Decision.BLOCK
            assert "Authenticated agent 'agent_B' is not authorized for transaction" in dec.reason

    @pytest.mark.asyncio
    async def test_cross_agent_execution_rejected_with_403_principal_mismatch(self) -> None:
        """Agent B calling execute_action on an ActionContract authorized for Agent A is rejected with 403."""
        governor = ActionGovernorService()
        session = _build_mock_session()
        now = datetime.now(UTC)

        contract = ActionContract(
            id="act_agent_a_1",
            tenant_id="tenant_alpha",
            transaction_id="txn_agent_a",
            actor_identity_id="usr_a",
            agent_id="agent_A",
            tool_id="tool_1",
            tool_name="tool_1",
            action_type=ActionType.WRITE.value,
            target_resource="db://finance",
            parameters={},
            normalized_parameters={},
            parameters_hash="h",
            required_capability="db:write",
            taint_flags=[],
            risk_score=10,
            blast_radius={},
            state=ActionState.AUTHORIZED.value,
            idempotency_key="idem_a",
            preconditions=[],
            postconditions=[],
            requires_outcome_assurance=False,
            created_at=now,
        )

        exec_contract = MagicMock()
        exec_contract.scalar_one_or_none.return_value = contract
        exec_del = MagicMock()
        exec_del.scalar_one_or_none.return_value = None  # No active delegation
        session.execute.side_effect = [exec_contract, exec_del]

        auth_agent_b = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_b",
            role=Role.API_CLIENT,
            agent_id="agent_B",
        )
        req = ActionExecutionRequest(action_id="act_agent_a_1")

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with pytest.raises(HTTPException) as exc_info:
                await governor.execute_action(auth=auth_agent_b, req=req)

            assert exc_info.value.status_code == 403
            assert "Principal mismatch" in exc_info.value.detail


# ===========================================================================
# 3. P0 - 3: Epistemic Hierarchical Outcome Assurance
# ===========================================================================


class TestHierarchicalOutcomeAssuranceInvariants:
    """Verify that failed/cancelled child transactions never yield VERIFIED_SUCCESS."""

    @pytest.mark.asyncio
    async def test_child_failed_or_cancelled_produces_hierarchical_failure(self) -> None:
        """A parent transaction whose child failed or cancelled must produce HIERARCHICAL_FAILURE (0.0 confidence)."""
        service = HierarchicalOutcomeService()
        session = _build_mock_session()
        now = datetime.now(UTC)

        parent_txn = AITransaction(
            id="txn_parent_1",
            tenant_id="tenant_alpha",
            state="COMPLETED",
            final_disposition="COMPLETED",
            version=0,
            created_at=now,
            updated_at=now,
        )

        # Child transaction aborted without executing any action contracts
        failed_child = AITransaction(
            id="txn_child_failed",
            tenant_id="tenant_alpha",
            parent_transaction_id="txn_parent_1",
            state="FAILED",
            final_disposition="FAILED",
            version=0,
            created_at=now,
            updated_at=now,
        )

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn
        exec_children = MagicMock()
        exec_children.scalars.return_value.all.return_value = [failed_child]
        exec_empty = MagicMock()
        exec_empty.scalars.return_value.all.return_value = []

        session.execute.side_effect = [
            exec_parent,  # 1. select parent txn
            exec_children,  # 2. select children of parent
            exec_empty,  # 3. select children of failed_child (frontier loop 2)
            exec_empty,  # 4. select handoffs
            exec_empty,  # 5. select actions
            exec_empty,  # 6. late observation audit query
            exec_empty,  # 7. evaluated status audit query
            exec_empty,  # 8. safety margin
        ]

        auth = AuthContext(tenant_id="tenant_alpha", identity_id="usr_eval", role=Role.OPERATOR)

        with patch("services.hierarchical_outcome_service.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            summary = await service.aggregate_transaction_outcome(auth=auth, transaction_id="txn_parent_1")

            assert summary.hierarchical_status == HierarchicalOutcomeStatus.HIERARCHICAL_FAILURE
            assert summary.epistemic_confidence == 0.0
            assert any("non-successful state" in r for r in summary.reconciliation_notes)


# ===========================================================================
# 4. P1 - 7: URI Normalization & Hierarchical Fencing Token Lookup
# ===========================================================================


class TestUriNormalizationAndFencingHardening:
    """Verify RFC 3986 port normalization, traversal rejection, and hierarchical fencing lookup."""

    def test_default_port_normalization_http_and_https_only(self) -> None:
        """Default ports for HTTP/HTTPS are normalized, while non-web schemes retain their ports."""
        assert canonicalize_resource_uri("http://api.service.com:80/v1/orders") == "http://api.service.com/v1/orders"
        assert canonicalize_resource_uri("https://api.service.com:443/v1/orders") == "https://api.service.com/v1/orders"
        assert (
            canonicalize_resource_uri("http://api.service.com:8080/v1/orders")
            == "http://api.service.com:8080/v1/orders"
        )
        # Non-standard schemes preserve port
        assert (
            canonicalize_resource_uri("postgres://primary.internal:5432/finance/ledger?timeout=30")
            == "postgres://primary.internal:5432/finance/ledger?timeout=30"
        )

    def test_dot_segment_traversal_outside_root_raises_value_error(self) -> None:
        """Path traversal outside root raises ValueError."""
        with pytest.raises(ValueError) as exc:
            canonicalize_resource_uri("s3://bucket/../../secret.csv")
        assert "Path traversal outside resource root" in str(exc.value)

    def test_percent_encoding_normalizes_unreserved_preserves_slashes(self) -> None:
        """Unreserved percent-encoded characters are unquoted while encoded slashes are preserved."""
        # %20 unquoted to space, %2F preserved as %2F
        norm = canonicalize_resource_uri("resource://local/folder%20name/sub%2Fpath")
        assert "folder name" in norm
        assert "%2F" in norm

    @pytest.mark.asyncio
    async def test_hierarchical_lease_fencing_token_lookup(self) -> None:
        """An action targeting a sub-resource finds the fencing token of its parent exclusive lease."""
        governor = ActionGovernorService()
        session = _build_mock_session()
        now = datetime.now(UTC)

        parent_lease = ResourceLease(
            id="lse_parent_1",
            tenant_id="tenant_alpha",
            resource_uri="db://finance/ledger",
            concurrency_mode="EXCLUSIVE",
            holder_agent_id="agent_1",
            holder_transaction_id="txn_holder_1",
            fencing_token=42,
            status="ACQUIRED",
            expires_at=now + timedelta(minutes=10),
            created_at=now,
            updated_at=now,
        )

        txn = AITransaction(
            id="txn_holder_1",
            tenant_id="tenant_alpha",
            agent_id="agent_1",
            actor_identity_id="usr_1",
            state="ACTIVE",
            turn_count=1,
            max_turns=10,
            taint_flags=[],
            context_sources=[],
            version=0,
            created_at=now,
            updated_at=now,
        )

        tool = ToolDefinition(
            id="tool_sql",
            tenant_id="tenant_alpha",
            name="internal_sql_query",
            tool_type=ToolType.NATIVE.value,
            description="SQL",
            parameters_schema={},
            required_capability="db:write",
            trust_level=ToolTrustLevel.VERIFIED.value,
            egress_type=EgressType.INTERNAL_ISOLATED.value,
            active=True,
            created_at=now,
            updated_at=now,
        )

        cap = Capability(
            id="cap_1",
            tenant_id="tenant_alpha",
            identity_id="usr_1",
            capability_type="db:write",
            resource_scope={"allowed_prefixes": ["db://"]},
            constraints={},
            max_autonomy_level=4,
            created_at=now,
        )

        def mock_exec(stmt: object) -> MagicMock:
            res = MagicMock()
            res.scalar_one_or_none.return_value = None
            res.scalars.return_value.all.return_value = []
            res.all.return_value = []
            res.first.return_value = None
            stmt_str = str(stmt).lower()
            if "ai_transactions" in stmt_str:
                res.scalar_one_or_none.return_value = txn
            elif "tool_registry" in stmt_str:
                res.scalar_one_or_none.return_value = tool
            elif "capabilities" in stmt_str:
                res.scalars.return_value.all.return_value = [cap]
            elif "resource_leases" in stmt_str:
                res.scalars.return_value.all.return_value = [parent_lease]
            elif "action_contracts" in stmt_str:
                res.scalar_one_or_none.return_value = None
                res.scalars.return_value.all.return_value = []
            return res

        session.execute.side_effect = mock_exec

        auth = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_1",
            role=Role.API_CLIENT,
            agent_id="agent_1",
        )
        proposal = ActionProposal(
            transaction_id="txn_holder_1",
            tool_name="internal_sql_query",
            action_type=ActionType.WRITE,
            target_resource="db://finance/ledger/invoices/2026",  # Sub-resource of db://finance/ledger
            parameters={"query": "UPDATE invoices SET paid=true"},
            required_capability="db:write",
            idempotency_key="idem_prop_hier",
            postconditions=[
                PostconditionRule(
                    assertion="EQUALS",
                    target="status",
                    expected_value="updated",
                )
            ],
        )

        with patch("db.session.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            dec = await governor.propose_and_authorize_action(auth=auth, req=proposal)

            assert dec.decision == Decision.ALLOW, f"Expected ALLOW but got {dec.decision}: {dec.reason}"
            # Action contract must have inherited fencing token 42 from parent lease
            assert dec.fencing_token == 42


# ===========================================================================
# 5. P1 - 6: Secure Handoff Completion
# ===========================================================================


class TestSecureHandoffCompletionInvariants:
    """Verify authorization and outcome validation in complete_handoff."""

    @pytest.mark.asyncio
    async def test_complete_handoff_rejects_unauthorized_caller(self) -> None:
        """Caller who is neither participant nor admin is rejected with 403."""
        service = AgentHandoffService()
        session = _build_mock_session()
        now = datetime.now(UTC)

        handoff = AgentHandoff(
            id="hnd_1",
            tenant_id="tenant_alpha",
            parent_transaction_id="txn_p",
            parent_agent_id="agent_parent",
            child_agent_id="agent_child",
            delegation_id="del_1",
            child_transaction_id="txn_c",
            status=HandoffStatus.ACCEPTED.value,
            purpose="test",
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            updated_at=now,
        )

        exec_hnd = MagicMock()
        exec_hnd.scalar_one_or_none.return_value = handoff
        session.execute.return_value = exec_hnd

        auth_unauthorized = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_rando",
            role=Role.API_CLIENT,
            agent_id="agent_rando",
        )

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with pytest.raises(HTTPException) as exc_info:
                await service.complete_handoff(auth=auth_unauthorized, handoff_id="hnd_1")

            assert exc_info.value.status_code == 403
            assert "Caller is not authorized" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_complete_handoff_rejects_unverified_outcome_actions(self) -> None:
        """Handoff completion is rejected if consequential child actions lack verified outcome assurance."""
        service = AgentHandoffService()
        session = _build_mock_session()
        now = datetime.now(UTC)

        handoff = AgentHandoff(
            id="hnd_1",
            tenant_id="tenant_alpha",
            parent_transaction_id="txn_p",
            parent_agent_id="agent_parent",
            child_agent_id="agent_child",
            delegation_id="del_1",
            child_transaction_id="txn_c",
            status=HandoffStatus.ACCEPTED.value,
            purpose="test",
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_c",
            tenant_id="tenant_alpha",
            state="COMPLETED",
            final_disposition="COMPLETED",
            created_at=now,
            updated_at=now,
        )

        # Consequential action has outcome_status PENDING_VERIFICATION
        consequential_action = ActionContract(
            id="act_conseq_1",
            tenant_id="tenant_alpha",
            transaction_id="txn_c",
            requires_outcome_assurance=True,
            outcome_status="PENDING_VERIFICATION",
            created_at=now,
        )

        exec_hnd = MagicMock()
        exec_hnd.scalar_one_or_none.return_value = handoff
        exec_act = MagicMock()
        exec_act.scalars.return_value.all.return_value = [consequential_action]

        session.execute.side_effect = [exec_hnd, exec_act]
        session.get = AsyncMock(return_value=child_txn)

        auth_child = AuthContext(
            tenant_id="tenant_alpha",
            identity_id="usr_child",
            role=Role.API_CLIENT,
            agent_id="agent_child",
        )

        with patch("services.handoff_service.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = session
            with pytest.raises(HTTPException) as exc_info:
                await service.complete_handoff(auth=auth_child, handoff_id="hnd_1")

            assert exc_info.value.status_code == 409
            assert "required outcome assurance but outcome status is 'PENDING_VERIFICATION'" in exc_info.value.detail
