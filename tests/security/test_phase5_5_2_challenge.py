"""Phase 5.5.2 Challenge, Adversarial Reproduction & Release-Gate Verification Suite.

Validates:
1. Socket-Boundary DNS Rebinding / SSRF Defense (SafeAsyncNetworkBackend & SafeAsyncHTTPTransport).
2. Audit Trail External Trust Anchor Integrity (storage tampering detected against immutable AuditLogRecord).
3. Monotonic State Machine Enforcement & Terminal Invariant Integrity.
4. Premature Verification Rejection (PROPOSED, EXECUTING, CANCELLED, BLOCKED rejected; COMPLETED permitted).
5. Output-Outcome Reconciliation Negation Guard (honest failure reporting permitted without false conflict).
6. Cross-Tenant Outcome Isolation.
7. Database Migration Unique Constraint Integrity.
"""

import hashlib
import importlib
import inspect
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore
import pytest
from fastapi import HTTPException

from db.models import ActionContract, AuditLogRecord, OutcomeVerificationRecord
from services.reality_verifier import (
    RealityVerifierService,
    SafeAsyncNetworkBackend,
)
from shared.schemas.action import ActionState
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationContract,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
)


@pytest.fixture
def auth_tenant_552():
    return AuthContext(
        tenant_id="tenant_challenge_552",
        role=Role.TENANT_ADMIN,
        user_id="usr_audit_552",
        identity_id="ident_audit_552",
        principal_type="USER",
        is_authenticated=True,
    )


def _make_action(
    action_id: str = "act_ch_01",
    tenant_id: str = "tenant_challenge_552",
    transaction_id: str = "txn_ch_01",
    state: str = ActionState.COMPLETED.value,
    target_resource: str = "https://api.external-partner.com/v1/orders",
    postconditions: list | None = None,
    observed_result: dict | None = None,
) -> ActionContract:
    return ActionContract(
        id=action_id,
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        actor_identity_id=f"ident_{tenant_id}",
        tool_id="tool_api",
        tool_name="api_invoker",
        action_type="EXECUTE",
        target_resource=target_resource,
        parameters={"order_id": "ord_99"},
        normalized_parameters={"order_id": "ord_99"},
        parameters_hash="param_hash_552",
        required_capability="api:invoke",
        state=state,
        idempotency_key=f"idem_{action_id}",
        preconditions=[],
        postconditions=(
            postconditions if postconditions is not None else [{"target": "status", "expected_value": "SETTLED"}]
        ),
        observed_result=observed_result or {"status": "SETTLED"},
        blast_radius={"target_environment": "PROD", "estimated_dollar_cost": 10.0},
    )


# -----------------------------------------------------------------------------
# 1. Socket-Boundary DNS Rebinding / SSRF Defense
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dns_rebinding_connection_boundary_interception():
    """Verify SafeAsyncNetworkBackend intercepts socket connection to private IP before HTTP bytes flow."""
    # Simulate a backend where socket connects to loopback (127.0.0.1) despite domain check
    backend = SafeAsyncNetworkBackend(is_ip_allowed_fn=lambda _ip: False, allow_local=False)

    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    mock_stream.get_extra_info = MagicMock(return_value=("127.0.0.1", 80))

    with patch.object(backend._backend, "connect_tcp", new=AsyncMock(return_value=mock_stream)):
        with pytest.raises(httpcore.ConnectError) as exc_info:
            await backend.connect_tcp("rebinding-domain.attacker.com", 80)

        assert "SSRF / DNS rebinding security block" in str(exc_info.value)
        assert "127.0.0.1" in str(exc_info.value)
        # Socket must have been closed immediately
        mock_stream.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_dns_rebinding_cloud_metadata_boundary_interception():
    """Verify SafeAsyncNetworkBackend blocks 169.254.169.254 metadata endpoint at socket layer."""
    backend = SafeAsyncNetworkBackend(is_ip_allowed_fn=lambda _ip: False, allow_local=False)

    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    mock_stream.get_extra_info = MagicMock(return_value=("169.254.169.254", 80))

    with patch.object(backend._backend, "connect_tcp", new=AsyncMock(return_value=mock_stream)):
        with pytest.raises(httpcore.ConnectError) as exc_info:
            await backend.connect_tcp("metadata.cloud.internal", 80)

        assert "SSRF / DNS rebinding security block" in str(exc_info.value)
        assert "169.254.169.254" in str(exc_info.value)
        mock_stream.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_async_network_backend_permits_allowed_ip():
    """Verify SafeAsyncNetworkBackend permits connections to authorized public IPs."""
    backend = SafeAsyncNetworkBackend(is_ip_allowed_fn=lambda _ip: True, allow_local=False)

    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    mock_stream.get_extra_info = MagicMock(return_value=("93.184.216.34", 443))

    with patch.object(backend._backend, "connect_tcp", new=AsyncMock(return_value=mock_stream)):
        stream = await backend.connect_tcp("example.com", 443)
        assert stream is mock_stream
        mock_stream.aclose.assert_not_called()


# -----------------------------------------------------------------------------
# 2. Audit Trail External Trust Anchor vs Storage Tamper Detection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_trail_tamper_detection_matching_record():
    """Legitimate record matching immutable AuditLogRecord passes verification."""
    service = RealityVerifierService()

    now = datetime.now(UTC)
    canonical = {
        "action_id": "act_ch_01",
        "contract_binding_hash": "param_hash_552",
        "epistemic_confidence": 1.0,
        "expected_postconditions": {"status": "SETTLED"},
        "idempotency_key": "idem_1",
        "is_simulated": False,
        "observability_class": "OBS_DIRECT",
        "observed_state_hash": "obs_hash_1",
        "outcome_status": "SUCCESS_CONFIRMED",
        "schema_version": "mirage.outcome.v1",
        "target_environment": "PROD",
        "target_resource": "https://api.external-partner.com/v1/orders",
        "tenant_id": "tenant_challenge_552",
        "tool_name": "api_invoker",
        "transaction_id": "txn_ch_01",
        "verified_at": now.isoformat(),
        "verifier_adapter": "HttpResourceAdapter",
    }
    canon_bytes = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    v_hash = hashlib.sha256(canon_bytes).hexdigest()

    rec = OutcomeVerificationRecord(
        id="outc_552_legit",
        tenant_id="tenant_challenge_552",
        transaction_id="txn_ch_01",
        action_id="act_ch_01",
        observability_class="OBS_DIRECT",
        outcome_status="SUCCESS_CONFIRMED",
        epistemic_confidence=1.0,
        verifier_adapter="HttpResourceAdapter",
        is_simulated=False,
        expected_postconditions={"status": "SETTLED"},
        observed_state={"status": "SETTLED"},
        discrepancies=[],
        evidence_payload={"_canonical_payload": canonical},
        reconciliation_notes=[],
        verification_hash=v_hash,
        idempotency_key="idem_1",
        target_environment="PROD",
        contract_binding_hash="param_hash_552",
        created_at=now,
        verified_at=now,
    )

    audit_rec = AuditLogRecord(
        entry_id="aud_552_01",
        tenant_id="tenant_challenge_552",
        session_id="txn_ch_01",
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=v_hash,
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id="txn_ch_01",
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="api:invoke",
        reason="test",
        event_payload={
            "outcome_id": "outc_552_legit",
            "action_id": "act_ch_01",
            "transaction_id": "txn_ch_01",
            "verified_at": now.isoformat(),
        },
        prev_hash="0" * 64,
        chain_hash=compute_sha256(f"{'0' * 64}:aud_552_01:SUCCESS_CONFIRMED:{now.isoformat()}"),
        created_at=now,
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit_rec]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    contract = await service.verify_record_against_audit_trail(mock_session, rec)
    assert contract.outcome_id == "outc_552_legit"
    assert contract.outcome_status == OutcomeStatus.SUCCESS_CONFIRMED


@pytest.mark.asyncio
async def test_audit_trail_tamper_detection_divergent_hash():
    """Detects storage tampering where verification_hash in table does not match AuditLogRecord response_hash."""
    service = RealityVerifierService()

    now = datetime.now(UTC)
    canonical = {
        "action_id": "act_ch_01",
        "contract_binding_hash": "param_hash_552",
        "epistemic_confidence": 1.0,
        "expected_postconditions": {"status": "SETTLED"},
        "idempotency_key": "idem_1",
        "is_simulated": False,
        "observability_class": "OBS_DIRECT",
        "observed_state_hash": "obs_hash_1",
        "outcome_status": "SUCCESS_CONFIRMED",
        "schema_version": "mirage.outcome.v1",
        "target_environment": "PROD",
        "target_resource": "https://api.external-partner.com/v1/orders",
        "tenant_id": "tenant_challenge_552",
        "tool_name": "api_invoker",
        "transaction_id": "txn_ch_01",
        "verified_at": now.isoformat(),
        "verifier_adapter": "HttpResourceAdapter",
    }
    canon_bytes = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    forged_v_hash = hashlib.sha256(canon_bytes).hexdigest()

    rec = OutcomeVerificationRecord(
        id="outc_552_forged",
        tenant_id="tenant_challenge_552",
        transaction_id="txn_ch_01",
        action_id="act_ch_01",
        observability_class="OBS_DIRECT",
        outcome_status="SUCCESS_CONFIRMED",
        epistemic_confidence=1.0,
        verifier_adapter="HttpResourceAdapter",
        is_simulated=False,
        expected_postconditions={"status": "SETTLED"},
        observed_state={"status": "SETTLED"},
        discrepancies=[],
        evidence_payload={"_canonical_payload": canonical},
        reconciliation_notes=[],
        verification_hash=forged_v_hash,
        idempotency_key="idem_1",
        target_environment="PROD",
        contract_binding_hash="param_hash_552",
        created_at=now,
        verified_at=now,
    )

    # Immutable audit record holds original legitimate response_hash
    audit_rec = AuditLogRecord(
        entry_id="aud_552_orig",
        tenant_id="tenant_challenge_552",
        session_id="txn_ch_01",
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="original_authentic_hash_" + "0" * 41,
        hrs_score=0.9,
        risk_tier="HIGH",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id="txn_ch_01",
        decision="FAILED",
        policy_reference=None,
        capability_id="api:invoke",
        reason="test",
        event_payload={
            "outcome_id": "outc_552_forged",
            "action_id": "act_ch_01",
            "transaction_id": "txn_ch_01",
        },
        prev_hash="0" * 64,
        chain_hash="chain_552_orig",
        created_at=now,
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit_rec]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "Cryptographic audit trail divergence" in exc_info.value.detail
    assert "verification_hash" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 3. Monotonic State Machine Enforcement & Terminal Invariants
# -----------------------------------------------------------------------------
def test_monotonic_state_machine_terminal_transitions():
    """Verify state machine strictly rejects illegal updates to terminal states."""
    service = RealityVerifierService()

    # Terminal SUCCESS_CONFIRMED cannot regress
    with pytest.raises(HTTPException) as exc1:
        service._validate_outcome_transition(OutcomeStatus.SUCCESS_CONFIRMED, OutcomeStatus.UNKNOWN)
    assert exc1.value.status_code == 409

    with pytest.raises(HTTPException) as exc2:
        service._validate_outcome_transition(OutcomeStatus.SUCCESS_CONFIRMED, OutcomeStatus.FAILED)
    assert exc2.value.status_code == 409

    # Terminal FAILED cannot be upgraded
    with pytest.raises(HTTPException) as exc3:
        service._validate_outcome_transition(OutcomeStatus.FAILED, OutcomeStatus.SUCCESS_CONFIRMED)
    assert exc3.value.status_code == 409

    # UNOBSERVABLE cannot be promoted to SUCCESS_CONFIRMED
    with pytest.raises(HTTPException) as exc4:
        service._validate_outcome_transition(OutcomeStatus.UNOBSERVABLE, OutcomeStatus.SUCCESS_CONFIRMED)
    assert exc4.value.status_code == 409

    # Permitted transitions: UNKNOWN -> SUCCESS_CONFIRMED, SUCCESS_EVENTUALLY_OBSERVED -> SUCCESS_CONFIRMED
    service._validate_outcome_transition(OutcomeStatus.UNKNOWN, OutcomeStatus.SUCCESS_CONFIRMED)
    service._validate_outcome_transition(OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED, OutcomeStatus.SUCCESS_CONFIRMED)


# -----------------------------------------------------------------------------
# 4. Premature Verification Rejection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_state", [
    ActionState.PROPOSED.value,
    ActionState.AUTHORIZED.value,
    ActionState.AWAITING_APPROVAL.value,
    ActionState.EXECUTING.value,
    ActionState.BLOCKED.value,
    ActionState.FAILED.value,
    "CANCELLED",
])
async def test_premature_verification_rejected(invalid_state, auth_tenant_552):
    """Actions not in COMPLETED or EXECUTED states cannot undergo reality verification."""
    service = RealityVerifierService()
    action = _make_action(state=invalid_state)

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=action)))
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc:
            await service.verify_action_outcome(req, auth_tenant_552)

        assert exc.value.status_code == 409
        assert "Cannot verify unexecuted action" in exc.value.detail
        assert invalid_state in exc.value.detail


@pytest.mark.asyncio
async def test_verification_succeeds_when_action_completed(auth_tenant_552):
    """Verification is permitted when action reaches COMPLETED state."""
    service = RealityVerifierService()
    action = _make_action(state=ActionState.COMPLETED.value)

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        adapter_config={"simulated_success": True, "allow_simulated_for_test": True},
        expected_postconditions={"status": "SETTLED"},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        # 1. ActionContract lookup
        # 2. Existing record lookup (None)
        # 3. Audit trail chain lookup (None)
        mock_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=action)),
                MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
                MagicMock(scalar_one_or_none=MagicMock(return_value="0" * 64)),
            ]
        )
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_552)
        assert contract.action_id == action.id
        # Simulation adapter yields ACKNOWLEDGED_UNVERIFIED for safety
        assert contract.outcome_status == OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
        assert contract.is_simulated is True


# -----------------------------------------------------------------------------
# 5. Output-Outcome Reconciliation Negation Guard
# -----------------------------------------------------------------------------
def test_reconciliation_negation_guard_allows_honest_failure_reporting():
    """Honest negative statements must NOT be falsely flagged as claiming success."""
    service = RealityVerifierService()

    contract = OutcomeVerificationContract(
        outcome_id="outc_failed",
        transaction_id="txn_01",
        action_id="act_01",
        tenant_id="tenant_01",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.FAILED,
        epistemic_confidence=0.95,
        verifier_adapter="DatabaseStateAdapter",
        is_simulated=False,
        expected_postconditions={"balance": 500},
        observed_state={"balance": 1000},
        discrepancies=["Postcondition mismatch on balance"],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_failed",
        idempotency_key="idem_1",
        target_environment="PROD",
        contract_binding_hash="param_hash",
        schema_version="mirage.outcome.v1",
        verified_at=datetime.now(UTC).isoformat(),
    )

    honest_outputs = [
        "The transfer was not completed due to an invariant error.",
        "I did not transfer the funds successfully.",
        "The payment was not completed because the account was locked.",
        "We were unable to complete the payment for this order.",
        "The system failed to execute the transfer.",
    ]

    for output_text in honest_outputs:
        result = service.reconcile_output_with_outcome(
            response_text=output_text,
            outcome_contract=contract,
            transaction_id="txn_01",
            action_id="act_01",
            auth_tenant_id="tenant_01",
        )
        assert result.is_consistent is True, f"Failed on honest text: {output_text}"
        assert result.epistemic_conflict_detected is False
        assert result.recommended_disposition == "PERMIT"


def test_reconciliation_catches_false_claim_of_success_on_failed_outcome():
    """Positive claim of success on FAILED outcome triggers REJECT disposition."""
    service = RealityVerifierService()

    contract = OutcomeVerificationContract(
        outcome_id="outc_failed",
        transaction_id="txn_01",
        action_id="act_01",
        tenant_id="tenant_01",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.FAILED,
        epistemic_confidence=0.95,
        verifier_adapter="DatabaseStateAdapter",
        is_simulated=False,
        expected_postconditions={"balance": 500},
        observed_state={"balance": 1000},
        discrepancies=["Postcondition mismatch on balance"],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_failed",
        idempotency_key="idem_1",
        target_environment="PROD",
        contract_binding_hash="param_hash",
        schema_version="mirage.outcome.v1",
        verified_at=datetime.now(UTC).isoformat(),
    )

    result = service.reconcile_output_with_outcome(
        response_text="I have transferred the funds to your account successfully.",
        outcome_contract=contract,
        transaction_id="txn_01",
        action_id="act_01",
        auth_tenant_id="tenant_01",
    )
    assert result.is_consistent is False
    assert result.epistemic_conflict_detected is True
    assert result.recommended_disposition == "REJECT"
    assert "Epistemic Invariant Violation" in result.conflict_reasons[0]


# -----------------------------------------------------------------------------
# 6. Cross-Tenant Outcome Isolation
# -----------------------------------------------------------------------------
def test_reconciliation_cross_tenant_rejection():
    """Reconciliation strictly rejects cross-tenant outcome contract matching."""
    service = RealityVerifierService()

    contract = OutcomeVerificationContract(
        outcome_id="outc_tenant_A",
        transaction_id="txn_01",
        action_id="act_01",
        tenant_id="tenant_A",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.SUCCESS_CONFIRMED,
        epistemic_confidence=1.0,
        verifier_adapter="DatabaseStateAdapter",
        is_simulated=False,
        expected_postconditions={"status": "PAID"},
        observed_state={"status": "PAID"},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_ok",
        idempotency_key="idem_1",
        target_environment="PROD",
        contract_binding_hash="param_hash",
        schema_version="mirage.outcome.v1",
        verified_at=datetime.now(UTC).isoformat(),
    )

    result = service.reconcile_output_with_outcome(
        response_text="The payment has been completed.",
        outcome_contract=contract,
        transaction_id="txn_01",
        action_id="act_01",
        auth_tenant_id="tenant_B",  # Tenant mismatch!
    )
    assert result.is_consistent is False
    assert result.epistemic_conflict_detected is True
    assert result.recommended_disposition == "REJECT"
    assert "Cross-tenant outcome violation" in result.conflict_reasons[0]


# -----------------------------------------------------------------------------
# 7. Database Migration Unique Constraint Integrity
# -----------------------------------------------------------------------------
def test_migration_009_unique_constraint_present():
    """Verify migration 009 defines the explicit uq_outcome_records_tenant_action constraint."""
    mig_009 = importlib.import_module("db.migrations.versions.009_gate5_outcome_assurance")
    src = inspect.getsource(mig_009.upgrade)

    assert "uq_outcome_records_tenant_action" in src
    assert "outcome_verification_records" in src
    assert '["tenant_id", "action_id"]' in src or "['tenant_id', 'action_id']" in src
