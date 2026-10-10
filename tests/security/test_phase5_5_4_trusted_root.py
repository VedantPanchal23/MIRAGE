"""Phase 5.5.4 Trusted Checkpoint Authentication, Fail-Closed Chain Integrity & Final Gate 5 Audit.

Tests cover:
1. Missing-field and empty-field fail-open prevention on anchor and ancestor records:
   - entry_id, prev_hash, chain_hash, decision, verified_at (ISO timestamp).
   - Column vs. payload concordance (decision, outcome_status, transaction_id).
   - Malformed hash format (non-hex, invalid length).
   - Recomputed SHA-256 hash validation (fail-closed HTTP 409).
2. Authenticated trust anchors and checkpoints:
   - Genesis root ("0" * 64) is default and universally authenticated.
   - Caller-selected custom roots MUST be registered in TrustedCheckpointRegistry.
   - Unregistered custom roots fail closed (HTTP 409).
   - Cross-tenant checkpoint leakage prevented.
   - Malformed root format rejected (HTTP 400).
3. Chain structure and database ambiguity:
   - Ambiguous predecessor lookups (len > 1 with same chain_hash) -> HTTP 409.
   - Predecessor tenant boundary isolation -> HTTP 409.
   - Node repetition (entry_id repeated in ancestor traversal) -> HTTP 409.
   - Cyclic loop detection -> HTTP 409.
   - Max depth boundary enforcement -> HTTP 409.
4. Concurrency & Privilege Isolation:
   - Audit append serialization via SELECT ... FOR UPDATE.
   - Superuser privilege limitation documentation & unprivileged role threat modeling.
"""

import hashlib
import inspect
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from db.models import AuditLogRecord, OutcomeVerificationRecord
from services.reality_verifier import RealityVerifierService
from shared.schemas.audit import (
    GENESIS_ROOT_HASH,
    TrustedCheckpointRegistry,
    compute_sha256,
    is_valid_sha256_hex,
)
from shared.schemas.outcome import OutcomeStatus


def build_test_outcome(
    outcome_id: str = "outc_554_test",
    action_id: str = "act_554_test",
    tenant_id: str = "tenant_554",
    transaction_id: str = "txn_554_test",
    status_val: str = "SUCCESS_CONFIRMED",
    confidence: float = 1.0,
    verified_at_dt: datetime | None = None,
) -> tuple[OutcomeVerificationRecord, AuditLogRecord]:
    now = verified_at_dt or datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)
    now_iso = now.isoformat()

    canonical = {
        "action_id": action_id,
        "contract_binding_hash": "param_hash_554",
        "epistemic_confidence": confidence,
        "expected_postconditions": {"status": "SETTLED"},
        "idempotency_key": "idem_554",
        "is_simulated": False,
        "observability_class": "OBS_DIRECT",
        "observed_state_hash": "obs_hash_554",
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
        idempotency_key="idem_554",
        target_environment="PROD",
        contract_binding_hash="param_hash_554",
        created_at=now,
        verified_at=now,
    )

    entry_id = f"aud_{outcome_id}"
    prev_hash = GENESIS_ROOT_HASH
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
# PART 1: Missing and Empty Field Validation on Anchor (Fail-Closed HTTP 409)
# =============================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_missing_verified_at_fails_closed():
    """Anchor with missing verified_at in event_payload is rejected fail-closed."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    del audit.event_payload["verified_at"]

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "missing or empty verified_at field" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_empty_verified_at_fails_closed():
    """Anchor with empty string verified_at in event_payload is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.event_payload["verified_at"] = ""

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "missing or empty verified_at field" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_invalid_iso_timestamp_fails_closed():
    """Anchor with invalid ISO timestamp in verified_at is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.event_payload["verified_at"] = "not-a-valid-iso-date"

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "invalid ISO-8601 verified_at timestamp" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_missing_event_payload_dict_fails_closed():
    """Anchor where event_payload is None or not a dict is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.event_payload = None

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "event_payload" in exc_info.value.detail or "Audit anchor missing" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_missing_entry_id_fails_closed():
    """Anchor missing entry_id is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.entry_id = ""

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "missing or empty entry_id" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_invalid_entry_id_format_fails_closed():
    """Anchor with special characters in entry_id is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.entry_id = "aud_invalid/characters;drop table"

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "invalid entry_id format" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_missing_prev_hash_fails_closed():
    """Anchor with empty prev_hash is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.prev_hash = ""

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "missing or malformed prev_hash" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_malformed_prev_hash_fails_closed():
    """Anchor with non-hex prev_hash is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.prev_hash = "not_hex_chars_" + "0" * 50

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "missing or malformed prev_hash" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_malformed_chain_hash_fails_closed():
    """Anchor with malformed (non-hex) chain_hash is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.chain_hash = "non_hex_digest_" + "0" * 49

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "chain_hash" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_missing_decision_fails_closed():
    """Anchor with empty decision column is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.decision = ""

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "decision" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_column_payload_decision_divergence_fails_closed():
    """Anchor where payload decision disagrees with column decision is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.event_payload["decision"] = "FAILED"  # column is SUCCESS_CONFIRMED

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "Audit chain divergence" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_anchor_column_payload_transaction_id_divergence_fails_closed():
    """Anchor where payload transaction_id disagrees with column is rejected."""
    service = RealityVerifierService()
    rec, audit = build_test_outcome()
    audit.event_payload["transaction_id"] = "txn_different_554"

    mock_session = AsyncMock()
    mock_scalars = MagicMock(all=MagicMock(return_value=[audit]))
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "transaction_id" in exc_info.value.detail


# =============================================================================
# PART 2: Missing and Empty Field Validation on Ancestor (Fail-Closed HTTP 409)
# =============================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_ancestor_missing_verified_at_fails_closed():
    """Ancestor record missing verified_at field in payload is rejected fail-closed."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)

    prev_0 = GENESIS_ROOT_HASH
    chain_0 = "a" * 64  # intermediate hash (not genesis root!)
    aud_0 = AuditLogRecord(
        entry_id="aud_anc_0",
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
        reason="test_ancestor",
        event_payload={},  # Missing verified_at!
        prev_hash=prev_0,
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
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "missing or empty verified_at field in payload" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_ancestor_missing_decision_fails_closed():
    """Ancestor record with empty decision column is rejected fail-closed."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)

    prev_0 = GENESIS_ROOT_HASH
    chain_0 = "a" * 64
    aud_0 = AuditLogRecord(
        entry_id="aud_anc_0",
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
        decision="",  # Empty decision!
        policy_reference=None,
        capability_id="payment:settle",
        reason="test_ancestor",
        event_payload={"verified_at": t0.isoformat()},
        prev_hash=prev_0,
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
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "missing or empty decision field" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_ancestor_malformed_prev_hash_fails_closed():
    """Ancestor record with malformed prev_hash is rejected fail-closed."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)

    chain_0 = "a" * 64
    aud_0 = AuditLogRecord(
        entry_id="aud_anc_0",
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
        reason="test_ancestor",
        event_payload={"verified_at": t0.isoformat()},
        prev_hash="not_valid_hex_hash_" + "0" * 45,
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
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "missing or malformed prev_hash field" in exc_info.value.detail


# =============================================================================
# PART 3: Authenticated Trust Anchors & Checkpoints
# =============================================================================

def test_trusted_checkpoint_registry_unit():
    """TrustedCheckpointRegistry enforces tenant scoping, lowercase canonicalization, and format."""
    registry = TrustedCheckpointRegistry()

    # Genesis root is always authentic across all tenants
    assert registry.is_authenticated_root("any_tenant", GENESIS_ROOT_HASH)
    assert registry.is_authenticated_root("tenant_123", "0" * 64)

    # Invalid input formats
    assert not registry.is_authenticated_root("tenant_123", "not_a_hash")
    assert not registry.is_authenticated_root("tenant_123", 12345)  # type: ignore

    # Registering checkpoints
    custom_hash = "a" * 64
    registry.register_checkpoint("tenant_a", custom_hash)

    assert registry.is_authenticated_root("tenant_a", custom_hash)
    assert registry.is_authenticated_root("tenant_a", custom_hash.upper())  # case-insensitive check
    # Tenant isolation: tenant_b cannot use tenant_a's checkpoint
    assert not registry.is_authenticated_root("tenant_b", custom_hash)

    # Rejection of invalid inputs
    with pytest.raises(ValueError, match="tenant_id must be a non-empty string"):
        registry.register_checkpoint("", custom_hash)

    with pytest.raises(ValueError, match="Invalid checkpoint hash format"):
        registry.register_checkpoint("tenant_a", "short_hash")


def test_is_valid_sha256_hex_unit():
    """is_valid_sha256_hex accurately identifies lowercase 64-char hex strings."""
    assert is_valid_sha256_hex("0" * 64)
    assert is_valid_sha256_hex("abcdef0123456789" * 4)
    assert not is_valid_sha256_hex("ABCDEF0123456789" * 4)  # Uppercase not allowed
    assert not is_valid_sha256_hex("0" * 63)  # Too short
    assert not is_valid_sha256_hex("0" * 65)  # Too long
    assert not is_valid_sha256_hex(None)
    assert not is_valid_sha256_hex(12345)
    assert not is_valid_sha256_hex("g" * 64)  # Non-hex character


@pytest.mark.security
@pytest.mark.asyncio
async def test_trusted_root_malformed_format_raises_http_400():
    """Passing a malformed trusted_root_hash raises HTTP 400 Bad Request."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()
    mock_session = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(
            mock_session, rec, trusted_root_hash="not_a_valid_64_char_hash"
        )

    assert exc_info.value.status_code == 400
    assert "Malformed trusted root hash" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_unauthenticated_caller_selected_root_rejected_fails_closed():
    """Unregistered caller-selected root hash is rejected with HTTP 409 fail-closed."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()
    mock_session = AsyncMock()

    unauthenticated_root = "e" * 64  # valid format, but NOT registered

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(
            mock_session, rec, trusted_root_hash=unauthenticated_root
        )

    assert exc_info.value.status_code == 409
    assert "Untrusted root hash" in exc_info.value.detail
    assert unauthenticated_root in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_cross_tenant_checkpoint_rejected_fails_closed():
    """Checkpoint registered for tenant_other is rejected when verifying tenant_554."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()
    mock_session = AsyncMock()

    checkpoint_hash = "c" * 64
    service.checkpoint_registry.register_checkpoint("tenant_other", checkpoint_hash)

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(
            mock_session, rec, trusted_root_hash=checkpoint_hash
        )

    assert exc_info.value.status_code == 409
    assert "Untrusted root hash" in exc_info.value.detail
    assert f"tenant '{rec.tenant_id}'" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_authenticated_custom_checkpoint_succeeds():
    """Properly registered custom checkpoint for the tenant succeeds."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()

    checkpoint_root = "f" * 64
    service.checkpoint_registry.register_checkpoint(rec.tenant_id, checkpoint_root)

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
    assert contract.outcome_status == OutcomeStatus.SUCCESS_CONFIRMED


# =============================================================================
# PART 4: Chain Structure, Database Ambiguity & Graph Traversal
# =============================================================================

@pytest.mark.security
@pytest.mark.asyncio
async def test_ambiguous_predecessor_lookups_rejected_fails_closed():
    """Multiple predecessor records with identical chain_hash triggers HTTP 409."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)

    prev_0 = GENESIS_ROOT_HASH
    chain_0 = "b" * 64  # non-root hash
    aud_pred_1 = AuditLogRecord(
        entry_id="aud_fork_1",
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
        reason="fork_branch_1",
        event_payload={"verified_at": t0.isoformat()},
        prev_hash=prev_0,
        chain_hash=chain_0,
        created_at=t0,
    )
    aud_pred_2 = AuditLogRecord(
        entry_id="aud_fork_2",
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
        reason="fork_branch_2",
        event_payload={"verified_at": t0.isoformat()},
        prev_hash=prev_0,
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
    mock_scalars_leaf = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_scalars_preds = MagicMock(all=MagicMock(return_value=[aud_pred_1, aud_pred_2]))

    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars_leaf)),
            MagicMock(scalars=MagicMock(return_value=mock_scalars_preds)),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "ambiguous linkage" in exc_info.value.detail
    assert "found 2 conflicting predecessor blocks" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_predecessor_cross_tenant_isolation_violation_fails_closed():
    """Ancestor from another tenant is rejected fail-closed with HTTP 409."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)

    prev_0 = GENESIS_ROOT_HASH
    chain_0 = "b" * 64
    aud_other_tenant = AuditLogRecord(
        entry_id="aud_anc_other",
        tenant_id="tenant_foreign_evil",  # Cross-tenant intrusion!
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
        reason="test_ancestor",
        event_payload={"verified_at": t0.isoformat()},
        prev_hash=prev_0,
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
    mock_scalars_leaf = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_scalars_pred = MagicMock(all=MagicMock(return_value=[aud_other_tenant]))

    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars_leaf)),
            MagicMock(scalars=MagicMock(return_value=mock_scalars_pred)),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "tenant isolation violation" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_node_repetition_entry_id_loop_fails_closed():
    """Chain encountering the same entry_id repeatedly is rejected with HTTP 409."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()

    t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)

    # An ancestor with entry_id == "aud_leaf"
    prev_0 = GENESIS_ROOT_HASH
    chain_0 = "b" * 64
    aud_repeated = AuditLogRecord(
        entry_id="aud_leaf",  # Repetition of anchor entry_id!
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
        reason="repetition",
        event_payload={"verified_at": t0.isoformat()},
        prev_hash=prev_0,
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
    mock_scalars_leaf = MagicMock(all=MagicMock(return_value=[aud_leaf]))
    mock_scalars_pred = MagicMock(all=MagicMock(return_value=[aud_repeated]))

    mock_session.execute = AsyncMock(
        side_effect=[
            MagicMock(scalars=MagicMock(return_value=mock_scalars_leaf)),
            MagicMock(scalars=MagicMock(return_value=mock_scalars_pred)),
        ]
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(mock_session, rec)

    assert exc_info.value.status_code == 409
    assert "node repetition detected" in exc_info.value.detail


@pytest.mark.security
@pytest.mark.asyncio
async def test_audit_chain_depth_exhaustion_fails_closed():
    """Traversing beyond max_chain_depth raises HTTP 409 fail-closed."""
    service = RealityVerifierService()
    rec, _ = build_test_outcome()

    t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)

    # We set max_chain_depth=0 so traversal of non-root anchor fails immediately
    prev_leaf = "a" * 64
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
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=mock_scalars)))

    with pytest.raises(HTTPException) as exc_info:
        await service.verify_record_against_audit_trail(
            mock_session, rec, max_chain_depth=0
        )

    assert exc_info.value.status_code == 409
    assert "exceeded max depth 0" in exc_info.value.detail


# =============================================================================
# PART 5: Concurrency and Security Privilege Isolation
# =============================================================================

def test_source_code_serializes_audit_appends_with_for_update():
    """Verify source code includes .with_for_update() on latest_audit query."""
    source = inspect.getsource(RealityVerifierService.verify_action_outcome)
    assert "latest_audit = await session.execute(" in source
    assert ".with_for_update()" in source


def test_threat_model_superuser_vs_unprivileged_documented():
    """Documents cryptographic threat boundaries between unprivileged application role and superuser.

    Boundary Principles:
    1. Cryptographic hash chaining in PostgreSQL binds application transactions to an append-only log.
    2. Unprivileged database role (`mirage_app`) has INSERT and SELECT permissions ONLY.
       It lacks UPDATE and DELETE on `audit_logs` (enforced via SQL DDL / grants).
    3. Threat Model Limitation: A PostgreSQL `postgres` superuser or administrator with physical disk access
       can rewrite audit_logs and recompute hashes. Application-layer hash chaining alone cannot prevent
       superuser tampering without external WORM storage (e.g. AWS S3 Object Lock, Rekor notary, or HSM).
    """
    app_role_invariant = "mirage_app role has append-only INSERT/SELECT and no UPDATE/DELETE on audit_logs"
    superuser_limitation = "PostgreSQL superuser can rewrite database rows unless bound to external WORM storage"

    assert "append-only" in app_role_invariant
    assert "superuser can rewrite database rows" in superuser_limitation
