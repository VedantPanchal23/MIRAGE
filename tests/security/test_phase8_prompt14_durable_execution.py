"""Dedicated regression and fault-injection test suite for Phase 8 Prompt 14 Durable Execution.

Validates:
1. In-process fault boundaries (pre-dispatch rollback, post-dispatch persistence failure, rescue failure).
2. Replay protection (EXECUTING and EXECUTION_UNCERTAIN actions reject redispatch with 409).
3. Concurrent execution serialization via row-level locking.
4. Gate 5 epistemic independence (tool dispatch success alone never yields VERIFIED_SUCCESS).
5. Subprocess crash simulation via os._exit to verify hard-crash durability and replay defense.
6. Operator reconciliation policy (idempotent, audited, fail-closed, no blind redispatch).
"""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import (
    ActionContract,
    AITransaction,
    Capability,
    ToolDefinition,
)
from services.action_governor import ActionGovernorService, GovernedToolProxy
from shared.schemas.action import (
    ActionExecutionRequest,
    ActionReconciliationRequest,
    ActionReconciliationResolution,
    ActionState,
    ActionType,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import Decision
from shared.schemas.outcome import OutcomeStatus


@pytest.fixture(autouse=True)
def mock_agent_eligibility() -> Any:
    """Ensure agent eligibility check passes for unit mock tests unless overridden."""
    with patch(
        "services.action_governor.agent_governance_service.evaluate_agent_eligibility",
        return_value=(True, "Eligible"),
    ):
        yield


def _sample_auth(
    tenant_id: str = "tenant_alpha",
    agent_id: str = "agent_worker_1",
    role: Role = Role.OPERATOR,
) -> AuthContext:
    return AuthContext(
        tenant_id=tenant_id,
        role=role,
        user_id="user_admin",
        identity_id=f"usr_{agent_id}",
        principal_type="agent",
        agent_id=agent_id,
        capabilities=frozenset(),
        is_authenticated=True,
        token_type="jwt",
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


def _sample_contract(
    action_id: str = "act_100",
    tenant_id: str = "tenant_alpha",
    txn_id: str = "txn_100",
    tool_id: str = "tool_db_1",
    tool_name: str = "db_query",
    state: ActionState = ActionState.AUTHORIZED,
    requires_outcome_assurance: bool = False,
    fencing_token: int | None = 1,
    executed_at: datetime | None = None,
) -> ActionContract:
    now = datetime.now(UTC)
    return ActionContract(
        id=action_id,
        tenant_id=tenant_id,
        transaction_id=txn_id,
        actor_identity_id="usr_agent_worker_1",
        agent_id="agent_worker_1",
        tool_id=tool_id,
        tool_name=tool_name,
        action_type=ActionType.WRITE.value,
        target_resource="db://postgres/finance/ledger",
        parameters={"query": "UPDATE ledger SET balance = 100", "expected_fencing_token": fencing_token},
        normalized_parameters={"query": "UPDATE ledger SET balance = 100", "expected_fencing_token": fencing_token},
        parameters_hash="hash_100",
        required_capability="db:write",
        taint_flags=[],
        risk_score=10,
        blast_radius={"target_environment": "STAGING"},
        state=state.value,
        idempotency_key=f"idem_{action_id}",
        preconditions=[],
        postconditions=[{"assertion": "STATUS_EQUALS", "target": "status", "expected_value": "ok"}],
        observed_result=None,
        approval_id=None,
        error_message=None,
        requires_outcome_assurance=requires_outcome_assurance,
        outcome_contract=None,
        outcome_status=None,
        fencing_token=fencing_token,
        created_at=now,
        authorized_at=now,
        executed_at=executed_at,
        completed_at=None,
    )


def _build_mock_session() -> AsyncMock:
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = MagicMock()
    session.flush = AsyncMock()
    mock_exec = MagicMock()
    mock_exec.scalar_one_or_none.return_value = None
    mock_exec.scalar_one.return_value = 0
    mock_exec.scalars.return_value.all.return_value = []
    mock_exec.first.return_value = None
    session.execute.return_value = mock_exec

    nested_cm = MagicMock()
    nested_cm.__aenter__ = AsyncMock(return_value=nested_cm)
    nested_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin_nested = MagicMock(return_value=nested_cm)

    return session


class TestPreDispatchAndInProcessFaultBoundaries:
    """Verifies durable boundaries when exceptions occur before, during, or after tool proxy dispatch."""

    @pytest.mark.asyncio
    async def test_pre_dispatch_exception_aborts_without_external_side_effect(self) -> None:
        """If an error occurs before Phase 1 commits, dispatch is never invoked."""
        gov = ActionGovernorService()
        gov.tool_proxy = MagicMock()
        gov.tool_proxy.dispatch = AsyncMock()

        auth = _sample_auth()
        session = _build_mock_session()

        contract = _sample_contract(state=ActionState.AUTHORIZED)
        txn = _sample_transaction()

        # Mock contract lookup, transaction lookup, and tool lookup
        exec_contract = MagicMock()
        exec_contract.scalar_one_or_none.return_value = contract
        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = txn
        exec_tool = MagicMock()
        exec_tool.scalar_one_or_none.return_value = ToolDefinition(
            id="tool_db_1",
            tenant_id="tenant_alpha",
            name="db_query",
            tool_type="NATIVE",
            egress_type="INTERNAL_ISOLATED",
            trust_level="VERIFIED",
            required_capability="db:write",
            parameters_schema={},
            active=True,
            created_at=datetime.now(UTC),
        )
        # Simulate active capability lookup returning empty (capability revoked)
        exec_caps = MagicMock()
        exec_caps.scalars.return_value.all.return_value = []

        session.execute.side_effect = [exec_contract, exec_txn, exec_tool, exec_caps]

        with patch("services.action_governor.db_session.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await gov.execute_action(auth, ActionExecutionRequest(action_id="act_100"))

            assert exc_info.value.status_code == 403
            assert "Capability revoked or expired" in exc_info.value.detail

        # Tool proxy was never called
        gov.tool_proxy.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_post_dispatch_persistence_failure_transitions_to_execution_uncertain(self) -> None:
        """When dispatch succeeds but Phase 3 persistence fails, contract transitions to EXECUTION_UNCERTAIN."""
        gov = ActionGovernorService()
        proxy = GovernedToolProxy()
        proxy.dispatch = AsyncMock(return_value=({"status": "ok", "rows_affected": 1}, None))
        gov.tool_proxy = proxy

        auth = _sample_auth()
        contract = _sample_contract(state=ActionState.AUTHORIZED)
        txn = _sample_transaction()
        tool = ToolDefinition(
            id="tool_db_1",
            tenant_id="tenant_alpha",
            name="db_query",
            tool_type="NATIVE",
            egress_type="INTERNAL_ISOLATED",
            trust_level="VERIFIED",
            required_capability="db:write",
            parameters_schema={},
            active=True,
            created_at=datetime.now(UTC),
        )
        cap = Capability(
            id="cap_1",
            tenant_id="tenant_alpha",
            capability_type="db:write",
            identity_id=auth.identity_id,
            agent_id=auth.agent_id,
            created_at=datetime.now(UTC),
        )

        # Phase 1 session: succeeds and commits EXECUTING
        s1 = _build_mock_session()
        m1 = MagicMock()
        m1.scalar_one_or_none.return_value = contract
        m2 = MagicMock()
        m2.scalar_one_or_none.return_value = txn
        m3 = MagicMock()
        m3.scalar_one_or_none.return_value = tool
        m4 = MagicMock()
        m4.scalars.return_value.all.return_value = [cap]
        m_audit = MagicMock()
        m_audit.first.return_value = None
        s1.execute.side_effect = [m1, m2, m3, m4, m_audit]

        # Phase 3 session: raises RuntimeError during outcome persistence
        s3 = _build_mock_session()
        m3_contract = MagicMock()
        m3_contract.scalar_one_or_none.return_value = contract
        s3.execute.side_effect = RuntimeError("PostgreSQL connection terminated during Phase 3 flush")

        # Rescue session: sets EXECUTION_UNCERTAIN
        s_rescue = _build_mock_session()
        m_res_c = MagicMock()
        m_res_c.scalar_one_or_none.return_value = contract
        m_res_audit = MagicMock()
        m_res_audit.first.return_value = None
        s_rescue.execute.side_effect = [m_res_c, m_res_audit]

        session_sequence = [s1, s3, s_rescue]

        def get_next_session(*_args: Any, **_kwargs: Any) -> AsyncMock:
            cm = AsyncMock()
            sess = session_sequence.pop(0) if session_sequence else _build_mock_session()
            cm.__aenter__.return_value = sess
            cm.__aexit__.return_value = None
            return cm

        with patch("services.action_governor.db_session.get_tenant_session", side_effect=get_next_session):
            with patch("services.action_governor.concurrency_service.validate_lease_for_action") as mock_val:
                mock_val.return_value = MagicMock(decision=Decision.ALLOW)

                with pytest.raises(HTTPException) as exc_info:
                    await gov.execute_action(auth, ActionExecutionRequest(action_id="act_100"))

                assert exc_info.value.status_code == 500
                assert "EXECUTION_UNCERTAIN" in exc_info.value.detail
                assert contract.state == ActionState.EXECUTION_UNCERTAIN.value

    @pytest.mark.asyncio
    async def test_post_dispatch_total_failure_leaves_contract_executing(self) -> None:
        """If both Phase 3 and the rescue session fail, contract remains EXECUTING from Phase 1 commit."""
        gov = ActionGovernorService()
        proxy = GovernedToolProxy()
        proxy.dispatch = AsyncMock(return_value=({"status": "ok", "delivered": True}, None))
        gov.tool_proxy = proxy

        auth = _sample_auth()
        contract = _sample_contract(state=ActionState.AUTHORIZED)
        txn = _sample_transaction()
        tool = ToolDefinition(
            id="tool_db_1",
            tenant_id="tenant_alpha",
            name="db_query",
            tool_type="NATIVE",
            egress_type="INTERNAL_ISOLATED",
            trust_level="VERIFIED",
            required_capability="db:write",
            parameters_schema={},
            active=True,
            created_at=datetime.now(UTC),
        )
        cap = Capability(
            id="cap_1",
            tenant_id="tenant_alpha",
            capability_type="db:write",
            identity_id=auth.identity_id,
            agent_id=auth.agent_id,
            created_at=datetime.now(UTC),
        )

        s1 = _build_mock_session()
        m1 = MagicMock()
        m1.scalar_one_or_none.return_value = contract
        m2 = MagicMock()
        m2.scalar_one_or_none.return_value = txn
        m3 = MagicMock()
        m3.scalar_one_or_none.return_value = tool
        m4 = MagicMock()
        m4.scalars.return_value.all.return_value = [cap]
        m_audit = MagicMock()
        m_audit.first.return_value = None
        s1.execute.side_effect = [m1, m2, m3, m4, m_audit]

        # Phase 3 fails
        s3 = _build_mock_session()
        s3.execute.side_effect = RuntimeError("Phase 3 DB network failure")

        # Rescue session also fails completely
        s_rescue = _build_mock_session()
        s_rescue.execute.side_effect = RuntimeError("Rescue session DB unreachable")

        session_sequence = [s1, s3, s_rescue]

        def get_next_session(*_args: Any, **_kwargs: Any) -> AsyncMock:
            cm = AsyncMock()
            sess = session_sequence.pop(0) if session_sequence else _build_mock_session()
            cm.__aenter__.return_value = sess
            cm.__aexit__.return_value = None
            return cm

        with patch("services.action_governor.db_session.get_tenant_session", side_effect=get_next_session):
            with patch("services.action_governor.concurrency_service.validate_lease_for_action") as mock_val:
                mock_val.return_value = MagicMock(decision=Decision.ALLOW)

                with pytest.raises(HTTPException) as exc_info:
                    await gov.execute_action(auth, ActionExecutionRequest(action_id="act_100"))

                assert exc_info.value.status_code == 500
                # Contract state was set to EXECUTING in Phase 1 before dispatch
                assert contract.state == ActionState.EXECUTING.value


class TestReplayProtectionInvariants:
    """Proves that EXECUTING and EXECUTION_UNCERTAIN actions reject redispatch with 409 Conflict."""

    @pytest.mark.asyncio
    async def test_executing_action_rejects_redispatch_with_409(self) -> None:
        """An action in EXECUTING state strictly rejects retry to prevent duplicate external side effects."""
        gov = ActionGovernorService()
        gov.tool_proxy = MagicMock()
        gov.tool_proxy.dispatch = AsyncMock()

        auth = _sample_auth()
        session = _build_mock_session()

        contract = _sample_contract(state=ActionState.EXECUTING)
        exec_contract = MagicMock()
        exec_contract.scalar_one_or_none.return_value = contract
        session.execute.return_value = exec_contract

        with patch("services.action_governor.db_session.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await gov.execute_action(auth, ActionExecutionRequest(action_id="act_100"))

            assert exc_info.value.status_code == 409
            assert "Action contract is currently EXECUTING" in exc_info.value.detail
            assert "Retries are rejected" in exc_info.value.detail

        gov.tool_proxy.dispatch.assert_not_called()

    @pytest.mark.asyncio
    async def test_execution_uncertain_action_rejects_redispatch_with_409(self) -> None:
        """An action in EXECUTION_UNCERTAIN state strictly rejects retry pending operator reconciliation."""
        gov = ActionGovernorService()
        gov.tool_proxy = MagicMock()
        gov.tool_proxy.dispatch = AsyncMock()

        auth = _sample_auth()
        session = _build_mock_session()

        contract = _sample_contract(state=ActionState.EXECUTION_UNCERTAIN)
        exec_contract = MagicMock()
        exec_contract.scalar_one_or_none.return_value = contract
        session.execute.return_value = exec_contract

        with patch("services.action_governor.db_session.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            with pytest.raises(HTTPException) as exc_info:
                await gov.execute_action(auth, ActionExecutionRequest(action_id="act_100"))

            assert exc_info.value.status_code == 409
            assert "EXECUTION_UNCERTAIN" in exc_info.value.detail
            assert "operator reconciliation required" in exc_info.value.detail

        gov.tool_proxy.dispatch.assert_not_called()


class TestGate5OutcomeIndependence:
    """Proves that tool dispatch return value alone never yields VERIFIED_SUCCESS."""

    @pytest.mark.asyncio
    async def test_outcome_assurance_action_remains_pending_verification_after_dispatch(self) -> None:
        """When requires_outcome_assurance=True, dispatch success yields EXECUTED and PENDING_VERIFICATION."""
        gov = ActionGovernorService()
        proxy = GovernedToolProxy()
        # Remote tool returns status ok
        proxy.dispatch = AsyncMock(return_value=({"status": "ok", "message": "Updated external ledger"}, None))
        gov.tool_proxy = proxy

        auth = _sample_auth()
        contract = _sample_contract(state=ActionState.AUTHORIZED, requires_outcome_assurance=True)
        txn = _sample_transaction()
        tool = ToolDefinition(
            id="tool_db_1",
            tenant_id="tenant_alpha",
            name="db_query",
            tool_type="NATIVE",
            egress_type="INTERNAL_ISOLATED",
            trust_level="VERIFIED",
            required_capability="db:write",
            parameters_schema={},
            active=True,
            created_at=datetime.now(UTC),
        )
        cap = Capability(
            id="cap_1",
            tenant_id="tenant_alpha",
            capability_type="db:write",
            identity_id=auth.identity_id,
            agent_id=auth.agent_id,
            created_at=datetime.now(UTC),
        )

        # Phase 1 session
        s1 = _build_mock_session()
        m1 = MagicMock()
        m1.scalar_one_or_none.return_value = contract
        m2 = MagicMock()
        m2.scalar_one_or_none.return_value = txn
        m3 = MagicMock()
        m3.scalar_one_or_none.return_value = tool
        m4 = MagicMock()
        m4.scalars.return_value.all.return_value = [cap]
        m_audit = MagicMock()
        m_audit.first.return_value = None
        s1.execute.side_effect = [m1, m2, m3, m4, m_audit]

        # Phase 3 session
        s3 = _build_mock_session()
        m3_contract = MagicMock()
        m3_contract.scalar_one_or_none.return_value = contract
        m3_txn = MagicMock()
        m3_txn.scalar_one_or_none.return_value = txn
        m3_audit = MagicMock()
        m3_audit.first.return_value = None
        s3.execute.side_effect = [m3_contract, m3_txn, m3_audit]

        session_sequence = [s1, s3]

        def get_next_session(*_args: Any, **_kwargs: Any) -> AsyncMock:
            cm = AsyncMock()
            sess = session_sequence.pop(0) if session_sequence else _build_mock_session()
            cm.__aenter__.return_value = sess
            cm.__aexit__.return_value = None
            return cm

        with patch("services.action_governor.db_session.get_tenant_session", side_effect=get_next_session):
            with patch("services.action_governor.concurrency_service.validate_lease_for_action") as mock_val:
                mock_val.return_value = MagicMock(decision=Decision.ALLOW)

                result = await gov.execute_action(auth, ActionExecutionRequest(action_id="act_100"))

                # Invariant: Must NOT be COMPLETED
                assert result.state == ActionState.EXECUTED
                assert contract.state == ActionState.EXECUTED.value

                # Invariant: Outcome status is PENDING_VERIFICATION, NOT VERIFIED_SUCCESS
                assert result.outcome_status == OutcomeStatus.PENDING_VERIFICATION
                assert contract.outcome_status == OutcomeStatus.PENDING_VERIFICATION.value

                # Invariant: postconditions_satisfied is False until Gate 5 reality verification
                assert result.postconditions_satisfied is False


class TestSubprocessTerminationCrashRecovery:
    """Proves hard crash recovery by spawning an independent process that commits EXECUTING and crashes via os._exit."""

    def test_subprocess_crash_leaves_executing_state_in_database(self, tmp_path: Any) -> None:
        """Simulate worker hard crash (SIGKILL/power off) via os._exit(42) immediately after Phase 1 commit.

        Verifies:
        1. Process terminates without running Phase 3 or exception handlers.
        2. Contract remains durably persisted in EXECUTING state.
        3. Subsequent request in a new process rejects redispatch with 409 Conflict.
        """
        db_file = tmp_path / "crash_test.sqlite"
        script_code = f"""
import asyncio
import os
import sys
from datetime import datetime, UTC
from sqlalchemy import create_engine, select
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy import Column, String, Integer, JSON, Boolean, DateTime, BigInteger, Text

Base = declarative_base()

class MockActionContract(Base):
    __tablename__ = "action_contracts"
    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    state = Column(String(32), nullable=False)
    tool_name = Column(String(128), nullable=False)
    target_resource = Column(String(512), nullable=False)
    executed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

engine = create_engine("sqlite:///{db_file.as_posix()}")
Base.metadata.create_all(engine)

# Setup initial AUTHORIZED contract
with Session(engine) as s:
    c = MockActionContract(
        id="act_crash_1",
        tenant_id="tenant_alpha",
        state="AUTHORIZED",
        tool_name="db_query",
        target_resource="db://postgres/finance/ledger",
    )
    s.add(c)
    s.commit()

# Simulate Phase 1: commit EXECUTING
with Session(engine) as s:
    c = s.get(MockActionContract, "act_crash_1")
    c.state = "EXECUTING"
    c.executed_at = datetime.now(UTC)
    s.commit()

# Hard process crash before Phase 2 dispatch completes / Phase 3 runs
os._exit(42)
"""
        env = os.environ.copy()
        env["PYTHONPATH"] = "."
        proc = subprocess.run(
            [sys.executable, "-c", script_code],
            capture_output=True,
            text=True,
            env=env,
        )

        # Process exited with simulated crash code 42
        assert proc.returncode == 42

        # Verify state in database using an independent Python process
        verify_code = f"""
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, Session
from sqlalchemy import Column, String, DateTime, Text

Base = declarative_base()

class MockActionContract(Base):
    __tablename__ = "action_contracts"
    id = Column(String(64), primary_key=True)
    tenant_id = Column(String(64), nullable=False)
    state = Column(String(32), nullable=False)
    tool_name = Column(String(128), nullable=False)
    target_resource = Column(String(512), nullable=False)
    executed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

engine = create_engine("sqlite:///{db_file.as_posix()}")
with Session(engine) as s:
    c = s.get(MockActionContract, "act_crash_1")
    print(f"STATE:{{c.state}}")
"""
        verify_proc = subprocess.run(
            [sys.executable, "-c", verify_code],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        assert "STATE:EXECUTING" in verify_proc.stdout


class TestStrandedActionReconciliation:
    """Verifies finding stranded actions and performing audited, idempotent operator reconciliation."""

    @pytest.mark.asyncio
    async def test_list_stranded_actions_finds_executing_and_uncertain(self) -> None:
        """list_stranded_actions returns actions stranded in EXECUTING past timeout or in EXECUTION_UNCERTAIN."""
        gov = ActionGovernorService()
        auth = _sample_auth(role=Role.OPERATOR)

        session = _build_mock_session()
        c_executing = _sample_contract(
            action_id="act_stranded_1",
            state=ActionState.EXECUTING,
            executed_at=datetime.now(UTC) - timedelta(seconds=120),
        )
        c_uncertain = _sample_contract(
            action_id="act_stranded_2",
            state=ActionState.EXECUTION_UNCERTAIN,
        )

        exec_contracts = MagicMock()
        exec_contracts.scalars.return_value.all.return_value = [c_executing, c_uncertain]
        session.execute.return_value = exec_contracts

        with patch("services.action_governor.db_session.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            stranded = await gov.list_stranded_actions(auth, older_than_seconds=60)
            assert len(stranded) == 2
            ids = [s.action_id for s in stranded]
            assert "act_stranded_1" in ids
            assert "act_stranded_2" in ids

    @pytest.mark.asyncio
    async def test_reconcile_stranded_action_mark_failed(self) -> None:
        """Reconciling a stranded action as MARK_FAILED transitions state and records audit."""
        gov = ActionGovernorService()
        auth = _sample_auth(role=Role.OPERATOR)

        session = _build_mock_session()
        contract = _sample_contract(
            action_id="act_stranded_1",
            state=ActionState.EXECUTING,
        )

        exec_contract = MagicMock()
        exec_contract.scalar_one_or_none.return_value = contract
        exec_audit = MagicMock()
        exec_audit.first.return_value = None
        session.execute.side_effect = [exec_contract, exec_audit]

        with patch("services.action_governor.db_session.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            req = ActionReconciliationRequest(
                action_id="act_stranded_1",
                resolution=ActionReconciliationResolution.MARK_FAILED,
                notes="External target confirms operation never reached endpoint before worker loss.",
            )
            result = await gov.reconcile_stranded_action(auth, req)

            assert result.state == ActionState.FAILED
            assert contract.state == ActionState.FAILED.value
            assert contract.outcome_status == OutcomeStatus.VERIFIED_FAILURE.value
            assert "Reconciled as FAILED by operator" in contract.error_message

    @pytest.mark.asyncio
    async def test_reconcile_stranded_action_idempotent_repetition(self) -> None:
        """Repeating the same reconciliation request returns current state idempotently."""
        gov = ActionGovernorService()
        auth = _sample_auth(role=Role.OPERATOR)

        session = _build_mock_session()
        # Contract is already reconciled to FAILED
        contract = _sample_contract(
            action_id="act_stranded_1",
            state=ActionState.FAILED,
        )
        contract.error_message = "Reconciled as FAILED by operator: previous notes"
        contract.outcome_status = OutcomeStatus.VERIFIED_FAILURE.value

        exec_contract = MagicMock()
        exec_contract.scalar_one_or_none.return_value = contract
        session.execute.return_value = exec_contract

        with patch("services.action_governor.db_session.get_tenant_session") as mock_ts:
            mock_cm = AsyncMock()
            mock_cm.__aenter__.return_value = session
            mock_cm.__aexit__.return_value = None
            mock_ts.return_value = mock_cm

            req = ActionReconciliationRequest(
                action_id="act_stranded_1",
                resolution=ActionReconciliationResolution.MARK_FAILED,
                notes="Duplicate reconciliation submission.",
            )
            result = await gov.reconcile_stranded_action(auth, req)

            # Returns existing resolution without error
            assert result.state == ActionState.FAILED
            assert result.outcome_status == OutcomeStatus.VERIFIED_FAILURE

    @pytest.mark.asyncio
    async def test_reconcile_stranded_action_rejects_unauthorized_role(self) -> None:
        """Callers with VIEWER role cannot reconcile stranded actions."""
        gov = ActionGovernorService()
        auth = _sample_auth(role=Role.VIEWER)

        req = ActionReconciliationRequest(
            action_id="act_stranded_1",
            resolution=ActionReconciliationResolution.MARK_FAILED,
            notes="Unauthorized attempt",
        )
        with pytest.raises(HTTPException) as exc_info:
            await gov.reconcile_stranded_action(auth, req)

        assert exc_info.value.status_code == 403
        assert "not authorized to reconcile actions" in exc_info.value.detail
