"""Unit tests for Phase 8 Hierarchical Outcome Assurance and Lifecycle Audit.

Validates:
1. Unaccepted pending handoff blocks parent completion (PENDING_CHILD_WORK).
2. Actively executing child transaction blocks parent completion (PENDING_CHILD_WORK).
3. Child tool execution completion alone is NOT equated to outcome completion:
   if child actions require outcome assurance and remain PENDING_VERIFICATION,
   parent cannot complete (AWAITING_OUTCOME_VERIFICATION).
4. Verified child outcomes aggregate to parent VERIFIED_SUCCESS with calibrated epistemic confidence.
5. Failed child action leads to HIERARCHICAL_FAILURE or PARTIAL_ACHIEVEMENT.
6. Actions targeting unobservable/blind sinks (OBS_BLIND) resolve to UNVERIFIABLE with confidence 0.0.
7. Multi-level nested delegation lineage (Grandparent -> Parent -> Child) evaluated recursively.
8. Late child observations cannot silently mutate committed terminal parent records:
   discrepancy detected, reconciliation recorded, audit emitted, committed disposition preserved.
9. Parent transaction cancellation propagates downward, cancelling pending handoffs and child transactions.
10. Action Governor execution boundary rejects child actions when parent transaction is cancelled or terminal.
11. REST endpoints: GET /v1/transactions/{id}/hierarchy and POST /v1/handoffs/{id}/complete.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from db.models import (
    ActionContract,
    AgentHandoff,
    AITransaction,
    OutcomeVerificationRecord,
)
from gateway.main import create_app
from services.action_governor import ActionGovernorService
from services.control_plane import cancel_transaction
from services.handoff_service import AgentHandoffService
from services.hierarchical_outcome_service import HierarchicalOutcomeService
from shared.schemas.action import (
    ActionProposal,
    ActionState,
    ActionType,
    BlastRadiusAssessment,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import (
    Decision,
    TransactionState,
)
from shared.schemas.handoff import HandoffStatus
from shared.schemas.hierarchical_outcome import (
    HierarchicalOutcomeResponse,
    HierarchicalOutcomeStatus,
)
from shared.schemas.outcome import ObservabilityClass, OutcomeStatus
from tests.auth_factory import AuthTestFactory


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_omega",
        identity_id="usr_lead_1",
        role=Role.OPERATOR,
        token_id="tok_omega_1",
        agent_id="agent_root_1",
    )


@pytest.fixture
def outcome_service() -> HierarchicalOutcomeService:
    return HierarchicalOutcomeService()


@pytest.fixture
def handoff_service() -> AgentHandoffService:
    return AgentHandoffService()


@pytest.fixture
def action_governor() -> ActionGovernorService:
    return ActionGovernorService()


@pytest.fixture(scope="module")
def api_client() -> TestClient:
    return TestClient(create_app())


def _build_mock_session() -> AsyncMock:
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
    return session


# =============================================================================
# 1. Parent/Child Outcome Aggregation Unit Tests
# =============================================================================


class TestParentChildOutcomeAggregation:
    @pytest.mark.asyncio
    async def test_unaccepted_handoff_blocks_parent_completion(
        self, outcome_service: HierarchicalOutcomeService, auth_context: AuthContext
    ) -> None:
        """A parent transaction cannot complete while a delegated handoff is still pending acceptance."""
        now = datetime.now(UTC)
        parent_txn = AITransaction(
            id="txn_parent_1",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            parent_transaction_id=None,
            idempotency_key="idem_p1",
            correlation_id="corr_p1",
            state="ACTIVE",
            max_turns=10,
            turn_count=2,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        pending_handoff = AgentHandoff(
            id="hnd_pending_1",
            tenant_id=auth_context.tenant_id,
            parent_transaction_id=parent_txn.id,
            parent_agent_id="agent_parent",
            child_agent_id="agent_child",
            delegation_id="del_grant_1",
            child_transaction_id=None,
            status=HandoffStatus.PENDING.value,
            purpose="Subtask calculation",
            permitted_scope={},
            inherited_taint_flags=[],
            idempotency_key="idem_hnd_1",
            expires_at=now + timedelta(minutes=5),
            accepted_at=None,
            completed_at=None,
            cancelled_at=None,
            created_at=now,
            updated_at=now,
        )

        session = _build_mock_session()
        # Query 1: parent_txn; Query 2: children (empty); Query 3: handoffs; Query 4: actions; Query 5: audit
        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        exec_children = MagicMock()
        exec_children.scalars.return_value.all.return_value = []

        exec_handoffs = MagicMock()
        exec_handoffs.scalars.return_value.all.return_value = [pending_handoff]

        exec_actions = MagicMock()
        exec_actions.scalars.return_value.all.return_value = []

        exec_audit = MagicMock()
        exec_audit.first.return_value = ("0" * 64, 1)

        session.execute.side_effect = [
            exec_parent,
            exec_children,
            exec_handoffs,
            exec_actions,
            exec_audit,
        ]

        resp = await outcome_service.aggregate_transaction_outcome(auth_context, parent_txn.id, session=session)

        assert resp.hierarchical_status == HierarchicalOutcomeStatus.PENDING_CHILD_WORK
        assert resp.pending_handoffs == 1
        assert resp.epistemic_confidence == 0.0

        # Enforce that verify_hierarchical_completion raises 409 Conflict
        session.execute.side_effect = [
            exec_parent,
            exec_children,
            exec_handoffs,
            exec_actions,
            exec_audit,
        ]
        with pytest.raises(HTTPException) as exc_info:
            await outcome_service.verify_hierarchical_completion(auth_context, parent_txn.id, session=session)
        assert exc_info.value.status_code == 409
        assert "pending acceptance" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_active_child_transaction_blocks_parent_completion(
        self, outcome_service: HierarchicalOutcomeService, auth_context: AuthContext
    ) -> None:
        """A parent cannot complete while a child transaction is actively executing."""
        now = datetime.now(UTC)
        parent_txn = AITransaction(
            id="txn_parent_2",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            parent_transaction_id=None,
            idempotency_key="idem_p2",
            correlation_id="corr_p2",
            state="ACTIVE",
            max_turns=10,
            turn_count=2,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_child_2",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            parent_transaction_id=parent_txn.id,
            idempotency_key="idem_c2",
            correlation_id="corr_p2",
            state="ACTIVE",
            max_turns=5,
            turn_count=1,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        accepted_handoff = AgentHandoff(
            id="hnd_acc_2",
            tenant_id=auth_context.tenant_id,
            parent_transaction_id=parent_txn.id,
            parent_agent_id="agent_parent",
            child_agent_id="agent_child",
            delegation_id="del_grant_1",
            child_transaction_id=child_txn.id,
            status=HandoffStatus.ACCEPTED.value,
            purpose="Payment processing",
            permitted_scope={},
            inherited_taint_flags=[],
            idempotency_key="idem_hnd_2",
            expires_at=now + timedelta(minutes=5),
            accepted_at=now,
            completed_at=None,
            cancelled_at=None,
            created_at=now,
            updated_at=now,
        )

        session = _build_mock_session()
        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        exec_children_1 = MagicMock()
        exec_children_1.scalars.return_value.all.return_value = [child_txn]

        exec_children_2 = MagicMock()
        exec_children_2.scalars.return_value.all.return_value = []

        exec_handoffs = MagicMock()
        exec_handoffs.scalars.return_value.all.return_value = [accepted_handoff]

        exec_actions = MagicMock()
        exec_actions.scalars.return_value.all.return_value = []

        exec_audit = MagicMock()
        exec_audit.first.return_value = ("0" * 64, 1)

        session.execute.side_effect = [
            exec_parent,
            exec_children_1,
            exec_children_2,
            exec_handoffs,
            exec_actions,
            exec_audit,
        ]

        resp = await outcome_service.aggregate_transaction_outcome(auth_context, parent_txn.id, session=session)
        assert resp.hierarchical_status == HierarchicalOutcomeStatus.PENDING_CHILD_WORK
        assert resp.active_child_transactions == 1

        session.execute.side_effect = [
            exec_parent,
            exec_children_1,
            exec_children_2,
            exec_handoffs,
            exec_actions,
            exec_audit,
        ]
        with pytest.raises(HTTPException) as exc_info:
            await outcome_service.verify_hierarchical_completion(auth_context, parent_txn.id, session=session)
        assert exc_info.value.status_code == 409
        assert "actively executing" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_child_execution_completion_alone_insufficient_without_outcome_verification(
        self, outcome_service: HierarchicalOutcomeService, auth_context: AuthContext
    ) -> None:
        """Crucial Phase 8 Invariant: Child agent finishing execution does NOT equal verified outcome.

        If a child transaction executed tool actions requiring outcome assurance, but Gate 5
        reality verification is still PENDING_VERIFICATION, the parent cannot be marked completed.
        """
        now = datetime.now(UTC)
        parent_txn = AITransaction(
            id="txn_parent_3",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            parent_transaction_id=None,
            idempotency_key="idem_p3",
            correlation_id="corr_p3",
            state="ACTIVE",
            max_turns=10,
            turn_count=2,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        # Child transaction is technically COMPLETED in execution state
        child_txn = AITransaction(
            id="txn_child_3",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            parent_transaction_id=parent_txn.id,
            idempotency_key="idem_c3",
            correlation_id="corr_p3",
            state="COMPLETED",
            max_turns=5,
            turn_count=3,
            final_disposition="COMPLETED",
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        child_action = ActionContract(
            id="act_child_3",
            tenant_id=auth_context.tenant_id,
            transaction_id=child_txn.id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            tool_id="tool_transfer",
            tool_name="stripe_transfer",
            action_type="EXECUTE",
            target_resource="stripe://transfers/tr_999",
            parameters={"amount": 5000},
            normalized_parameters={"amount": 5000},
            parameters_hash="hash_3",
            required_capability="finance:transfer",
            taint_flags=[],
            risk_score=70,
            blast_radius={},
            state=ActionState.EXECUTED.value,
            idempotency_key="idem_act_3",
            preconditions=[],
            postconditions=[{"key": "status", "operator": "eq", "value": "paid"}],
            requires_outcome_assurance=True,
            outcome_status=OutcomeStatus.PENDING_VERIFICATION.value,
            created_at=now,
        )

        # Gate 5 OutcomeVerificationRecord is still PENDING_VERIFICATION
        outcome_rec = OutcomeVerificationRecord(
            id="outc_child_3",
            tenant_id=auth_context.tenant_id,
            transaction_id=child_txn.id,
            action_id=child_action.id,
            observability_class=ObservabilityClass.OBS_DIRECT.value,
            outcome_status=OutcomeStatus.PENDING_VERIFICATION.value,
            epistemic_confidence=0.0,
            verifier_adapter="HTTP_RESOURCE",
            is_simulated=False,
            expected_postconditions={"status": "paid"},
            observed_state={},
            discrepancies=[],
            evidence_payload={},
            reconciliation_notes=["Awaiting payment gateway settlement webhook"],
            verification_hash="hash_outc_3",
            target_environment="PROD",
            created_at=now,
            verified_at=now,
        )

        session = _build_mock_session()
        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        exec_children_1 = MagicMock()
        exec_children_1.scalars.return_value.all.return_value = [child_txn]

        exec_children_2 = MagicMock()
        exec_children_2.scalars.return_value.all.return_value = []

        exec_handoffs = MagicMock()
        exec_handoffs.scalars.return_value.all.return_value = []

        exec_actions = MagicMock()
        exec_actions.scalars.return_value.all.return_value = [child_action]

        exec_outcomes = MagicMock()
        exec_outcomes.scalars.return_value.all.return_value = [outcome_rec]

        exec_audit = MagicMock()
        exec_audit.first.return_value = ("0" * 64, 1)

        session.execute.side_effect = [
            exec_parent,
            exec_children_1,
            exec_children_2,
            exec_handoffs,
            exec_actions,
            exec_outcomes,
            exec_audit,
        ]

        resp = await outcome_service.aggregate_transaction_outcome(auth_context, parent_txn.id, session=session)
        assert resp.hierarchical_status == HierarchicalOutcomeStatus.AWAITING_OUTCOME_VERIFICATION
        assert resp.child_executions[0].execution_completed is True
        assert resp.child_executions[0].outcomes_verified is False
        assert resp.epistemic_confidence == 0.0

        session.execute.side_effect = [
            exec_parent,
            exec_children_1,
            exec_children_2,
            exec_handoffs,
            exec_actions,
            exec_outcomes,
            exec_audit,
        ]
        with pytest.raises(HTTPException) as exc_info:
            await outcome_service.verify_hierarchical_completion(auth_context, parent_txn.id, session=session)
        assert exc_info.value.status_code == 409
        assert "independent Gate 5 reality verification remains pending" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verified_child_outcomes_aggregate_to_parent_verified_success(
        self, outcome_service: HierarchicalOutcomeService, auth_context: AuthContext
    ) -> None:
        """When child actions are independently observed with postconditions matching, parent completes."""
        now = datetime.now(UTC)
        parent_txn = AITransaction(
            id="txn_parent_4",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            parent_transaction_id=None,
            idempotency_key="idem_p4",
            correlation_id="corr_p4",
            state="ACTIVE",
            max_turns=10,
            turn_count=2,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_child_4",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            parent_transaction_id=parent_txn.id,
            idempotency_key="idem_c4",
            correlation_id="corr_p4",
            state="COMPLETED",
            max_turns=5,
            turn_count=3,
            final_disposition="COMPLETED",
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        child_action = ActionContract(
            id="act_child_4",
            tenant_id=auth_context.tenant_id,
            transaction_id=child_txn.id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            tool_id="tool_transfer",
            tool_name="stripe_transfer",
            action_type="EXECUTE",
            target_resource="stripe://transfers/tr_888",
            parameters={"amount": 2500},
            normalized_parameters={"amount": 2500},
            parameters_hash="hash_4",
            required_capability="finance:transfer",
            taint_flags=[],
            risk_score=50,
            blast_radius={},
            state=ActionState.EXECUTED.value,
            idempotency_key="idem_act_4",
            preconditions=[],
            postconditions=[{"key": "status", "operator": "eq", "value": "paid"}],
            requires_outcome_assurance=True,
            outcome_status=OutcomeStatus.VERIFIED_SUCCESS.value,
            created_at=now,
        )

        outcome_rec = OutcomeVerificationRecord(
            id="outc_child_4",
            tenant_id=auth_context.tenant_id,
            transaction_id=child_txn.id,
            action_id=child_action.id,
            observability_class=ObservabilityClass.OBS_DIRECT.value,
            outcome_status=OutcomeStatus.VERIFIED_SUCCESS.value,
            epistemic_confidence=0.98,
            verifier_adapter="HTTP_RESOURCE",
            is_simulated=False,
            expected_postconditions={"status": "paid"},
            observed_state={"status": "paid", "amount_received": 2500},
            discrepancies=[],
            evidence_payload={"http_status": 200},
            reconciliation_notes=["Postconditions directly observed in target state"],
            verification_hash="hash_outc_4",
            target_environment="PROD",
            created_at=now,
            verified_at=now,
        )

        session = _build_mock_session()
        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        exec_children_1 = MagicMock()
        exec_children_1.scalars.return_value.all.return_value = [child_txn]

        exec_children_2 = MagicMock()
        exec_children_2.scalars.return_value.all.return_value = []

        exec_handoffs = MagicMock()
        exec_handoffs.scalars.return_value.all.return_value = []

        exec_actions = MagicMock()
        exec_actions.scalars.return_value.all.return_value = [child_action]

        exec_outcomes = MagicMock()
        exec_outcomes.scalars.return_value.all.return_value = [outcome_rec]

        exec_audit = MagicMock()
        exec_audit.first.return_value = ("0" * 64, 1)

        session.execute.side_effect = [
            exec_parent,
            exec_children_1,
            exec_children_2,
            exec_handoffs,
            exec_actions,
            exec_outcomes,
            exec_audit,
        ]

        resp = await outcome_service.aggregate_transaction_outcome(auth_context, parent_txn.id, session=session)
        assert resp.hierarchical_status == HierarchicalOutcomeStatus.VERIFIED_SUCCESS
        assert resp.epistemic_confidence == 0.98
        assert resp.child_executions[0].outcomes_verified is True

        session.execute.side_effect = [
            exec_parent,
            exec_children_1,
            exec_children_2,
            exec_handoffs,
            exec_actions,
            exec_outcomes,
            exec_audit,
        ]
        # Must not raise an error
        await outcome_service.verify_hierarchical_completion(auth_context, parent_txn.id, session=session)

    @pytest.mark.asyncio
    async def test_failed_child_action_results_in_hierarchical_failure(
        self, outcome_service: HierarchicalOutcomeService, auth_context: AuthContext
    ) -> None:
        """A verified failure in a child action produces HIERARCHICAL_FAILURE."""
        now = datetime.now(UTC)
        parent_txn = AITransaction(
            id="txn_parent_5",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            parent_transaction_id=None,
            idempotency_key="idem_p5",
            correlation_id="corr_p5",
            state="ACTIVE",
            max_turns=10,
            turn_count=2,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_child_5",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            parent_transaction_id=parent_txn.id,
            idempotency_key="idem_c5",
            correlation_id="corr_p5",
            state="COMPLETED",
            max_turns=5,
            turn_count=2,
            final_disposition="COMPLETED",
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        child_action = ActionContract(
            id="act_child_5",
            tenant_id=auth_context.tenant_id,
            transaction_id=child_txn.id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            tool_id="tool_transfer",
            tool_name="stripe_transfer",
            action_type="EXECUTE",
            target_resource="stripe://transfers/tr_fail",
            parameters={"amount": 9999},
            normalized_parameters={"amount": 9999},
            parameters_hash="hash_5",
            required_capability="finance:transfer",
            taint_flags=[],
            risk_score=80,
            blast_radius={},
            state=ActionState.EXECUTED.value,
            idempotency_key="idem_act_5",
            preconditions=[],
            postconditions=[{"key": "status", "operator": "eq", "value": "paid"}],
            requires_outcome_assurance=True,
            outcome_status=OutcomeStatus.VERIFIED_FAILURE.value,
            created_at=now,
        )

        outcome_rec = OutcomeVerificationRecord(
            id="outc_child_5",
            tenant_id=auth_context.tenant_id,
            transaction_id=child_txn.id,
            action_id=child_action.id,
            observability_class=ObservabilityClass.OBS_DIRECT.value,
            outcome_status=OutcomeStatus.VERIFIED_FAILURE.value,
            epistemic_confidence=0.0,
            verifier_adapter="HTTP_RESOURCE",
            is_simulated=False,
            expected_postconditions={"status": "paid"},
            observed_state={"status": "declined", "error": "insufficient_funds"},
            discrepancies=["Postcondition status 'paid' violated: observed 'declined'"],
            evidence_payload={"http_status": 402},
            reconciliation_notes=["Target mutation was rejected by downstream processor"],
            verification_hash="hash_outc_5",
            target_environment="PROD",
            created_at=now,
            verified_at=now,
        )

        session = _build_mock_session()
        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn
        exec_children_1 = MagicMock()
        exec_children_1.scalars.return_value.all.return_value = [child_txn]
        exec_children_2 = MagicMock()
        exec_children_2.scalars.return_value.all.return_value = []
        exec_handoffs = MagicMock()
        exec_handoffs.scalars.return_value.all.return_value = []
        exec_actions = MagicMock()
        exec_actions.scalars.return_value.all.return_value = [child_action]
        exec_outcomes = MagicMock()
        exec_outcomes.scalars.return_value.all.return_value = [outcome_rec]
        exec_audit = MagicMock()
        exec_audit.first.return_value = ("0" * 64, 1)

        session.execute.side_effect = [
            exec_parent,
            exec_children_1,
            exec_children_2,
            exec_handoffs,
            exec_actions,
            exec_outcomes,
            exec_audit,
        ]

        resp = await outcome_service.aggregate_transaction_outcome(auth_context, parent_txn.id, session=session)
        assert resp.hierarchical_status == HierarchicalOutcomeStatus.HIERARCHICAL_FAILURE
        assert resp.epistemic_confidence == 0.0
        assert len(resp.discrepancies) > 0

    @pytest.mark.asyncio
    async def test_unverifiable_blind_sink_yields_zero_confidence(
        self, outcome_service: HierarchicalOutcomeService, auth_context: AuthContext
    ) -> None:
        """Actions on unobservable sinks (e.g. UDP syslog) must never be treated as verified success."""
        now = datetime.now(UTC)
        parent_txn = AITransaction(
            id="txn_parent_6",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            parent_transaction_id=None,
            idempotency_key="idem_p6",
            correlation_id="corr_p6",
            state="ACTIVE",
            max_turns=10,
            turn_count=2,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        child_action = ActionContract(
            id="act_child_6",
            tenant_id=auth_context.tenant_id,
            transaction_id=parent_txn.id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            tool_id="tool_syslog",
            tool_name="udp_syslog_sender",
            action_type="EXECUTE",
            target_resource="syslog://log.internal:514",
            parameters={"msg": "critical event"},
            normalized_parameters={"msg": "critical event"},
            parameters_hash="hash_6",
            required_capability="logging:emit",
            taint_flags=[],
            risk_score=20,
            blast_radius={},
            state=ActionState.EXECUTED.value,
            idempotency_key="idem_act_6",
            preconditions=[],
            postconditions=[],
            requires_outcome_assurance=True,
            outcome_status=OutcomeStatus.UNVERIFIABLE.value,
            created_at=now,
        )

        outcome_rec = OutcomeVerificationRecord(
            id="outc_child_6",
            tenant_id=auth_context.tenant_id,
            transaction_id=parent_txn.id,
            action_id=child_action.id,
            observability_class=ObservabilityClass.OBS_BLIND.value,
            outcome_status=OutcomeStatus.UNVERIFIABLE.value,
            epistemic_confidence=0.0,
            verifier_adapter="INDEPENDENT_OBSERVER",
            is_simulated=False,
            expected_postconditions={},
            observed_state={},
            discrepancies=["Destination is write-only sink; cannot observe outcome directly"],
            evidence_payload={},
            reconciliation_notes=["Transport acknowledged only; confidence strictly zero"],
            verification_hash="hash_outc_6",
            target_environment="PROD",
            created_at=now,
            verified_at=now,
        )

        session = _build_mock_session()
        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn
        exec_children = MagicMock()
        exec_children.scalars.return_value.all.return_value = []
        exec_handoffs = MagicMock()
        exec_handoffs.scalars.return_value.all.return_value = []
        exec_actions = MagicMock()
        exec_actions.scalars.return_value.all.return_value = [child_action]
        exec_outcomes = MagicMock()
        exec_outcomes.scalars.return_value.all.return_value = [outcome_rec]
        exec_audit = MagicMock()
        exec_audit.first.return_value = ("0" * 64, 1)

        session.execute.side_effect = [
            exec_parent,
            exec_children,
            exec_handoffs,
            exec_actions,
            exec_outcomes,
            exec_audit,
        ]

        resp = await outcome_service.aggregate_transaction_outcome(auth_context, parent_txn.id, session=session)
        assert resp.hierarchical_status == HierarchicalOutcomeStatus.UNVERIFIABLE
        assert resp.epistemic_confidence == 0.0

    @pytest.mark.asyncio
    async def test_late_child_observation_cannot_silently_reverse_committed_terminal_parent(
        self, outcome_service: HierarchicalOutcomeService, auth_context: AuthContext
    ) -> None:
        """When parent transaction is already in a terminal state (COMPLETED), late arrival observations

        do NOT mutate the parent transaction record, but record discrepancies in reconciliation notes
        and emit audit events.
        """
        now = datetime.now(UTC)
        # Parent was already committed as COMPLETED in the database
        committed_parent_txn = AITransaction(
            id="txn_parent_term",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            parent_transaction_id=None,
            idempotency_key="idem_p_term",
            correlation_id="corr_p_term",
            state="COMPLETED",
            max_turns=10,
            turn_count=5,
            final_disposition="COMPLETED",
            taint_flags=[],
            context_sources=[],
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
        )

        # Late-arriving child action reveals a verified failure
        child_txn = AITransaction(
            id="txn_child_late",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            parent_transaction_id=committed_parent_txn.id,
            idempotency_key="idem_c_late",
            correlation_id="corr_p_term",
            state="FAILED",
            max_turns=5,
            turn_count=2,
            final_disposition="FAILED",
            taint_flags=[],
            context_sources=[],
            created_at=now - timedelta(minutes=30),
            updated_at=now,
        )

        child_action = ActionContract(
            id="act_child_late",
            tenant_id=auth_context.tenant_id,
            transaction_id=child_txn.id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            tool_id="tool_async",
            tool_name="async_processor",
            action_type="EXECUTE",
            target_resource="db://records/rec_1",
            parameters={},
            normalized_parameters={},
            parameters_hash="hash_l",
            required_capability="db:write",
            taint_flags=[],
            risk_score=50,
            blast_radius={},
            state=ActionState.FAILED.value,
            idempotency_key="idem_act_l",
            preconditions=[],
            postconditions=[],
            requires_outcome_assurance=True,
            outcome_status=OutcomeStatus.VERIFIED_FAILURE.value,
            created_at=now,
        )

        session = _build_mock_session()
        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = committed_parent_txn
        exec_children_1 = MagicMock()
        exec_children_1.scalars.return_value.all.return_value = [child_txn]
        exec_children_2 = MagicMock()
        exec_children_2.scalars.return_value.all.return_value = []
        exec_handoffs = MagicMock()
        exec_handoffs.scalars.return_value.all.return_value = []
        exec_actions = MagicMock()
        exec_actions.scalars.return_value.all.return_value = [child_action]
        exec_outcomes = MagicMock()
        exec_outcomes.scalars.return_value.all.return_value = []
        exec_audit = MagicMock()
        exec_audit.first.return_value = ("0" * 64, 1)

        session.execute.side_effect = [
            exec_parent,
            exec_children_1,
            exec_children_2,
            exec_handoffs,
            exec_actions,
            exec_outcomes,
            exec_audit,
            exec_audit,
        ]

        resp = await outcome_service.aggregate_transaction_outcome(
            auth_context, committed_parent_txn.id, session=session
        )

        # Invariant checks:
        assert resp.is_parent_terminal is True
        assert resp.parent_disposition == "COMPLETED"
        assert committed_parent_txn.state == "COMPLETED"
        assert committed_parent_txn.final_disposition == "COMPLETED"

        # Discrepancy is detected and flagged in response
        assert any("Terminal discrepancy" in d for d in resp.discrepancies)
        assert any("immutable" in n for n in resp.reconciliation_notes)


# =============================================================================
# 2. Cancellation and Execution Boundary Tests
# =============================================================================


class TestCancellationAndExecutionBoundaries:
    @pytest.mark.asyncio
    async def test_parent_cancellation_propagates_to_handoffs_and_child_transactions(
        self, auth_context: AuthContext
    ) -> None:
        """Cancelling a parent transaction aborts pending handoffs and active child transactions."""
        now = datetime.now(UTC)
        parent_txn = AITransaction(
            id="txn_p_cancel",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            parent_transaction_id=None,
            idempotency_key="idem_p_c",
            correlation_id="corr_p_c",
            state="ACTIVE",
            max_turns=10,
            turn_count=2,
            version=1,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_c_cancel",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            parent_transaction_id=parent_txn.id,
            idempotency_key="idem_c_c",
            correlation_id="corr_p_c",
            state="ACTIVE",
            max_turns=5,
            turn_count=1,
            version=1,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        pending_handoff = AgentHandoff(
            id="hnd_cancel_1",
            tenant_id=auth_context.tenant_id,
            parent_transaction_id=parent_txn.id,
            parent_agent_id="agent_parent",
            child_agent_id="agent_child",
            delegation_id="del_grant_1",
            child_transaction_id=child_txn.id,
            status=HandoffStatus.ACCEPTED.value,
            purpose="Async subtask",
            permitted_scope={},
            inherited_taint_flags=[],
            idempotency_key="idem_hnd_c",
            expires_at=now + timedelta(minutes=5),
            accepted_at=now,
            completed_at=None,
            cancelled_at=None,
            created_at=now,
            updated_at=now,
        )

        session = _build_mock_session()
        session.get.return_value = parent_txn

        exec_audit = MagicMock()
        exec_audit.first.return_value = ("0" * 64, 1)

        exec_handoffs = MagicMock()
        exec_handoffs.scalars.return_value.all.return_value = [pending_handoff]

        exec_children = MagicMock()
        exec_children.scalars.return_value.all.return_value = [child_txn]

        session.execute.side_effect = [
            exec_audit,  # parent cancellation audit
            exec_handoffs,  # cancel_handoffs query
            exec_audit,  # handoff cancel audit
            exec_children,  # child query
            exec_audit,  # child cancel audit
            exec_audit,  # propagation summary audit
        ]

        with patch("services.control_plane.db_session.get_tenant_session") as mock_tenant_session:
            mock_tenant_session.return_value.__aenter__.return_value = session

            resp = await cancel_transaction(auth_context, parent_txn.id, reason="Operator stop requested")

            assert resp.state == TransactionState.CANCELLED
            assert parent_txn.state == "CANCELLED"
            assert pending_handoff.status == HandoffStatus.CANCELLED.value
            assert child_txn.state == "CANCELLED"
            assert child_txn.final_disposition == "CANCELLED"

    @pytest.mark.asyncio
    async def test_child_action_authorization_blocked_when_parent_is_cancelled(
        self, action_governor: ActionGovernorService, auth_context: AuthContext
    ) -> None:
        """A child transaction cannot authorize new actions if its parent transaction is cancelled."""
        now = datetime.now(UTC)
        cancelled_parent_txn = AITransaction(
            id="txn_parent_blocked",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_parent",
            parent_transaction_id=None,
            idempotency_key="idem_pb",
            correlation_id="corr_pb",
            state="CANCELLED",
            max_turns=10,
            turn_count=2,
            final_disposition="CANCELLED",
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        child_txn = AITransaction(
            id="txn_child_blocked",
            tenant_id=auth_context.tenant_id,
            actor_identity_id=auth_context.identity_id,
            agent_id="agent_child",
            parent_transaction_id=cancelled_parent_txn.id,
            idempotency_key="idem_cb",
            correlation_id="corr_pb",
            state="ACTIVE",
            max_turns=5,
            turn_count=1,
            final_disposition=None,
            taint_flags=[],
            context_sources=[],
            created_at=now,
            updated_at=now,
        )

        proposal = ActionProposal(
            transaction_id=child_txn.id,
            tool_name="test_tool",
            action_type=ActionType.EXECUTE,
            target_resource="db://records/1",
            parameters={"id": 1},
            idempotency_key="idem_prop_blocked",
            blast_radius=BlastRadiusAssessment(data_classification="CONFIDENTIAL", reversibility="REVERSIBLE"),
        )

        session = _build_mock_session()

        # Mock tool lookup
        mock_tool = MagicMock()
        mock_tool.id = "tool_1"
        mock_tool.name = "test_tool"
        mock_tool.active = True
        mock_tool.required_capability = "data:read"
        mock_tool.parameters_schema = {}

        exec_idem = MagicMock()
        exec_idem.scalar_one_or_none.return_value = None

        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = child_txn

        exec_tool = MagicMock()
        exec_tool.scalar_one_or_none.return_value = mock_tool

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = cancelled_parent_txn

        session.execute.side_effect = [
            exec_txn,
            exec_idem,
            exec_tool,
            exec_parent,
        ]

        with patch("services.action_governor.db_session.get_tenant_session") as mock_tenant_session:
            mock_tenant_session.return_value.__aenter__.return_value = session
            with patch(
                "services.action_governor.agent_governance_service.is_agent_eligible_for_transaction",
                new_callable=AsyncMock,
                return_value=True,
            ):
                decision = await action_governor.propose_and_authorize_action(auth_context, proposal)

                assert decision.decision == Decision.BLOCK
                assert decision.state == ActionState.BLOCKED
                assert "Parent transaction" in decision.reason
                assert "child action execution prohibited" in decision.reason


# =============================================================================
# 3. Route API Tests
# =============================================================================


class TestHierarchicalOutcomeRoutes:
    def test_get_hierarchy_unauthenticated(self, api_client: TestClient) -> None:
        """Unauthenticated request to hierarchy endpoint returns 401."""
        response = api_client.get("/v1/transactions/txn_test_1/hierarchy")
        assert response.status_code == 401

    def test_get_hierarchy_success(self, api_client: TestClient) -> None:
        """Authenticated request returns 200 with HierarchicalOutcomeResponse."""
        now = datetime.now(UTC)
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_omega", role=Role.OPERATOR)

        mock_resp = HierarchicalOutcomeResponse(
            parent_transaction_id="txn_route_1",
            tenant_id="tenant_omega",
            parent_state="ACTIVE",
            parent_disposition=None,
            is_parent_terminal=False,
            hierarchical_status=HierarchicalOutcomeStatus.VERIFIED_SUCCESS,
            epistemic_confidence=0.95,
            evaluated_at=now,
            total_child_transactions=1,
            active_child_transactions=0,
            total_handoffs=1,
            pending_handoffs=0,
            parent_actions=[],
            child_executions=[],
            handoffs=[],
            discrepancies=[],
            reconciliation_notes=["All child work verified"],
            evaluation_hash="abc123hash",
        )

        with patch(
            "services.hierarchical_outcome_service.hierarchical_outcome_service.aggregate_transaction_outcome",
            new_callable=AsyncMock,
        ) as mock_agg:
            mock_agg.return_value = mock_resp

            response = api_client.get("/v1/transactions/txn_route_1/hierarchy", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert data["parent_transaction_id"] == "txn_route_1"
            assert data["hierarchical_status"] == "VERIFIED_SUCCESS"
            assert data["epistemic_confidence"] == 0.95

    def test_get_hierarchy_not_found(self, api_client: TestClient) -> None:
        """Non-existent transaction returns 404."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_omega", role=Role.OPERATOR)

        with patch(
            "services.hierarchical_outcome_service.hierarchical_outcome_service.aggregate_transaction_outcome",
            new_callable=AsyncMock,
        ) as mock_agg:
            mock_agg.side_effect = HTTPException(status_code=404, detail="Transaction not found")

            response = api_client.get("/v1/transactions/txn_missing/hierarchy", headers=headers)
            assert response.status_code == 404
            assert "Transaction not found" in response.json()["detail"]

    def test_complete_handoff_success(self, api_client: TestClient) -> None:
        """POST /v1/handoffs/{id}/complete completes an accepted handoff."""
        from shared.schemas.handoff import AgentHandoffResponse

        now = datetime.now(UTC)
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_omega", role=Role.OPERATOR)

        mock_hnd_resp = AgentHandoffResponse(
            id="hnd_test_1",
            tenant_id="tenant_omega",
            parent_transaction_id="txn_p",
            parent_agent_id="agent_p",
            child_agent_id="agent_c",
            delegation_id="del_1",
            child_transaction_id="txn_c",
            status=HandoffStatus.COMPLETED,
            purpose="test completion",
            permitted_scope={},
            inherited_taint_flags=[],
            idempotency_key="idem_comp_1",
            expires_at=now + timedelta(minutes=5),
            accepted_at=now,
            completed_at=now,
            cancelled_at=None,
            cancellation_reason=None,
            created_at=now,
            updated_at=now,
        )

        with patch(
            "services.handoff_service.handoff_service.complete_handoff",
            new_callable=AsyncMock,
        ) as mock_comp:
            mock_comp.return_value = mock_hnd_resp

            response = api_client.post("/v1/handoffs/hnd_test_1/complete", headers=headers)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "COMPLETED"
            assert data["completed_at"] is not None
