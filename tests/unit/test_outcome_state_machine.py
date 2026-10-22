"""Unit tests for Phase 6 Monotonic Outcome State Machine, Independent Observation, and Evidence Provenance."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import ActionContract, OutcomeVerificationRecord
from services.reality_verifier import (
    IndependentObserverAdapter,
    RealityVerifierService,
    _redact_sensitive_payload,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    IndependentObservation,
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
    compute_evidence_digest,
)


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_p6_sm",
        identity_id="usr_p6_sm_admin",
        role=Role.TENANT_ADMIN,
        token_id="tok_p6_sm",
    )


@pytest.fixture
def reality_service() -> RealityVerifierService:
    return RealityVerifierService()


def _mock_action(action_id: str = "act_p6_sm_1", target: str = "postgres://orders/101") -> ActionContract:
    now = datetime.now(UTC)
    return ActionContract(
        id=action_id,
        tenant_id="tenant_p6_sm",
        transaction_id="txn_p6_sm_1",
        actor_identity_id="usr_p6_sm_admin",
        tool_id="tool_order_updater",
        tool_name="update_order",
        action_type="WRITE",
        target_resource=target,
        parameters={"order_id": 101, "status": "SHIPPED"},
        normalized_parameters={"order_id": 101, "status": "SHIPPED"},
        parameters_hash="param_hash_p6_sm_1",
        required_capability="orders:write",
        taint_flags=[],
        risk_score=45,
        blast_radius={"target_environment": "PROD"},
        state="EXECUTED",
        idempotency_key=f"idem_{action_id}",
        preconditions=[],
        postconditions=[{"target": "status", "expected_value": "SHIPPED"}],
        requires_outcome_assurance=True,
        outcome_contract={
            "requires_outcome_assurance": True,
            "verification_deadline_seconds": 30.0,
            "acceptable_evidence_sources": ["observer_warehouse_sql", "observer_courier_api"],
            "risk_sensitive_verification_policy": "DEFAULT",
        },
        outcome_status=OutcomeStatus.PENDING_VERIFICATION.value,
        created_at=now - timedelta(seconds=10),
        executed_at=now - timedelta(seconds=5),
    )


def test_monotonic_state_machine_transition_rules(reality_service: RealityVerifierService) -> None:
    """Verify monotonic transition rules: permitted advances vs illegal regressions."""
    # PENDING_VERIFICATION can transition to terminal and intermediate states
    reality_service._validate_outcome_transition(OutcomeStatus.PENDING_VERIFICATION, OutcomeStatus.VERIFIED_SUCCESS)
    reality_service._validate_outcome_transition(OutcomeStatus.PENDING_VERIFICATION, OutcomeStatus.VERIFIED_FAILURE)
    reality_service._validate_outcome_transition(OutcomeStatus.PENDING_VERIFICATION, OutcomeStatus.PARTIAL_ACHIEVEMENT)
    reality_service._validate_outcome_transition(OutcomeStatus.PENDING_VERIFICATION, OutcomeStatus.UNKNOWN)
    reality_service._validate_outcome_transition(OutcomeStatus.PENDING_VERIFICATION, OutcomeStatus.UNVERIFIABLE)

    # Terminal VERIFIED_SUCCESS cannot regress to PENDING_VERIFICATION or FAILED
    with pytest.raises(HTTPException) as exc_info:
        reality_service._validate_outcome_transition(OutcomeStatus.VERIFIED_SUCCESS, OutcomeStatus.PENDING_VERIFICATION)
    assert exc_info.value.status_code == 409

    with pytest.raises(HTTPException) as exc_info2:
        reality_service._validate_outcome_transition(OutcomeStatus.VERIFIED_SUCCESS, OutcomeStatus.FAILED)
    assert exc_info2.value.status_code == 409

    # Terminal VERIFIED_FAILURE cannot upgrade to VERIFIED_SUCCESS
    with pytest.raises(HTTPException) as exc_info3:
        reality_service._validate_outcome_transition(OutcomeStatus.VERIFIED_FAILURE, OutcomeStatus.VERIFIED_SUCCESS)
    assert exc_info3.value.status_code == 409


@pytest.mark.asyncio
async def test_independent_observer_adapter_verifies_success() -> None:
    """Independent observation matching expected postconditions yields success with observer confidence."""
    adapter = IndependentObserverAdapter()
    action = _mock_action()
    now = datetime.now(UTC)
    state = {"status": "SHIPPED", "tracking_number": "TRK123456"}

    obs = IndependentObservation(
        observation_id="obs_001",
        source_id="observer_warehouse_sql",
        target_resource=action.target_resource,
        observed_at=now,
        observed_state=state,
        evidence_digest=compute_evidence_digest(state),
        epistemic_confidence=0.98,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SHIPPED"},
        observation=obs,
    )

    probe = await adapter.verify(action, req, action.tenant_id)
    assert probe.success_indicated is True
    assert len(probe.discrepancies) == 0
    assert probe.is_simulated is False
    assert probe.observed_state["status"] == "SHIPPED"


@pytest.mark.asyncio
async def test_independent_observer_adapter_rejects_digest_mismatch() -> None:
    """Tampered observation state with mismatched digest must fail closed with HTTP 400."""
    adapter = IndependentObserverAdapter()
    action = _mock_action()
    now = datetime.now(UTC)

    obs = IndependentObservation(
        observation_id="obs_tampered_001",
        source_id="observer_warehouse_sql",
        target_resource=action.target_resource,
        observed_at=now,
        observed_state={"status": "SHIPPED", "tampered_field": "injected_value"},
        evidence_digest="a" * 64,  # Does not match recomputed SHA-256 of observed_state!
        epistemic_confidence=0.98,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SHIPPED"},
        observation=obs,
    )

    with pytest.raises(HTTPException) as exc_info:
        await adapter.verify(action, req, action.tenant_id)
    assert exc_info.value.status_code == 400
    assert "Evidence digest mismatch" in exc_info.value.detail


@pytest.mark.asyncio
async def test_independent_observer_adapter_rejects_future_timestamp() -> None:
    """Observation timestamp in the future must fail closed with HTTP 400."""
    adapter = IndependentObserverAdapter()
    action = _mock_action()
    future_time = datetime.now(UTC) + timedelta(minutes=10)
    state = {"status": "SHIPPED"}

    obs = IndependentObservation(
        observation_id="obs_future_001",
        source_id="observer_warehouse_sql",
        target_resource=action.target_resource,
        observed_at=future_time,
        observed_state=state,
        evidence_digest=compute_evidence_digest(state),
        epistemic_confidence=0.98,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SHIPPED"},
        observation=obs,
    )

    with pytest.raises(HTTPException) as exc_info:
        await adapter.verify(action, req, action.tenant_id)
    assert exc_info.value.status_code == 400
    assert "Future observation timestamp" in exc_info.value.detail


@pytest.mark.asyncio
async def test_independent_observer_adapter_rejects_expired_observation() -> None:
    """Observation captured after action verification deadline must fail closed with HTTP 400."""
    adapter = IndependentObserverAdapter()
    action = _mock_action()
    # Action outcome_contract defines verification_deadline_seconds=30.0
    late_time = (action.executed_at or datetime.now(UTC)) + timedelta(seconds=45)
    state = {"status": "SHIPPED"}

    obs = IndependentObservation(
        observation_id="obs_expired_001",
        source_id="observer_warehouse_sql",
        target_resource=action.target_resource,
        observed_at=late_time,
        observed_state=state,
        evidence_digest=compute_evidence_digest(state),
        epistemic_confidence=0.98,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SHIPPED"},
        observation=obs,
    )

    with pytest.raises(HTTPException) as exc_info:
        await adapter.verify(action, req, action.tenant_id)
    assert exc_info.value.status_code == 400
    assert "Expired observation" in exc_info.value.detail


@pytest.mark.asyncio
async def test_independent_observer_adapter_rejects_target_mismatch() -> None:
    """Observation of a mismatched target resource must fail closed."""
    adapter = IndependentObserverAdapter()
    action = _mock_action(target="postgres://orders/101")
    now = datetime.now(UTC)

    obs = IndependentObservation(
        observation_id="obs_002",
        source_id="observer_warehouse_sql",
        target_resource="postgres://orders/999",  # Mismatch!
        observed_at=now,
        observed_state={"status": "SHIPPED"},
        evidence_digest="b" * 64,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SHIPPED"},
        observation=obs,
    )

    with pytest.raises(HTTPException) as exc_info:
        await adapter.verify(action, req, action.tenant_id)
    assert exc_info.value.status_code == 400
    assert "Target resource mismatch" in exc_info.value.detail


@pytest.mark.asyncio
async def test_independent_observer_adapter_rejects_stale_observation() -> None:
    """Observation timestamp earlier than action execution must be rejected as stale evidence."""
    adapter = IndependentObserverAdapter()
    action = _mock_action()

    # Observation 1 hour before action execution
    stale_time = (action.executed_at or datetime.now(UTC)) - timedelta(hours=1)

    obs = IndependentObservation(
        observation_id="obs_003",
        source_id="observer_warehouse_sql",
        target_resource=action.target_resource,
        observed_at=stale_time,
        observed_state={"status": "SHIPPED"},
        evidence_digest="c" * 64,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SHIPPED"},
        observation=obs,
    )

    with pytest.raises(HTTPException) as exc_info:
        await adapter.verify(action, req, action.tenant_id)
    assert exc_info.value.status_code == 400
    assert "Stale observation" in exc_info.value.detail


@pytest.mark.asyncio
async def test_independent_observer_adapter_rejects_untrusted_source() -> None:
    """Observation from a source not in acceptable_evidence_sources must be rejected."""
    adapter = IndependentObserverAdapter()
    action = _mock_action()
    now = datetime.now(UTC)

    obs = IndependentObservation(
        observation_id="obs_004",
        source_id="unauthorized_third_party_bot",  # Not in allowed list
        target_resource=action.target_resource,
        observed_at=now,
        observed_state={"status": "SHIPPED"},
        evidence_digest="d" * 64,
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SHIPPED"},
        observation=obs,
    )

    with pytest.raises(HTTPException) as exc_info:
        await adapter.verify(action, req, action.tenant_id)
    assert exc_info.value.status_code == 400
    assert "Untrusted evidence source" in exc_info.value.detail


@pytest.mark.asyncio
async def test_independent_observer_adapter_rejects_malformed_digest() -> None:
    """Invalid SHA-256 digest format must be rejected."""
    adapter = IndependentObserverAdapter()
    action = _mock_action()
    now = datetime.now(UTC)

    obs = IndependentObservation(
        observation_id="obs_005",
        source_id="observer_warehouse_sql",
        target_resource=action.target_resource,
        observed_at=now,
        observed_state={"status": "SHIPPED"},
        evidence_digest="invalid_not_hex_digest",  # Bad digest!
    )
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
        expected_postconditions={"status": "SHIPPED"},
        observation=obs,
    )

    with pytest.raises(HTTPException) as exc_info:
        await adapter.verify(action, req, action.tenant_id)
    assert exc_info.value.status_code == 400
    assert "Invalid evidence digest" in exc_info.value.detail


def test_sensitive_payload_redaction() -> None:
    """Secrets, API keys, and connection credentials must be scrubbed from observed payloads."""
    raw_payload = {
        "user": "alice",
        "api_key": "sk-1234567890abcdef123456",
        "nested": {
            "token": "ghp_12345678901234567890",
            "auth_header": "Bearer secret_jwt_token_xyz.123.abc",
            "db_uri": "postgres://admin:super_secret_password@db.prod.internal:5432/main",
        },
        "safe_field": 42,
    }

    clean = _redact_sensitive_payload(raw_payload)

    assert clean["api_key"] == "[REDACTED]"
    assert clean["nested"]["token"] == "[REDACTED]"
    assert "[REDACTED]" in clean["nested"]["auth_header"]
    assert "secret_jwt_token" not in clean["nested"]["auth_header"]
    assert "[REDACTED]" in clean["nested"]["db_uri"]
    assert "super_secret_password" not in clean["nested"]["db_uri"]
    assert clean["safe_field"] == 42


@pytest.mark.asyncio
async def test_deadline_expiration_downgrades_to_unknown(
    reality_service: RealityVerifierService,
    auth_context: AuthContext,
) -> None:
    """Pending outcome whose deadline has passed must automatically transition to UNKNOWN with confidence 0.0."""
    now = datetime.now(UTC)
    expired_record = OutcomeVerificationRecord(
        id="outc_expired_001",
        tenant_id=auth_context.tenant_id,
        transaction_id="txn_expired_1",
        action_id="act_expired_1",
        observability_class=ObservabilityClass.OBS_DIRECT.value,
        outcome_status=OutcomeStatus.PENDING_VERIFICATION.value,
        epistemic_confidence=0.0,
        verifier_adapter="PENDING_INDEPENDENT_OBSERVATION",
        is_simulated=False,
        expected_postconditions={"status": "CONFIRMED"},
        observed_state={},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_expired",
        idempotency_key="idem_expired",
        target_environment="PROD",
        contract_binding_hash="binding_hash",
        verification_deadline=now - timedelta(minutes=5),  # Passed 5 minutes ago
        created_at=now - timedelta(minutes=6),
        verified_at=now - timedelta(minutes=6),
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_db:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = expired_record
        mock_session.execute.return_value = mock_result
        mock_db.return_value.__aenter__.return_value = mock_session

        contract = await reality_service.get_outcome_by_id("outc_expired_001", auth_context.tenant_id)

        assert contract is not None
        assert contract.outcome_status == OutcomeStatus.UNKNOWN
        assert contract.epistemic_confidence == 0.0
        assert any("deadline expired" in note.lower() for note in contract.reconciliation_notes)
