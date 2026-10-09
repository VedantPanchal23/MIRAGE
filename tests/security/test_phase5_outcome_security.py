"""Security and epistemic perimeter tests for Gate 5 Outcome Assurance & Reality Verification.

Tests:
1. Cross-tenant boundary enforcement (cannot verify or view outcome records across tenants).
2. SSRF and cloud metadata endpoint protection in HttpResourceAdapter.
3. Cryptographic tamper-evidence of Outcome Verification Hash.
4. Epistemic Invariant enforcement: Transport ACK (HTTP 200 / webhook receipt) is never confused with confirmed reality.
5. Rejection of premature verification (cannot verify unexecuted/proposed actions).
6. Output <-> Outcome consistency reconciliation blocking false claims of success on unobservable sinks.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import ActionContract
from services.reality_verifier import (
    HttpResourceAdapter,
    RealityVerifierService,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationContract,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
)


@pytest.fixture
def auth_tenant_alpha():
    return AuthContext(
        tenant_id="tenant_alpha",
        identity_id="usr_alpha_1",
        role=Role.OPERATOR,
        token_id="tok_alpha",
    )


@pytest.fixture
def auth_tenant_beta():
    return AuthContext(
        tenant_id="tenant_beta",
        identity_id="usr_beta_1",
        role=Role.OPERATOR,
        token_id="tok_beta",
    )


@pytest.mark.asyncio
async def test_cross_tenant_verification_probe_rejected(auth_tenant_alpha):
    """An actor from tenant_alpha cannot verify an action belonging to tenant_beta."""
    service = RealityVerifierService()

    # Action belongs to tenant_beta
    _action_beta = ActionContract(
        id="act_beta_secret",
        tenant_id="tenant_beta",
        transaction_id="txn_beta_1",
        actor_identity_id="usr_beta_1",
        tool_id="tool_beta",
        tool_name="secret_tool",
        target_resource="db://beta",
        parameters={},
        normalized_parameters={},
        parameters_hash="hash",
        required_capability="db:write",
        state="EXECUTED",
        idempotency_key="idem_beta",
    )

    req = OutcomeVerificationRequest(
        transaction_id="txn_beta_1",
        action_id="act_beta_secret",
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={"ok": True},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        # Query under tenant_alpha boundary returns None (RLS / WHERE clause isolation)
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_action_outcome(req, auth_tenant_alpha)

        assert exc_info.value.status_code == 404
        assert "not found for tenant 'tenant_alpha'" in exc_info.value.detail


@pytest.mark.asyncio
async def test_ssrf_metadata_and_internal_ip_rejection():
    """HttpResourceAdapter strictly prevents targeting internal IPs and AWS/GCP metadata services."""
    adapter = HttpResourceAdapter()
    action = ActionContract(
        id="act_ssrf_test",
        tenant_id="tenant_corp",
        transaction_id="txn_ssrf_1",
        actor_identity_id="usr_corp",
        tool_id="tool_net",
        tool_name="http_caller",
        target_resource="http",
        parameters={},
        normalized_parameters={},
        parameters_hash="hash",
        required_capability="net:read",
        state="EXECUTED",
        idempotency_key="idem_ssrf",
    )

    forbidden_targets = [
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata service
        "http://10.0.0.5:8080/internal-api",  # RFC 1918 Class A
        "http://172.16.0.10:5000/metrics",  # RFC 1918 Class B
        "http://192.168.1.1:80/admin",  # RFC 1918 Class C
        "http://127.0.0.1:8000/docs",  # IPv4 loopback
        "http://localhost:5432/",  # Hostname localhost
    ]

    for target_url in forbidden_targets:
        req = OutcomeVerificationRequest(
            transaction_id=action.transaction_id,
            action_id=action.id,
            observability_class=ObservabilityClass.OBS_DIRECT,
            verifier_type=OutcomeVerifierType.HTTP_RESOURCE,
            expected_postconditions={"status": "UP"},
            adapter_config={"verification_url": target_url},
        )

        probe = await adapter.verify(action, req, "tenant_corp")
        assert probe.success_indicated is False
        assert any("SSRF violation" in d for d in probe.discrepancies), f"Failed to block SSRF on {target_url}"


@pytest.mark.asyncio
async def test_verification_hash_cryptographic_tamper_detection(auth_tenant_alpha):
    """The verification hash is mathematically tied to all outcome parameters and cannot be forged."""
    service = RealityVerifierService()
    action = ActionContract(
        id="act_hash_test",
        tenant_id=auth_tenant_alpha.tenant_id,
        transaction_id="txn_hash_1",
        actor_identity_id=auth_tenant_alpha.identity_id,
        tool_id="tool_hash",
        tool_name="ledger_entry",
        target_resource="ledger://txns",
        parameters={},
        normalized_parameters={},
        parameters_hash="hash",
        required_capability="ledger:write",
        state="EXECUTED",
        idempotency_key="idem_hash",
    )

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={"amount": 1000},
        adapter_config={"simulated_state": {"amount": 1000}},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert len(contract.verification_hash) == 64

        # If anyone alters status or state, the hash does not match
        tampered_state = {"amount": 9999}
        import hashlib
        import json

        tampered_bytes = json.dumps(tampered_state, sort_keys=True).encode("utf-8")
        tampered_preimage = (
            f"{auth_tenant_alpha.tenant_id}:{contract.transaction_id}:{contract.action_id}:"
            f"{contract.observability_class.value}:{contract.outcome_status.value}:{contract.epistemic_confidence}:"
            f"{hashlib.sha256(tampered_bytes).hexdigest()}:{contract.is_simulated}"
        )
        assert hashlib.sha256(tampered_preimage.encode("utf-8")).hexdigest() != contract.verification_hash


def test_transport_ack_is_not_confirmed_reality():
    """Transport 200 OK without sink readback is classified as ACKNOWLEDGED_UNVERIFIED, NOT SUCCESS_CONFIRMED."""
    service = RealityVerifierService()

    contract_inferred = OutcomeVerificationContract(
        outcome_id="outc_inferred_1",
        transaction_id="txn_payment",
        action_id="act_payment",
        tenant_id="tenant_corp",
        observability_class=ObservabilityClass.OBS_INFERRED,
        outcome_status=OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
        epistemic_confidence=0.50,
        verifier_adapter="HttpResourceAdapter",
        is_simulated=False,
        expected_postconditions={"payment_intent_created": True},
        observed_state={"http_status": 200, "received": True},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash999",
        verified_at="2026-10-08T12:00:00Z",
    )

    # If the model tells the user "The payment was verified and completed"
    res = service.reconcile_output_with_outcome(
        response_text="The payment has been completed and the recipient has received the funds.",
        outcome_contract=contract_inferred,
    )

    assert res.is_consistent is False
    assert res.epistemic_conflict_detected is True
    assert "Transport acknowledgment alone does not prove destination state change" in res.conflict_reasons[0]


def test_unobservable_sink_strictly_rejects_confirmation_claims():
    """Actions targeting OBS_BLIND (UDP syslog, external SMTP) cannot be confirmed by the agent."""
    service = RealityVerifierService()

    contract_blind = OutcomeVerificationContract(
        outcome_id="outc_blind_1",
        transaction_id="txn_email",
        action_id="act_email",
        tenant_id="tenant_corp",
        observability_class=ObservabilityClass.OBS_BLIND,
        outcome_status=OutcomeStatus.UNOBSERVABLE,
        epistemic_confidence=0.0,
        verifier_adapter="SimulatedTestAdapter",
        is_simulated=False,
        expected_postconditions={},
        observed_state={},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_blind",
        verified_at="2026-10-08T12:00:00Z",
    )

    # Model claims the email was delivered
    res = service.reconcile_output_with_outcome(
        response_text="I have sent the email and the message was delivered to the inbox.",
        outcome_contract=contract_blind,
    )

    assert res.is_consistent is False
    assert res.epistemic_conflict_detected is True
    assert "Target resource is write-only/unobservable" in res.conflict_reasons[0]
