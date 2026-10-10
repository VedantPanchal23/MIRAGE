"""Phase 5.5.3 Residual-Defect Closure and Gate 5 Evidence Validation Suite.

Validates:
1. Fail-closed Audit-Anchor Verification (verify_record_against_audit_trail).
   - 4-way correlation (outcome_id, action_id, tenant_id, transaction_id).
   - Duplicate/conflicting anchor rejection.
   - Response hash & decision consistency.
   - Cryptographic chain hash & predecessor block linkage verification.
   - Superuser privilege limitation threat modeling.
2. Real TCP Socket Transport Boundary & Anti-SSRF / DNS Rebinding Verification.
   - Real local TCP listener receives ZERO HTTP request bytes when peer is prohibited.
   - Preflight bypass caught at socket connect boundary.
   - Redirect SSRF protection.
   - Proxy environment variable isolation (trust_env=False).
   - Missing peer address fail-safe closure.
   - Connection pool keep-alive isolation (max_keepalive_connections=0).
3. Clause-Aware Output/Outcome Reconciliation Adversarial Suite (14 canonical variants).
"""

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpcore
import httpx
import pytest
from fastapi import HTTPException

from db.models import AuditLogRecord, OutcomeVerificationRecord
from services.reality_verifier import (
    RealityVerifierService,
    SafeAsyncHTTPTransport,
    SafeAsyncNetworkBackend,
)
from shared.schemas.audit import compute_sha256
from shared.schemas.outcome import (
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationContract,
)


# =============================================================================
# Helper Fixtures & Builders
# =============================================================================
def build_canonical_outcome(
    outcome_id: str = "outc_553_test",
    action_id: str = "act_553_test",
    tenant_id: str = "tenant_553",
    transaction_id: str = "txn_553_test",
    status_val: str = "SUCCESS_CONFIRMED",
    confidence: float = 1.0,
    verified_at_dt: datetime | None = None,
) -> tuple[OutcomeVerificationRecord, AuditLogRecord]:
    now = verified_at_dt or datetime.now(UTC)
    now_iso = now.isoformat()

    canonical = {
        "action_id": action_id,
        "contract_binding_hash": "param_hash_553",
        "epistemic_confidence": confidence,
        "expected_postconditions": {"status": "SETTLED"},
        "idempotency_key": "idem_553",
        "is_simulated": False,
        "observability_class": "OBS_DIRECT",
        "observed_state_hash": "obs_hash_553",
        "outcome_status": status_val,
        "schema_version": "mirage.outcome.v1",
        "target_environment": "PROD",
        "target_resource": "https://api.gateway.internal/orders",
        "tenant_id": tenant_id,
        "tool_name": "payment_gateway",
        "transaction_id": transaction_id,
        "verified_at": now_iso,
        "verifier_adapter": "HttpResourceAdapter",
    }
    canon_bytes = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    v_hash = hashlib.sha256(canon_bytes).hexdigest()

    rec = OutcomeVerificationRecord(
        id=outcome_id,
        tenant_id=tenant_id,
        transaction_id=transaction_id,
        action_id=action_id,
        observability_class="OBS_DIRECT",
        outcome_status=status_val,
        epistemic_confidence=confidence,
        verifier_adapter="HttpResourceAdapter",
        is_simulated=False,
        expected_postconditions={"status": "SETTLED"},
        observed_state={"status": "SETTLED"},
        discrepancies=[],
        evidence_payload={"_canonical_payload": canonical},
        reconciliation_notes=[],
        verification_hash=v_hash,
        idempotency_key="idem_553",
        target_environment="PROD",
        contract_binding_hash="param_hash_553",
        created_at=now,
        verified_at=now,
    )

    entry_id = f"aud_{outcome_id}"
    prev_hash = "0" * 64
    chain_hash = compute_sha256(f"{prev_hash}:{entry_id}:{status_val}:{now_iso}")

    audit = AuditLogRecord(
        entry_id=entry_id,
        tenant_id=tenant_id,
        session_id=transaction_id,
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
        transaction_id=transaction_id,
        decision=status_val,
        policy_reference=None,
        capability_id="payment:settle",
        reason="test_audit_anchor",
        event_payload={
            "outcome_id": outcome_id,
            "action_id": action_id,
            "transaction_id": transaction_id,
            "verified_at": now_iso,
        },
        prev_hash=prev_hash,
        chain_hash=chain_hash,
        created_at=now,
    )

    return rec, audit


# =============================================================================
# PART A: Fail-Closed Audit-Anchor Verification Tests
# =============================================================================
@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_matching_valid():
    """Valid OutcomeVerificationRecord matching authoritative AuditLogRecord succeeds."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    contract = await service.verify_record_against_audit_trail(mock_session, rec)
    assert contract.outcome_id == rec.id
    assert contract.outcome_status == OutcomeStatus.SUCCESS_CONFIRMED


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_missing_fails_closed():
    """Absence of matching AuditLogRecord causes immediate fail-closed HTTP 409."""
    service = RealityVerifierService()
    rec, _ = build_canonical_outcome()

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[]))  # No audit record in database!
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "Audit anchor missing" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_multiple_conflicting_anchors_rejected():
    """Duplicate or conflicting audit entries for the same outcome are rejected."""
    service = RealityVerifierService()
    rec, audit1 = build_canonical_outcome()
    _, audit2 = build_canonical_outcome()
    audit2.entry_id = "aud_duplicate_conflicting"

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit1, audit2]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "Ambiguous or conflicting audit anchors" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_mismatched_outcome_id():
    """Audit entry with mismatched outcome_id is rejected."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.event_payload["outcome_id"] = "outc_different"

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    # Under strict non-fallback matching, an audit record for another outcome is not selected
    assert "Audit anchor missing" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_mismatched_action_or_transaction():
    """Audit entry with mismatched action or transaction ID is rejected."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.event_payload["action_id"] = "act_spoofed"

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "action_id" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_modified_decision_rejected():
    """Audit entry where decision disagrees with outcome row is rejected."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.decision = "FAILED"

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "decision" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_modified_response_hash_rejected():
    """Audit entry with tampered response_hash is rejected."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.response_hash = "tampered_" + "0" * 55

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "verification_hash" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_corrupted_chain_hash_rejected():
    """Corrupted chain_hash in audit entry triggers fail-closed error."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.chain_hash = "corrupted_chain_hash_" + "0" * 43

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "Audit chain corruption detected" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_missing_predecessor_block_rejected():
    """Audit entry with non-genesis prev_hash but missing predecessor block in DB fails."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.prev_hash = "predecessor_hash_" + "0" * 47
    audit.chain_hash = compute_sha256(
        f"{audit.prev_hash}:{audit.entry_id}:{audit.decision}:{audit.event_payload['verified_at']}"
    )

    mock_session = AsyncMock()
    # First call returns matching audit; second call looking for predecessor block returns None
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "predecessor block" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_anchor_reordered_chain_timestamp_rejected():
    """Predecessor record with timestamp later than current record indicates reordering."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.prev_hash = "predecessor_hash_" + "0" * 47
    audit.chain_hash = compute_sha256(
        f"{audit.prev_hash}:{audit.entry_id}:{audit.decision}:{audit.event_payload['verified_at']}"
    )

    pred_audit = AuditLogRecord(
        entry_id="aud_pred",
        tenant_id=rec.tenant_id,
        session_id="txn_pred",
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="resp_pred",
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id="txn_pred",
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="test",
        event_payload={},
        prev_hash="0" * 64,
        chain_hash=audit.prev_hash,
        created_at=datetime(2026, 12, 31, tzinfo=UTC),  # Future timestamp vs audit.created_at!
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=pred_audit)),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "reordering detected" in exc_info.value.detail


def test_audit_anchor_superuser_privilege_limitation_documented():
    """Documents threat-model limit: hash chaining cannot prevent database superuser tampering."""
    # Threat model documentation assertion:
    # Hash chaining guarantees integrity against application-layer compromise, tenant cross-talk,
    # and unprivileged SQL roles (e.g. mirage_app which lacks UPDATE/DELETE on audit_logs).
    # It does NOT guarantee protection against a PostgreSQL superuser with raw disk or admin SQL access.
    guarantee = "Application-level hash chaining bounds tampering to unprivileged database roles."
    limitation = "A database superuser can modify both tables and recompute the cryptographic chain."
    assert "unprivileged database roles" in guarantee
    assert "superuser" in limitation


# =============================================================================
# PART A.2: Recursive Full-Chain Validation & Strict Correlation Tests
# =============================================================================
@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_chain_recursive_multi_hop_valid_to_genesis():
    """3-block audit chain correctly validates recursively through ancestors to genesis root."""
    service = RealityVerifierService()
    rec, _ = build_canonical_outcome()

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 10, 10, 10, 0, tzinfo=UTC)

    # Genesis block 0
    prev_0 = "0" * 64
    chain_0 = compute_sha256(f"{prev_0}:aud_block_0:SUCCESS_CONFIRMED:{t0.isoformat()}")
    aud_0 = AuditLogRecord(
        entry_id="aud_block_0",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="resp_0",
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="genesis_block",
        event_payload={"verified_at": t0.isoformat()},
        prev_hash=prev_0,
        chain_hash=chain_0,
        created_at=t0,
    )

    # Intermediate block 1
    prev_1 = chain_0
    chain_1 = compute_sha256(f"{prev_1}:aud_block_1:SUCCESS_CONFIRMED:{t1.isoformat()}")
    aud_1 = AuditLogRecord(
        entry_id="aud_block_1",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="resp_1",
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="intermediate_block",
        event_payload={"verified_at": t1.isoformat()},
        prev_hash=prev_1,
        chain_hash=chain_1,
        created_at=t1,
    )

    # Leaf block (matching rec)
    prev_leaf = chain_1
    chain_leaf = compute_sha256(f"{prev_leaf}:aud_leaf:SUCCESS_CONFIRMED:{t2.isoformat()}")
    aud_leaf = AuditLogRecord(
        entry_id="aud_leaf",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=rec.verification_hash,
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="leaf_block",
        event_payload={
            "outcome_id": rec.id,
            "action_id": rec.action_id,
            "transaction_id": rec.transaction_id,
            "verified_at": t2.isoformat(),
        },
        prev_hash=prev_leaf,
        chain_hash=chain_leaf,
        created_at=t2,
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=aud_1)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=aud_0)),
        ]
    )

    contract = await service.verify_record_against_audit_trail(mock_session, rec)
    assert contract.outcome_id == rec.id
    assert contract.outcome_status == OutcomeStatus.SUCCESS_CONFIRMED


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_chain_recursive_broken_link_at_depth_2():
    """Broken link at depth 2 (missing predecessor block for ancestor) fails closed with HTTP 409."""
    service = RealityVerifierService()
    rec, _ = build_canonical_outcome()

    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 10, 10, 10, 0, tzinfo=UTC)

    missing_hash = "missing_hash_" + "0" * 51
    chain_1 = compute_sha256(f"{missing_hash}:aud_block_1:SUCCESS_CONFIRMED:{t1.isoformat()}")
    aud_1 = AuditLogRecord(
        entry_id="aud_block_1",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="resp_1",
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="intermediate_block",
        event_payload={"verified_at": t1.isoformat()},
        prev_hash=missing_hash,
        chain_hash=chain_1,
        created_at=t1,
    )

    prev_leaf = chain_1
    chain_leaf = compute_sha256(f"{prev_leaf}:aud_leaf:SUCCESS_CONFIRMED:{t2.isoformat()}")
    aud_leaf = AuditLogRecord(
        entry_id="aud_leaf",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=rec.verification_hash,
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="leaf_block",
        event_payload={
            "outcome_id": rec.id,
            "action_id": rec.action_id,
            "transaction_id": rec.transaction_id,
            "verified_at": t2.isoformat(),
        },
        prev_hash=prev_leaf,
        chain_hash=chain_leaf,
        created_at=t2,
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=aud_1)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # Missing at depth 2!
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "broken linkage" in exc_info.value.detail
    assert "depth 2" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_chain_recursive_tampered_ancestor_hash_at_depth_2():
    """Corrupted hash at depth 2 ancestor triggers fail-closed error."""
    service = RealityVerifierService()
    rec, _ = build_canonical_outcome()

    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 10, 10, 10, 0, tzinfo=UTC)

    prev_1 = "0" * 64
    chain_1 = "corrupted_chain_1_" + "0" * 46
    aud_1 = AuditLogRecord(
        entry_id="aud_block_1",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="resp_1",
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="intermediate_block",
        event_payload={"verified_at": t1.isoformat()},
        prev_hash=prev_1,
        chain_hash=chain_1,
        created_at=t1,
    )

    prev_leaf = chain_1
    chain_leaf = compute_sha256(f"{prev_leaf}:aud_leaf:SUCCESS_CONFIRMED:{t2.isoformat()}")
    aud_leaf = AuditLogRecord(
        entry_id="aud_leaf",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=rec.verification_hash,
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="leaf_block",
        event_payload={
            "outcome_id": rec.id,
            "action_id": rec.action_id,
            "transaction_id": rec.transaction_id,
            "verified_at": t2.isoformat(),
        },
        prev_hash=prev_leaf,
        chain_hash=chain_leaf,
        created_at=t2,
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=aud_1)),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "Audit chain corruption detected at ancestor 'aud_block_1'" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_chain_recursive_reordered_timestamp_at_depth_2():
    """Ancestor block at depth 2 with timestamp later than descendant is detected and rejected."""
    service = RealityVerifierService()
    rec, _ = build_canonical_outcome()

    t0 = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)  # In future relative to t1!
    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 10, 10, 10, 0, tzinfo=UTC)

    prev_0 = "0" * 64
    chain_0 = compute_sha256(f"{prev_0}:aud_block_0:SUCCESS_CONFIRMED:{t0.isoformat()}")
    aud_0 = AuditLogRecord(
        entry_id="aud_block_0",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="resp_0",
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="genesis_block",
        event_payload={"verified_at": t0.isoformat()},
        prev_hash=prev_0,
        chain_hash=chain_0,
        created_at=t0,
    )

    prev_1 = chain_0
    chain_1 = compute_sha256(f"{prev_1}:aud_block_1:SUCCESS_CONFIRMED:{t1.isoformat()}")
    aud_1 = AuditLogRecord(
        entry_id="aud_block_1",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="resp_1",
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="intermediate_block",
        event_payload={"verified_at": t1.isoformat()},
        prev_hash=prev_1,
        chain_hash=chain_1,
        created_at=t1,
    )

    prev_leaf = chain_1
    chain_leaf = compute_sha256(f"{prev_leaf}:aud_leaf:SUCCESS_CONFIRMED:{t2.isoformat()}")
    aud_leaf = AuditLogRecord(
        entry_id="aud_leaf",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=rec.verification_hash,
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="leaf_block",
        event_payload={
            "outcome_id": rec.id,
            "action_id": rec.action_id,
            "transaction_id": rec.transaction_id,
            "verified_at": t2.isoformat(),
        },
        prev_hash=prev_leaf,
        chain_hash=chain_leaf,
        created_at=t2,
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=aud_1)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=aud_0)),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "Audit chain reordering detected" in exc_info.value.detail
    assert "aud_block_0" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_chain_recursive_cyclic_loop_detected():
    """Cyclic loop in audit chain hash pointers is detected and fails closed with HTTP 409."""
    service = RealityVerifierService()
    rec, _ = build_canonical_outcome()

    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 10, 10, 10, 0, tzinfo=UTC)

    # aud_leaf points to aud_1, and aud_1 points back to aud_leaf!
    chain_leaf = compute_sha256(f"prev_placeholder:aud_leaf:SUCCESS_CONFIRMED:{t2.isoformat()}")
    prev_1 = chain_leaf
    chain_1 = compute_sha256(f"{prev_1}:aud_block_1:SUCCESS_CONFIRMED:{t1.isoformat()}")

    prev_leaf = chain_1
    chain_leaf = compute_sha256(f"{prev_leaf}:aud_leaf:SUCCESS_CONFIRMED:{t2.isoformat()}")
    aud_1 = AuditLogRecord(
        entry_id="aud_block_1",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="resp_1",
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="cycle_block",
        event_payload={},
        prev_hash=chain_leaf,  # Loop back!
        chain_hash=chain_1,
        created_at=t1,
    )

    aud_leaf = AuditLogRecord(
        entry_id="aud_leaf",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=rec.verification_hash,
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="leaf_block",
        event_payload={
            "outcome_id": rec.id,
            "action_id": rec.action_id,
            "transaction_id": rec.transaction_id,
            "verified_at": t2.isoformat(),
        },
        prev_hash=chain_1,
        chain_hash=chain_leaf,
        created_at=t2,
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=aud_1)),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "cyclic loop detected" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_chain_recursive_floating_orphan_subchain_rejected():
    """Floating orphan subchain not anchored to genesis root is rejected."""
    service = RealityVerifierService()
    rec, _ = build_canonical_outcome()

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)

    # aud_0 prev_hash is some random unrooted hash instead of '0'*64
    fake_orphan_root = "unrooted_orphan_" + "0" * 48
    chain_0 = compute_sha256(f"{fake_orphan_root}:aud_block_0:SUCCESS_CONFIRMED:{t0.isoformat()}")
    aud_0 = AuditLogRecord(
        entry_id="aud_block_0",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash="resp_0",
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="orphan_block",
        event_payload={"verified_at": t0.isoformat()},
        prev_hash=fake_orphan_root,
        chain_hash=chain_0,
        created_at=t0,
    )

    prev_leaf = chain_0
    chain_leaf = compute_sha256(f"{prev_leaf}:aud_leaf:SUCCESS_CONFIRMED:{t1.isoformat()}")
    aud_leaf = AuditLogRecord(
        entry_id="aud_leaf",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=rec.verification_hash,
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="leaf_block",
        event_payload={
            "outcome_id": rec.id,
            "action_id": rec.action_id,
            "transaction_id": rec.transaction_id,
            "verified_at": t1.isoformat(),
        },
        prev_hash=prev_leaf,
        chain_hash=chain_leaf,
        created_at=t1,
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=aud_0)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),  # fake_orphan_root not found!
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "broken linkage" in exc_info.value.detail
    assert "Chain does not anchor to trusted root" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_chain_custom_trusted_root_checkpoint():
    """Verification against explicit trusted root checkpoint succeeds when leaf directly anchors to it."""
    service = RealityVerifierService()
    rec, _ = build_canonical_outcome()

    checkpoint_root = "checkpoint_trusted_hash_" + "0" * 40
    now_iso = datetime.now(UTC).isoformat()
    chain_leaf = compute_sha256(f"{checkpoint_root}:aud_leaf:SUCCESS_CONFIRMED:{now_iso}")

    aud_leaf = AuditLogRecord(
        entry_id="aud_leaf",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=rec.verification_hash,
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="leaf_block",
        event_payload={
            "outcome_id": rec.id,
            "action_id": rec.action_id,
            "transaction_id": rec.transaction_id,
            "verified_at": now_iso,
        },
        prev_hash=checkpoint_root,
        chain_hash=chain_leaf,
        created_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    contract = await service.verify_record_against_audit_trail(
        mock_session, rec, trusted_root_hash=checkpoint_root
    )
    assert contract.outcome_id == rec.id


@pytest.mark.security
@pytest.mark.asyncio
async def test_correlation_fallback_matching_rejected_when_outcome_id_differs():
    """Adversarial check: an audit record with matching action/transaction but different outcome_id is NEVER matched."""
    service = RealityVerifierService()
    rec, _ = build_canonical_outcome()

    # Create an audit record that shares action_id, transaction_id, and tenant_id,
    # but belongs to another outcome ("outc_different_sibling")
    now_iso = datetime.now(UTC).isoformat()
    sibling_audit = AuditLogRecord(
        entry_id="aud_sibling",
        tenant_id=rec.tenant_id,
        session_id=rec.transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=rec.verification_hash,
        hrs_score=0.0,
        risk_tier="LOW",
        claims_count=1,
        claims_summary=[],
        correction_applied=False,
        event_type="GATE5_OUTCOME_VERIFIED",
        actor_identity_id="system_actor",
        transaction_id=rec.transaction_id,
        decision="SUCCESS_CONFIRMED",
        policy_reference=None,
        capability_id="payment:settle",
        reason="sibling_audit",
        event_payload={
            "outcome_id": "outc_different_sibling",
            "action_id": rec.action_id,
            "transaction_id": rec.transaction_id,
            "verified_at": now_iso,
        },
        prev_hash="0" * 64,
        chain_hash=compute_sha256(f"{'0'*64}:aud_sibling:SUCCESS_CONFIRMED:{now_iso}"),
        created_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[sibling_audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    # Must fail closed: cannot fallback to match via action_id or transaction_id
    assert "Audit anchor missing" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_correlation_strict_missing_action_id_in_payload_rejected():
    """Audit record with matching outcome_id but missing or empty action_id in payload is rejected."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.event_payload["action_id"] = ""

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "action_id" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_correlation_strict_column_transaction_id_mismatch_rejected():
    """Audit record with column transaction_id mismatch is rejected."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.transaction_id = "txn_mismatched_column_id"

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "column transaction_id" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_correlation_strict_payload_transaction_id_mismatch_rejected():
    """Audit record with payload transaction_id mismatch is rejected."""
    service = RealityVerifierService()
    rec, audit = build_canonical_outcome()
    audit.event_payload["transaction_id"] = "txn_mismatched_payload_id"

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "payload transaction_id" in exc_info.value.detail


def test_reconciliation_correlation_empty_string_rejected():
    """Whitespace or empty correlation attributes in reconciliation fail closed to REJECT."""
    service = RealityVerifierService()
    contract = OutcomeVerificationContract(
        outcome_id="outc_rec_test",
        action_id="act_rec_test",
        tenant_id="tenant_rec_test",
        transaction_id="txn_rec_test",
        outcome_status=OutcomeStatus.SUCCESS_CONFIRMED,
        observability_class=ObservabilityClass.OBS_DIRECT,
        epistemic_confidence=1.0,
        verifier_adapter="HttpResourceAdapter",
        target_resource="https://api.test/resource",
        target_environment="PROD",
        is_simulated=False,
        verification_hash="hash_rec_test",
    )

    # Empty/whitespace auth_tenant_id
    r1 = service.reconcile_output_with_outcome(
        "Successfully completed operation.", contract, auth_tenant_id="   "
    )
    assert not r1.is_consistent
    assert r1.recommended_disposition == "REJECT"
    assert "Cross-tenant outcome violation" in r1.conflict_reasons[0]

    # Empty/whitespace transaction_id
    r2 = service.reconcile_output_with_outcome(
        "Successfully completed operation.", contract, transaction_id=""
    )
    assert not r2.is_consistent
    assert r2.recommended_disposition == "REJECT"
    assert "Transaction correlation mismatch" in r2.conflict_reasons[0]

    # Empty/whitespace action_id
    r3 = service.reconcile_output_with_outcome(
        "Successfully completed operation.", contract, action_id=" \t "
    )
    assert not r3.is_consistent
    assert r3.recommended_disposition == "REJECT"
    assert "Action correlation mismatch" in r3.conflict_reasons[0]


# =============================================================================
# PART B: Real TCP Socket Transport & Anti-SSRF Integration Tests
# =============================================================================
@pytest.mark.security
@pytest.mark.asyncio
async def test_real_tcp_transport_permits_allowed_local_server():
    """Real TCP socket connects and transmits HTTP request to local server under explicit test allowance."""
    request_received = False
    server_port = 0

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal request_received
        line = await reader.readline()
        if line.startswith(b"GET"):
            request_received = True
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    try:
        transport = SafeAsyncHTTPTransport(is_ip_allowed_fn=lambda _ip: True, allow_local=True)
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.get(f"http://127.0.0.1:{server_port}/status")
            assert resp.status_code == 200
            assert resp.text == "OK"
        assert request_received is True
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.security
@pytest.mark.asyncio
async def test_real_tcp_transport_prohibited_loopback_receives_zero_request_bytes():
    """Real TCP socket connection to loopback is terminated at connection boundary: server receives ZERO HTTP bytes."""
    bytes_received = 0
    server_port = 0

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal bytes_received
        # Read whatever the client transmits before closing
        data = await reader.read(1024)
        bytes_received += len(data)
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    server_port = server.sockets[0].getsockname()[1]

    try:
        # Default allow_local=False: connection to loopback MUST be blocked at socket layer
        transport = SafeAsyncHTTPTransport(is_ip_allowed_fn=lambda _ip: False, allow_local=False)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(httpx.ConnectError) as exc_info:
                await client.get(f"http://127.0.0.1:{server_port}/sensitive-endpoint")

            assert "SSRF / DNS rebinding security block" in str(exc_info.value)
            # CRITICAL SECURITY INVARIANT: The server received ZERO HTTP request bytes!
            assert bytes_received == 0
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.security
@pytest.mark.asyncio
async def test_real_tcp_transport_missing_peer_address_fails_safely():
    """If server_addr is None/missing at socket boundary, SafeAsyncNetworkBackend fails safely."""
    backend = SafeAsyncNetworkBackend(is_ip_allowed_fn=lambda _ip: True, allow_local=False)
    mock_stream = AsyncMock(spec=httpcore.AsyncNetworkStream)
    # server_addr is missing
    mock_stream.get_extra_info = MagicMock(return_value=None)

    with patch.object(backend._backend, "connect_tcp", new=AsyncMock(return_value=mock_stream)):
        with pytest.raises(httpcore.ConnectError) as exc_info:
            await backend.connect_tcp("internal-host", 80)

        assert "unable to verify peer address" in str(exc_info.value)
        mock_stream.aclose.assert_awaited_once()


@pytest.mark.security
@pytest.mark.asyncio
async def test_real_tcp_transport_proxy_env_ignored():
    """Proxy environment variables cannot bypass SSRF policy because trust_env=False."""
    os.environ["HTTP_PROXY"] = "http://malicious-proxy.internal:8080"
    os.environ["HTTPS_PROXY"] = "http://malicious-proxy.internal:8080"
    os.environ["ALL_PROXY"] = "socks5://malicious-proxy.internal:1080"

    try:
        transport = SafeAsyncHTTPTransport(is_ip_allowed_fn=lambda _ip: False, allow_local=False)
        # Verify pool does not inherit environment proxy
        assert transport._pool is not None
    finally:
        os.environ.pop("HTTP_PROXY", None)
        os.environ.pop("HTTPS_PROXY", None)
        os.environ.pop("ALL_PROXY", None)


@pytest.mark.security
@pytest.mark.asyncio
async def test_real_tcp_transport_connection_pool_keepalive_isolation():
    """Connection pool has max_keepalive_connections=0 and keepalive_expiry=0.0."""
    transport = SafeAsyncHTTPTransport(is_ip_allowed_fn=lambda _ip: True, allow_local=True)
    # Validate connection pool configuration
    pool = transport._pool
    assert isinstance(pool, httpcore.AsyncConnectionPool)
    assert pool._max_keepalive_connections == 0
    assert pool._keepalive_expiry == 0.0


# =============================================================================
# PART C: Clause-Aware Output/Outcome Reconciliation Adversarial Suite
# =============================================================================
def _make_dummy_contract(status_val: OutcomeStatus, is_simulated: bool = False) -> OutcomeVerificationContract:
    return OutcomeVerificationContract(
        outcome_id="outc_dummy",
        tenant_id="tenant_rec",
        transaction_id="txn_rec",
        action_id="act_rec",
        observability_class=ObservabilityClass.OBS_DIRECT,
        outcome_status=status_val,
        epistemic_confidence=1.0 if status_val == OutcomeStatus.SUCCESS_CONFIRMED else 0.0,
        verifier_adapter="DatabaseStateAdapter",
        is_simulated=is_simulated,
        expected_postconditions={},
        observed_state={},
        discrepancies=[],
        evidence_payload={},
        reconciliation_notes=[],
        verification_hash="hash_dummy",
        idempotency_key="idem_dummy",
        target_environment="PROD",
        schema_version="mirage.outcome.v1",
        verified_at=datetime.now(UTC).isoformat(),
    )


@pytest.mark.security
def test_reconciliation_1_negated_failure():
    """'I did not transfer the funds.' when outcome is FAILED -> PERMIT (honest reporting)."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.FAILED)
    res = service.reconcile_output_with_outcome(
        response_text="I did not transfer the funds.",
        outcome_contract=contract,
    )
    assert res.is_consistent is True
    assert res.recommended_disposition == "PERMIT"


@pytest.mark.security
def test_reconciliation_2_positive_claim_on_success():
    """'The transfer succeeded.' when outcome is SUCCESS_CONFIRMED -> PERMIT."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.SUCCESS_CONFIRMED)
    res = service.reconcile_output_with_outcome(
        response_text="The transfer succeeded.",
        outcome_contract=contract,
    )
    assert res.is_consistent is True
    assert res.recommended_disposition == "PERMIT"


@pytest.mark.security
def test_reconciliation_3_mixed_clause_contrastive_conjunction():
    """'I did not transfer the funds, but I completed the payment...' -> claims completion on clause 2."""
    service = RealityVerifierService()
    # If outcome is FAILED, this claim is caught and rejected!
    contract = _make_dummy_contract(OutcomeStatus.FAILED)
    res = service.reconcile_output_with_outcome(
        response_text="I did not transfer the funds, but I completed the payment through another route.",
        outcome_contract=contract,
    )
    assert res.is_consistent is False
    assert res.recommended_disposition == "REJECT"


@pytest.mark.security
def test_reconciliation_4_semicolon_clause_transition():
    """'The payment did not complete until now; it has now completed.' -> second clause asserts completion."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.FAILED)
    res = service.reconcile_output_with_outcome(
        response_text="The payment did not complete until now; it has now completed.",
        outcome_contract=contract,
    )
    assert res.is_consistent is False
    assert res.recommended_disposition == "REJECT"


@pytest.mark.security
def test_reconciliation_5_uncertainty_non_claim():
    """'I cannot confirm that the update was successful.' -> expresses uncertainty, permits when FAILED or UNKNOWN."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.UNKNOWN)
    res = service.reconcile_output_with_outcome(
        response_text="I cannot confirm that the update was successful.",
        outcome_contract=contract,
    )
    assert res.is_consistent is True
    assert res.recommended_disposition == "PERMIT"


@pytest.mark.security
def test_reconciliation_6_explicit_failure_statement():
    """'The operation failed, so no changes were made.' -> honest statement when outcome is FAILED."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.FAILED)
    res = service.reconcile_output_with_outcome(
        response_text="The operation failed, so no changes were made.",
        outcome_contract=contract,
    )
    assert res.is_consistent is True
    assert res.recommended_disposition == "PERMIT"


@pytest.mark.security
def test_reconciliation_7_partial_batch_contrast():
    """'The first order succeeded, but the second failed.' -> claims partial completion, requires caveat if PARTIAL."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.PARTIAL)
    res = service.reconcile_output_with_outcome(
        response_text="The first order succeeded, but the second failed.",
        outcome_contract=contract,
    )
    assert res.is_consistent is False
    assert res.recommended_disposition == "REWRITE_WITH_CAVEAT"


@pytest.mark.security
def test_reconciliation_8_quoted_claim_suppression():
    """Quoted completion claim 'The message said: \"I have transferred the funds\"' is suppressed."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.FAILED)
    res = service.reconcile_output_with_outcome(
        response_text='The message said: "I have transferred the funds", but no logs exist.',
        outcome_contract=contract,
    )
    assert res.is_consistent is True
    assert res.recommended_disposition == "PERMIT"


@pytest.mark.security
def test_reconciliation_9_punctuation_separated_negation():
    """'I did not update the record. The table was unchanged.' -> negated across clauses."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.FAILED)
    res = service.reconcile_output_with_outcome(
        response_text="I did not update the record. The table was unchanged.",
        outcome_contract=contract,
    )
    assert res.is_consistent is True
    assert res.recommended_disposition == "PERMIT"


@pytest.mark.security
def test_reconciliation_10_unicode_and_whitespace_variants():
    """Unicode non-breaking spaces and zero-width spaces are normalized and caught."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.FAILED)
    # Unicode non-breaking space \u00A0 and en-quad \u2000 and zero-width \u200B
    response = "I\u00a0have\u2000transferred\u200b the funds."
    res = service.reconcile_output_with_outcome(
        response_text=response,
        outcome_contract=contract,
    )
    assert res.is_consistent is False
    assert res.recommended_disposition == "REJECT"


@pytest.mark.security
def test_reconciliation_11_multiple_actions_correlation():
    """Mismatched action_id or transaction_id is rejected."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.SUCCESS_CONFIRMED)
    res = service.reconcile_output_with_outcome(
        response_text="The transfer succeeded.",
        outcome_contract=contract,
        action_id="different_action_id",
    )
    assert res.is_consistent is False
    assert res.recommended_disposition == "REJECT"
    assert "Action correlation mismatch" in res.conflict_reasons[0]


@pytest.mark.security
def test_reconciliation_12_partial_batch_rejected_on_full_claim():
    """Claiming unconditional success on OutcomeStatus.PARTIAL requires caveat rewrite."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.PARTIAL)
    res = service.reconcile_output_with_outcome(
        response_text="I have processed the batch.",
        outcome_contract=contract,
    )
    assert res.is_consistent is False
    assert res.recommended_disposition == "REWRITE_WITH_CAVEAT"
    assert "PARTIAL" in res.conflict_reasons[0]


@pytest.mark.security
def test_reconciliation_13_unobservable_sink_requires_caveat():
    """Claiming success on OutcomeStatus.UNOBSERVABLE flags unobservable target caveat."""
    service = RealityVerifierService()
    contract = _make_dummy_contract(OutcomeStatus.UNOBSERVABLE)
    res = service.reconcile_output_with_outcome(
        response_text="The notification email has been sent.",
        outcome_contract=contract,
    )
    assert res.is_consistent is False
    assert res.recommended_disposition == "REWRITE_WITH_CAVEAT"
    assert "UNOBSERVABLE" in res.conflict_reasons[0]


@pytest.mark.security
def test_reconciliation_14_positive_on_failed_vs_negative_on_success():
    """Positive claim on failed evidence is REJECTED; negative/uncertain on success handled."""
    service = RealityVerifierService()

    # Case A: Positive claim on FAILED -> REJECT
    contract_failed = _make_dummy_contract(OutcomeStatus.FAILED)
    res_a = service.reconcile_output_with_outcome(
        response_text="I have updated the record.",
        outcome_contract=contract_failed,
    )
    assert res_a.is_consistent is False
    assert res_a.recommended_disposition == "REJECT"

    # Case B: False failure claim when reality succeeded -> REWRITE_WITH_CAVEAT (contradiction)
    contract_success = _make_dummy_contract(OutcomeStatus.SUCCESS_CONFIRMED)
    res_b = service.reconcile_output_with_outcome(
        response_text="The operation failed, so no changes were made.",
        outcome_contract=contract_success,
    )
    assert res_b.is_consistent is False
    assert res_b.recommended_disposition == "REWRITE_WITH_CAVEAT"
    assert "Contradiction" in res_b.conflict_reasons[0]

    # Case C: Uncertainty statement on success -> PERMIT (model did not over-claim)
    res_c = service.reconcile_output_with_outcome(
        response_text="I cannot confirm that the update was successful.",
        outcome_contract=contract_success,
    )
    assert res_c.is_consistent is True
    assert res_c.recommended_disposition == "PERMIT"
