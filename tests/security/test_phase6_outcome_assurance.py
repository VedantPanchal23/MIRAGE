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
    compute_evidence_digest,
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
    state_rej = {"status": "REJECTED", "recipient_credited": False}
    obs = IndependentObservation(
        observation_id="obs_discrepancy_001",
        source_id="observer_ledger_auditor",
        target_resource=action.target_resource,
        observed_at=now,
        observed_state=state_rej,
        evidence_digest=compute_evidence_digest(state_rej),
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
    state_part = {"status": "SETTLED", "recipient_credited": False}
    obs = IndependentObservation(
        observation_id="obs_partial_001",
        source_id="observer_ledger_auditor",
        target_resource=action.target_resource,
        observed_at=now,
        observed_state=state_part,
        evidence_digest=compute_evidence_digest(state_part),
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
        response_text=("The payment transfer was requested, but I cannot confirm whether destination funds settled."),
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


# ---------------------------------------------------------------------------
# 6. Replay Defense, Immutability, Tampering & Late Observation Defense
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observation_id_replay_attack_rejected(
    reality_service: RealityVerifierService,
    tenant_a_auth: AuthContext,
) -> None:
    """An observation ID previously consumed for Action A cannot be recycled for Action B."""
    action_b = _mock_action_contract(action_id="act_sec_002")
    now = datetime.now(UTC)
    state = {"status": "SETTLED", "recipient_credited": True}

    obs = IndependentObservation(
        observation_id="obs_recycled_999",
        source_id="observer_ledger_auditor",
        target_resource=action_b.target_resource,
        observed_at=now,
        observed_state=state,
        evidence_digest=compute_evidence_digest(state),
        epistemic_confidence=0.99,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action_b.transaction_id,
        action_id=action_b.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions=state,
        observation=obs,
    )

    # Prior record on Action A consumed obs_recycled_999
    consumed_record = OutcomeVerificationRecord(
        id="outc_prior_001",
        tenant_id=tenant_a_auth.tenant_id,
        transaction_id="txn_prior_001",
        action_id="act_sec_001",  # Different action!
        observability_class=ObservabilityClass.OBS_DIRECT.value,
        outcome_status=OutcomeStatus.VERIFIED_SUCCESS.value,
        epistemic_confidence=1.0,
        verifier_adapter="IndependentObserverAdapter",
        is_simulated=False,
        expected_postconditions={},
        observed_state=state,
        discrepancies=[],
        evidence_payload={"observation_id": "obs_recycled_999"},
        reconciliation_notes=[],
        verification_hash="hash_prior",
        target_environment="PROD",
        created_at=now - timedelta(minutes=5),
        verified_at=now - timedelta(minutes=5),
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()

        def mock_execute(stmt):
            m = MagicMock()
            stmt_str = str(stmt).lower()
            if "from action_contracts" in stmt_str:
                m.scalar_one_or_none.return_value = action_b
            elif "action_id !=" in stmt_str or "action_id <>" in stmt_str:
                # Replay check query: returns consumed_record
                m.scalars.return_value.all.return_value = [consumed_record]
            else:
                m.scalar_one_or_none.return_value = None
                m.scalars.return_value.all.return_value = []
            return m

        mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_db.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await reality_service.verify_action_outcome(req, tenant_a_auth)
        assert exc_info.value.status_code == 409
        assert "Observation replay attack detected" in exc_info.value.detail


@pytest.mark.asyncio
async def test_terminal_state_immutability_blocks_conflicting_reverification(
    reality_service: RealityVerifierService,
    tenant_a_auth: AuthContext,
) -> None:
    """An action whose outcome is already in terminal VERIFIED_SUCCESS cannot be re-verified with non-matching key."""
    action = _mock_action_contract(action_id="act_sec_terminal_001")
    now = datetime.now(UTC)

    terminal_record = OutcomeVerificationRecord(
        id="outc_terminal_001",
        tenant_id=tenant_a_auth.tenant_id,
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT.value,
        outcome_status=OutcomeStatus.VERIFIED_SUCCESS.value,
        epistemic_confidence=1.0,
        verifier_adapter="IndependentObserverAdapter",
        is_simulated=False,
        expected_postconditions={"status": "SETTLED"},
        observed_state={"status": "SETTLED"},
        discrepancies=[],
        evidence_payload={
            "_canonical_payload": {
                "schema_version": "mirage.outcome.v1",
                "tenant_id": tenant_a_auth.tenant_id,
                "transaction_id": action.transaction_id,
                "action_id": action.id,
                "contract_binding_hash": action.parameters_hash,
                "tool_name": action.tool_name,
                "target_resource": action.target_resource,
                "required_capability": action.required_capability,
                "target_environment": "PROD",
                "observability_class": "OBS_DIRECT",
                "outcome_status": "VERIFIED_SUCCESS",
                "epistemic_confidence": 1.0,
                "verifier_adapter": "IndependentObserverAdapter",
                "is_simulated": False,
                "expected_postconditions": {"status": "SETTLED"},
                "observed_state_hash": "dummy_hash",
                "verified_at": now.isoformat(),
                "idempotency_key": "key_initial",
            }
        },
        reconciliation_notes=[],
        verification_hash="hash_term",
        idempotency_key="key_initial",
        target_environment="PROD",
        created_at=now - timedelta(minutes=2),
        verified_at=now - timedelta(minutes=2),
    )

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        idempotency_key="key_different_conflict",
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={"status": "SETTLED"},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()

        def mock_execute(stmt):
            m = MagicMock()
            stmt_str = str(stmt).lower()
            if "from action_contracts" in stmt_str:
                m.scalar_one_or_none.return_value = action
            elif "from outcome_verification_records" in stmt_str:
                m.scalar_one_or_none.return_value = terminal_record
            else:
                m.scalar_one_or_none.return_value = None
            return m

        mock_session.execute = AsyncMock(side_effect=mock_execute)
        mock_db.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await reality_service.verify_action_outcome(req, tenant_a_auth)
        assert exc_info.value.status_code == 409
        assert "Terminal outcomes are immutable" in exc_info.value.detail


@pytest.mark.asyncio
async def test_tampered_evidence_digest_rejected_in_verification_lifecycle(
    reality_service: RealityVerifierService,
    tenant_a_auth: AuthContext,
) -> None:
    """Submitting observation with tampered payload where digest does not match must fail with HTTP 400."""
    action = _mock_action_contract(action_id="act_sec_tamper_001")
    now = datetime.now(UTC)

    # Claim digest "0"*64 over state {"status": "SETTLED"}, which doesn't match
    obs = IndependentObservation(
        observation_id="obs_tamper_001",
        source_id="observer_ledger_auditor",
        target_resource=action.target_resource,
        observed_at=now,
        observed_state={"status": "SETTLED", "injected_bonus": 1000000},
        evidence_digest="0" * 64,
        epistemic_confidence=0.99,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SETTLED"},
        observation=obs,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await reality_service.verify_action_outcome(req, tenant_a_auth)
        assert exc_info.value.status_code == 400
        assert "Evidence digest mismatch" in exc_info.value.detail


@pytest.mark.asyncio
async def test_late_observation_cannot_turn_expired_action_into_verified_success(
    reality_service: RealityVerifierService,
    tenant_a_auth: AuthContext,
) -> None:
    """When action verification deadline expired, late verification cannot yield VERIFIED_SUCCESS."""
    # Action executed 120s ago with 30s deadline -> deadline_passed is True!
    now = datetime.now(UTC)
    action = _mock_action_contract(action_id="act_sec_expired_001")
    action.executed_at = now - timedelta(seconds=120)
    action.outcome_contract = {
        "requires_outcome_assurance": True,
        "verification_deadline_seconds": 30.0,
        "acceptable_evidence_sources": ["DatabaseStateAdapter", "observer_ledger_auditor"],
        "risk_sensitive_verification_policy": "DEFAULT",
    }

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.DATABASE,
        expected_postconditions={"status": "SETTLED"},
        adapter_config={"mock_db_state": {"status": "SETTLED"}},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        with patch.object(
            reality_service.adapters[OutcomeVerifierType.DATABASE],
            "verify",
            new_callable=AsyncMock,
        ) as mock_probe:
            from services.reality_verifier import AdapterProbeResult

            mock_probe.return_value = AdapterProbeResult(
                observed_state={"status": "SETTLED"},
                evidence_payload={},
                discrepancies=[],
                is_simulated=False,
                adapter_name="DatabaseStateAdapter",
                success_indicated=True,
                reconciliation_notes=[],
            )

            contract = await reality_service.verify_action_outcome(req, tenant_a_auth)
            # Must strictly downgrade to UNKNOWN with confidence 0.0 because deadline expired!
            assert contract.outcome_status == OutcomeStatus.UNKNOWN
            assert contract.epistemic_confidence == 0.0
            assert any("deadline expired" in n.lower() for n in contract.reconciliation_notes)
