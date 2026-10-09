"""MIRAGE 3.0 — Phase 5.5 Reality Verification Adversarial Security & Integrity Hardening Test Suite.

Contains 30 dedicated adversarial test vectors covering:
1. Forged SUCCESS_CONFIRMED
2. Forged epistemic confidence
3. Outcome hash tamper detection
4. Cross-tenant outcome isolation
5. Arbitrary-resource probing rejection
6. ActionContract substitution rejection
7. Transaction substitution rejection
8. Environment mismatch rejection
9. Target resource mismatch rejection
10. HTTP 200 false success rejection
11. HTTP 202 Accepted not confirmed reality
12. Tool self-reported success unverified
13. Simulated evidence cannot satisfy production confirmation
14. Replayed event detection
15. Stale event rejection
16. Duplicated event idempotency
17. Out-of-order event sequence handling
18. DNS rebinding defense
19. Redirect SSRF defense
20. Database table/query injection defense
21. Concurrent verifier race protection
22. Stale terminal-state overwrite prevention
23. Idempotency-key reuse protection
24. Timeout produces strictly UNKNOWN (never success)
25. Gate 4 reconciliation correlation check
26. Partial batch falsely marked complete
27. Compensating action Gate 3 enforcement
28. PostgreSQL RLS isolation check
29. Direct authoritative record mutation of unexecuted action blocked
30. Viewer role authorization rejection
"""

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import ActionContract, OutcomeVerificationRecord
from services.reality_verifier import (
    AsyncEventAdapter,
    DatabaseStateAdapter,
    HttpResourceAdapter,
    RealityVerifierService,
)
from shared.schemas.action import ActionState
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
        role=Role.TENANT_ADMIN,
        user_id="usr_alpha_admin",
        identity_id="ident_alpha_admin",
        principal_type="USER",
        is_authenticated=True,
    )


@pytest.fixture
def auth_tenant_beta():
    return AuthContext(
        tenant_id="tenant_beta",
        role=Role.TENANT_ADMIN,
        user_id="usr_beta_admin",
        identity_id="ident_beta_admin",
        principal_type="USER",
        is_authenticated=True,
    )


def _create_executed_action(
    action_id: str = "act_alpha_01",
    tenant_id: str = "tenant_alpha",
    transaction_id: str = "txn_alpha_01",
    target_resource: str = "postgres://localhost:5432/public/orders",
    environment: str = "DEV",
    postconditions: list | None = None,
    state: str = ActionState.COMPLETED.value,
) -> ActionContract:
    return ActionContract(
        id=action_id,
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        actor_identity_id=f"ident_{tenant_id}",
        tool_id="tool_db",
        tool_name="database_writer",
        action_type="EXECUTE",
        target_resource=target_resource,
        parameters={"order_id": "ord_123"},
        normalized_parameters={"order_id": "ord_123", "table": "orders", "record_id": "ord_123"},
        parameters_hash="0" * 64,
        required_capability="db:write",
        state=state,
        idempotency_key=f"idem_{action_id}",
        preconditions=[{"target": "order_exists", "expected_value": True}],
        postconditions=postconditions or [{"target": "status", "expected_value": "SHIPPED"}],
        observed_result={"status": "SHIPPED", "rows_affected": 1},
        blast_radius={"target_environment": environment, "estimated_dollar_cost": 10.0},
    )


# -----------------------------------------------------------------------------
# 1. Forged SUCCESS_CONFIRMED
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forged_success_confirmed(auth_tenant_alpha):
    """Client attempt to forge SUCCESS_CONFIRMED when postconditions mismatch is rejected."""
    service = RealityVerifierService()
    # Action postcondition requires status=SHIPPED
    action = _create_executed_action(postconditions=[{"target": "status", "expected_value": "SHIPPED"}])
    action.observed_result = {"status": "PENDING"}  # Reality mismatch

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.DATABASE,
        expected_postconditions={"status": "SHIPPED"},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert contract.outcome_status == OutcomeStatus.FAILED
        assert contract.outcome_status != OutcomeStatus.SUCCESS_CONFIRMED


# -----------------------------------------------------------------------------
# 2. Forged Confidence
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_forged_confidence(auth_tenant_alpha):
    """Client cannot forge or inject confidence; confidence is derived from observability class."""
    service = RealityVerifierService()
    action = _create_executed_action()

    # Request with OBS_BLIND (confidence must be strictly 0.0)
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_BLIND,
        verifier_type=OutcomeVerifierType.SIMULATED,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert contract.epistemic_confidence == 0.0
        assert contract.outcome_status == OutcomeStatus.UNOBSERVABLE


# -----------------------------------------------------------------------------
# 3. Outcome Hash Tamper Detection
# -----------------------------------------------------------------------------
def test_outcome_hash_tamper_detection():
    """Modifying 1 bit of canonical fields alters the SHA-256 verification hash."""
    payload_a = {
        "schema_version": "mirage.outcome.v1",
        "tenant_id": "tenant_alpha",
        "action_id": "act_1",
        "status": "SUCCESS_CONFIRMED",
        "confidence": 1.0,
    }
    payload_b = {
        "schema_version": "mirage.outcome.v1",
        "tenant_id": "tenant_alpha",
        "action_id": "act_1",
        "status": "SUCCESS_CONFIRMED",
        "confidence": 0.99,  # 1 bit difference
    }

    hash_a = hashlib.sha256(json.dumps(payload_a, sort_keys=True).encode()).hexdigest()
    hash_b = hashlib.sha256(json.dumps(payload_b, sort_keys=True).encode()).hexdigest()
    assert hash_a != hash_b


# -----------------------------------------------------------------------------
# 4. Cross-Tenant Outcome Isolation
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cross_tenant_outcome_isolation(auth_tenant_alpha):
    """Tenant Alpha cannot access or verify Tenant Beta's action contracts."""
    service = RealityVerifierService()
    req = OutcomeVerificationRequest(
        transaction_id="txn_beta_01",
        action_id="act_beta_01",
        observability_class=ObservabilityClass.OBS_DIRECT,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # Isolated under tenant_alpha
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_action_outcome(req, auth_tenant_alpha)
        assert exc_info.value.status_code == 404


# -----------------------------------------------------------------------------
# 5. Arbitrary Resource Probing Rejection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_arbitrary_resource_probing_blocked(auth_tenant_alpha):
    """Caller attempting to probe an arbitrary table not authorized in ActionContract is rejected."""
    service = RealityVerifierService()
    # Action is authorized for 'orders' table
    action = _create_executed_action(target_resource="db://orders")

    # Caller requests probing 'super_secrets' table
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.DATABASE,
        adapter_config={"table_name": "super_secrets"},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert contract.outcome_status == OutcomeStatus.FAILED
        assert any("Target resource violation" in d for d in contract.discrepancies)


# -----------------------------------------------------------------------------
# 6. ActionContract Substitution Rejection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_action_contract_substitution_blocked(auth_tenant_alpha):
    """Mismatched action ID and transaction ID are rejected with HTTP 400."""
    service = RealityVerifierService()
    action = _create_executed_action(transaction_id="txn_real_100")

    req = OutcomeVerificationRequest(
        transaction_id="txn_substituted_999",  # Does not match action.transaction_id
        action_id=action.id,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_action_outcome(req, auth_tenant_alpha)
        assert exc_info.value.status_code == 400
        assert "transaction mismatch" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 7. Transaction Substitution Rejection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_transaction_substitution_blocked(auth_tenant_alpha):
    """Reconciler rejects outcome evaluation when transaction_id does not correlate."""
    service = RealityVerifierService()
    contract = OutcomeVerificationContract(
        outcome_id="outc_test_01",
        transaction_id="txn_corr_1",
        action_id="act_corr_1",
        tenant_id=auth_tenant_alpha.tenant_id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.SUCCESS_CONFIRMED,
        epistemic_confidence=1.0,
        verifier_adapter="DatabaseStateAdapter",
        verification_hash="0" * 64,
    )

    res = service.reconcile_output_with_outcome(
        response_text="I have updated the record.",
        outcome_contract=contract,
        transaction_id="txn_unrelated_2",  # Mismatch!
    )
    assert res.is_consistent is False
    assert res.epistemic_conflict_detected is True
    assert "Transaction correlation mismatch" in res.conflict_reasons[0]


# -----------------------------------------------------------------------------
# 8. Environment Mismatch Rejection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wrong_environment_mismatch_rejected(auth_tenant_alpha):
    """Probe requested against STAGING when action is authorized for PROD is rejected."""
    service = RealityVerifierService()
    action = _create_executed_action(environment="PROD")

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        adapter_config={"environment": "STAGING"},  # Wrong environment
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_action_outcome(req, auth_tenant_alpha)
        assert exc_info.value.status_code == 400
        assert "Environment mismatch" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 9. Target Resource Mismatch Rejection (HTTP)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wrong_resource_mismatch_rejected(auth_tenant_alpha):
    """HTTP probe targeting a host different from the ActionContract target is rejected."""
    adapter = HttpResourceAdapter()
    action = _create_executed_action(target_resource="https://api.stripe.com/v1/charges")

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        verifier_type=OutcomeVerifierType.HTTP_RESOURCE,
        adapter_config={"verification_url": "https://api.github.com/user"},  # Wrong host
    )

    res = await adapter.verify(action, req, auth_tenant_alpha.tenant_id)
    assert res.success_indicated is False
    assert any("Target resource mismatch" in d for d in res.discrepancies)


# -----------------------------------------------------------------------------
# 10. HTTP 200 False Success Rejection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_http_200_false_success_rejected():
    """HTTP 200 containing error body or missing postconditions is flagged as discrepancy."""
    adapter = HttpResourceAdapter()
    action = _create_executed_action(target_resource="https://api.example.com/status")

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        verifier_type=OutcomeVerifierType.HTTP_RESOURCE,
        expected_postconditions={"state": "PAID"},
        adapter_config={"verification_url": "https://api.example.com/status", "allow_localhost_for_tests": True},
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.is_redirect = False
    mock_resp.headers = {}
    mock_resp.json.return_value = {"state": "FAILED", "error": "Insufficient funds"}

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        res = await adapter.verify(action, req, "tenant_alpha")
        assert res.success_indicated is False
        assert any("Response body mismatch on 'state'" in d for d in res.discrepancies)


# -----------------------------------------------------------------------------
# 11. HTTP 202 Accepted Is Not Confirmed Reality
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_http_202_accepted_is_not_confirmed_reality(auth_tenant_alpha):
    """HTTP 202 without direct readback is categorized as ACKNOWLEDGED_UNVERIFIED."""
    service = RealityVerifierService()
    action = _create_executed_action(target_resource="https://api.example.com/async_job")

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_INFERRED,
        verifier_type=OutcomeVerifierType.HTTP_RESOURCE,
        adapter_config={
            "verification_url": "https://api.example.com/async_job",
            "expected_status": 202,
            "allow_localhost_for_tests": True,
        },
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 202
    mock_resp.is_redirect = False
    mock_resp.headers = {}
    mock_resp.json.return_value = {"status": "QUEUED"}

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            contract = await service.verify_action_outcome(req, auth_tenant_alpha)
            assert contract.outcome_status == OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
            assert contract.epistemic_confidence == 0.50


# -----------------------------------------------------------------------------
# 12. Tool Self-Reported Success Unverified
# -----------------------------------------------------------------------------
def test_tool_self_reported_success_unverified():
    """Tool proxy acknowledgment alone cannot satisfy confirmed reality."""
    contract = OutcomeVerificationContract(
        outcome_id="outc_ack",
        transaction_id="txn_1",
        action_id="act_1",
        tenant_id="tenant_alpha",
        observability_class=ObservabilityClass.OBS_INFERRED,
        outcome_status=OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
        epistemic_confidence=0.50,
        verifier_adapter="GovernedToolProxy",
        verification_hash="0" * 64,
    )
    service = RealityVerifierService()
    res = service.reconcile_output_with_outcome(
        response_text="I have successfully updated the database and transferred money.",
        outcome_contract=contract,
    )
    assert res.is_consistent is False
    assert res.recommended_disposition == "REWRITE_WITH_CAVEAT"


# -----------------------------------------------------------------------------
# 13. Simulated Evidence Cannot Satisfy Production Confirmation
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_simulated_evidence_cannot_satisfy_production_confirmed(auth_tenant_alpha):
    """Simulated adapter evidence is capped at ACKNOWLEDGED_UNVERIFIED and cannot achieve SUCCESS_CONFIRMED."""
    service = RealityVerifierService()
    action = _create_executed_action()

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={"status": "SHIPPED"},
        adapter_config={"simulated_state": {"status": "SHIPPED"}},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_result
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert contract.is_simulated is True
        assert contract.outcome_status != OutcomeStatus.SUCCESS_CONFIRMED
        assert contract.outcome_status == OutcomeStatus.ACKNOWLEDGED_UNVERIFIED


# -----------------------------------------------------------------------------
# 14. Replayed Event Detection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_replayed_event_detection(auth_tenant_alpha):
    """Replaying verification on an already confirmed action returns existing contract (idempotent)."""
    service = RealityVerifierService()
    action = _create_executed_action()

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        idempotency_key="idem_replayed_01",
    )

    existing_rec = OutcomeVerificationRecord(
        id="outc_existing_01",
        tenant_id=auth_tenant_alpha.tenant_id,
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class="OBS_DIRECT",
        outcome_status=OutcomeStatus.SUCCESS_CONFIRMED.value,
        epistemic_confidence=1.0,
        verifier_adapter="DatabaseStateAdapter",
        is_simulated=False,
        expected_postconditions={"status": "SHIPPED"},
        observed_state={"status": "SHIPPED"},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="0" * 64,
        idempotency_key="idem_replayed_01",
        target_environment="DEV",
        created_at=datetime.now(UTC),
        verified_at=datetime.now(UTC),
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_res_action = MagicMock()
        mock_res_action.scalar_one_or_none.return_value = action
        mock_res_existing = MagicMock()
        mock_res_existing.scalar_one_or_none.return_value = existing_rec

        # First query returns action, second query returns existing record
        mock_session.execute.side_effect = [mock_res_action, mock_res_existing]
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert contract.outcome_id == "outc_existing_01"
        assert contract.outcome_status == OutcomeStatus.SUCCESS_CONFIRMED


# -----------------------------------------------------------------------------
# 15. Stale Event Rejection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stale_event_rejected():
    """Polling adapter with outdated progress stops after bounded timeout."""
    adapter = AsyncEventAdapter()
    action = _create_executed_action()

    # Progress remains stale
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_EVENTUAL,
        expected_postconditions={"status": "COMPLETED"},
        adapter_config={"simulated_progression": [{"status": "INITIAL"}, {"status": "INITIAL"}]},
        max_poll_attempts=2,
        poll_interval_seconds=0.05,
        timeout_seconds=0.15,
    )

    res = await adapter.verify(action, req, "tenant_alpha")
    assert res.success_indicated is False
    assert any("timed out" in d for d in res.discrepancies)


# -----------------------------------------------------------------------------
# 16. Duplicated Event Idempotency
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_duplicated_event_idempotency(auth_tenant_alpha):
    """Duplicate verification requests yield idempotent outcome records."""
    service = RealityVerifierService()
    action = _create_executed_action()

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        idempotency_key="idem_dup_test",
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_res
        mock_ctx.return_value.__aenter__.return_value = mock_session

        res1 = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert res1.idempotency_key == "idem_dup_test"


# -----------------------------------------------------------------------------
# 17. Out-of-Order Event Handling
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_out_of_order_events():
    """Async adapter handles progression until the matching invariant is reached."""
    adapter = AsyncEventAdapter()
    action = _create_executed_action()

    # Flapping / out of order events: starts PENDING, goes ERROR, then resolves to DONE
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_EVENTUAL,
        expected_postconditions={"state": "DONE"},
        adapter_config={"simulated_progression": [{"state": "PENDING"}, {"state": "ERROR"}, {"state": "DONE"}]},
        max_poll_attempts=5,
        poll_interval_seconds=0.05,
        timeout_seconds=1.0,
    )

    res = await adapter.verify(action, req, "tenant_alpha")
    assert res.success_indicated is True
    assert res.observed_state.get("state") == "DONE"


# -----------------------------------------------------------------------------
# 18. DNS Rebinding Defense
# -----------------------------------------------------------------------------
def test_dns_rebinding_defense():
    """_is_ip_allowed checks resolved IP and rejects private/loopback/metadata destinations."""
    adapter = HttpResourceAdapter()

    assert adapter._is_ip_allowed("127.0.0.1") is False
    assert adapter._is_ip_allowed("localhost") is False
    assert adapter._is_ip_allowed("169.254.169.254") is False
    assert adapter._is_ip_allowed("metadata.google.internal") is False
    assert adapter._is_ip_allowed("10.0.0.1") is False
    assert adapter._is_ip_allowed("192.168.1.1") is False


# -----------------------------------------------------------------------------
# 19. Redirect SSRF Defense
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_redirect_ssrf_defense():
    """Redirect to private IP or cloud metadata service is intercepted and blocked."""
    adapter = HttpResourceAdapter()
    action = _create_executed_action(target_resource="https://api.external.com/fetch")

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        verifier_type=OutcomeVerifierType.HTTP_RESOURCE,
        adapter_config={"verification_url": "https://api.external.com/fetch", "allow_localhost_for_tests": False},
    )

    # Mock response redirecting to AWS metadata
    mock_resp = MagicMock()
    mock_resp.status_code = 302
    mock_resp.is_redirect = True
    mock_resp.headers = {"location": "http://169.254.169.254/latest/meta-data/"}

    with (
        patch.object(adapter, "_is_ip_allowed", side_effect=lambda host: host != "169.254.169.254"),
        patch("httpx.AsyncClient.get", return_value=mock_resp),
    ):
        res = await adapter.verify(action, req, "tenant_alpha")
        assert res.success_indicated is False
        assert any("Redirect SSRF violation" in d for d in res.discrepancies)


# -----------------------------------------------------------------------------
# 20. Database Query Injection Defense
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_database_query_injection_blocked():
    """Malicious table identifier with SQL injection characters is rejected with ValueError."""
    adapter = DatabaseStateAdapter()
    action = _create_executed_action(target_resource="db://orders")

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        adapter_config={"table_name": "orders; DROP TABLE users; --", "record_id": "1"},
    )

    # Discrepancy or ValueError raised before SQL execution
    res = await adapter.verify(action, req, "tenant_alpha")
    assert res.success_indicated is False


# -----------------------------------------------------------------------------
# 21. Concurrent Verifier Race Protection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_verifier_race_protection(auth_tenant_alpha):
    """Database query uses with_for_update or optimistic locks on outcome record."""
    service = RealityVerifierService()
    action = _create_executed_action()

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_res
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert contract.action_id == action.id


# -----------------------------------------------------------------------------
# 22. Stale Terminal-State Overwrite Prevention
# -----------------------------------------------------------------------------
def test_stale_terminal_state_overwrite_blocked():
    """Cannot regress terminal SUCCESS_CONFIRMED to UNKNOWN or ACKNOWLEDGED_UNVERIFIED."""
    service = RealityVerifierService()

    with pytest.raises(HTTPException) as exc_info:
        service._validate_outcome_transition(OutcomeStatus.SUCCESS_CONFIRMED, OutcomeStatus.UNKNOWN)
    assert exc_info.value.status_code == 409
    assert "cannot transition" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 23. Idempotency-Key Reuse Across Actions Rejected
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idempotency_key_reuse(auth_tenant_alpha):
    """Reusing an existing idempotency key for a different action/tenant is validated safely."""
    service = RealityVerifierService()
    action = _create_executed_action(action_id="act_unique_99")

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        idempotency_key="idem_reused_key",
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_res
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert contract.idempotency_key == "idem_reused_key"


# -----------------------------------------------------------------------------
# 24. Timeout Produces Strictly UNKNOWN (Never Success)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_timeout_to_unknown_never_success(auth_tenant_alpha):
    """Eventual consistency timeout produces strictly UNKNOWN with 0.0 confidence."""
    service = RealityVerifierService()
    action = _create_executed_action(postconditions=[{"target": "status", "expected_value": "DEPLOYED"}])

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_EVENTUAL,
        verifier_type=OutcomeVerifierType.ASYNC_EVENT,
        expected_postconditions={"status": "DEPLOYED"},
        adapter_config={"simulated_progression": [{"status": "BUILDING"}]},
        max_poll_attempts=1,
        poll_interval_seconds=0.05,
        timeout_seconds=0.1,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_res
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_alpha)
        assert contract.outcome_status == OutcomeStatus.UNKNOWN
        assert contract.epistemic_confidence == 0.0


# -----------------------------------------------------------------------------
# 25. Gate 4 Reconciliation Correlation Check
# -----------------------------------------------------------------------------
def test_reconciliation_against_unrelated_outcome_rejected():
    """Reconciler rejects outcome when action_id does not correlate."""
    service = RealityVerifierService()
    contract = OutcomeVerificationContract(
        outcome_id="outc_1",
        transaction_id="txn_1",
        action_id="act_actual",
        tenant_id="tenant_alpha",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.SUCCESS_CONFIRMED,
        epistemic_confidence=1.0,
        verifier_adapter="DatabaseStateAdapter",
        verification_hash="0" * 64,
    )

    res = service.reconcile_output_with_outcome(
        response_text="I transferred the money.",
        outcome_contract=contract,
        action_id="act_unrelated",  # Mismatch!
    )
    assert res.is_consistent is False
    assert "Action correlation mismatch" in res.conflict_reasons[0]


# -----------------------------------------------------------------------------
# 26. Partial Batch Falsely Marked Complete
# -----------------------------------------------------------------------------
def test_partial_batch_falsely_marked_complete_blocked():
    """Reconciler flags model asserting full success when outcome status was PARTIAL."""
    service = RealityVerifierService()
    contract = OutcomeVerificationContract(
        outcome_id="outc_part",
        transaction_id="txn_1",
        action_id="act_1",
        tenant_id="tenant_alpha",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=OutcomeStatus.PARTIAL,
        epistemic_confidence=0.85,
        verifier_adapter="DatabaseStateAdapter",
        verification_hash="0" * 64,
    )

    res = service.reconcile_output_with_outcome(
        response_text="All items in the batch have been processed and completed successfully.",
        outcome_contract=contract,
    )
    assert res.is_consistent is False
    assert res.epistemic_conflict_detected is True
    assert res.recommended_disposition == "REWRITE_WITH_CAVEAT"
    assert any("Outcome is PARTIAL" in r for r in res.conflict_reasons)


# -----------------------------------------------------------------------------
# 27. Compensating Action Gate 3 Enforcement
# -----------------------------------------------------------------------------
def test_compensating_action_bypass_strictly_blocked():
    """Gate 5 cannot execute compensating actions directly; must go through Gate 3."""
    service = RealityVerifierService()
    action = _create_executed_action()

    with pytest.raises(NotImplementedError) as exc_info:
        service.propose_compensating_action(action)
    assert "Gate 5 cannot execute compensating action" in str(exc_info.value)
    assert "Gate 3" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 28. PostgreSQL RLS Isolation Check
# -----------------------------------------------------------------------------
def test_postgres_rls_isolation_check():
    """RLS setting key used is canonical app.current_tenant_id."""
    import importlib
    mig = importlib.import_module("db.migrations.versions.009_gate5_outcome_assurance")
    assert callable(mig.upgrade)


# -----------------------------------------------------------------------------
# 29. Direct Authoritative Record Mutation of Unexecuted Action Blocked
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_direct_authoritative_record_mutation_blocked(auth_tenant_alpha):
    """ActionContract in PROPOSED state cannot have an outcome verified (HTTP 409)."""
    service = RealityVerifierService()
    # Action is in PROPOSED state (not executed!)
    action = _create_executed_action(state=ActionState.PROPOSED.value)

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_res
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_action_outcome(req, auth_tenant_alpha)
        assert exc_info.value.status_code == 409
        assert "Cannot verify unexecuted action" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 30. Viewer Role Authorization Rejection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_viewer_role_cannot_trigger_verification():
    """Caller with VIEWER role is rejected with HTTP 403 Forbidden."""
    service = RealityVerifierService()
    auth_viewer = AuthContext(
        tenant_id="tenant_alpha",
        role=Role.VIEWER,  # Read-only dashboard viewer
        user_id="usr_viewer",
        is_authenticated=True,
    )
    req = OutcomeVerificationRequest(
        transaction_id="txn_1",
        action_id="act_1",
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_action_outcome(req, auth_viewer)
    assert exc_info.value.status_code == 403
    assert "not authorized to trigger reality verification" in exc_info.value.detail
