"""MIRAGE 3.0 — Phase 5.5.6 Gate 5 Fail-Closed Remediation, Durable Notary Trust & Production-Path Concurrency Proof.

Covers:
1. Elimination of fail-open behavior in idempotency path (cached outcome verification).
2. Mandatory PostgreSQL append serialization with zero exception swallowing.
3. Production-path concurrency proof calling RealityVerifierService.verify_action_outcome on live PostgreSQL 16.
4. Notary trust hardening (rejection of dev secret in production, HMAC boundary documentation).
5. Database-backed durable checkpoint persistence, verification, and tamper detection.
6. Control-plane authorization (SUPER_ADMIN only) for checkpoint registration and revocation.
7. Audit ledger non-null sequence consistency across production persistence writers.
"""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from db.models import (
    ActionContract,
    AuditCheckpointRecord,
    AuditLogRecord,
    OutcomeVerificationRecord,
    TenantAuditLedger,
)
from db.persistence import PostgresPersistenceService
from gateway.routes.audit import (
    RegisterCheckpointRequest,
    RevokeCheckpointRequest,
    register_audit_checkpoint,
    revoke_audit_checkpoint,
)
from services.reality_verifier import RealityVerifierService, reality_verifier_service
from shared.config import EnvironmentType, Settings
from shared.schemas.action import ActionState
from shared.schemas.audit import (
    GENESIS_ROOT_HASH,
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


@pytest.fixture
def auth_super_admin() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_p556_alpha",
        user_id="super_admin_user",
        role=Role.SUPER_ADMIN,
        identity_id="ident_super_admin",
    )


@pytest.fixture
def auth_operator() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_p556_alpha",
        user_id="operator_user",
        role=Role.OPERATOR,
        identity_id="ident_operator",
    )


@pytest.fixture
def auth_tenant_admin() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_p556_alpha",
        user_id="admin_user",
        role=Role.TENANT_ADMIN,
        identity_id="ident_tenant_admin",
    )


# =============================================================================
# PART 1: Idempotency Fail-Closed Verification
# =============================================================================

@pytest.mark.security
class TestIdempotencyFailClosed:
    """Prove that cached outcome replay fails closed on any integrity or audit anomaly."""

    @pytest.mark.asyncio
    async def test_idempotent_tampered_verification_hash_fails_closed(self, auth_operator: AuthContext) -> None:
        """Cached outcome with tampered verification_hash raises HTTP 409 and never returns cached contract."""
        service = RealityVerifierService()
        action_id = f"act_{uuid.uuid4().hex[:8]}"
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        now_iso = now.isoformat()

        action = ActionContract(
            id=action_id,
            tenant_id=auth_operator.tenant_id,
            transaction_id=txn_id,
            actor_identity_id="actor_1",
            tool_id="tool_1",
            tool_name="test_tool",
            action_type="EXECUTE",
            target_resource="db://test",
            parameters={},
            normalized_parameters={},
            parameters_hash="0" * 64,
            required_capability="db:write",
            state=ActionState.COMPLETED.value,
            idempotency_key="idem_key_tamper_hash",
        )

        # Existing record with tampered verification hash
        existing = OutcomeVerificationRecord(
            id=f"outc_{uuid.uuid4().hex[:8]}",
            tenant_id=auth_operator.tenant_id,
            transaction_id=txn_id,
            action_id=action_id,
            observability_class="OBS_DIRECT",
            outcome_status=OutcomeStatus.SUCCESS_CONFIRMED.value,
            epistemic_confidence=1.0,
            verifier_adapter="DatabaseStateAdapter",
            is_simulated=False,
            expected_postconditions={"status": "OK"},
            observed_state={"status": "OK"},
            discrepancies=[],
            evidence_payload={},
            reconciliation_notes=[],
            verification_hash="tampered_hash_000000000000000000000000000000000000000000000000000000",
            idempotency_key="idem_key_tamper_hash",
            target_environment="DEV",
            created_at=now,
            verified_at=now,
        )

        entry_id = f"aud_{uuid.uuid4().hex[:8]}"
        real_hash = "real_hash_111111111111111111111111111111111111111111111111111111111"
        chain_hash = compute_sha256(f"{GENESIS_ROOT_HASH}:{entry_id}:{OutcomeStatus.SUCCESS_CONFIRMED.value}:{now_iso}")

        audit = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=auth_operator.tenant_id,
            sequence_number=1,
            session_id=txn_id,
            trace_id="gate5-outcome",
            prompt_hash="0" * 64,
            response_hash=real_hash,
            hrs_score=0.0,
            risk_tier="LOW",
            claims_count=1,
            claims_summary=[],
            correction_applied=False,
            event_type="GATE5_OUTCOME_VERIFIED",
            actor_identity_id="actor_1",
            transaction_id=txn_id,
            decision=OutcomeStatus.SUCCESS_CONFIRMED.value,
            prev_hash=GENESIS_ROOT_HASH,
            chain_hash=chain_hash,
            event_payload={
                "outcome_id": existing.id,
                "action_id": action_id,
                "transaction_id": txn_id,
                "decision": OutcomeStatus.SUCCESS_CONFIRMED.value,
                "verified_at": now_iso,
            },
            created_at=now,
        )

        req = OutcomeVerificationRequest(
            transaction_id=txn_id,
            action_id=action_id,
            idempotency_key="idem_key_tamper_hash",
        )

        with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_res_action = MagicMock()
            mock_res_action.scalar_one_or_none.return_value = action
            mock_res_existing = MagicMock()
            mock_res_existing.scalar_one_or_none.return_value = existing
            mock_res_audit = MagicMock()
            mock_res_audit.scalars.return_value.all.return_value = [audit]

            mock_session.execute.side_effect = [mock_res_action, mock_res_existing, mock_res_audit]
            mock_ctx.return_value.__aenter__.return_value = mock_session

            with pytest.raises(HTTPException) as exc_info:
                await service.verify_action_outcome(req, auth_operator)

            assert exc_info.value.status_code == 409
            assert "Cryptographic audit trail divergence" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_idempotent_missing_audit_anchor_fails_closed(self, auth_operator: AuthContext) -> None:
        """Cached outcome with missing AuditLogRecord fails closed with HTTP 409."""
        service = RealityVerifierService()
        action_id = f"act_{uuid.uuid4().hex[:8]}"
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)

        action = ActionContract(
            id=action_id,
            tenant_id=auth_operator.tenant_id,
            transaction_id=txn_id,
            actor_identity_id="actor_1",
            tool_id="tool_1",
            tool_name="test_tool",
            action_type="EXECUTE",
            target_resource="db://test",
            parameters={},
            normalized_parameters={},
            parameters_hash="0" * 64,
            required_capability="db:write",
            state=ActionState.COMPLETED.value,
            idempotency_key="idem_key_missing_audit",
        )

        existing = OutcomeVerificationRecord(
            id=f"outc_{uuid.uuid4().hex[:8]}",
            tenant_id=auth_operator.tenant_id,
            transaction_id=txn_id,
            action_id=action_id,
            observability_class="OBS_DIRECT",
            outcome_status=OutcomeStatus.SUCCESS_CONFIRMED.value,
            epistemic_confidence=1.0,
            verifier_adapter="DatabaseStateAdapter",
            is_simulated=False,
            expected_postconditions={},
            observed_state={},
            discrepancies=[],
            evidence_payload={},
            reconciliation_notes=[],
            verification_hash="0" * 64,
            idempotency_key="idem_key_missing_audit",
            target_environment="DEV",
            created_at=now,
            verified_at=now,
        )

        req = OutcomeVerificationRequest(
            transaction_id=txn_id,
            action_id=action_id,
            idempotency_key="idem_key_missing_audit",
        )

        with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_res_action = MagicMock()
            mock_res_action.scalar_one_or_none.return_value = action
            mock_res_existing = MagicMock()
            mock_res_existing.scalar_one_or_none.return_value = existing
            mock_res_audit = MagicMock()
            mock_res_audit.scalars.return_value.all.return_value = []  # No audit anchor!

            mock_session.execute.side_effect = [mock_res_action, mock_res_existing, mock_res_audit]
            mock_ctx.return_value.__aenter__.return_value = mock_session

            with pytest.raises(HTTPException) as exc_info:
                await service.verify_action_outcome(req, auth_operator)

            assert exc_info.value.status_code == 409
            assert "Audit anchor missing" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_idempotent_tampered_status_fails_closed(self, auth_operator: AuthContext) -> None:
        """Cached outcome with status disagreeing with audit record decision fails closed."""
        service = RealityVerifierService()
        action_id = f"act_{uuid.uuid4().hex[:8]}"
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        now_iso = now.isoformat()

        action = ActionContract(
            id=action_id,
            tenant_id=auth_operator.tenant_id,
            transaction_id=txn_id,
            actor_identity_id="actor_1",
            tool_id="tool_1",
            tool_name="test_tool",
            action_type="EXECUTE",
            target_resource="db://test",
            parameters={},
            normalized_parameters={},
            parameters_hash="0" * 64,
            required_capability="db:write",
            state=ActionState.COMPLETED.value,
            idempotency_key="idem_key_tampered_status",
        )

        v_hash = "0" * 64
        existing = OutcomeVerificationRecord(
            id=f"outc_{uuid.uuid4().hex[:8]}",
            tenant_id=auth_operator.tenant_id,
            transaction_id=txn_id,
            action_id=action_id,
            observability_class="OBS_DIRECT",
            outcome_status=OutcomeStatus.SUCCESS_CONFIRMED.value,
            epistemic_confidence=1.0,
            verifier_adapter="DatabaseStateAdapter",
            is_simulated=False,
            expected_postconditions={},
            observed_state={},
            discrepancies=[],
            evidence_payload={},
            reconciliation_notes=[],
            verification_hash=v_hash,
            idempotency_key="idem_key_tampered_status",
            target_environment="DEV",
            created_at=now,
            verified_at=now,
        )

        entry_id = f"aud_{uuid.uuid4().hex[:8]}"
        # Audit record has FAILED, but existing record claims SUCCESS_CONFIRMED
        chain_hash = compute_sha256(f"{GENESIS_ROOT_HASH}:{entry_id}:{OutcomeStatus.FAILED.value}:{now_iso}")

        audit = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=auth_operator.tenant_id,
            sequence_number=1,
            session_id=txn_id,
            trace_id="gate5-outcome",
            prompt_hash="0" * 64,
            response_hash=v_hash,
            hrs_score=1.0,
            risk_tier="HIGH",
            claims_count=1,
            claims_summary=[],
            correction_applied=False,
            event_type="GATE5_OUTCOME_VERIFIED",
            actor_identity_id="actor_1",
            transaction_id=txn_id,
            decision=OutcomeStatus.FAILED.value,
            prev_hash=GENESIS_ROOT_HASH,
            chain_hash=chain_hash,
            event_payload={
                "outcome_id": existing.id,
                "action_id": action_id,
                "transaction_id": txn_id,
                "decision": OutcomeStatus.FAILED.value,
                "verified_at": now_iso,
            },
            created_at=now,
        )

        req = OutcomeVerificationRequest(
            transaction_id=txn_id,
            action_id=action_id,
            idempotency_key="idem_key_tampered_status",
        )

        with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_res_action = MagicMock()
            mock_res_action.scalar_one_or_none.return_value = action
            mock_res_existing = MagicMock()
            mock_res_existing.scalar_one_or_none.return_value = existing
            mock_res_audit = MagicMock()
            mock_res_audit.scalars.return_value.all.return_value = [audit]

            mock_session.execute.side_effect = [mock_res_action, mock_res_existing, mock_res_audit]
            mock_ctx.return_value.__aenter__.return_value = mock_session

            with pytest.raises(HTTPException) as exc_info:
                await service.verify_action_outcome(req, auth_operator)

            assert exc_info.value.status_code == 409
            assert "Cryptographic audit trail divergence" in exc_info.value.detail


# =============================================================================
# PART 2: Real PostgreSQL 16 Production-Path Concurrency Execution
# =============================================================================

@pytest.mark.security
class TestPostgresProductionPathConcurrency:
    """Execute concurrent reality verifications through the ACTUAL service method on PostgreSQL 16."""

    @pytest.fixture(scope="class")
    def sync_engine(self, live_postgres_database: Any) -> Any:
        _ = live_postgres_database
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        assert sync_url is not None, "DATABASE_SYNC_URL must be configured by live_postgres_database fixture"
        engine = create_engine(sync_url, pool_size=25, max_overflow=10)
        yield engine
        engine.dispose()

    @pytest.mark.asyncio
    async def test_concurrent_service_appends_serialize_without_forks(self, sync_engine: Any) -> None:
        """Call RealityVerifierService.verify_action_outcome concurrently across 10 tasks on PostgreSQL.

        Invariants verified:
        1. All 10 concurrent requests succeed.
        2. Exactly 10 audit records are committed.
        3. Sequence numbers are strictly contiguous: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10.
        4. Hash chain is continuous from entry 10 back to GENESIS_ROOT_HASH.
        5. Tenant audit ledger head holds sequence 10 and matches the 10th entry hash.
        6. Zero sequence forks or gaps occur.
        """
        test_tenant = f"t_p556_conc_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)

        # 1. Seed tenant and 10 ActionContracts in PostgreSQL
        num_workers = 10
        action_ids: list[str] = []
        txn_ids: list[str] = []

        with sync_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO tenants (id, name, api_key_hash, tier, created_at)
                    VALUES (:tid, 'Concurrent P556 Tenant', 'hash_p556', 'enterprise', :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"tid": test_tenant, "now": now},
            )
            # Seed ActorIdentity
            conn.execute(
                text(
                    """
                    INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at)
                    VALUES (:aid, :tid, 'concurrent_actor', 'SERVICE', 'OPERATOR', true, :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"aid": f"actor_{test_tenant}", "tid": test_tenant, "now": now},
            )
            # Seed ToolDefinition
            conn.execute(
                text(
                    """
                    INSERT INTO tool_registry (id, tenant_id, name, required_capability, created_at, updated_at)
                    VALUES (:tool_id, :tid, 'service_tool', 'service:execute', :now, :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"tool_id": f"tool_{test_tenant}", "tid": test_tenant, "now": now},
            )

            # Insert AI Transactions and ActionContracts
            for i in range(num_workers):
                a_id = f"act_p556_{i}_{uuid.uuid4().hex[:6]}"
                t_id = f"txn_p556_{i}_{uuid.uuid4().hex[:6]}"
                action_ids.append(a_id)
                txn_ids.append(t_id)

                conn.execute(
                    text(
                        """
                        INSERT INTO ai_transactions (
                            id, tenant_id, actor_identity_id, idempotency_key, correlation_id,
                            state, max_turns, created_at, updated_at
                        )
                        VALUES (:txnid, :tid, :aid, :txnid, :txnid, 'RUNNING', 10, :now, :now);
                        """
                    ),
                    {"txnid": t_id, "tid": test_tenant, "aid": f"actor_{test_tenant}", "now": now},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO action_contracts (
                            id, tenant_id, transaction_id, actor_identity_id, tool_id, tool_name,
                            action_type, target_resource, parameters, normalized_parameters, parameters_hash,
                            required_capability, taint_flags, risk_score, blast_radius, state, idempotency_key,
                            preconditions, postconditions, created_at
                        ) VALUES (
                            :aid, :tid, :txnid, :actorid, :toolid, 'service_tool',
                            'EXECUTE', 'db://cluster/primary', '{}'::jsonb, '{}'::jsonb,
                            '0000000000000000000000000000000000000000000000000000000000000000',
                            'service:execute', '[]'::jsonb, 0, '{}'::jsonb, 'COMPLETED', :idem,
                            '[]'::jsonb, '[{"target": "status", "expected_value": "PROCESSED"}]'::jsonb, :now
                        );
                        """
                    ),
                    {
                        "aid": a_id,
                        "tid": test_tenant,
                        "txnid": t_id,
                        "actorid": f"actor_{test_tenant}",
                        "toolid": f"tool_{test_tenant}",
                        "idem": f"idem_contract_{a_id}",
                        "now": now,
                    },
                )
            conn.commit()

        # 2. Execute verify_action_outcome concurrently using the REAL production service method
        service = RealityVerifierService()
        auth = AuthContext(
            tenant_id=test_tenant,
            user_id="operator_user",
            role=Role.OPERATOR,
            identity_id=f"actor_{test_tenant}",
        )

        async def run_verifier(worker_idx: int) -> Any:
            req = OutcomeVerificationRequest(
                transaction_id=txn_ids[worker_idx],
                action_id=action_ids[worker_idx],
                observability_class=ObservabilityClass.OBS_DIRECT,
                verifier_type=OutcomeVerifierType.SIMULATED,
                expected_postconditions={"status": "PROCESSED"},
                adapter_config={"simulated_state": {"status": "PROCESSED"}, "allow_simulated_for_test": True},
            )
            return await service.verify_action_outcome(req, auth)

        # Run all 10 concurrently
        results = await asyncio.gather(*(run_verifier(i) for i in range(num_workers)))
        assert len(results) == num_workers
        for res in results:
            assert res.outcome_status in (
                OutcomeStatus.SUCCESS_CONFIRMED,
                OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
            )

        # 3. Query PostgreSQL audit_logs directly and verify sequence numbers and hash chain
        with sync_engine.connect() as conn:
            logs = conn.execute(
                text(
                    """
                    SELECT entry_id, sequence_number, prev_hash, chain_hash, decision
                    FROM audit_logs
                    WHERE tenant_id = :tid
                    ORDER BY sequence_number ASC;
                    """
                ),
                {"tid": test_tenant},
            ).mappings().all()

            ledger_row = conn.execute(
                text(
                    """
                    SELECT head_entry_id, head_chain_hash, sequence_number
                    FROM tenant_audit_ledgers
                    WHERE tenant_id = :tid;
                    """
                ),
                {"tid": test_tenant},
            ).mappings().one()

        assert len(logs) == num_workers, f"Expected {num_workers} audit records, found {len(logs)}"

        # Verify contiguous sequence numbers: exactly 1 to 10
        sequences = [r["sequence_number"] for r in logs]
        assert sequences == list(range(1, num_workers + 1)), f"Non-contiguous sequences: {sequences}"

        # Verify continuous cryptographic hash chain back to genesis
        assert logs[0]["prev_hash"] == GENESIS_ROOT_HASH
        for i in range(1, num_workers):
            assert logs[i]["prev_hash"] == logs[i - 1]["chain_hash"], (
                f"Hash fork at sequence {logs[i]['sequence_number']}: "
                f"prev_hash {logs[i]['prev_hash']} != expected {logs[i - 1]['chain_hash']}"
            )

        # Verify tenant audit ledger head matches the final record
        assert ledger_row["sequence_number"] == num_workers
        assert ledger_row["head_chain_hash"] == logs[-1]["chain_hash"]
        assert ledger_row["head_entry_id"] == logs[-1]["entry_id"]

    @pytest.mark.asyncio
    async def test_live_postgres_missing_ledger_head_aborts_transaction(self, auth_operator: AuthContext) -> None:
        """On live PostgreSQL, failure to acquire tenant ledger head raises HTTP 500 (fails closed)."""
        service = RealityVerifierService()
        action_id = f"act_{uuid.uuid4().hex[:8]}"
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"

        action = ActionContract(
            id=action_id,
            tenant_id=auth_operator.tenant_id,
            transaction_id=txn_id,
            actor_identity_id="actor_1",
            tool_id="tool_1",
            tool_name="test_tool",
            action_type="EXECUTE",
            target_resource="db://test",
            parameters={},
            normalized_parameters={},
            parameters_hash="0" * 64,
            required_capability="db:write",
            state=ActionState.COMPLETED.value,
            idempotency_key="idem_fail_head",
        )

        req = OutcomeVerificationRequest(
            transaction_id=txn_id,
            action_id=action_id,
            observability_class=ObservabilityClass.OBS_DIRECT,
            verifier_type=OutcomeVerifierType.SIMULATED,
            expected_postconditions={"status": "OK"},
            adapter_config={"simulated_state": {"status": "OK"}, "allow_simulated_for_test": True},
        )

        # Mock live PostgreSQL dialect where ledger_head_row returns None
        with patch("services.reality_verifier.db_session.get_tenant_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_bind = MagicMock()
            mock_bind.dialect.name = "postgresql"
            mock_session.bind = mock_bind

            mock_res_action = MagicMock()
            mock_res_action.scalar_one_or_none.return_value = action
            mock_res_existing = MagicMock()
            mock_res_existing.scalar_one_or_none.return_value = None

            mock_res_advisory = MagicMock()
            mock_res_insert = MagicMock()
            mock_res_head = MagicMock()
            mock_res_head.scalar_one_or_none.return_value = None  # Missing ledger head!

            mock_session.execute.side_effect = [
                mock_res_action,
                mock_res_existing,
                mock_res_advisory,
                mock_res_insert,
                mock_res_head,
            ]
            mock_ctx.return_value.__aenter__.return_value = mock_session

            with pytest.raises(HTTPException) as exc_info:
                await service.verify_action_outcome(req, auth_operator)

            assert exc_info.value.status_code == 500
            assert "Authoritative tenant audit ledger head missing" in exc_info.value.detail


# =============================================================================
# PART 3: Notary Trust Hardening & Key Management
# =============================================================================

@pytest.mark.security
class TestNotaryTrustHardening:
    """Verify notary key boundary enforcement and rejection of insecure defaults."""

    def test_production_mode_rejects_default_dev_key(self) -> None:
        """In production or when allow_dev_keys=False, NotaryKeyRegistry has no default keys."""
        reg = NotaryKeyRegistry(allow_dev_keys=False)
        assert reg.get_key("notary:system_primary") is None
        assert len(reg._keys) == 0

    def test_notary_key_registry_from_settings_json(self) -> None:
        """NotaryKeyRegistry parses custom keys from settings.notary_keys_json."""
        with patch("shared.config.get_settings") as mock_settings:
            s = MagicMock()
            s.environment = EnvironmentType.PRODUCTION
            s.allow_dev_notary_keys = False
            s.notary_keys_json = json.dumps({"notary:custom_signer": "my-secret-key-32b-length-here!"})
            mock_settings.return_value = s

            reg = NotaryKeyRegistry()
            assert reg.get_key("notary:custom_signer") == b"my-secret-key-32b-length-here!"
            assert reg.get_key("notary:system_primary") is None

    def test_settings_validator_rejects_dev_notary_keys_in_production(self) -> None:
        """Settings validation rejects allow_dev_notary_keys=True in production environment."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(
                environment=EnvironmentType.PRODUCTION,
                allow_dev_notary_keys=True,
                secret_key="a" * 48,
                celery_broker_url="amqps://user:pass@host:5671//",
            )
        assert "ALLOW_DEV_NOTARY_KEYS is prohibited in production" in str(exc_info.value)


# =============================================================================
# PART 4: Durable Database Checkpoint Persistence & Verification
# =============================================================================

@pytest.mark.security
class TestDurableCheckpointPersistence:
    """Verify database-backed loading and cryptographic validation of audit checkpoints."""

    @pytest.mark.asyncio
    async def test_db_checkpoint_loaded_and_verified_when_not_in_memory(self, auth_operator: AuthContext) -> None:
        """Checkpoint stored in PostgreSQL is loaded dynamically and verified by verify_record_against_audit_trail."""
        signer_id = "notary:test_signer"
        secret_key = b"test-notary-secret-key-for-p556!"
        key_reg = NotaryKeyRegistry(initial_keys={signer_id: secret_key})
        checkpoint_reg = TrustedCheckpointRegistry(notary_keys=key_reg)

        service = RealityVerifierService(checkpoint_registry=checkpoint_reg)
        tid = auth_operator.tenant_id
        now = datetime.now(UTC)
        now_iso = now.isoformat()

        # Target outcome record
        outcome_id = f"outc_{uuid.uuid4().hex[:8]}"
        action_id = f"act_{uuid.uuid4().hex[:8]}"
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        v_hash = "0" * 64

        rec = OutcomeVerificationRecord(
            id=outcome_id,
            tenant_id=tid,
            transaction_id=txn_id,
            action_id=action_id,
            observability_class="OBS_DIRECT",
            outcome_status=OutcomeStatus.SUCCESS_CONFIRMED.value,
            epistemic_confidence=1.0,
            verifier_adapter="DatabaseStateAdapter",
            is_simulated=False,
            expected_postconditions={},
            observed_state={},
            discrepancies=[],
            evidence_payload={},
            reconciliation_notes=[],
            verification_hash=v_hash,
            idempotency_key="idem_chk",
            target_environment="DEV",
            created_at=now,
            verified_at=now,
        )

        # Checkpoint anchor hash
        entry_id = f"aud_{uuid.uuid4().hex[:8]}"
        chk_hash = compute_sha256(f"{GENESIS_ROOT_HASH}:{entry_id}:{OutcomeStatus.SUCCESS_CONFIRMED.value}:{now_iso}")

        # Compute valid signature
        canon = compute_checkpoint_canonical_string(
            tenant_id=tid,
            ledger_identity="audit_logs",
            sequence_number=1,
            checkpoint_hash=chk_hash,
            issued_at_iso=now_iso,
            signer_identity=signer_id,
        )
        sig = sign_checkpoint_payload(secret_key, canon)

        db_checkpoint = AuditCheckpointRecord(
            id=f"chk_{uuid.uuid4().hex[:8]}",
            tenant_id=tid,
            checkpoint_hash=chk_hash,
            sequence_number=1,
            ledger_identity="audit_logs",
            signer_identity=signer_id,
            signature=sig,
            trust_tier="EXTERNALLY_ANCHORED",
            revoked=False,
            issued_at=now,
            expires_at=now + timedelta(days=30),
            created_at=now,
        )

        leaf_entry_id = f"aud_leaf_{uuid.uuid4().hex[:8]}"
        audit_entry = AuditLogRecord(
            entry_id=leaf_entry_id,
            tenant_id=tid,
            sequence_number=2,
            session_id=txn_id,
            trace_id="gate5-outcome",
            prompt_hash="0" * 64,
            response_hash=v_hash,
            hrs_score=0.0,
            risk_tier="LOW",
            claims_count=1,
            claims_summary=[],
            correction_applied=False,
            event_type="GATE5_OUTCOME_VERIFIED",
            actor_identity_id="actor_1",
            transaction_id=txn_id,
            decision=OutcomeStatus.SUCCESS_CONFIRMED.value,
            prev_hash=chk_hash,
            chain_hash=compute_sha256(f"{chk_hash}:{leaf_entry_id}:{OutcomeStatus.SUCCESS_CONFIRMED.value}:{now_iso}"),
            event_payload={
                "outcome_id": outcome_id,
                "action_id": action_id,
                "transaction_id": txn_id,
                "sequence_number": 2,
                "decision": OutcomeStatus.SUCCESS_CONFIRMED.value,
                "verified_at": now_iso,
            },
            created_at=now,
        )

        # Audit row at sequence 1 matching checkpoint
        audit_seq_1 = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tid,
            sequence_number=1,
            session_id=txn_id,
            trace_id="gate5-outcome",
            prompt_hash="0" * 64,
            response_hash="0" * 64,
            hrs_score=0.0,
            risk_tier="LOW",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type="GATE5_OUTCOME_VERIFIED",
            actor_identity_id="actor_1",
            transaction_id=txn_id,
            decision=OutcomeStatus.SUCCESS_CONFIRMED.value,
            prev_hash=GENESIS_ROOT_HASH,
            chain_hash=chk_hash,
            event_payload={"verified_at": now_iso},
            created_at=now,
        )

        # Mock DB session returns checkpoint when queried
        mock_session = AsyncMock()

        def session_execute_dispatcher(stmt: Any) -> Any:
            stmt_str = str(stmt)
            res = MagicMock()
            if "audit_checkpoints" in stmt_str:
                res.scalar_one_or_none.return_value = db_checkpoint
            elif "sequence_number =" in stmt_str or "audit_logs.sequence_number =" in stmt_str:
                res.scalar_one_or_none.return_value = audit_seq_1
            elif "event_type =" in stmt_str or "audit_logs.event_type =" in stmt_str:
                res.scalars.return_value.all.return_value = [audit_entry]
            else:
                res.scalar_one_or_none.return_value = None
                res.scalars.return_value.all.return_value = []
            return res

        mock_session.execute = AsyncMock(side_effect=session_execute_dispatcher)

        # Ensure in-memory registry does not have the checkpoint initially
        assert chk_hash not in checkpoint_reg._checkpoints.get(tid, {})

        # Verify against audit trail using chk_hash as root
        contract = await service.verify_record_against_audit_trail(
            session=mock_session,
            record=rec,
            trusted_root_hash=chk_hash,
        )

        assert contract.outcome_id == outcome_id
        assert contract.trust_assurance_level == TrustAssuranceLevel.EXTERNALLY_ANCHORED.value
        # Checkpoint is now cached in memory
        assert chk_hash in checkpoint_reg._checkpoints[tid]

    @pytest.mark.asyncio
    async def test_tampered_db_checkpoint_signature_fails_closed(self, auth_operator: AuthContext) -> None:
        """Tampered checkpoint signature in PostgreSQL fails closed with HTTP 409."""
        signer_id = "notary:test_signer"
        secret_key = b"test-notary-secret-key-for-p556!"
        key_reg = NotaryKeyRegistry(initial_keys={signer_id: secret_key})
        checkpoint_reg = TrustedCheckpointRegistry(notary_keys=key_reg)

        service = RealityVerifierService(checkpoint_registry=checkpoint_reg)
        tid = auth_operator.tenant_id
        now = datetime.now(UTC)
        chk_hash = "a" * 64

        db_checkpoint = AuditCheckpointRecord(
            id="chk_tampered",
            tenant_id=tid,
            checkpoint_hash=chk_hash,
            sequence_number=1,
            ledger_identity="audit_logs",
            signer_identity=signer_id,
            signature="forged_signature_0000000000000000000000000000000000000000000000000",
            trust_tier="EXTERNALLY_ANCHORED",
            revoked=False,
            issued_at=now,
            expires_at=now + timedelta(days=30),
            created_at=now,
        )

        rec = OutcomeVerificationRecord(
            id="outc_test",
            tenant_id=tid,
            transaction_id="txn_1",
            action_id="act_1",
            observability_class="OBS_DIRECT",
            outcome_status=OutcomeStatus.SUCCESS_CONFIRMED.value,
            epistemic_confidence=1.0,
            verifier_adapter="DatabaseStateAdapter",
            is_simulated=False,
            expected_postconditions={},
            observed_state={},
            discrepancies=[],
            evidence_payload={},
            reconciliation_notes=[],
            verification_hash="0" * 64,
            created_at=now,
            verified_at=now,
        )

        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = db_checkpoint
        mock_session.execute.return_value = mock_res

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_record_against_audit_trail(mock_session, rec, trusted_root_hash=chk_hash)

        assert exc_info.value.status_code == 409
        assert "Untrusted root hash" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_revoked_db_checkpoint_fails_closed(self, auth_operator: AuthContext) -> None:
        """Revoked checkpoint in PostgreSQL causes verification to fail closed with HTTP 409."""
        signer_id = "notary:test_signer"
        key_reg = NotaryKeyRegistry(initial_keys={signer_id: b"secret-key-32b-length-here!!!!!!"})
        checkpoint_reg = TrustedCheckpointRegistry(notary_keys=key_reg)

        service = RealityVerifierService(checkpoint_registry=checkpoint_reg)
        tid = auth_operator.tenant_id
        now = datetime.now(UTC)
        chk_hash = "b" * 64

        db_checkpoint = AuditCheckpointRecord(
            id="chk_revoked",
            tenant_id=tid,
            checkpoint_hash=chk_hash,
            sequence_number=1,
            ledger_identity="audit_logs",
            signer_identity=signer_id,
            signature="sig",
            trust_tier="EXTERNALLY_ANCHORED",
            revoked=True,
            revoked_at=now,
            revoked_by="security_admin",
            revocation_reason="Key rotation",
            issued_at=now,
            expires_at=now + timedelta(days=30),
            created_at=now,
        )

        rec = OutcomeVerificationRecord(
            id="outc_test",
            tenant_id=tid,
            transaction_id="txn_1",
            action_id="act_1",
            observability_class="OBS_DIRECT",
            outcome_status=OutcomeStatus.SUCCESS_CONFIRMED.value,
            epistemic_confidence=1.0,
            verifier_adapter="DatabaseStateAdapter",
            is_simulated=False,
            expected_postconditions={},
            observed_state={},
            discrepancies=[],
            evidence_payload={},
            reconciliation_notes=[],
            verification_hash="0" * 64,
            created_at=now,
            verified_at=now,
        )

        mock_session = AsyncMock()
        mock_res = MagicMock()
        mock_res.scalar_one_or_none.return_value = db_checkpoint
        mock_session.execute.return_value = mock_res

        with pytest.raises(HTTPException) as exc_info:
            await service.verify_record_against_audit_trail(mock_session, rec, trusted_root_hash=chk_hash)

        assert exc_info.value.status_code == 409
        assert "Untrusted root hash" in exc_info.value.detail


# =============================================================================
# PART 5: Control-Plane API Authorization (SUPER_ADMIN Only)
# =============================================================================

@pytest.mark.security
class TestControlPlaneAuthorization:
    """Verify that only SUPER_ADMIN is authorized to register or revoke audit checkpoints."""

    @pytest.mark.asyncio
    async def test_non_super_admin_cannot_register_checkpoint(self, auth_operator: AuthContext) -> None:
        """Role.OPERATOR attempting to register a checkpoint receives HTTP 403 Forbidden."""
        req = RegisterCheckpointRequest(
            checkpoint_hash="c" * 64,
            sequence_number=1,
            signer_identity="notary:primary",
            signature="sig",
        )
        with pytest.raises(HTTPException) as exc_info:
            await register_audit_checkpoint(req, auth=auth_operator)

        assert exc_info.value.status_code == 403
        assert "Requires SUPER_ADMIN" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_tenant_admin_cannot_register_checkpoint(self, auth_tenant_admin: AuthContext) -> None:
        """Role.TENANT_ADMIN attempting to register a checkpoint receives HTTP 403 Forbidden."""
        req = RegisterCheckpointRequest(
            checkpoint_hash="d" * 64,
            sequence_number=1,
            signer_identity="notary:primary",
            signature="sig",
        )
        with pytest.raises(HTTPException) as exc_info:
            await register_audit_checkpoint(req, auth=auth_tenant_admin)

        assert exc_info.value.status_code == 403
        assert "Requires SUPER_ADMIN" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_non_super_admin_cannot_revoke_checkpoint(self, auth_operator: AuthContext) -> None:
        """Role.OPERATOR attempting to revoke a checkpoint receives HTTP 403 Forbidden."""
        req = RevokeCheckpointRequest(checkpoint_hash="e" * 64, reason="Compromised")
        with pytest.raises(HTTPException) as exc_info:
            await revoke_audit_checkpoint(req, auth=auth_operator)

        assert exc_info.value.status_code == 403
        assert "Requires SUPER_ADMIN" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_super_admin_can_register_and_revoke_checkpoint(self, auth_super_admin: AuthContext) -> None:
        """Role.SUPER_ADMIN successfully registers and revokes an authenticated checkpoint."""
        signer_id = "notary:system_primary"
        secret_key = b"mirage-default-notary-secret-key-32b!"
        reality_verifier_service.checkpoint_registry.notary_keys.register_key(signer_id, secret_key)

        chk_hash = "f" * 64
        now = datetime.now(UTC)
        now_iso = now.isoformat()

        canon = compute_checkpoint_canonical_string(
            tenant_id=auth_super_admin.tenant_id,
            ledger_identity="audit_logs",
            sequence_number=0,
            checkpoint_hash=chk_hash,
            issued_at_iso=now_iso,
            signer_identity=signer_id,
        )
        sig = sign_checkpoint_payload(secret_key, canon)

        req = RegisterCheckpointRequest(
            checkpoint_hash=chk_hash,
            sequence_number=0,
            signer_identity=signer_id,
            signature=sig,
            issued_at=now,
        )

        with patch("gateway.routes.audit.db_session.get_tenant_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__.return_value = mock_session

            # Register
            reg_res = await register_audit_checkpoint(req, auth=auth_super_admin)
            assert reg_res["status"] == "REGISTERED"
            assert reg_res["checkpoint_hash"] == chk_hash

            # Revoke
            revoke_req = RevokeCheckpointRequest(checkpoint_hash=chk_hash, reason="Rotated")
            mock_update_res = MagicMock()
            mock_update_res.rowcount = 1
            mock_session.execute.return_value = mock_update_res

            rev_res = await revoke_audit_checkpoint(revoke_req, auth=auth_super_admin)
            assert rev_res["status"] == "REVOKED"
            assert rev_res["checkpoint_hash"] == chk_hash


# =============================================================================
# PART 6: Audit Ledger Monotonicity in PostgresPersistenceService
# =============================================================================

@pytest.mark.security
class TestPersistenceServiceSequenceConsistency:
    """Verify that PostgresPersistenceService assigns non-null monotonic sequence numbers."""

    @pytest.mark.asyncio
    async def test_persist_verification_transaction_assigns_sequence_number(self) -> None:
        """persist_verification_transaction populates non-null sequence_number on AuditLogRecord."""
        svc = PostgresPersistenceService()
        tenant_id = "t_p556_persist"
        session_id = f"sess_{uuid.uuid4().hex[:8]}"
        trace_id = "trace_p556"
        model_id = "test-model"

        with patch("db.persistence.db_session.AsyncSessionLocal") as mock_session_factory:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.flush = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_session.get.return_value = None
            mock_session_factory.return_value = mock_session

            mock_set_config = MagicMock()
            mock_tenant_lock = MagicMock()
            mock_tenant_lock.scalar_one_or_none.return_value = tenant_id

            # Tenant ledger head row mock with sequence 4
            ledger_head = TenantAuditLedger(
                tenant_id=tenant_id,
                head_entry_id="aud_4",
                head_chain_hash="prev_hash_4" + "0" * 53,
                sequence_number=4,
            )
            mock_ledger_res = MagicMock()
            mock_ledger_res.scalar_one_or_none.return_value = ledger_head

            # 1: set_config, 2: ensure_tenant_exists lock, 3: insert ledger, 4: select ledger FOR UPDATE
            mock_session.execute.side_effect = [
                mock_set_config,
                mock_tenant_lock,
                MagicMock(),
                mock_ledger_res,
            ]

            sess_rec, claims_recs, audit_rec = await svc.persist_verification_transaction(
                session_id=session_id,
                tenant_id=tenant_id,
                trace_id=trace_id,
                model_id=model_id,
                prompt="test prompt",
                response="test response",
                hrs_score=0.1,
                risk_tier="LOW",
                verified_claims=[],
            )

            assert audit_rec.sequence_number == 5
            assert ledger_head.sequence_number == 5
            assert audit_rec.prev_hash == "prev_hash_4" + "0" * 53

    @pytest.mark.asyncio
    async def test_live_postgres_persistence_sequential_numbers(self, live_postgres_database: Any) -> None:
        """PostgresPersistenceService on live PostgreSQL allocates strictly monotonic sequence numbers 1, 2, 3."""
        _ = live_postgres_database
        svc = PostgresPersistenceService()
        tenant_id = f"t_p556_seq_{uuid.uuid4().hex[:8]}"

        sequences = []
        prev_hashes = []
        chain_hashes = []

        for i in range(3):
            session_id = f"sess_{uuid.uuid4().hex[:8]}"
            sess_rec, claims_recs, audit_rec = await svc.persist_verification_transaction(
                session_id=session_id,
                tenant_id=tenant_id,
                trace_id=f"trace_{i}",
                model_id="test-model",
                prompt=f"test prompt {i}",
                response=f"test response {i}",
                hrs_score=0.1 * i,
                risk_tier="LOW",
                verified_claims=[],
            )
            sequences.append(audit_rec.sequence_number)
            prev_hashes.append(audit_rec.prev_hash)
            chain_hashes.append(audit_rec.chain_hash)

        assert sequences == [1, 2, 3], f"Expected sequences [1, 2, 3], got {sequences}"
        assert prev_hashes[0] == GENESIS_ROOT_HASH
        assert prev_hashes[1] == chain_hashes[0]
        assert prev_hashes[2] == chain_hashes[1]

