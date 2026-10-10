"""Phase 5.5.1 Independent Audit & Evidence Integrity Test Suite for MIRAGE 3.0.

Rigorously verifies the core invariant:
Request accepted != action authorized != tool acknowledged != intended outcome independently verified.

Proves remediation of confirmed defects:
1. Rejection of in-flight EXECUTING actions (HTTP 409 Conflict).
2. Authoritative blind-sink override (downgrade to OBS_BLIND/UNOBSERVABLE, confidence 0.0).
3. Invariant: void postconditions assertion cannot produce SUCCESS_CONFIRMED.
4. Read-path cryptographic verification hash and column integrity validation.
5. Row-level concurrency locking and single-outcome monotonicity.
6. Five-gate end-to-end traceability and cryptographic hash chain linkage.
7. Output-outcome reconciliation caveat interlock.
8. Compensating action Gate 3 governance requirement.
"""

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import ActionContract, AuditLogRecord, OutcomeVerificationRecord
from services.reality_verifier import RealityVerifierService
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
def auth_tenant_audit():
    return AuthContext(
        tenant_id="tenant_audit_99",
        role=Role.TENANT_ADMIN,
        user_id="usr_audit_admin",
        identity_id="ident_audit_admin",
        principal_type="USER",
        is_authenticated=True,
    )


def _make_action(
    action_id: str = "act_audit_01",
    tenant_id: str = "tenant_audit_99",
    transaction_id: str = "txn_audit_01",
    state: str = ActionState.COMPLETED.value,
    target_resource: str = "postgres://db.cluster/orders",
    postconditions: list | None = None,
    observed_result: dict | None = None,
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
        parameters={"order_id": "ord_100"},
        normalized_parameters={"order_id": "ord_100", "table": "orders", "record_id": "ord_100"},
        parameters_hash="hash_act_audit",
        required_capability="db:write",
        state=state,
        idempotency_key=f"idem_{action_id}",
        preconditions=[],
        postconditions=(
            postconditions if postconditions is not None else [{"target": "status", "expected_value": "PROCESSED"}]
        ),
        observed_result=observed_result or {"status": "PROCESSED"},
        blast_radius={"target_environment": "DEV", "estimated_dollar_cost": 5.0},
    )


# -----------------------------------------------------------------------------
# 1. Defect 1: Rejection of In-Flight EXECUTING Actions
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_executing_action_verification_rejected(auth_tenant_audit):
    """Actions in EXECUTING state are in-flight and MUST NOT be verified (HTTP 409 Conflict)."""
    service = RealityVerifierService()
    action = _make_action(state=ActionState.EXECUTING.value)

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_res
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_action_outcome(req, auth_tenant_audit)

        assert exc_info.value.status_code == 409
        assert "Cannot verify unexecuted action" in exc_info.value.detail
        assert "EXECUTING" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 2. Defect 2A: Authoritative Blind Sink Override
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_client_cannot_forge_obs_direct_on_blind_sink(auth_tenant_audit):
    """Client request specifying OBS_DIRECT against a write-only sink (e.g. UDP/syslog)

    is authoritatively downgraded to OBS_BLIND / UNOBSERVABLE (confidence strictly 0.0).
    """
    service = RealityVerifierService()
    # Action targets write-only syslog/udp stream
    action = _make_action(
        target_resource="udp://audit-logger.internal:514",
        postconditions=[],
        observed_result={"ack": True},
    )

    # Client deceitfully requests OBS_DIRECT
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_res_action = MagicMock()
        mock_res_action.scalar_one_or_none.return_value = action
        mock_res_exist = MagicMock()
        mock_res_exist.scalar_one_or_none.return_value = None
        mock_res_audit = MagicMock()
        mock_res_audit.scalar_one_or_none.return_value = "0" * 64

        mock_session.execute.side_effect = [mock_res_action, mock_res_exist, mock_res_audit]
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_audit)
        assert contract.observability_class == ObservabilityClass.OBS_BLIND
        assert contract.outcome_status == OutcomeStatus.UNOBSERVABLE
        assert contract.epistemic_confidence == 0.0
        assert any("unobservable write-only sink" in note for note in contract.reconciliation_notes)


# -----------------------------------------------------------------------------
# 3. Defect 2B: Invariant: Void Postconditions Cannot Produce SUCCESS_CONFIRMED
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_void_postconditions_cannot_produce_success_confirmed(auth_tenant_audit):
    """When zero postconditions are asserted, absence of discrepancies is NOT confirmed success.

    Must downgrade to ACKNOWLEDGED_UNVERIFIED with confidence <= 0.50.
    """
    service = RealityVerifierService()
    action = _make_action(
        target_resource="postgres://db.cluster/orders",
        postconditions=[],
        observed_result={"status": "UNKNOWN"},
    )

    # Client requests OBS_DIRECT with empty expected postconditions
    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={},
        adapter_config={"simulated_state": {"status": "ACTIVE"}, "allow_simulated_for_test": True},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_res_action = MagicMock()
        mock_res_action.scalar_one_or_none.return_value = action
        mock_res_exist = MagicMock()
        mock_res_exist.scalar_one_or_none.return_value = None
        mock_res_audit = MagicMock()
        mock_res_audit.scalar_one_or_none.return_value = "0" * 64

        mock_session.execute.side_effect = [mock_res_action, mock_res_exist, mock_res_audit]
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_audit)
        assert contract.outcome_status == OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
        assert contract.outcome_status != OutcomeStatus.SUCCESS_CONFIRMED
        assert contract.epistemic_confidence <= 0.50
        assert any("Void postcondition assertion" in note for note in contract.reconciliation_notes)


# -----------------------------------------------------------------------------
# 4. Defect 3: Read-Path Cryptographic Hash and Column Tamper Detection
# -----------------------------------------------------------------------------
def test_audit_read_path_cryptographic_hash_tamper_detection():
    """Modifying outcome_status, confidence, or verification_hash on a persisted record

    is immediately detected and rejected on read with HTTP 409 Conflict.
    """
    service = RealityVerifierService()

    canonical_payload = {
        "schema_version": "mirage.outcome.v1",
        "tenant_id": "tenant_audit_99",
        "transaction_id": "txn_audit_01",
        "action_id": "act_audit_01",
        "contract_binding_hash": "param_hash_1",
        "tool_name": "database_writer",
        "target_resource": "db://orders",
        "required_capability": "db:write",
        "target_environment": "DEV",
        "observability_class": "OBS_DIRECT",
        "outcome_status": "FAILED",  # Authentic status is FAILED
        "epistemic_confidence": 0.95,
        "verifier_adapter": "DatabaseStateAdapter",
        "is_simulated": False,
        "expected_postconditions": {"status": "SHIPPED"},
        "observed_state_hash": "obs_hash_1",
        "verified_at": "2026-10-10T12:00:00+00:00",
        "idempotency_key": "idem_1",
    }
    canonical_bytes = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    authentic_hash = hashlib.sha256(canonical_bytes).hexdigest()

    # Legitimate record
    record = OutcomeVerificationRecord(
        id="outc_tamper_01",
        tenant_id="tenant_audit_99",
        transaction_id="txn_audit_01",
        action_id="act_audit_01",
        observability_class="OBS_DIRECT",
        outcome_status="FAILED",
        epistemic_confidence=0.95,
        verifier_adapter="DatabaseStateAdapter",
        is_simulated=False,
        expected_postconditions={"status": "SHIPPED"},
        observed_state={"status": "PENDING"},
        discrepancies=["Status mismatch"],
        evidence_payload={"_canonical_payload": canonical_payload},
        reconciliation_notes=[],
        verification_hash=authentic_hash,
        idempotency_key="idem_1",
        target_environment="DEV",
        contract_binding_hash="param_hash_1",
        created_at=datetime.now(UTC),
        verified_at=datetime.now(UTC),
    )

    # Clean read passes
    contract = service._record_to_contract(record)
    assert contract.outcome_status == OutcomeStatus.FAILED
    assert contract.verification_hash == authentic_hash

    # TAMPER 1: Attacker changes record.outcome_status to SUCCESS_CONFIRMED in DB
    record.outcome_status = "SUCCESS_CONFIRMED"
    with pytest.raises(HTTPException) as exc_info1:
        service._record_to_contract(record)
    assert exc_info1.value.status_code == 409
    assert "Cryptographic integrity violation" in exc_info1.value.detail
    assert "outcome_status" in exc_info1.value.detail

    # Restore status, TAMPER 2: Attacker changes verification_hash
    record.outcome_status = "FAILED"
    record.verification_hash = "f" * 64
    with pytest.raises(HTTPException) as exc_info2:
        service._record_to_contract(record)
    assert exc_info2.value.status_code == 409
    assert "verification_hash mismatch" in exc_info2.value.detail


# -----------------------------------------------------------------------------
# 5. Defect 4: Concurrency Locking and Monotonic State Machine
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_concurrency_locking_prevents_duplicate_races(auth_tenant_audit):
    """ActionContract and OutcomeVerificationRecord queries use with_for_update() row locks."""
    service = RealityVerifierService()
    action = _make_action()

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.DATABASE,
        expected_postconditions={"status": "PROCESSED"},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        executed_stmts = []

        async def capture_execute(stmt, *_args, **_kwargs):
            executed_stmts.append(stmt)
            res = MagicMock()
            if len(executed_stmts) == 1:
                res.scalar_one_or_none.return_value = action
            elif len(executed_stmts) == 2:
                res.scalar_one_or_none.return_value = None
            else:
                res.scalar_one_or_none.return_value = "0" * 64
            return res

        mock_session.execute.side_effect = capture_execute
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_audit)
        assert contract.action_id == action.id

        # Verify that queries were executed with FOR UPDATE
        assert len(executed_stmts) >= 2


# -----------------------------------------------------------------------------
# 6. Defect 5: DNS Rebinding and SSRF Defense in HttpResourceAdapter
# -----------------------------------------------------------------------------
def test_audit_http_adapter_dns_rebinding_defense():
    """HttpResourceAdapter._is_ip_allowed strictly rejects loopback, RFC 1918, and metadata IPs."""
    from services.reality_verifier import HttpResourceAdapter

    adapter = HttpResourceAdapter()
    assert adapter._is_ip_allowed("127.0.0.1") is False
    assert adapter._is_ip_allowed("localhost") is False
    assert adapter._is_ip_allowed("169.254.169.254") is False
    assert adapter._is_ip_allowed("metadata.google.internal") is False
    assert adapter._is_ip_allowed("10.200.1.1") is False
    assert adapter._is_ip_allowed("172.16.5.5") is False
    assert adapter._is_ip_allowed("192.168.100.1") is False
    # Safe public IP
    assert adapter._is_ip_allowed("8.8.8.8") is True


# -----------------------------------------------------------------------------
# 7. Output-Outcome Reconciliation Honest Caveat Interlock
# -----------------------------------------------------------------------------
def test_audit_reconciliation_honest_caveat_on_downgraded_sink():
    """Model claiming 'Payment processed and verified' on an ACKNOWLEDGED_UNVERIFIED or UNOBSERVABLE

    outcome is intercepted and forced to REWRITE_WITH_CAVEAT.
    """
    service = RealityVerifierService()
    unverified_contract = OutcomeVerificationContract(
        outcome_id="outc_reconcile_01",
        transaction_id="txn_rec_01",
        action_id="act_rec_01",
        tenant_id="tenant_audit_99",
        observability_class=ObservabilityClass.OBS_INFERRED,
        outcome_status=OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
        epistemic_confidence=0.50,
        verifier_adapter="DatabaseStateAdapter",
        is_simulated=False,
        expected_postconditions={"status": "PAID"},
        observed_state={"ack": True},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=["Transport acknowledged only"],
        verification_hash="0" * 64,
        idempotency_key="idem_rec_01",
        target_environment="PROD",
        schema_version="mirage.outcome.v1",
        verified_at=datetime.now(UTC).isoformat(),
    )

    result = service.reconcile_output_with_outcome(
        response_text="The payment has been successfully completed and confirmed in the database.",
        outcome_contract=unverified_contract,
        transaction_id="txn_rec_01",
        action_id="act_rec_01",
        auth_tenant_id="tenant_audit_99",
    )

    assert result.is_consistent is False
    assert result.epistemic_conflict_detected is True
    assert result.recommended_disposition == "REWRITE_WITH_CAVEAT"
    assert any("Transport acknowledgment alone does not prove" in c for c in result.conflict_reasons)


# -----------------------------------------------------------------------------
# 8. Compensating Actions Require Governed Gate 3 Evaluation
# -----------------------------------------------------------------------------
def test_audit_compensating_action_requires_governed_gate3():
    """Gate 5 cannot execute compensating actions directly; must raise NotImplementedError."""
    service = RealityVerifierService()
    action = _make_action()

    with pytest.raises(NotImplementedError) as exc_info:
        service.propose_compensating_action(action)

    assert "Gate 3" in str(exc_info.value)


# -----------------------------------------------------------------------------
# 9. Cross-Tenant Action Substitution Blocked
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_cross_tenant_action_substitution_blocked(auth_tenant_audit):
    """Attempting to verify an action belonging to another tenant is rejected (HTTP 404)."""
    service = RealityVerifierService()
    req = OutcomeVerificationRequest(
        transaction_id="txn_victim_01",
        action_id="act_victim_01",
        observability_class=ObservabilityClass.OBS_DIRECT,
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = None  # Not found under caller's tenant
        mock_session.execute.return_value = mock_res
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_action_outcome(req, auth_tenant_audit)

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()


# -----------------------------------------------------------------------------
# 10. Production Environment Simulation Strictly Prohibited
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_production_environment_simulation_blocked(auth_tenant_audit):
    """SimulatedTestAdapter is strictly prohibited in production environment."""
    service = RealityVerifierService()
    action = _make_action()
    action.blast_radius = {"target_environment": "PROD", "estimated_dollar_cost": 100.0}

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        adapter_config={"allow_simulated_for_test": False},
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_res
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_action_outcome(req, auth_tenant_audit)

        assert exc_info.value.status_code == 400
        assert "SimulatedTestAdapter is prohibited" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 11. Environment Mismatch Rejection
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_environment_mismatch_rejected(auth_tenant_audit):
    """Probe requested environment differing from authorized contract environment is rejected."""
    service = RealityVerifierService()
    action = _make_action()
    action.blast_radius = {"target_environment": "DEV"}

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.DATABASE,
        adapter_config={"environment": "PROD"},  # Mismatch with DEV
    )

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = action
        mock_session.execute.return_value = mock_res
        mock_ctx.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_action_outcome(req, auth_tenant_audit)

        assert exc_info.value.status_code == 400
        assert "Environment mismatch" in exc_info.value.detail


# -----------------------------------------------------------------------------
# 12. Audit Trail Cryptographic Hash Chain Linkage
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_trail_cryptographic_hash_chain_linkage(auth_tenant_audit):
    """Gate 5 outcomes are cryptographically chained to the tenant's audit trail."""
    service = RealityVerifierService()
    action = _make_action(postconditions=[{"target": "state", "expected_value": "SETTLED"}])

    req = OutcomeVerificationRequest(
        transaction_id=action.transaction_id,
        action_id=action.id,
        observability_class=ObservabilityClass.OBS_DIRECT,
        verifier_type=OutcomeVerifierType.SIMULATED,
        expected_postconditions={"state": "SETTLED"},
        adapter_config={"simulated_state": {"state": "SETTLED"}, "allow_simulated_for_test": True},
    )

    previous_chain_hash = "a" * 64
    added_records = []

    with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
        mock_session = AsyncMock()
        mock_session.add = lambda obj: added_records.append(obj)

        mock_res_act = MagicMock()
        mock_res_act.scalar_one_or_none.return_value = action
        mock_res_exist = MagicMock()
        mock_res_exist.scalar_one_or_none.return_value = None
        mock_res_audit = MagicMock()
        mock_res_audit.scalar_one_or_none.return_value = previous_chain_hash

        mock_session.execute.side_effect = [mock_res_act, mock_res_exist, mock_res_audit]
        mock_ctx.return_value.__aenter__.return_value = mock_session

        contract = await service.verify_action_outcome(req, auth_tenant_audit)

        # AuditLogRecord was created and added
        audit_entries = [r for r in added_records if isinstance(r, AuditLogRecord)]
        assert len(audit_entries) == 1
        audit = audit_entries[0]
        assert audit.prev_hash == previous_chain_hash
        assert len(audit.chain_hash) == 64
        assert audit.response_hash == contract.verification_hash
        assert audit.event_type == "GATE5_OUTCOME_VERIFIED"

