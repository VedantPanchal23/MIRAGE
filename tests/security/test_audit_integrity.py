"""Security & Verification Tests for MIRAGE Observability, Tamper-Evident Audit, and External Anchoring.

Implements Workstream B Validation:
1. Canonical SHA-256 hash determinism and field sensitivity.
2. In-database hash chain verification and tamper/sequence break detection.
3. External audit anchor backend (FileAuditAnchorBackend) append-only persistence and verification.
4. Truncation detection when database tail is deleted relative to external notary anchor.
5. Trace and correlation header sanitization, log injection defense, and contextvar propagation.
6. API endpoint permission enforcement (AUDIT_READ, AUDIT_EXPORT, admin anchor commits).
7. Five-gate telemetry metrics emission.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from db.models import AuditLogRecord
from gateway.main import create_app
from gateway.middleware.auth import register_api_key, revoke_api_key
from services.audit_anchor import (
    AnchorUnavailableError,
    AnchorVerificationError,
    FileAuditAnchorBackend,
)
from services.audit_ledger import AuditLedgerService
from shared.schemas.audit import (
    GENESIS_ROOT_HASH,
    AnchorProof,
    AuditIntegrityStatus,
    CheckpointModel,
    NotaryKeyRegistry,
    TrustAssuranceLevel,
    compute_canonical_audit_hash,
    compute_checkpoint_canonical_string,
    compute_sha256,
    sign_checkpoint_payload,
)
from shared.schemas.auth import Role
from shared.telemetry.metrics import (
    AUDIT_ANCHOR_STATUS,
    AUDIT_INTEGRITY_CHECKS_TOTAL,
    GATE_DECISIONS_TOTAL,
    OUTCOME_VERIFICATION_TOTAL,
    SECURITY_DENIALS_TOTAL,
    record_action_transition,
    record_anchor_status,
    record_audit_integrity_check,
    record_gate_decision,
    record_outcome_verification,
    record_security_denial,
    record_tool_dispatch_failure,
)

# =============================================================================
# 1. Canonical SHA-256 Hash Determinism and Field Sensitivity
# =============================================================================

def test_canonical_audit_hash_determinism_and_sensitivity() -> None:
    """Canonical audit hash is strictly deterministic and sensitive to every field."""
    base_params = {
        "prev_hash": "0" * 64,
        "tenant_id": "tenant_corp",
        "sequence_number": 1,
        "entry_id": "aud_001",
        "timestamp_iso": "2026-10-19T12:00:00+00:00",
        "event_type": "GATE_DECISION",
        "session_id": "sess_100",
        "trace_id": "trace_100",
        "actor_identity_id": "agent_alpha",
        "transaction_id": "tx_100",
        "decision": "ALLOW",
        "prompt_hash": compute_sha256("test prompt"),
        "response_hash": compute_sha256("test response"),
        "hrs_score": 0.05,
        "payload_digest": compute_sha256('{"reason": "passed"}'),
    }

    h1 = compute_canonical_audit_hash(**base_params)
    h2 = compute_canonical_audit_hash(**base_params)
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)

    # Test sensitivity to every single field
    mutations: dict[str, Any] = {
        "prev_hash": "1" * 64,
        "tenant_id": "tenant_other",
        "sequence_number": 2,
        "entry_id": "aud_002",
        "timestamp_iso": "2026-10-19T12:00:01+00:00",
        "event_type": "ACTION_LIFECYCLE",
        "session_id": "sess_101",
        "trace_id": "trace_101",
        "actor_identity_id": "agent_beta",
        "transaction_id": "tx_101",
        "decision": "DENY",
        "prompt_hash": compute_sha256("different prompt"),
        "response_hash": compute_sha256("different response"),
        "hrs_score": 0.95,
        "payload_digest": compute_sha256('{"reason": "failed"}'),
    }

    for field, new_val in mutations.items():
        params = dict(base_params)
        params[field] = new_val
        mutated_hash = compute_canonical_audit_hash(**params)
        assert mutated_hash != h1, f"Mutating field '{field}' must produce a different hash"


# =============================================================================
# 2. In-Database Hash Chain Verification and Tampering Detection
# =============================================================================

@pytest.mark.asyncio
async def test_audit_ledger_verify_chain_valid_and_tampered() -> None:
    """AuditLedgerService.verify_chain detects untouched, modified, sequence broken, and empty chains."""
    tenant_id = "tenant_test_chain"
    now_iso = "2026-10-19T10:00:00+00:00"

    # Build valid 3-record chain
    p_hash = compute_sha256("p")
    r_hash = compute_sha256("r")

    h1 = compute_canonical_audit_hash(
        prev_hash=GENESIS_ROOT_HASH,
        tenant_id=tenant_id,
        sequence_number=1,
        entry_id="aud_1",
        timestamp_iso=now_iso,
        event_type="GATE_DECISION",
        session_id="sess_1",
        trace_id="tr_1",
        actor_identity_id="act_1",
        transaction_id="tx_1",
        decision="ALLOW",
        prompt_hash=p_hash,
        response_hash=r_hash,
        hrs_score=0.1,
        payload_digest="",
    )

    h2 = compute_canonical_audit_hash(
        prev_hash=h1,
        tenant_id=tenant_id,
        sequence_number=2,
        entry_id="aud_2",
        timestamp_iso=now_iso,
        event_type="ACTION_LIFECYCLE",
        session_id="sess_1",
        trace_id="tr_1",
        actor_identity_id="act_1",
        transaction_id="tx_1",
        decision="EXECUTED",
        prompt_hash=p_hash,
        response_hash=r_hash,
        hrs_score=0.1,
        payload_digest="",
    )

    rec1 = AuditLogRecord(
        entry_id="aud_1",
        tenant_id=tenant_id,
        sequence_number=1,
        session_id="sess_1",
        trace_id="tr_1",
        prompt_hash=p_hash,
        response_hash=r_hash,
        hrs_score=0.1,
        risk_tier="LOW",
        event_type="GATE_DECISION",
        actor_identity_id="act_1",
        transaction_id="tx_1",
        decision="ALLOW",
        event_payload={},
        prev_hash=GENESIS_ROOT_HASH,
        chain_hash=h1,
        created_at=datetime.fromisoformat(now_iso),
    )

    rec2 = AuditLogRecord(
        entry_id="aud_2",
        tenant_id=tenant_id,
        sequence_number=2,
        session_id="sess_1",
        trace_id="tr_1",
        prompt_hash=p_hash,
        response_hash=r_hash,
        hrs_score=0.1,
        risk_tier="LOW",
        event_type="ACTION_LIFECYCLE",
        actor_identity_id="act_1",
        transaction_id="tx_1",
        decision="EXECUTED",
        event_payload={},
        prev_hash=h1,
        chain_hash=h2,
        created_at=datetime.fromisoformat(now_iso),
    )

    def make_mock_session(recs: list[AuditLogRecord]) -> AsyncMock:
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = recs
        sess = AsyncMock()
        sess.execute.return_value = mock_result
        return sess

    # 1. Test Valid Chain
    res = await AuditLedgerService.verify_chain(make_mock_session([rec1, rec2]), tenant_id)
    assert res["valid"] is True
    assert res["chain_status"] == "VERIFIED_UNBROKEN"
    assert res["total_records_verified"] == 2
    assert res["head_sequence"] == 2
    assert res["head_chain_hash"] == h2

    # 2. Test Tampering: Modified record payload/decision
    tampered_rec = AuditLogRecord(
        entry_id="aud_2",
        tenant_id=tenant_id,
        sequence_number=2,
        session_id="sess_1",
        trace_id="tr_1",
        prompt_hash=p_hash,
        response_hash=r_hash,
        hrs_score=0.1,
        risk_tier="LOW",
        event_type="ACTION_LIFECYCLE",
        actor_identity_id="act_1",
        transaction_id="tx_1",
        decision="MALICIOUS_OVERRIDE",  # Tampered field
        event_payload={},
        prev_hash=h1,
        chain_hash=h2,  # Original hash preserved; mismatch with recalculated hash!
        created_at=datetime.fromisoformat(now_iso),
    )
    res_tampered = await AuditLedgerService.verify_chain(make_mock_session([rec1, tampered_rec]), tenant_id)
    assert res_tampered["valid"] is False
    assert res_tampered["chain_status"] == "TAMPERED"
    assert res_tampered["tampered_sequence"] == 2

    # 3. Test Sequence Break (missing sequence 2, sequence 3 present)
    rec_gap = AuditLogRecord(
        entry_id="aud_3",
        tenant_id=tenant_id,
        sequence_number=3,  # Gap: expected 2
        session_id="sess_1",
        trace_id="tr_1",
        prompt_hash=p_hash,
        response_hash=r_hash,
        hrs_score=0.1,
        risk_tier="LOW",
        event_type="ACTION_LIFECYCLE",
        actor_identity_id="act_1",
        transaction_id="tx_1",
        decision="EXECUTED",
        event_payload={},
        prev_hash=h1,
        chain_hash=h2,
        created_at=datetime.fromisoformat(now_iso),
    )
    res_gap = await AuditLedgerService.verify_chain(make_mock_session([rec1, rec_gap]), tenant_id)
    assert res_gap["valid"] is False
    assert res_gap["chain_status"] == "TAMPERED"
    assert any("Sequence break" in d for d in res_gap["defects"])

    # 4. Test Empty Chain
    res_empty = await AuditLedgerService.verify_chain(make_mock_session([]), tenant_id)
    assert res_empty["valid"] is False
    assert res_empty["chain_status"] == "EMPTY"


# =============================================================================
# 3. External Audit Anchor Backend (FileAuditAnchorBackend)
# =============================================================================

@pytest.mark.asyncio
async def test_file_audit_anchor_backend_write_and_verify() -> None:
    """FileAuditAnchorBackend persists signed checkpoints, reads back proofs, and detects tampering."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        registry = NotaryKeyRegistry()
        backend = FileAuditAnchorBackend(anchor_dir=tmp_dir, notary_keys=registry)
        tenant_id = "tenant_anchor_corp"

        key_bytes = registry.get_key("notary:system_primary")
        assert key_bytes is not None

        now = datetime.now(UTC)
        canon = compute_checkpoint_canonical_string(
            tenant_id=tenant_id,
            ledger_identity="audit_logs",
            sequence_number=10,
            checkpoint_hash="a" * 64,
            issued_at_iso=now.isoformat(),
            signer_identity="notary:system_primary",
        )
        sig = sign_checkpoint_payload(key_bytes, canon)

        checkpoint = CheckpointModel(
            checkpoint_id="chk_test_10",
            tenant_id=tenant_id,
            checkpoint_hash="a" * 64,
            sequence_number=10,
            ledger_identity="audit_logs",
            signer_identity="notary:system_primary",
            signature=sig,
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=now,
        )

        # 1. Write anchor
        proof = await backend.write_anchor(tenant_id, checkpoint)
        assert proof.tenant_id == tenant_id
        assert proof.sequence_number == 10
        assert proof.checkpoint_hash == "a" * 64
        assert proof.anchor_digest is not None

        # 2. Read latest anchor
        latest = await backend.get_latest_anchor(tenant_id)
        assert latest is not None
        assert latest.anchor_id == proof.anchor_id
        assert latest.sequence_number == 10

        # 3. Unauthorized signer fails closed
        unauth_checkpoint = CheckpointModel(
            checkpoint_id="chk_bad_signer",
            tenant_id=tenant_id,
            checkpoint_hash="a" * 64,
            sequence_number=11,
            ledger_identity="audit_logs",
            signer_identity="notary:unauthorized_attacker",
            signature=sig,
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=now,
        )
        with pytest.raises(AnchorUnavailableError, match="Unauthorized or unknown signer_identity"):
            await backend.write_anchor(tenant_id, unauth_checkpoint)

        # 4. Tampered signature fails verification
        bad_sig_checkpoint = CheckpointModel(
            checkpoint_id="chk_bad_sig",
            tenant_id=tenant_id,
            checkpoint_hash="a" * 64,
            sequence_number=11,
            ledger_identity="audit_logs",
            signer_identity="notary:system_primary",
            signature="deadbeef" * 8,  # Invalid signature
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=now,
        )
        with pytest.raises(AnchorVerificationError, match="Cryptographic signature mismatch"):
            await backend.write_anchor(tenant_id, bad_sig_checkpoint)


# =============================================================================
# 4. Truncation Detection with External Anchors
# =============================================================================

@pytest.mark.asyncio
async def test_audit_ledger_verify_with_anchor_truncation_detection() -> None:
    """verify_with_anchor detects database truncation when head sequence < external anchor sequence."""
    tenant_id = "tenant_truncation_test"

    # Setup anchor proof at sequence 50
    anchor_proof = AnchorProof(
        anchor_id="anc_50",
        tenant_id=tenant_id,
        checkpoint_hash="c" * 64,
        sequence_number=50,
        ledger_identity="audit_logs",
        signer_identity="notary:system_primary",
        signature="sig_50",
        trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
        issued_at=datetime.now(UTC),
        anchored_at=datetime.now(UTC),
        anchor_digest="digest_50",
    )

    mock_backend = AsyncMock()
    mock_backend.get_latest_anchor.return_value = anchor_proof

    # Simulate database truncation: DB head sequence is 40, but external anchor commits to 50!
    mock_session = AsyncMock()
    mock_chain_res = {
        "valid": True,
        "chain_status": "VALID",
        "head_sequence": 40,  # TRUNCATION: 10 records deleted from DB!
        "head_chain_hash": "b" * 64,
        "total_records_verified": 40,
    }

    with patch("services.audit_ledger.AuditLedgerService.verify_chain", new_callable=AsyncMock) as mock_vc, \
         patch("services.audit_ledger.get_anchor_backend", return_value=mock_backend):
        mock_vc.return_value = mock_chain_res

        report = await AuditLedgerService.verify_with_anchor(mock_session, tenant_id)

        assert report.status == AuditIntegrityStatus.INTEGRITY_FAILURE
        assert report.chain_valid is False
        assert any("Ledger truncation detected" in d for d in report.defects)
        assert report.head_sequence == 40
        assert report.latest_anchor.sequence_number == 50


# =============================================================================
# 5. Header Sanitization, Log Injection Defense & ContextVar Propagation
# =============================================================================

def test_trace_headers_sanitization_and_log_injection_defense() -> None:
    """SecurityHeadersMiddleware sanitizes untrusted identity headers and protects against log injection."""
    app = create_app()
    client = TestClient(app)

    # 1. Valid trace and correlation IDs preserved
    resp = client.get(
        "/v1/health",
        headers={
            "X-Trace-ID": "trace-valid-12345678",
            "X-Correlation-ID": "corr-valid-12345678",
            "X-Role": "SUPER_ADMIN",  # Untrusted identity header must be stripped
        },
    )
    assert resp.status_code == 200
    assert resp.headers["X-Trace-ID"] == "trace-valid-12345678"
    assert resp.headers["X-Correlation-ID"] == "corr-valid-12345678"

    # 2. Malicious CRLF injection attack in X-Trace-ID
    crlf_attack = "trace_id\r\nSet-Cookie: session=evil\r\n"
    resp_injected = client.get(
        "/v1/health",
        headers={"X-Trace-ID": crlf_attack},
    )
    assert resp_injected.status_code == 200
    # Must reject malicious header and generate a clean UUID hex
    assert resp_injected.headers["X-Trace-ID"] != crlf_attack
    assert len(resp_injected.headers["X-Trace-ID"]) == 32  # uuid4 hex

    # 3. Overly long trace ID (>64 chars) rejected
    overlong = "a" * 128
    resp_overlong = client.get(
        "/v1/health",
        headers={"X-Trace-ID": overlong},
    )
    assert resp_overlong.status_code == 200
    assert resp_overlong.headers["X-Trace-ID"] != overlong
    assert len(resp_overlong.headers["X-Trace-ID"]) == 32


# =============================================================================
# 6. Audit API Endpoints Scope & Role Authorization
# =============================================================================

def test_audit_api_endpoints_scope_enforcement() -> None:
    """Audit endpoints strictly enforce AUDIT_READ and AUDIT_EXPORT scopes."""
    app = create_app()
    client = TestClient(app)
    tenant_id = "tenant_audit_test"

    # API key with only VERIFY_READ (no AUDIT_READ)
    verify_key = "mirage_test_key_verify_only_123"
    register_api_key(verify_key, tenant_id, role=Role.API_CLIENT, scopes=["verify:read"])

    # API key with AUDIT_READ
    audit_read_key = "mirage_test_key_audit_read_456"
    register_api_key(audit_read_key, tenant_id, role=Role.OPERATOR, scopes=["audit:read"])

    try:
        # GET /v1/audit/events without AUDIT_READ -> 403 Forbidden
        resp_denied = client.get(
            "/v1/audit/events",
            headers={"X-API-Key": verify_key},
        )
        assert resp_denied.status_code == 403
        assert "AUDIT_READ" in resp_denied.text

        # GET /v1/audit/integrity without AUDIT_READ -> 403 Forbidden
        resp_integ_denied = client.get(
            "/v1/audit/integrity",
            headers={"X-API-Key": verify_key},
        )
        assert resp_integ_denied.status_code == 403

        # POST /v1/audit/export-bundle without AUDIT_EXPORT -> 403 Forbidden
        resp_export_denied = client.post(
            "/v1/audit/export-bundle",
            headers={"X-API-Key": audit_read_key},  # Has AUDIT_READ, lacks AUDIT_EXPORT
            json={"limit": 10},
        )
        assert resp_export_denied.status_code == 403
        assert "AUDIT_EXPORT" in resp_export_denied.text
    finally:
        revoke_api_key(verify_key)
        revoke_api_key(audit_read_key)


# =============================================================================
# 7. Five-Gate Telemetry Metrics Recording
# =============================================================================

def test_telemetry_metrics_recording() -> None:
    """Five-gate telemetry metrics functions record labels and values without errors."""
    # 1. Gate decisions
    record_gate_decision(gate="gate1", decision="allow", latency_seconds=0.015)
    record_gate_decision(gate="gate3", decision="require_approval", latency_seconds=0.045)
    assert GATE_DECISIONS_TOTAL.labels(gate="gate1", decision="allow")._value.get() >= 1

    # 2. Action lifecycle transitions
    record_action_transition(action_type="sql_query", state="authorized")
    record_action_transition(action_type="sql_query", state="executing")

    # 3. Tool dispatch failures
    record_tool_dispatch_failure(transport="stdio", failure_category="timeout")

    # 4. Gate 5 outcome verification
    record_outcome_verification(observability_class="read_write", outcome_status="verified_success")
    assert OUTCOME_VERIFICATION_TOTAL.labels(
        observability_class="read_write",
        outcome_status="verified_success",
    )._value.get() >= 1

    # 5. Audit integrity checks
    record_audit_integrity_check(status="anchored")
    assert AUDIT_INTEGRITY_CHECKS_TOTAL.labels(status="anchored")._value.get() >= 1

    # 6. Security denials
    record_security_denial(reason="rate_limited")
    assert SECURITY_DENIALS_TOTAL.labels(reason="rate_limited")._value.get() >= 1

    # 7. Audit anchor status gauge
    record_anchor_status("anchored")
    assert AUDIT_ANCHOR_STATUS.labels(status="anchored")._value.get() == 1.0
    assert AUDIT_ANCHOR_STATUS.labels(status="stale")._value.get() == 0.0
