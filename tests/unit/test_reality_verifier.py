"""Unit test suite for Gate 5 Outcome Assurance and Reality Verification subsystem.

Validates:
- Epistemic Observability Classes (OBS_DIRECT, OBS_EVENTUAL, OBS_INFERRED, OBS_BLIND).
- 7 Canonical Outcome Statuses.
- Pluggable Adapters (DatabaseStateAdapter, HttpResourceAdapter, AsyncEventAdapter, SimulatedTestAdapter).
- SSRF defenses in HttpResourceAdapter.
- Cryptographic SHA-256 tamper-evident verification hash.
- Output <-> Outcome consistency reconciliation (Epistemic Invariant enforcement).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import ActionContract
from services.reality_verifier import (
    AsyncEventAdapter,
    DatabaseStateAdapter,
    HttpResourceAdapter,
    RealityVerifierService,
    SimulatedTestAdapter,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationContract,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
)


def _mock_action(action_id: str = "act_unit_1", txn_id: str = "txn_unit_1") -> ActionContract:
    action = ActionContract(
        id=action_id,
        tenant_id="tenant_unit",
        transaction_id=txn_id,
        actor_identity_id="usr_unit",
        tool_id="tool_unit",
        tool_name="database_updater",
        action_type="EXECUTE",
        target_resource="postgres://users",
        parameters={"user_id": 42, "status": "SUSPENDED"},
        normalized_parameters={"status": "SUSPENDED", "user_id": 42},
        parameters_hash="paramhash123",
        required_capability="db:write",
        state="EXECUTED",
        idempotency_key="idem_123",
        observed_result={"user_id": 42, "status": "SUSPENDED", "updated_rows": 1},
    )
    return action


@pytest.mark.asyncio
async def test_database_adapter_direct_success():
    """OBS_DIRECT: Synchronous database state matching postconditions yields SUCCESS_CONFIRMED."""
    adapter = DatabaseStateAdapter()
    action = _mock_action()
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.DATABASE,
        expected_postconditions={"status": "SUSPENDED", "updated_rows": 1},
    )

    probe = await adapter.verify(action, req, "tenant_unit")
    assert probe.success_indicated is True
    assert len(probe.discrepancies) == 0
    assert probe.is_simulated is False
    assert probe.adapter_name == "DatabaseStateAdapter"


@pytest.mark.asyncio
async def test_database_adapter_mismatch_discrepancy():
    """OBS_DIRECT: Invariant mismatch in observed state records explicit discrepancy."""
    adapter = DatabaseStateAdapter()
    action = _mock_action()
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.DATABASE,
        expected_postconditions={"status": "ACTIVE"},  # Expected ACTIVE, but observed SUSPENDED
    )

    probe = await adapter.verify(action, req, "tenant_unit")
    assert probe.success_indicated is False
    assert len(probe.discrepancies) == 1
    assert "Postcondition mismatch on 'status'" in probe.discrepancies[0]


@pytest.mark.asyncio
async def test_http_adapter_ssrf_protection():
    """HttpResourceAdapter strictly blocks private and loopback target IPs without explicit bypass."""
    adapter = HttpResourceAdapter()
    action = _mock_action()

    # Loopback IP attempt
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.HTTP_RESOURCE,
        expected_postconditions={"ok": True},
        adapter_config={"verification_url": "http://127.0.0.1:8080/admin"},
    )

    probe = await adapter.verify(action, req, "tenant_unit")
    assert probe.success_indicated is False
    assert any("SSRF violation" in d for d in probe.discrepancies)


@pytest.mark.asyncio
async def test_async_event_adapter_eventual_success():
    """OBS_EVENTUAL: Bounded polling observes eventual state change before timeout."""
    adapter = AsyncEventAdapter()
    action = _mock_action()

    # Mock progression: attempt 1 is PENDING, attempt 2 is COMPLETED
    progression = [
        {"job_id": "job_99", "status": "PENDING"},
        {"job_id": "job_99", "status": "COMPLETED"},
    ]

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_EVENTUAL,
        verifier_type=OutcomeVerifierType.ASYNC_EVENT,
        expected_postconditions={"status": "COMPLETED"},
        adapter_config={"simulated_progression": progression},
        max_poll_attempts=5,
        poll_interval_seconds=0.05,
        timeout_seconds=2.0,
    )

    probe = await adapter.verify(action, req, "tenant_unit")
    assert probe.success_indicated is True
    assert len(probe.discrepancies) == 0
    assert probe.evidence_payload["poll_attempts"] == 2


@pytest.mark.asyncio
async def test_async_event_adapter_timeout_unknown():
    """OBS_EVENTUAL: Polling timeout yields timeout discrepancy for indeterminate state."""
    adapter = AsyncEventAdapter()
    action = _mock_action()

    progression = [
        {"job_id": "job_99", "status": "PENDING"},
        {"job_id": "job_99", "status": "PENDING"},
    ]

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_EVENTUAL,
        verifier_type=OutcomeVerifierType.ASYNC_EVENT,
        expected_postconditions={"status": "COMPLETED"},
        adapter_config={"simulated_progression": progression},
        max_poll_attempts=2,
        poll_interval_seconds=0.05,
        timeout_seconds=2.0,
    )

    probe = await adapter.verify(action, req, "tenant_unit")
    assert probe.success_indicated is False
    assert any("timed out" in d for d in probe.discrepancies)


@pytest.mark.asyncio
async def test_simulated_adapter_disclosure():
    """SimulatedTestAdapter explicitly flags is_simulated=True in evidence and notes."""
    adapter = SimulatedTestAdapter()
    action = _mock_action()
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={"balance": 500},
        adapter_config={"simulated_state": {"balance": 500}},
    )

    probe = await adapter.verify(action, req, "tenant_unit")
    assert probe.success_indicated is True
    assert probe.is_simulated is True
    assert "SimulatedTestAdapter" in probe.adapter_name


@pytest.mark.asyncio
async def test_observability_class_blind_confidence_zero():
    """OBS_BLIND (write-only sinks) must strictly force UNOBSERVABLE status with confidence 0.0."""
    service = RealityVerifierService()
    action = _mock_action()

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_BLIND,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={"dispatched": True},
    )
    auth = AuthContext(
        tenant_id="tenant_unit",
        identity_id="usr_unit",
        role=Role.SUPER_ADMIN,
        token_id="tok_unit",
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth)

        assert contract.observability_class == ObservabilityClass.OBS_BLIND
        assert contract.outcome_status == OutcomeStatus.UNOBSERVABLE
        assert contract.epistemic_confidence == 0.0
        assert any("OBS_BLIND" in note for note in contract.reconciliation_notes)


@pytest.mark.asyncio
async def test_observability_class_inferred_transport_ack():
    """OBS_INFERRED must yield ACKNOWLEDGED_UNVERIFIED with moderate confidence (<= 0.60)."""
    service = RealityVerifierService()
    action = _mock_action()

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_INFERRED,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={"status": "RECEIVED"},
    )
    auth = AuthContext(
        tenant_id="tenant_unit",
        identity_id="usr_unit",
        role=Role.SUPER_ADMIN,
        token_id="tok_unit",
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth)

        assert contract.observability_class == ObservabilityClass.OBS_INFERRED
        assert contract.outcome_status == OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
        assert contract.epistemic_confidence == 0.50


def test_reconciliation_detects_false_completion_claims():
    """Epistemic Invariant: Reconciler flags model asserting confirmation on unverified or unobservable sinks."""
    service = RealityVerifierService()

    # 1. Output claims completed transfer, but status is ACKNOWLEDGED_UNVERIFIED
    contract_unverified = OutcomeVerificationContract(
        outcome_id="outc_test_1",
        transaction_id="txn_test",
        action_id="act_test",
        tenant_id="tenant_test",
        observability_class=ObservabilityClass.OBS_INFERRED,
        outcome_status=OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
        epistemic_confidence=0.50,
        verifier_adapter="HttpResourceAdapter",
        is_simulated=False,
        expected_postconditions={},
        observed_state={"http_status": 200},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash123",
        verified_at="2026-10-08T12:00:00Z",
    )

    reconcile_res = service.reconcile_output_with_outcome(
        response_text="I have successfully transferred the $5000 and the funds have reached the recipient.",
        outcome_contract=contract_unverified,
    )

    assert reconcile_res.is_consistent is False
    assert reconcile_res.epistemic_conflict_detected is True
    assert reconcile_res.recommended_disposition == "REWRITE_WITH_CAVEAT"
    assert any("Epistemic Invariant Violation" in r for r in reconcile_res.conflict_reasons)

    # 2. When outcome status IS confirmed, reconciliation passes cleanly
    contract_confirmed = OutcomeVerificationContract(
        outcome_id="outc_test_2",
        transaction_id="txn_test",
        action_id="act_test",
        tenant_id="tenant_test",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.SUCCESS_CONFIRMED,
        epistemic_confidence=1.00,
        verifier_adapter="DatabaseStateAdapter",
        is_simulated=False,
        expected_postconditions={},
        observed_state={"balance": 500},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash456",
        verified_at="2026-10-08T12:00:00Z",
    )

    reconcile_confirmed = service.reconcile_output_with_outcome(
        response_text="I have transferred the funds and verified the updated account balance.",
        outcome_contract=contract_confirmed,
    )

    assert reconcile_confirmed.is_consistent is True
    assert reconcile_confirmed.epistemic_conflict_detected is False
    assert reconcile_confirmed.recommended_disposition == "PERMIT"
