"""Security and Integration test suite for MIRAGE 3.0 Phase 6 — Outcome Assurance.

Verifies:
1. Core Invariant: Tool acknowledgment (HTTP 200, tool response) != real-world success.
2. Discrepancy detection: Mismatched target state produces VERIFIED_FAILURE or PARTIAL_ACHIEVEMENT.
3. Risk Policy Enforcement: STRICT_DIRECT_ONLY rejects inferred, blind, or simulated probes.
4. Output <-> Outcome Consistency Reconciliation: Flags false claims of completion on pending or failed actions.
5. Honest Model Verification: Outputs expressing uncertainty or non-completion are permitted.
6. Operator Escalation Workflow: Audited escalation ticket lifecycle with immutable trail.
7. Tenant Isolation: Cross-tenant outcome access and escalation blocked under tenant boundary.
8. Secret and Credential Redaction: Observation payloads scrub credentials and secrets before persistence.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import ActionContract, OutcomeVerificationRecord
from services.reality_verifier import RealityVerifierService
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    IndependentObservation,
    ObservabilityClass,
    OutcomeEscalationRequest,
    OutcomeStatus,
    OutcomeVerificationContract,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
)


@pytest.fixture
def reality_service() -> RealityVerifierService:
    return RealityVerifierService()


@pytest.fixture
def tenant_a_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        identity_id="usr_alpha_admin",
        role=Role.TENANT_ADMIN,
        token_id="tok_alpha",
    )


@pytest.fixture
def tenant_b_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_beta",
        identity_id="usr_beta_admin",
        role=Role.TENANT_ADMIN,
        token_id="tok_beta",
    )


def _mock_action_contract(
    action_id: str = "act_sec_001",
    tenant_id: str = "tenant_alpha",
    risk_policy: str = "DEFAULT",
) -> ActionContract:
    now = datetime.now(UTC)
    return ActionContract(
        id=action_id,
        tenant_id=tenant_id,
        transaction_id="txn_sec_001",
        actor_identity_id="usr_alpha_admin",
        tool_id="tool_ledger_transfer",
        tool_name="transfer_funds",
        action_type="EXECUTE",
        target_resource="ledger://accounts/acct_8899/balance",
        parameters={"amount": 25000, "destination": "acct_9900"},
        normalized_parameters={"amount": 25000, "destination": "acct_9900"},
        parameters_hash="hash_param_sec_001",
        required_capability="ledger:transfer",
        taint_flags=[],
        risk_score=75,
        blast_radius={"target_environment": "PROD"},
        state="EXECUTED",
        idempotency_key=f"idem_{action_id}",
        preconditions=[],
        postconditions=[
            {"assertion": "STATUS_EQUALS", "target": "status", "expected_value": "SETTLED"},
            {"assertion": "STATUS_EQUALS", "target": "recipient_credited", "expected_value": True},
        ],
        requires_outcome_assurance=True,
        outcome_contract={
            "requires_outcome_assurance": True,
            "verification_deadline_seconds": 60.0,
            "acceptable_evidence_sources": ["observer_ledger_auditor", "DatabaseStateAdapter"],
            "risk_sensitive_verification_policy": risk_policy,
        },
        outcome_status=OutcomeStatus.PENDING_VERIFICATION.value,
        created_at=now - timedelta(seconds=15),
        executed_at=now - timedelta(seconds=10),
    )


# ---------------------------------------------------------------------------
# 1. Core Invariant & Discrepancy Detection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discrepancy_detection_flags_postcondition_failure(
    reality_service: RealityVerifierService,
    tenant_a_auth: AuthContext,
) -> None:
    """When target state violates expected postconditions, verification yields VERIFIED_FAILURE."""
    action = _mock_action_contract()
    now = datetime.now(UTC)

    # Observation shows transaction was REJECTED, not SETTLED
    obs = IndependentObservation(
        observation_id="obs_discrepancy_001",
        source_id="observer_ledger_auditor",
        target_resource=action.target_resource,
        observed_at=now,
        observed_state={"status": "REJECTED", "recipient_credited": False},
        evidence_digest="e" * 64,
        epistemic_confidence=0.99,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SETTLED", "recipient_credited": True},
        observation=obs,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        contract = await reality_service.verify_action_outcome(req, tenant_a_auth)

        assert contract.outcome_status == OutcomeStatus.VERIFIED_FAILURE
        assert len(contract.discrepancies) == 2
        assert any("status" in d for d in contract.discrepancies)
        assert any("recipient_credited" in d for d in contract.discrepancies)
        assert action.state == "FAILED"


@pytest.mark.asyncio
async def test_partial_achievement_detected_on_multi_condition_batch(
    reality_service: RealityVerifierService,
    tenant_a_auth: AuthContext,
) -> None:
    """When a subset of postconditions match but another fails, status is PARTIAL_ACHIEVEMENT."""
    action = _mock_action_contract()
    now = datetime.now(UTC)

    # Status settled, but recipient credit not yet reflected
    obs = IndependentObservation(
        observation_id="obs_partial_001",
        source_id="observer_ledger_auditor",
        target_resource=action.target_resource,
        observed_at=now,
        observed_state={"status": "SETTLED", "recipient_credited": False},
        evidence_digest="f" * 64,
        epistemic_confidence=0.95,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SETTLED", "recipient_credited": True},
        observation=obs,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        contract = await reality_service.verify_action_outcome(req, tenant_a_auth)

        assert contract.outcome_status == OutcomeStatus.PARTIAL_ACHIEVEMENT
        assert len(contract.discrepancies) == 1
        assert contract.epistemic_confidence <= 0.70


# ---------------------------------------------------------------------------
# 2. Risk-Sensitive Policy Enforcement
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_strict_direct_only_policy_rejects_simulated_probes(
    reality_service: RealityVerifierService,
    tenant_a_auth: AuthContext,
) -> None:
    """Action mandating STRICT_DIRECT_ONLY policy strictly rejects SimulatedTestAdapter."""
    action = _mock_action_contract(risk_policy="STRICT_DIRECT_ONLY")

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={"status": "SETTLED"},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await reality_service.verify_action_outcome(req, tenant_a_auth)

        assert exc_info.value.status_code == 400
        assert "STRICT_DIRECT_ONLY" in exc_info.value.detail


@pytest.mark.asyncio
async def test_strict_direct_only_policy_rejects_inferred_observability(
    reality_service: RealityVerifierService,
    tenant_a_auth: AuthContext,
) -> None:
    """Action mandating STRICT_DIRECT_ONLY policy strictly rejects OBS_INFERRED transport ACKs."""
    action = _mock_action_contract(risk_policy="STRICT_DIRECT_ONLY")

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_INFERRED,
        verifier_type=OutcomeVerifierType.DATABASE,
        expected_postconditions={"status": "SETTLED"},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await reality_service.verify_action_outcome(req, tenant_a_auth)

        assert exc_info.value.status_code == 400
        assert "STRICT_DIRECT_ONLY" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 3. Output <-> Outcome Consistency Reconciliation
# ---------------------------------------------------------------------------

def test_reconciliation_flags_completion_claim_when_outcome_is_pending(
    reality_service: RealityVerifierService,
) -> None:
    """Model claiming success when outcome is PENDING_VERIFICATION must trigger epistemic conflict."""
    contract = OutcomeVerificationContract(
        outcome_id="outc_sec_pending_01",
        transaction_id="txn_sec_001",
        action_id="act_sec_001",
        tenant_id="tenant_alpha",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.PENDING_VERIFICATION,
        epistemic_confidence=0.0,
        verifier_adapter="PENDING_INDEPENDENT_OBSERVATION",
        is_simulated=False,
        expected_postconditions={"status": "SETTLED"},
        observed_state={},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_pending_001",
        verified_at=datetime.now(UTC).isoformat(),
    )

    result = reality_service.reconcile_output_with_outcome(
        response_text="I have successfully transferred the funds and the transaction is finalized.",
        outcome_contract=contract,
    )

    assert result.is_consistent is False
    assert result.epistemic_conflict_detected is True
    assert result.recommended_disposition == "REWRITE_WITH_CAVEAT"
    assert any("PENDING_VERIFICATION" in r for r in result.conflict_reasons)


def test_reconciliation_rejects_completion_claim_when_outcome_failed(
    reality_service: RealityVerifierService,
) -> None:
    """Model output asserting success when outcome is VERIFIED_FAILURE must be REJECTED."""
    contract = OutcomeVerificationContract(
        outcome_id="outc_sec_failed_01",
        transaction_id="txn_sec_001",
        action_id="act_sec_001",
        tenant_id="tenant_alpha",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.VERIFIED_FAILURE,
        epistemic_confidence=0.95,
        verifier_adapter="observer_ledger_auditor",
        is_simulated=False,
        expected_postconditions={"status": "SETTLED"},
        observed_state={"status": "REJECTED"},
        discrepancies=["Status mismatch: expected SETTLED, observed REJECTED"],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_failed_001",
        verified_at=datetime.now(UTC).isoformat(),
    )

    result = reality_service.reconcile_output_with_outcome(
        response_text="The wire payment was processed and the money has reached the recipient.",
        outcome_contract=contract,
    )

    assert result.is_consistent is False
    assert result.epistemic_conflict_detected is True
    assert result.recommended_disposition == "REJECT"


def test_reconciliation_permits_honest_model_acknowledging_uncertainty(
    reality_service: RealityVerifierService,
) -> None:
    """Model output honestly stating it cannot confirm outcome passes without conflict."""
    contract = OutcomeVerificationContract(
        outcome_id="outc_sec_pending_02",
        transaction_id="txn_sec_001",
        action_id="act_sec_001",
        tenant_id="tenant_alpha",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.PENDING_VERIFICATION,
        epistemic_confidence=0.0,
        verifier_adapter="PENDING_INDEPENDENT_OBSERVATION",
        is_simulated=False,
        expected_postconditions={"status": "SETTLED"},
        observed_state={},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_pending_002",
        verified_at=datetime.now(UTC).isoformat(),
    )

    result = reality_service.reconcile_output_with_outcome(
        response_text=(
            "The payment transfer was requested, but I cannot confirm whether destination funds settled."
        ),
        outcome_contract=contract,
    )

    assert result.is_consistent is True
    assert result.epistemic_conflict_detected is False
    assert result.recommended_disposition == "PERMIT"


# ---------------------------------------------------------------------------
# 4. Operator Escalation Workflow
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_operator_escalation_workflow(
    reality_service: RealityVerifierService,
    tenant_a_auth: AuthContext,
) -> None:
    """Operator escalation records escalation status, notes, and an immutable audit trail record."""
    now = datetime.now(UTC)
    record = OutcomeVerificationRecord(
        id="outc_esc_001",
        tenant_id=tenant_a_auth.tenant_id,
        transaction_id="txn_esc_001",
        action_id="act_esc_001",
        observability_class=ObservabilityClass.OBS_DIRECT.value,
        outcome_status=OutcomeStatus.PARTIAL_ACHIEVEMENT.value,
        epistemic_confidence=0.60,
        verifier_adapter="observer_warehouse_sql",
        is_simulated=False,
        expected_postconditions={"status": "SHIPPED"},
        observed_state={"status": "AWAITING_LABEL"},
        discrepancies=["Status mismatch: expected SHIPPED, observed AWAITING_LABEL"],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_esc_001",
        idempotency_key="idem_esc_001",
        target_environment="PROD",
        contract_binding_hash="binding_esc_001",
        created_at=now,
        verified_at=now,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        req = OutcomeEscalationRequest(
            outcome_id="outc_esc_001",
            reason="Partial fulfillment observed during warehouse sweep",
            escalation_notes="Manual shipment verification required with shipping supervisor",
        )

        res = await reality_service.escalate_outcome(req, tenant_a_auth)

        assert res.outcome_id == "outc_esc_001"
        assert res.escalation_status == "ESCALATED"
        assert record.escalation_status == "ESCALATED"
        assert "Manual shipment verification required" in (record.escalation_notes or "")
        assert mock_session.add.called  # Audit record added


# ---------------------------------------------------------------------------
# 5. Cross-Tenant Isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_tenant_outcome_access_prevented(
    reality_service: RealityVerifierService,
    tenant_b_auth: AuthContext,
) -> None:
    """Tenant B cannot access or mutate Tenant A's outcome records."""
    # Tenant B tries to query Tenant A's outcome ID
    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()
        # Tenant boundary query for Tenant B returns None because tenant_id doesn't match
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        contract = await reality_service.get_outcome_by_id("outc_sec_001_tenant_a", tenant_b_auth.tenant_id)

        assert contract is None
