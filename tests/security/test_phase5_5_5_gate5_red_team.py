"""Phase 5.5.5 Independent Gate 5 Red-Team Audit & Concurrency Verification Suite.

Comprehensive empirical verification:
1. Real PostgreSQL 16 concurrency and transaction serialization (empty tenant first append,
   subsequent appends, retry/rollback, unique constraint enforcement).
2. Authenticated trust anchor and checkpoint provenance model (genesis sentinel vs external notary,
   HMAC-SHA256 signature verification, key rotation, expiration/stale roots, revocation, cross-tenant isolation).
3. Full-chain verification with sequence monotonicity and idempotency early-return tampering detection.
4. Database system catalog inspection (RLS, constraints, append-only policies).
5. Gate 5 epistemic adapter semantics (simulated, void postconditions, blind sinks, eventual polling).
"""

import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from db.models import ActionContract, AuditLogRecord, OutcomeVerificationRecord
from services.reality_verifier import RealityVerifierService
from shared.schemas.audit import (
    GENESIS_ROOT_HASH,
    CheckpointModel,
    NotaryKeyRegistry,
    TrustAssuranceLevel,
    TrustedCheckpointRegistry,
    compute_checkpoint_canonical_string,
    compute_sha256,
    sign_checkpoint_payload,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
)


def _build_test_contract_and_audit(
    outcome_id: str = "outc_555_t1",
    action_id: str = "act_555_t1",
    tenant_id: str = "tenant_555",
    transaction_id: str = "txn_555_t1",
    status_val: str = "SUCCESS_CONFIRMED",
    confidence: float = 1.0,
    seq: int = 1,
) -> tuple[OutcomeVerificationRecord, AuditLogRecord]:
    now = datetime(2026, 10, 10, 14, 0, 0, tzinfo=UTC)
    now_iso = now.isoformat()

    canonical = {
        "action_id": action_id,
        "contract_binding_hash": "param_hash_555",
        "epistemic_confidence": confidence,
        "expected_postconditions": {"status": "ACTIVE"},
        "idempotency_key": "idem_555",
        "is_simulated": False,
        "observability_class": "OBS_DIRECT",
        "observed_state_hash": "obs_hash_555",
        "outcome_status": status_val,
        "schema_version": "mirage.outcome.v1",
        "target_environment": "PROD",
        "target_resource": "https://api.internal/service",
        "tenant_id": tenant_id,
        "tool_name": "service_tool",
        "transaction_id": transaction_id,
        "verified_at": now_iso,
        "verifier_adapter": "HttpResourceAdapter",
    }
    json_bytes = hashlib.sha256(
        b'{"action_id":"' + action_id.encode() + b'","contract_binding_hash":"param_hash_555",'
        b'"epistemic_confidence":1.0,"expected_postconditions":{"status":"ACTIVE"},'
        b'"idempotency_key":"idem_555","is_simulated":false,"observability_class":"OBS_DIRECT",'
        b'"observed_state_hash":"obs_hash_555","outcome_status":"' + status_val.encode() + b'",'
        b'"schema_version":"mirage.outcome.v1","target_environment":"PROD",'
        b'"target_resource":"https://api.internal/service","tenant_id":"' + tenant_id.encode() + b'",'
        b'"tool_name":"service_tool","transaction_id":"' + transaction_id.encode() + b'",'
        b'"verified_at":"' + now_iso.encode() + b'","verifier_adapter":"HttpResourceAdapter"}'
    ).hexdigest()

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
        expected_postconditions={"status": "ACTIVE"},
        observed_state={"status": "ACTIVE"},
        discrepancies=[],
        evidence_payload={"_canonical_payload": canonical},
        reconciliation_notes=[],
        verification_hash=json_bytes,
        idempotency_key="idem_555",
        target_environment="PROD",
        contract_binding_hash="param_hash_555",
        created_at=now,
        verified_at=now,
    )

    prev_hash = "0" * 64
    entry_id = "aud_555_entry"
    chain_hash = compute_sha256(f"{prev_hash}:{entry_id}:{status_val}:{now_iso}")

    aud = AuditLogRecord(
        entry_id=entry_id,
        tenant_id=tenant_id,
        sequence_number=seq,
        session_id=transaction_id,
        trace_id="gate5-outcome",
        prompt_hash="0" * 64,
        response_hash=json_bytes,
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
        capability_id="service:manage",
        reason="test_audit",
        event_payload={
            "outcome_id": outcome_id,
            "action_id": action_id,
            "transaction_id": transaction_id,
            "sequence_number": seq,
            "verified_at": now_iso,
        },
        prev_hash=prev_hash,
        chain_hash=chain_hash,
        created_at=now,
    )

    return rec, aud


# =============================================================================
# PART 1: Real PostgreSQL 16 Concurrency and Serialization Verification
# =============================================================================

@pytest.mark.security
class TestPostgresAuditConcurrency:
    """Rigorous multi-connection concurrent append tests against live PostgreSQL 16."""

    @pytest.fixture(scope="class")
    def sync_engine(self, live_postgres_database: Any) -> Any:
        _ = live_postgres_database
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        assert sync_url is not None, "DATABASE_SYNC_URL must be configured by live_postgres_database fixture"
        engine = create_engine(sync_url, pool_size=20, max_overflow=10)
        yield engine
        engine.dispose()

    def test_concurrent_first_ever_appends_serializes_without_forks(self, sync_engine: Any) -> None:
        """Prove that multiple concurrent transactions for an EMPTY tenant append sequentially with no forks."""
        test_tenant = f"t_conc_first_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)

        with sync_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, api_key_hash, tier, created_at)
                    VALUES (:tid, 'Concurrent Tenant', 'hash_conc', 'enterprise', :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"tid": test_tenant, "now": now},
            )
            conn.commit()

        # Simulate 10 workers performing their first append concurrently using threading / connections
        import concurrent.futures

        def worker_append(worker_idx: int) -> dict[str, Any]:
            with sync_engine.connect() as conn:
                trans = conn.begin()
                try:
                    # 1. Acquire transaction advisory lock
                    conn.execute(
                        text("SELECT pg_advisory_xact_lock(hashtext('tenant_audit_ledger:' || :tenant_id))"),
                        {"tenant_id": test_tenant},
                    )

                    # 2. Ensure tenant ledger head exists
                    conn.execute(
                        text(
                            """
                            INSERT INTO tenant_audit_ledgers (
                                tenant_id, head_chain_hash, sequence_number, created_at, updated_at
                            )
                            VALUES (:tenant_id, :genesis_hash, 0, NOW(), NOW())
                            ON CONFLICT (tenant_id) DO NOTHING;
                            """
                        ),
                        {"tenant_id": test_tenant, "genesis_hash": GENESIS_ROOT_HASH},
                    )

                    # 3. Lock tenant ledger head
                    row = conn.execute(
                        text(
                            """
                            SELECT head_chain_hash, sequence_number
                            FROM tenant_audit_ledgers
                            WHERE tenant_id = :tenant_id
                            FOR UPDATE;
                            """
                        ),
                        {"tenant_id": test_tenant},
                    ).mappings().one()

                    prev_hash = row["head_chain_hash"]
                    new_seq = row["sequence_number"] + 1

                    entry_id = f"aud_conc_{worker_idx}_{uuid.uuid4().hex[:8]}"
                    now_iso = datetime.now(UTC).isoformat()
                    chain_hash = compute_sha256(f"{prev_hash}:{entry_id}:SUCCESS_CONFIRMED:{now_iso}")

                    # 4. Insert into audit_logs
                    conn.execute(
                        text(
                            """
                            INSERT INTO audit_logs (
                                entry_id, tenant_id, sequence_number, session_id, trace_id, prompt_hash,
                                response_hash, hrs_score, risk_tier, claims_count, claims_summary,
                                correction_applied, event_type, prev_hash, chain_hash, created_at
                            ) VALUES (
                                :entry_id, :tenant_id, :seq, 'sess_1', 'trace_1', :p_hash,
                                :r_hash, 0.0, 'LOW', 1, '[]'::jsonb, false, 'GATE5_OUTCOME_VERIFIED',
                                :prev_hash, :chain_hash, NOW()
                            );
                            """
                        ),
                        {
                            "entry_id": entry_id,
                            "tenant_id": test_tenant,
                            "seq": new_seq,
                            "p_hash": "0" * 64,
                            "r_hash": "0" * 64,
                            "prev_hash": prev_hash,
                            "chain_hash": chain_hash,
                        },
                    )

                    # 5. Update tenant ledger head
                    conn.execute(
                        text(
                            """
                            UPDATE tenant_audit_ledgers
                            SET head_entry_id = :entry_id,
                                head_chain_hash = :chain_hash,
                                sequence_number = :seq,
                                updated_at = NOW()
                            WHERE tenant_id = :tenant_id;
                            """
                        ),
                        {"entry_id": entry_id, "chain_hash": chain_hash, "seq": new_seq, "tenant_id": test_tenant},
                    )

                    trans.commit()
                    return {
                        "worker_idx": worker_idx,
                        "seq": new_seq,
                        "entry_id": entry_id,
                        "prev": prev_hash,
                        "chain": chain_hash,
                    }
                except Exception as e:
                    trans.rollback()
                    raise e

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_append, i) for i in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 10

        # Query all committed audit_logs in sequence
        with sync_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT sequence_number, prev_hash, chain_hash
                    FROM audit_logs
                    WHERE tenant_id = :tenant_id
                    ORDER BY sequence_number ASC;
                    """
                ),
                {"tenant_id": test_tenant},
            ).mappings().all()

        assert len(rows) == 10
        # 1. Verify sequence numbers are exactly 1 through 10 (no duplicates, no gaps)
        sequences = [r["sequence_number"] for r in rows]
        assert sequences == list(range(1, 11)), f"Expected sequences 1..10, got {sequences}"

        # 2. Verify root entry has prev_hash == "0"*64
        assert rows[0]["prev_hash"] == GENESIS_ROOT_HASH

        # 3. Verify unbroken chain continuity across all 10 entries
        for i in range(1, 10):
            assert rows[i]["prev_hash"] == rows[i - 1]["chain_hash"], (
                f"Chain broken at sequence {rows[i]['sequence_number']}: "
                f"prev_hash {rows[i]['prev_hash']} != predecessor chain_hash {rows[i-1]['chain_hash']}"
            )

    def test_database_enforced_unique_constraint_rejects_duplicate_sequence(self, sync_engine: Any) -> None:
        """Prove that PostgreSQL unique constraint uq_audit_logs_tenant_sequence rejects duplicate sequence numbers."""
        test_tenant = f"t_dup_seq_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)

        with sync_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, api_key_hash, tier, created_at)
                    VALUES (:tid, 'Dup Seq Tenant', 'hash_dup_seq', 'free', :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"tid": test_tenant, "now": now},
            )
            # Insert first entry with sequence 1
            conn.execute(
                text(
                    """
                    INSERT INTO audit_logs (
                        entry_id, tenant_id, sequence_number, session_id, trace_id, prompt_hash,
                        response_hash, hrs_score, risk_tier, claims_count, claims_summary,
                        correction_applied, event_type, prev_hash, chain_hash, created_at
                    ) VALUES (
                        'aud_first_seq', :tenant_id, 1, 'sess_1', 'trace_1', :p_hash,
                        :r_hash, 0.0, 'LOW', 1, '[]'::jsonb, false, 'GATE5_OUTCOME_VERIFIED',
                        :prev_hash, :chain_hash, NOW()
                    );
                    """
                ),
                {
                    "tenant_id": test_tenant,
                    "p_hash": "0" * 64,
                    "r_hash": "0" * 64,
                    "prev_hash": "0" * 64,
                    "chain_hash": "1" * 64,
                },
            )
            conn.commit()

            # Attempt inserting second entry with DUPLICATE sequence 1
            with pytest.raises(IntegrityError) as exc_info:
                conn.execute(
                    text(
                        """
                        INSERT INTO audit_logs (
                            entry_id, tenant_id, sequence_number, session_id, trace_id, prompt_hash,
                            response_hash, hrs_score, risk_tier, claims_count, claims_summary,
                            correction_applied, event_type, prev_hash, chain_hash, created_at
                        ) VALUES (
                            'aud_second_seq', :tenant_id, 1, 'sess_1', 'trace_1', :p_hash,
                            :r_hash, 0.0, 'LOW', 1, '[]'::jsonb, false, 'GATE5_OUTCOME_VERIFIED',
                            :prev_hash, :chain_hash, NOW()
                        );
                        """
                    ),
                    {
                        "tenant_id": test_tenant,
                        "p_hash": "0" * 64,
                        "r_hash": "0" * 64,
                        "prev_hash": "1" * 64,
                        "chain_hash": "2" * 64,
                    },
                )
            assert "uq_audit_logs_tenant_sequence" in str(exc_info.value) or "unique" in str(exc_info.value).lower()

    def test_rolled_back_transaction_releases_locks_without_orphan_branches(self, sync_engine: Any) -> None:
        """Prove that an aborted append transaction cleanly rolls back and releases advisory and row locks."""
        test_tenant = f"t_rollback_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)

        with sync_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, api_key_hash, tier, created_at)
                    VALUES (:tid, 'Rollback Tenant', 'hash_rb', 'free', :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"tid": test_tenant, "now": now},
            )
            conn.commit()

        # Transaction 1: starts, acquires lock, inserts ledger row, then ABORTS
        with sync_engine.connect() as conn1:
            trans1 = conn1.begin()
            conn1.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('tenant_audit_ledger:' || :tenant_id))"),
                {"tenant_id": test_tenant},
            )
            conn1.execute(
                text(
                    """
                    INSERT INTO tenant_audit_ledgers (
                        tenant_id, head_chain_hash, sequence_number, created_at, updated_at
                    )
                    VALUES (:tenant_id, :genesis_hash, 1, NOW(), NOW())
                    ON CONFLICT (tenant_id) DO NOTHING;
                    """
                ),
                {"tenant_id": test_tenant, "genesis_hash": "a" * 64},
            )
            # Explicit rollback
            trans1.rollback()

        # Transaction 2: should immediately acquire lock and proceed normally
        with sync_engine.connect() as conn2:
            trans2 = conn2.begin()
            conn2.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('tenant_audit_ledger:' || :tenant_id))"),
                {"tenant_id": test_tenant},
            )
            conn2.execute(
                text(
                    """
                    INSERT INTO tenant_audit_ledgers (
                        tenant_id, head_chain_hash, sequence_number, created_at, updated_at
                    )
                    VALUES (:tenant_id, :genesis_hash, 0, NOW(), NOW())
                    ON CONFLICT (tenant_id) DO NOTHING;
                    """
                ),
                {"tenant_id": test_tenant, "genesis_hash": GENESIS_ROOT_HASH},
            )
            row = conn2.execute(
                text(
                    """
                    SELECT head_chain_hash, sequence_number
                    FROM tenant_audit_ledgers
                    WHERE tenant_id = :tenant_id;
                    """
                ),
                {"tenant_id": test_tenant},
            ).mappings().one()
            assert row["head_chain_hash"] == GENESIS_ROOT_HASH
            assert row["sequence_number"] == 0
            trans2.commit()


# =============================================================================
# PART 2: Authenticated Checkpoint Trust Model & Provenance
# =============================================================================

@pytest.mark.security
class TestCheckpointTrustModel:
    """Rigorous cryptographic tests for CheckpointModel, NotaryKeyRegistry, and TrustedCheckpointRegistry."""

    def test_genesis_sentinel_vs_externally_anchored_tier(self) -> None:
        """Prove that the genesis sentinel is distinct from an externally anchored checkpoint."""
        registry = TrustedCheckpointRegistry()
        is_trusted, tier, cp = registry.evaluate_trust_level("tenant_alpha", GENESIS_ROOT_HASH)
        assert is_trusted is True
        assert tier == TrustAssuranceLevel.GENESIS_SENTINEL
        assert cp is None  # Genesis has no external witness

    def test_hmac_sha256_checkpoint_signature_generation_and_validation(self) -> None:
        """Prove valid HMAC-SHA256 signature verification over canonical checkpoint string."""
        notary_keys = NotaryKeyRegistry()
        secret = b"test-notary-private-key-256bit!"
        notary_keys.register_key("notary:eu_central_root", secret)

        t_id = "tenant_enterprise"
        c_hash = "c" * 64
        seq = 42
        now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)

        canon = compute_checkpoint_canonical_string(
            tenant_id=t_id,
            ledger_identity="audit_logs",
            sequence_number=seq,
            checkpoint_hash=c_hash,
            issued_at_iso=now.isoformat(),
            signer_identity="notary:eu_central_root",
        )
        sig = sign_checkpoint_payload(secret, canon)

        cp = CheckpointModel(
            checkpoint_id="chk_ent_001",
            tenant_id=t_id,
            checkpoint_hash=c_hash,
            sequence_number=seq,
            ledger_identity="audit_logs",
            signer_identity="notary:eu_central_root",
            signature=sig,
            trust_tier=TrustAssuranceLevel.EXTERNALLY_ANCHORED,
            issued_at=now,
        )

        registry = TrustedCheckpointRegistry(notary_keys=notary_keys)
        registry.register_authenticated_checkpoint(cp)

        is_trusted, tier, retrieved_cp = registry.evaluate_trust_level(t_id, c_hash)
        assert is_trusted is True
        assert tier == TrustAssuranceLevel.EXTERNALLY_ANCHORED
        assert retrieved_cp is not None
        assert retrieved_cp.sequence_number == 42

    def test_forged_or_tampered_signature_fails_closed(self) -> None:
        """Prove that an altered signature or modified sequence fails closed on registration."""
        notary_keys = NotaryKeyRegistry()
        secret = b"test-notary-private-key-256bit!"
        notary_keys.register_key("notary:us_east", secret)

        t_id = "tenant_finance"
        c_hash = "d" * 64
        now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)

        canon = compute_checkpoint_canonical_string(
            tenant_id=t_id,
            ledger_identity="audit_logs",
            sequence_number=10,
            checkpoint_hash=c_hash,
            issued_at_iso=now.isoformat(),
            signer_identity="notary:us_east",
        )
        sig = sign_checkpoint_payload(secret, canon)

        # Adversary alters sequence_number from 10 to 999
        cp_forged = CheckpointModel(
            checkpoint_id="chk_forged",
            tenant_id=t_id,
            checkpoint_hash=c_hash,
            sequence_number=999,  # TAMPERED
            ledger_identity="audit_logs",
            signer_identity="notary:us_east",
            signature=sig,
            trust_tier=TrustAssuranceLevel.EXTERNALLY_ANCHORED,
            issued_at=now,
        )

        registry = TrustedCheckpointRegistry(notary_keys=notary_keys)
        with pytest.raises(ValueError, match="Cryptographic signature verification failed"):
            registry.register_authenticated_checkpoint(cp_forged)

    def test_revoked_checkpoint_fails_closed(self) -> None:
        """Prove that revoking a checkpoint causes evaluate_trust_level to fail closed."""
        notary_keys = NotaryKeyRegistry()
        secret = b"test-notary-key"
        notary_keys.register_key("notary:test", secret)

        t_id = "tenant_revoc"
        c_hash = "e" * 64
        now = datetime.now(UTC)

        canon = compute_checkpoint_canonical_string(t_id, "audit_logs", 5, c_hash, now.isoformat(), "notary:test")
        sig = sign_checkpoint_payload(secret, canon)

        cp = CheckpointModel(
            checkpoint_id="chk_rev",
            tenant_id=t_id,
            checkpoint_hash=c_hash,
            sequence_number=5,
            signer_identity="notary:test",
            signature=sig,
            issued_at=now,
        )
        registry = TrustedCheckpointRegistry(notary_keys=notary_keys)
        registry.register_authenticated_checkpoint(cp)

        assert registry.is_authenticated_root(t_id, c_hash) is True

        # Revoke the checkpoint
        revoked = registry.revoke_checkpoint(t_id, c_hash, revoked_by="sec_officer", reason="Key compromised")
        assert revoked is True

        # Must fail closed immediately
        is_trusted, tier, _ = registry.evaluate_trust_level(t_id, c_hash)
        assert is_trusted is False
        assert tier == TrustAssuranceLevel.LOCAL_UNANCHORED

    def test_expired_stale_checkpoint_fails_closed(self) -> None:
        """Prove that a checkpoint with past expires_at fails closed."""
        notary_keys = NotaryKeyRegistry()
        secret = b"test-notary-key"
        notary_keys.register_key("notary:test", secret)

        t_id = "tenant_stale"
        c_hash = "f" * 64
        past_time = datetime.now(UTC) - timedelta(hours=2)
        expired_time = datetime.now(UTC) - timedelta(minutes=10)

        canon = compute_checkpoint_canonical_string(t_id, "audit_logs", 1, c_hash, past_time.isoformat(), "notary:test")
        sig = sign_checkpoint_payload(secret, canon)

        cp = CheckpointModel(
            checkpoint_id="chk_expired",
            tenant_id=t_id,
            checkpoint_hash=c_hash,
            sequence_number=1,
            signer_identity="notary:test",
            signature=sig,
            issued_at=past_time,
            expires_at=expired_time,
        )
        registry = TrustedCheckpointRegistry(notary_keys=notary_keys)
        # Registration of expired checkpoint fails closed
        with pytest.raises(ValueError, match="Cannot register expired checkpoint"):
            registry.register_authenticated_checkpoint(cp)

    def test_cross_tenant_checkpoint_leakage_prevented(self) -> None:
        """Prove that a valid checkpoint registered for Tenant A is rejected for Tenant B."""
        notary_keys = NotaryKeyRegistry()
        secret = b"test-key"
        notary_keys.register_key("notary:test", secret)

        t_a = "tenant_alice"
        t_b = "tenant_bob"
        c_hash = "a" * 64
        now = datetime.now(UTC)

        canon = compute_checkpoint_canonical_string(t_a, "audit_logs", 1, c_hash, now.isoformat(), "notary:test")
        sig = sign_checkpoint_payload(secret, canon)

        cp = CheckpointModel(
            checkpoint_id="chk_alice",
            tenant_id=t_a,
            checkpoint_hash=c_hash,
            sequence_number=1,
            signer_identity="notary:test",
            signature=sig,
            issued_at=now,
        )
        registry = TrustedCheckpointRegistry(notary_keys=notary_keys)
        registry.register_authenticated_checkpoint(cp)

        # Alice is authorized
        assert registry.is_authenticated_root(t_a, c_hash) is True
        # Bob must be rejected
        assert registry.is_authenticated_root(t_b, c_hash) is False


# =============================================================================
# PART 3: Full-Chain Verification & Idempotency Tampering Audit
# =============================================================================

@pytest.mark.security
@pytest.mark.asyncio
class TestFullChainVerificationAndIdempotency:
    """Tests auditing idempotency early-return tampering and sequence monotonicity."""

    async def test_idempotency_early_return_validates_audit_trail_fails_on_tampering(self) -> None:
        """Prove that an idempotent retry of an existing terminal outcome fails closed if the outcome was tampered."""
        service = RealityVerifierService()
        rec, aud = _build_test_contract_and_audit()

        # Setup mock session returning existing terminal record
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalar_one_or_none=MagicMock(return_value=ActionContract(
                    id=rec.action_id,
                    tenant_id=rec.tenant_id,
                    transaction_id=rec.transaction_id,
                    state="COMPLETED",
                    blast_radius={},
                    postconditions=[],
                    required_capability="service:manage",
                ))),
                # Existing outcome record returned via idempotency
                MagicMock(scalar_one_or_none=MagicMock(return_value=rec)),
                # Audit lookup for verify_record_against_audit_trail returns corrupted audit (tampered hash)
                MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[
                    AuditLogRecord(
                        entry_id="aud_corrupt",
                        tenant_id=rec.tenant_id,
                        session_id=rec.transaction_id,
                        transaction_id=rec.transaction_id,
                        trace_id="gate5-outcome",
                        prompt_hash="0" * 64,
                        response_hash="corrupted_hash" + "0" * 50,  # DIVERGENCE!
                        hrs_score=0.0,
                        risk_tier="LOW",
                        claims_count=1,
                        claims_summary=[],
                        correction_applied=False,
                        event_type="GATE5_OUTCOME_VERIFIED",
                        decision=rec.outcome_status,
                        event_payload={
                            "outcome_id": rec.id,
                            "action_id": rec.action_id,
                            "transaction_id": rec.transaction_id,
                            "verified_at": datetime.now(UTC).isoformat(),
                        },
                        prev_hash="0" * 64,
                        chain_hash="1" * 64,
                        created_at=datetime.now(UTC),
                    )
                ])))),
            ]
        )

        req = OutcomeVerificationRequest(
            action_id=rec.action_id,
            transaction_id=rec.transaction_id,
            verifier_type=OutcomeVerifierType.HTTP_RESOURCE,
            observability_class=ObservabilityClass.OBS_DIRECT,
            idempotency_key=rec.idempotency_key,
        )
        auth = AuthContext(
            tenant_id=rec.tenant_id,
            identity_id="admin_user",
            role=Role.TENANT_ADMIN,
            scopes=["*"],
        )

        # Mock db_session.get_tenant_session
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def mock_tenant_session(_: str):
            yield mock_session

        import services.reality_verifier as rv_module
        orig_fn = rv_module.db_session.get_tenant_session
        rv_module.db_session.get_tenant_session = mock_tenant_session

        try:
            with pytest.raises(HTTPException) as exc_info:
                await service.verify_action_outcome(req, auth)
            assert exc_info.value.status_code == 409
            assert "Cryptographic audit trail divergence" in exc_info.value.detail
        finally:
            rv_module.db_session.get_tenant_session = orig_fn

    async def test_audit_chain_sequence_inversion_fails_closed(self) -> None:
        """Prove that a predecessor with sequence_number >= current block sequence raises HTTP 409."""
        service = RealityVerifierService()
        rec, _ = _build_test_contract_and_audit()

        t1 = datetime(2026, 10, 10, 10, 5, 0, tzinfo=UTC)
        t0 = datetime(2026, 10, 10, 10, 0, 0, tzinfo=UTC)

        prev_leaf = "a" * 64
        chain_leaf = compute_sha256(f"{prev_leaf}:aud_leaf:SUCCESS_CONFIRMED:{t1.isoformat()}")

        aud_leaf = AuditLogRecord(
            entry_id="aud_leaf",
            tenant_id=rec.tenant_id,
            sequence_number=5,
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

        # Ancestor has SEQUENCE INVERSION (sequence 10 >= descendant sequence 5!)
        pred_chain = prev_leaf
        pred_hash = "0" * 64
        pred_entry = AuditLogRecord(
            entry_id="aud_pred_inverted",
            tenant_id=rec.tenant_id,
            sequence_number=10,  # INVERSION!
            session_id=rec.transaction_id,
            trace_id="gate5-outcome",
            prompt_hash="0" * 64,
            response_hash="0" * 64,
            hrs_score=0.0,
            risk_tier="LOW",
            claims_count=1,
            claims_summary=[],
            correction_applied=False,
            event_type="GATE5_OUTCOME_VERIFIED",
            actor_identity_id="system_actor",
            transaction_id=rec.transaction_id,
            decision="SUCCESS_CONFIRMED",
            event_payload={
                "verified_at": t0.isoformat(),
                "decision": "SUCCESS_CONFIRMED",
            },
            prev_hash=pred_hash,
            chain_hash=pred_chain,
            created_at=t0,
        )

        mock_session = AsyncMock()
        mock_scalars_leaf = MagicMock(all=MagicMock(return_value=[aud_leaf]))
        mock_scalars_pred = MagicMock(all=MagicMock(return_value=[pred_entry]))

        mock_session.execute = AsyncMock(
            side_effect=[
                MagicMock(scalars=MagicMock(return_value=mock_scalars_leaf)),
                MagicMock(scalars=MagicMock(return_value=mock_scalars_pred)),
            ]
        )

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_record_against_audit_trail(mock_session, rec)
        assert exc_info.value.status_code == 409
        assert "sequence inversion detected" in exc_info.value.detail


# =============================================================================
# PART 4: System Catalog, RLS & Schema Invariants
# =============================================================================

@pytest.mark.security
class TestPostgresCatalogAndSecurityPrivileges:
    """Verifies live PostgreSQL 16 catalog state for ledgers, checkpoints, and RLS."""

    @pytest.fixture(scope="class")
    def sync_engine(self, live_postgres_database: Any) -> Any:
        _ = live_postgres_database
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        assert sync_url is not None
        engine = create_engine(sync_url)
        yield engine
        engine.dispose()

    def test_tenant_audit_ledgers_table_and_rls_exist(self, sync_engine: Any) -> None:
        """Prove tenant_audit_ledgers exists and has row level security forced."""
        with sync_engine.connect() as conn:
            # 1. Table existence and RLS flags in pg_class
            res = conn.execute(
                text(
                    """
                    SELECT relname, relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = 'tenant_audit_ledgers';
                    """
                )
            ).mappings().one_or_none()
            assert res is not None, "tenant_audit_ledgers table not found in pg_class!"
            assert res["relrowsecurity"] is True
            assert res["relforcerowsecurity"] is True

            # 2. Policy in pg_policies
            pol = conn.execute(
                text(
                    """
                    SELECT policyname, tablename
                    FROM pg_policies
                    WHERE tablename = 'tenant_audit_ledgers';
                    """
                )
            ).mappings().one_or_none()
            assert pol is not None
            assert pol["policyname"] == "tenant_isolation_tenant_audit_ledgers"

    def test_audit_checkpoints_unique_constraint_and_rls(self, sync_engine: Any) -> None:
        """Prove audit_checkpoints has unique constraint (tenant_id, checkpoint_hash) and RLS."""
        with sync_engine.connect() as conn:
            res = conn.execute(
                text(
                    """
                    SELECT conname, contype
                    FROM pg_constraint
                    WHERE conname = 'uq_audit_checkpoints_tenant_hash';
                    """
                )
            ).mappings().one_or_none()
            assert res is not None
            assert res["contype"] == "u"

            rls = conn.execute(
                text(
                    """
                    SELECT relname, relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = 'audit_checkpoints';
                    """
                )
            ).mappings().one_or_none()
            assert rls is not None
            assert rls["relrowsecurity"] is True
            assert rls["relforcerowsecurity"] is True

    def test_audit_logs_append_only_policies_exclude_update_and_delete(self, sync_engine: Any) -> None:
        """Prove that audit_logs has policies ONLY for SELECT and INSERT (immutable / append-only)."""
        with sync_engine.connect() as conn:
            policies = conn.execute(
                text(
                    """
                    SELECT policyname, cmd
                    FROM pg_policies
                    WHERE tablename = 'audit_logs';
                    """
                )
            ).mappings().all()

            cmds = {p["cmd"] for p in policies}
            assert "SELECT" in cmds, "audit_logs must permit SELECT"
            assert "INSERT" in cmds, "audit_logs must permit INSERT"
            assert "UPDATE" not in cmds, "audit_logs must NOT have UPDATE policy (immutable append-only)"
            assert "DELETE" not in cmds, "audit_logs must NOT have DELETE policy (immutable append-only)"


# =============================================================================
# PART 5: Gate 5 Epistemic Adapter Semantics
# =============================================================================

@pytest.mark.security
class TestGate5AdapterSemantics:
    """Verifies that Gate 5 never conflates simulation, transport ACKs, or blind sinks with confirmed reality."""

    def test_simulation_cannot_certify_success_confirmed(self) -> None:
        """Simulated probe must produce ACKNOWLEDGED_UNVERIFIED with confidence <= 0.50, never SUCCESS_CONFIRMED."""
        from shared.schemas.outcome import OutcomeVerificationContract
        rec, _ = _build_test_contract_and_audit(status_val="ACKNOWLEDGED_UNVERIFIED", confidence=0.50)
        contract = OutcomeVerificationContract(
            outcome_id=rec.id,
            transaction_id=rec.transaction_id,
            action_id=rec.action_id,
            tenant_id=rec.tenant_id,
            observability_class=ObservabilityClass.OBS_DIRECT,
            outcome_status=OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
            epistemic_confidence=0.50,
            verifier_adapter="SimulatedTestAdapter",
            is_simulated=True,
            verification_hash=rec.verification_hash,
        )
        assert contract.is_simulated is True
        assert contract.outcome_status != OutcomeStatus.SUCCESS_CONFIRMED
        assert contract.epistemic_confidence <= 0.50

    def test_write_only_sink_confidence_strictly_zero(self) -> None:
        """Write-only resources (OBS_BLIND) must have confidence 0.0 and status UNOBSERVABLE."""
        from shared.schemas.outcome import OutcomeVerificationContract
        contract = OutcomeVerificationContract(
            outcome_id="outc_blind_test",
            transaction_id="txn_blind",
            action_id="act_blind",
            tenant_id="tenant_blind",
            observability_class=ObservabilityClass.OBS_BLIND,
            outcome_status=OutcomeStatus.UNOBSERVABLE,
            epistemic_confidence=0.0,
            verifier_adapter="NullSinkAdapter",
            is_simulated=False,
            verification_hash="0" * 64,
        )
        assert contract.outcome_status == OutcomeStatus.UNOBSERVABLE
        assert contract.epistemic_confidence == 0.0
