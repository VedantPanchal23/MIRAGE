"""Unit tests for Phase 6 Outcome Contracts and Execution Assurance lifecycle."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from db.models import ActionContract, AITransaction, OutcomeVerificationRecord, ToolDefinition
from services.action_governor import ActionGovernorService
from shared.schemas.action import (
    ActionExecutionRequest,
    ActionProposal,
    ActionState,
    Decision,
    PostconditionRule,
    PreconditionRule,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    OutcomeContractSpec,
    OutcomeStatus,
    RiskSensitiveVerificationPolicy,
)


def _build_behavioral_mock_session(
    txn: AITransaction | None = None,
    contract: ActionContract | None = None,
    tool: ToolDefinition | None = None,
    caps: list[Any] | None = None,
    leases: list[Any] | None = None,
    audit_chain: tuple[str, int] = ("0" * 64, 0),
    blast_radius: tuple[int, int] = (0, 0),
    costs: list[Any] | None = None,
    approvals: Any | None = None,
) -> AsyncMock:
    """Build a behavior-oriented fake session for outcome contract testing.

    Avoids brittle sequential call-count coupling while guaranteeing fail-closed
    and exact entity resolution for all Phase 6-8 governance queries.
    """
    mock_session = AsyncMock()

    async def _execute_fake(statement: Any, *args: Any, **kwargs: Any) -> MagicMock:
        stmt_str = str(statement)
        res = MagicMock()
        res.scalar_one_or_none.return_value = None
        res.scalars.return_value.all.return_value = []
        res.scalars.return_value.first.return_value = None
        res.all.return_value = []
        res.first.return_value = None
        res.one.return_value = blast_radius
        res.scalar_one.return_value = None
        res.scalar.return_value = None

        if "ai_transactions" in stmt_str or "AITransaction" in stmt_str:
            res.scalar_one_or_none.return_value = txn
        elif "action_contracts" in stmt_str or "ActionContract" in stmt_str:
            res.scalar_one_or_none.return_value = contract
        elif "tool_registry" in stmt_str or "ToolDefinition" in stmt_str or "tools" in stmt_str:
            res.scalar_one_or_none.return_value = tool
        elif "resource_leases" in stmt_str or "ResourceLease" in stmt_str:
            res.scalars.return_value.all.return_value = leases or []
            res.all.return_value = leases or []
        elif "capabilities" in stmt_str or "AgentCapability" in stmt_str:
            res.scalars.return_value.all.return_value = caps or []
            res.all.return_value = caps or []
        elif "action_approvals" in stmt_str or "ActionApproval" in stmt_str:
            res.scalar_one_or_none.return_value = approvals
        elif "budgets" in stmt_str or "Budget" in stmt_str:
            res.scalars.return_value.all.return_value = costs or []
        elif "audit_events" in stmt_str or "AuditEvent" in stmt_str:
            res.first.return_value = audit_chain
            res.scalar_one_or_none.return_value = None
        return res

    mock_session.execute.side_effect = _execute_fake
    return mock_session


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_p6_contracts",
        identity_id="usr_p6_admin",
        role=Role.TENANT_ADMIN,
        token_id="tok_p6_contracts",
    )


@pytest.fixture
def governor_service() -> ActionGovernorService:
    return ActionGovernorService()


def _mock_ai_transaction(txn_id: str, tenant_id: str) -> AITransaction:
    now = datetime.now(UTC)
    return AITransaction(
        id=txn_id,
        tenant_id=tenant_id,
        actor_identity_id="usr_p6_admin",
        idempotency_key=f"idem_{txn_id}",
        correlation_id=f"corr_{txn_id}",
        state="OPEN",
        max_turns=10,
        turn_count=1,
        taint_flags=[],
        context_sources=[],
        final_disposition=None,
        created_at=now,
        updated_at=now,
    )


def _mock_tool_definition(name: str, tenant_id: str) -> ToolDefinition:
    now = datetime.now(UTC)
    return ToolDefinition(
        id=f"tool_id_{name}",
        tenant_id=tenant_id,
        name=name,
        description=f"Mock tool {name}",
        tool_type="NATIVE",
        egress_type="INTERNAL_ISOLATED",
        trust_level="VERIFIED",
        required_capability="db:write",
        active=True,
        parameters_schema={"type": "object", "properties": {}},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_action_proposal_blocks_mutating_action_without_postconditions(
    governor_service: ActionGovernorService,
    auth_context: AuthContext,
) -> None:
    """Mutating action requiring outcome assurance must fail closed if postconditions are missing."""
    proposal = ActionProposal(
        transaction_id="txn_p6_001",
        tool_name="write_file",
        action_type="WRITE",
        target_resource="file:///tmp/audit_log.txt",
        parameters={"content": "secure log entry"},
        preconditions=[],
        postconditions=[],  # Missing postconditions
        idempotency_key="idem_p6_contract_001",
    )

    txn = _mock_ai_transaction("txn_p6_001", auth_context.tenant_id)
    tool = _mock_tool_definition("write_file", auth_context.tenant_id)

    now = datetime.now(UTC)
    mock_cap = MagicMock()
    mock_cap.active = True
    mock_cap.expires_at = now + timedelta(hours=1)
    mock_cap.constraints = {}
    mock_cap.resource_scope = {}
    mock_cap.max_autonomy_level = 4

    mock_session = _build_behavioral_mock_session(
        txn=txn,
        tool=tool,
        caps=[mock_cap],
        leases=[],
        blast_radius=(0, 0),
        costs=[],
    )

    with patch("services.action_governor.db_session.get_tenant_session") as mock_db:
        mock_db.return_value.__aenter__.return_value = mock_session

        decision = await governor_service.propose_and_authorize_action(auth_context, proposal)

        assert decision.decision == Decision.BLOCK
        assert decision.state == ActionState.BLOCKED
        assert "Outcome Assurance contract violation" in decision.reason
        assert "postcondition" in decision.reason.lower()


@pytest.mark.asyncio
async def test_action_proposal_blocks_negative_verification_deadline() -> None:
    """Outcome contract with non-positive verification deadline must fail closed."""
    with pytest.raises(ValidationError):
        OutcomeContractSpec(
            requires_outcome_assurance=True,
            expected_postconditions=[{"target": "status", "expected_value": "ACTIVE"}],
            acceptable_evidence_sources=["obs_source_1"],
            verification_deadline_seconds=0.0,
        )


@pytest.mark.asyncio
async def test_action_proposal_authorizes_valid_outcome_contract(
    governor_service: ActionGovernorService,
    auth_context: AuthContext,
) -> None:
    """Mutating action with valid OutcomeContractSpec authorizes and stores contract."""
    proposal = ActionProposal(
        transaction_id="txn_p6_002",
        tool_name="update_user",
        action_type="WRITE",
        target_resource="postgres://users/42",
        parameters={"status": "SUSPENDED", "user_exists": True},
        preconditions=[PreconditionRule(check_type="EQUALS", target="user_exists", expected_value=True)],
        postconditions=[PostconditionRule(assertion="STATUS_EQUALS", target="status", expected_value="SUSPENDED")],
        outcome_contract=OutcomeContractSpec(
            requires_outcome_assurance=True,
            expected_postconditions=[{"target": "status", "expected_value": "SUSPENDED"}],
            acceptable_evidence_sources=["DatabaseStateAdapter", "obs_trusted_1"],
            verification_deadline_seconds=45.0,
            risk_sensitive_verification_policy=RiskSensitiveVerificationPolicy.DEFAULT,
        ),
        idempotency_key="idem_p6_contract_002",
    )

    txn = _mock_ai_transaction("txn_p6_002", auth_context.tenant_id)
    tool = _mock_tool_definition("update_user", auth_context.tenant_id)

    now = datetime.now(UTC)
    mock_cap = MagicMock()
    mock_cap.active = True
    mock_cap.expires_at = now + timedelta(hours=1)
    mock_cap.constraints = {}
    mock_cap.resource_scope = {}
    mock_cap.max_autonomy_level = 4

    mock_session = _build_behavioral_mock_session(
        txn=txn,
        tool=tool,
        caps=[mock_cap],
        leases=[],
        blast_radius=(0, 0),
        costs=[],
        audit_chain=("0" * 64, 0),
    )

    with patch("services.action_governor.db_session.get_tenant_session") as mock_db:
        mock_db.return_value.__aenter__.return_value = mock_session

        decision = await governor_service.propose_and_authorize_action(auth_context, proposal)

        assert decision.decision == Decision.ALLOW
        assert decision.state in (ActionState.AUTHORIZED, ActionState.AWAITING_APPROVAL)
        assert decision.action_id.startswith("act_")


@pytest.mark.asyncio
async def test_execution_creates_pending_verification_record(
    governor_service: ActionGovernorService,
    auth_context: AuthContext,
) -> None:
    """Executing an action requiring outcome assurance transitions to EXECUTED and PENDING_VERIFICATION.

    Core Invariant: Tool return value / transport HTTP 200 is NOT proof of real-world success.
    """
    now = datetime.now(UTC)
    mock_contract = ActionContract(
        id="act_p6_exec_001",
        tenant_id=auth_context.tenant_id,
        transaction_id="txn_p6_exec_001",
        actor_identity_id=auth_context.identity_id,
        tool_id="tool_payment_sender",
        tool_name="send_payment",
        action_type="EXECUTE",
        target_resource="https://api.stripe.com/v1/transfers",
        parameters={"amount": 5000, "currency": "USD"},
        normalized_parameters={"amount": 5000, "currency": "USD"},
        parameters_hash="param_hash_exec_001",
        required_capability="payment:execute",
        taint_flags=[],
        risk_score=50,
        blast_radius={"target_environment": "PROD"},
        state=ActionState.AUTHORIZED.value,
        idempotency_key="idem_p6_exec_001",
        preconditions=[],
        postconditions=[{"assertion": "STATUS_EQUALS", "target": "payment_status", "expected_value": "PAID"}],
        requires_outcome_assurance=True,
        outcome_contract={
            "requires_outcome_assurance": True,
            "verification_deadline_seconds": 30.0,
            "acceptable_evidence_sources": ["obs_stripe_webhook", "HttpResourceAdapter"],
        },
        outcome_status=OutcomeStatus.PENDING_VERIFICATION.value,
        created_at=now,
        authorized_at=now,
    )
    mock_txn = _mock_ai_transaction("txn_p6_exec_001", auth_context.tenant_id)
    tool = _mock_tool_definition("send_payment", auth_context.tenant_id)
    tool.id = mock_contract.tool_id
    tool.required_capability = mock_contract.required_capability

    mock_cap = MagicMock()
    mock_cap.active = True
    mock_cap.expires_at = now + timedelta(hours=1)
    mock_cap.capability_type = mock_contract.required_capability

    mock_session = _build_behavioral_mock_session(
        txn=mock_txn,
        contract=mock_contract,
        tool=tool,
        caps=[mock_cap],
        leases=[],
        audit_chain=("0" * 64, 0),
    )

    with patch("services.action_governor.db_session.get_tenant_session") as mock_db, \
         patch.object(governor_service.tool_proxy, "dispatch", new_callable=AsyncMock) as mock_dispatch:

        mock_db.return_value.__aenter__.return_value = mock_session

        # Tool returns successful transport ACK
        mock_dispatch.return_value = ({"http_status": 200, "id": "tr_12345", "status": "submitted"}, None)

        req = ActionExecutionRequest(action_id="act_p6_exec_001")
        exec_res = await governor_service.execute_action(auth_context, req)

        # Core Invariants verified:
        assert exec_res.state == ActionState.EXECUTED
        assert exec_res.requires_outcome_assurance is True
        assert exec_res.outcome_status == OutcomeStatus.PENDING_VERIFICATION
        assert exec_res.outcome_id is not None
        assert exec_res.postconditions_satisfied is False  # Acknowledgment is not verification!

        # Check that OutcomeVerificationRecord was added to session
        added_records = [
            call[0][0] for call in mock_session.add.call_args_list
            if isinstance(call[0][0], OutcomeVerificationRecord)
        ]
        assert len(added_records) == 1
        record = added_records[0]
        assert record.outcome_status == OutcomeStatus.PENDING_VERIFICATION.value
        assert record.epistemic_confidence == 0.0
        assert record.verification_deadline is not None


@pytest.mark.asyncio
async def test_read_only_action_completes_without_gate5_pending(
    governor_service: ActionGovernorService,
    auth_context: AuthContext,
) -> None:
    """Non-mutating read-only actions transition directly to COMPLETED without Gate 5 pending record."""
    now = datetime.now(UTC)
    mock_contract = ActionContract(
        id="act_p6_read_001",
        tenant_id=auth_context.tenant_id,
        transaction_id="txn_p6_read_001",
        actor_identity_id=auth_context.identity_id,
        tool_id="tool_file_reader",
        tool_name="read_file",
        action_type="READ",
        target_resource="file:///tmp/readme.txt",
        parameters={"path": "/tmp/readme.txt"},
        normalized_parameters={"path": "/tmp/readme.txt"},
        parameters_hash="param_hash_read_001",
        required_capability="filesystem:read",
        taint_flags=[],
        risk_score=5,
        blast_radius={"target_environment": "DEV"},
        state=ActionState.AUTHORIZED.value,
        idempotency_key="idem_p6_read_001",
        preconditions=[],
        postconditions=[],
        requires_outcome_assurance=False,
        outcome_contract=None,
        outcome_status=None,
        created_at=now,
        authorized_at=now,
    )
    mock_txn = _mock_ai_transaction("txn_p6_read_001", auth_context.tenant_id)
    tool = _mock_tool_definition("read_file", auth_context.tenant_id)
    tool.id = mock_contract.tool_id
    tool.required_capability = mock_contract.required_capability

    mock_cap = MagicMock()
    mock_cap.active = True
    mock_cap.expires_at = now + timedelta(hours=1)
    mock_cap.capability_type = mock_contract.required_capability

    mock_session = _build_behavioral_mock_session(
        txn=mock_txn,
        contract=mock_contract,
        tool=tool,
        caps=[mock_cap],
        leases=[],
        audit_chain=("0" * 64, 0),
    )

    with patch("services.action_governor.db_session.get_tenant_session") as mock_db, \
         patch.object(governor_service.tool_proxy, "dispatch", new_callable=AsyncMock) as mock_dispatch:

        mock_db.return_value.__aenter__.return_value = mock_session

        mock_dispatch.return_value = ({"content": "Hello World", "bytes": 11}, None)

        req = ActionExecutionRequest(action_id="act_p6_read_001")
        exec_res = await governor_service.execute_action(auth_context, req)

        assert exec_res.state == ActionState.COMPLETED
        assert exec_res.requires_outcome_assurance is False
        assert exec_res.outcome_status is None
        assert exec_res.postconditions_satisfied is True


# =============================================================================
# Regression tests for lease expiration semantics & time-bounded invariants
# =============================================================================

def test_lease_expiry_semantics_valid_and_malformed() -> None:
    """Verify production lease expiry semantics:

    1. Active lease with future expiry -> active.
    2. Active lease with past expiry -> inactive.
    3. Active lease with None/missing expiry -> strictly rejected as inactive (never indefinitely valid).
    4. Active lease with non-datetime expiry -> strictly rejected as inactive.
    5. Inactive status -> inactive regardless of expiry.
    """
    from services.concurrency_service import is_lease_active
    from shared.schemas.concurrency import LeaseStatus

    now = datetime.now(UTC)

    # 1. Valid future expiry
    valid_lease = MagicMock()
    valid_lease.status = LeaseStatus.ACQUIRED.value
    valid_lease.expires_at = now + timedelta(minutes=10)
    assert is_lease_active(valid_lease, now) is True

    # 2. Expired past lease
    expired_lease = MagicMock()
    expired_lease.status = LeaseStatus.ACQUIRED.value
    expired_lease.expires_at = now - timedelta(seconds=1)
    assert is_lease_active(expired_lease, now) is False

    # 3. None / missing expiry (MUST NOT be treated as indefinitely valid!)
    none_lease = MagicMock()
    none_lease.status = LeaseStatus.ACQUIRED.value
    none_lease.expires_at = None
    assert is_lease_active(none_lease, now) is False

    # 4. Malformed non-datetime expiry
    malformed_lease = MagicMock()
    malformed_lease.status = LeaseStatus.ACQUIRED.value
    malformed_lease.expires_at = "2099-01-01"
    assert is_lease_active(malformed_lease, now) is False

    # 5. Non-ACQUIRED status
    released_lease = MagicMock()
    released_lease.status = LeaseStatus.RELEASED.value
    released_lease.expires_at = now + timedelta(minutes=10)
    assert is_lease_active(released_lease, now) is False

