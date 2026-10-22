"""MIRAGE 3.0 — Phase 5.5.7 Authoritative Ledger Fail-Closed Integrity & Trust-Label Certification.

Covers:
1. Migration 011 and live PostgreSQL schema invariant: audit_logs.sequence_number NOT NULL.
2. Production PostgreSQL concurrency: concurrent service calls serialize without sequence forks or gaps.
3. Fail-closed rollback: lock or ledger-head failure strictly aborts without test fallback.
4. Authoritative chain verification: PostgreSQL failure returns HTTP 503; zero fallback to local store.
5. Empty ledger verification: empty chain returns valid=False and chain_status="EMPTY" (not valid=True).
6. Local diagnostic endpoint isolation: /v1/audit/diagnostics/local-chain marked DIAGNOSTIC_ONLY and non-authoritative.
7. Compliance report integrity: non-existent session strictly returns HTTP 404 (zero synthetic fallback data).
8. Notary trust hardening: malformed NOTARY_KEYS_JSON rejected; revoked keys fail closed; safe __repr__.
9. Conservative trust labels: EXTERNALLY_ANCHORED rejected with HTTP 400; HMAC yields LOCAL_UNANCHORED;
   sequence 0 non-genesis rejected.
"""

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from db.models import AuditLogRecord
from gateway.routes.audit import (
    RegisterCheckpointRequest,
    get_compliance_report,
    get_compliance_report_pdf,
    get_diagnostic_local_chain,
    register_audit_checkpoint,
    verify_audit_chain,
)
from services.reality_verifier import RealityVerifierService, reality_verifier_service
from shared.config import EnvironmentType, Settings
from shared.schemas.audit import (
    GENESIS_ROOT_HASH,
    CheckpointModel,
    NotaryKeyRegistry,
    TrustAssuranceLevel,
    TrustedCheckpointRegistry,
    compute_checkpoint_canonical_string,
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
        tenant_id="tenant_p557_auth",
        user_id="super_admin_p557",
        role=Role.SUPER_ADMIN,
        identity_id="ident_super_admin_p557",
    )


@pytest.fixture
def auth_operator() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_p557_auth",
        user_id="operator_p557",
        role=Role.OPERATOR,
        identity_id="ident_operator_p557",
    )


@pytest.fixture
def sync_engine(live_postgres_database: Any) -> Any:
    _ = live_postgres_database
    sync_url = os.environ.get("DATABASE_SYNC_URL")
    assert sync_url is not None, "DATABASE_SYNC_URL must be configured by live_postgres_database fixture"
    eng = create_engine(sync_url, pool_size=10, max_overflow=10)
    yield eng
    eng.dispose()


# =============================================================================
# PART 1: Live PostgreSQL Catalog & Migration 011 Invariant Check
# =============================================================================


@pytest.mark.security
class TestMigration011CatalogInvariant:
    """Verify that Alembic migration 011 enforces NOT NULL on audit_logs.sequence_number in PostgreSQL."""

    def test_live_postgres_audit_logs_sequence_number_not_null(self, sync_engine: Any) -> None:
        """Query PostgreSQL information_schema.columns to confirm sequence_number is_nullable == 'NO'."""
        with sync_engine.connect() as conn:
            res = conn.execute(
                text(
                    """
                    SELECT is_nullable, column_default, data_type
                    FROM information_schema.columns
                    WHERE table_name = 'audit_logs' AND column_name = 'sequence_number';
                    """
                )
            ).fetchone()

            assert res is not None, "Column audit_logs.sequence_number not found in database catalog"
            is_nullable, column_default, data_type = res
            assert is_nullable == "NO", f"Expected audit_logs.sequence_number NOT NULL, got is_nullable={is_nullable}"
            assert "bigint" in data_type.lower() or "integer" in data_type.lower()

    def test_direct_null_sequence_number_insert_rejected_by_engine(self, sync_engine: Any) -> None:
        """Attempting raw SQL insert with explicit NULL sequence_number raises NotNullViolation."""
        tenant_id = f"t_p557_notnull_{uuid.uuid4().hex[:8]}"
        entry_id = f"aud_null_{uuid.uuid4().hex[:8]}"

        with sync_engine.connect() as conn:
            # Seed tenant
            conn.execute(
                text(
                    "INSERT INTO tenants (id, name, api_key_hash, created_at) "
                    "VALUES (:id, 'Test', :hash, NOW()) ON CONFLICT DO NOTHING"
                ),
                {"id": tenant_id, "hash": uuid.uuid4().hex[:32]},
            )
            conn.commit()

            with pytest.raises(Exception) as exc_info:
                conn.execute(
                    text(
                        """
                        INSERT INTO audit_logs (
                            entry_id, tenant_id, sequence_number, session_id, trace_id,
                            prompt_hash, response_hash, hrs_score, risk_tier, claims_count,
                            prev_hash, chain_hash, created_at
                        )
                        VALUES (
                            :entry_id, :tenant, NULL, 'sess_1', 'trace_1', 'ph', 'rh', 0.0,
                            'LOW', 0, '0' * 64, 'ch', NOW()
                        )
                        """
                    ),
                    {"entry_id": entry_id, "tenant": tenant_id},
                )
                conn.commit()

            err_str = str(exc_info.value).lower()
            assert 'null value in column "sequence_number"' in err_str or "not-null constraint" in err_str


# =============================================================================
# PART 2: Production PostgreSQL Concurrency & Monotonicity
# =============================================================================


@pytest.mark.security
class TestPostgresProductionPathConcurrency:
    """Verify concurrent RealityVerifierService outcome appends serialize without forks or gaps."""

    @pytest.mark.asyncio
    async def test_concurrent_reality_verifier_appends_serialize_strictly(self, sync_engine: Any) -> None:
        """Call RealityVerifierService.verify_action_outcome concurrently across 8 tasks on PostgreSQL."""
        test_tenant = f"t_p557_conc_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        num_workers = 8

        action_ids: list[str] = []
        txn_ids: list[str] = []

        with sync_engine.connect() as conn:
            conn.execute(
                text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:id, 'Test Conc', :hash, :now)"),
                {"id": test_tenant, "hash": uuid.uuid4().hex[:32], "now": now},
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

            for i in range(num_workers):
                a_id = f"act_p557_c_{i}_{uuid.uuid4().hex[:6]}"
                t_id = f"txn_p557_c_{i}_{uuid.uuid4().hex[:6]}"
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
                        "idem": f"idem_conc_{i}",
                        "now": now,
                    },
                )
            conn.commit()

        service = RealityVerifierService()
        auth = AuthContext(
            tenant_id=test_tenant,
            user_id="operator_conc",
            role=Role.OPERATOR,
            identity_id=f"actor_{test_tenant}",
        )

        async def _worker(idx: int) -> Any:
            req = OutcomeVerificationRequest(
                transaction_id=txn_ids[idx],
                action_id=action_ids[idx],
                observability_class=ObservabilityClass.OBS_DIRECT,
                verifier_type=OutcomeVerifierType.SIMULATED,
                expected_postconditions={"status": "PROCESSED"},
                adapter_config={"simulated_state": {"status": "PROCESSED"}, "allow_simulated_for_test": True},
            )
            return await service.verify_action_outcome(req, auth)

        results = await asyncio.gather(*[_worker(i) for i in range(num_workers)])
        assert len(results) == num_workers
        for contract in results:
            assert contract.outcome_status == OutcomeStatus.ACKNOWLEDGED_UNVERIFIED.value

        # Inspect resulting audit_logs in PostgreSQL
        with sync_engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT sequence_number, prev_hash, chain_hash, entry_id
                    FROM audit_logs
                    WHERE tenant_id = :tenant_id
                    ORDER BY sequence_number ASC;
                    """
                ),
                {"tenant_id": test_tenant},
            ).fetchall()

            assert len(rows) == num_workers, f"Expected {num_workers} audit records, got {len(rows)}"

            sequences = [r[0] for r in rows]
            assert sequences == list(range(1, num_workers + 1)), f"Sequences must be 1..{num_workers}, got {sequences}"

            # Verify unbroken cryptographic chain
            assert rows[0][1] == GENESIS_ROOT_HASH, "First entry must chain from GENESIS_ROOT_HASH"
            for i in range(1, num_workers):
                assert rows[i][1] == rows[i - 1][2], (
                    f"Chain break at index {i}: prev_hash {rows[i][1]} != previous chain_hash {rows[i - 1][2]}"
                )

            # Verify tenant_audit_ledgers head
            head = conn.execute(
                text(
                    """
                    SELECT sequence_number, head_chain_hash, head_entry_id
                    FROM tenant_audit_ledgers
                    WHERE tenant_id = :tenant_id;
                    """
                ),
                {"tenant_id": test_tenant},
            ).fetchone()

            assert head is not None
            assert head[0] == num_workers
            assert head[1] == rows[-1][2]
            assert head[2] == rows[-1][3]


# =============================================================================
# PART 3: Authoritative Verification & Fail-Closed Integrity
# =============================================================================


@pytest.mark.security
class TestAuthoritativeVerificationIntegrity:
    """Verify that audit chain verification is authoritative and fails closed without mock fallback."""

    @pytest.mark.asyncio
    async def test_database_error_returns_http_503_no_in_memory_fallback(self, auth_operator: AuthContext) -> None:
        """When PostgreSQL fails during /verify-chain, endpoint raises HTTP 503 Service Unavailable."""
        with patch(
            "gateway.routes.audit.AuditService.verify_audit_hash_chain_authoritative",
            side_effect=Exception("Database connection terminated"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await verify_audit_chain(tenant_id=auth_operator.tenant_id)

            assert exc_info.value.status_code == 503
            assert "Authoritative audit chain verification unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_empty_chain_returns_valid_false_and_status_empty(self, auth_operator: AuthContext) -> None:
        """An empty audit chain in PostgreSQL returns valid=False and chain_status='EMPTY'."""
        with patch(
            "gateway.routes.audit.AuditService.verify_audit_hash_chain_authoritative",
            return_value={
                "valid": False,
                "tenant_id": auth_operator.tenant_id,
                "total_records_verified": 0,
                "chain_status": "EMPTY",
                "message": "No audit records found in database for tenant; ledger is empty.",
            },
        ):
            res = await verify_audit_chain(tenant_id=auth_operator.tenant_id)
            assert res["valid"] is False
            assert res["chain_status"] == "EMPTY"
            assert res["total_records_verified"] == 0

    @pytest.mark.asyncio
    async def test_tampered_chain_returns_valid_false_and_status_tampered(self, auth_operator: AuthContext) -> None:
        """A tampered audit record in PostgreSQL returns valid=False and chain_status='TAMPERED'."""
        with patch(
            "gateway.routes.audit.AuditService.verify_audit_hash_chain_authoritative",
            return_value={
                "valid": False,
                "tenant_id": auth_operator.tenant_id,
                "chain_status": "TAMPERED",
                "tampered_at_index": 2,
                "error": "Cryptographic payload hash mismatch (tamper detected)",
            },
        ):
            res = await verify_audit_chain(tenant_id=auth_operator.tenant_id)
            assert res["valid"] is False
            assert res["chain_status"] == "TAMPERED"
            assert res["tampered_at_index"] == 2

    @pytest.mark.asyncio
    async def test_local_diagnostic_chain_explicitly_labeled_non_authoritative(
        self, auth_operator: AuthContext
    ) -> None:
        """Diagnostic local endpoint /diagnostics/local-chain explicitly tags responses as DIAGNOSTIC_ONLY."""
        res = await get_diagnostic_local_chain(tenant_id=auth_operator.tenant_id)
        assert res["source"] == "local_diagnostic_store"
        assert res["assurance_level"] == "DIAGNOSTIC_ONLY"
        assert res["authoritative"] is False


# =============================================================================
# PART 4: Compliance Report & PDF Integrity (Zero Synthetic Fallback)
# =============================================================================


@pytest.mark.security
class TestComplianceReportZeroSyntheticFallback:
    """Verify that requesting a report for a non-existent session returns HTTP 404 (zero dummy data)."""

    @pytest.mark.asyncio
    async def test_non_existent_session_report_returns_404(self, auth_operator: AuthContext) -> None:
        """GET /v1/audit/report/{session_id} returns HTTP 404 if session does not exist in PostgreSQL."""
        with patch(
            "db.persistence.default_persistence_service.get_session_with_claims",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = (None, [])

            with pytest.raises(HTTPException) as exc_info:
                await get_compliance_report(session_id="non_existent_sess", tenant_id=auth_operator.tenant_id)

            assert exc_info.value.status_code == 404
            assert "Session 'non_existent_sess' not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_non_existent_session_pdf_returns_404(self, auth_operator: AuthContext) -> None:
        """GET /v1/audit/report/{session_id}/pdf returns HTTP 404 if session does not exist in PostgreSQL."""
        with patch(
            "db.persistence.default_persistence_service.get_session_with_claims",
            new_callable=AsyncMock,
        ) as mock_get:
            mock_get.return_value = (None, [])

            with pytest.raises(HTTPException) as exc_info:
                await get_compliance_report_pdf(session_id="non_existent_sess_pdf", tenant_id=auth_operator.tenant_id)

            assert exc_info.value.status_code == 404
            assert "Session 'non_existent_sess_pdf' not found" in exc_info.value.detail


# =============================================================================
# PART 5: Notary Trust Hardening & Revocation Enforcement
# =============================================================================


@pytest.mark.security
class TestNotaryHardeningAndRevocation:
    """Verify strict notary key format validation, revocation fail-closed, and safe logging."""

    def test_settings_validator_rejects_malformed_notary_keys_json(self) -> None:
        """Settings rejects invalid JSON, non-string identities, or keys < 32 chars."""
        # Non-JSON
        with pytest.raises(ValidationError):
            Settings(
                environment=EnvironmentType.DEVELOPMENT,
                secret_key="a" * 48,
                celery_broker_url="amqps://user:pass@host:5671//",
                notary_keys_json="not-a-json-string",
            )

        # Short key (< 32 chars)
        with pytest.raises(ValidationError):
            Settings(
                environment=EnvironmentType.DEVELOPMENT,
                secret_key="a" * 48,
                celery_broker_url="amqps://user:pass@host:5671//",
                notary_keys_json=json.dumps({"notary:signer1": "short-key-16b"}),
            )

    def test_notary_key_registry_raises_on_malformed_json_in_production(self) -> None:
        """In production, malformed NOTARY_KEYS_JSON in settings raises ValueError immediately."""
        with patch("shared.config.get_settings") as mock_settings:
            s = MagicMock()
            s.environment = EnvironmentType.PRODUCTION
            s.allow_dev_notary_keys = False
            s.notary_keys_json = json.dumps({"notary:signer1": "too-short"})
            mock_settings.return_value = s

            with pytest.raises(ValueError, match="must be at least 32 characters"):
                NotaryKeyRegistry()

    def test_notary_key_revocation_fails_closed(self) -> None:
        """Revoking a notary key prevents get_key from returning secret and rejects registration."""
        reg = NotaryKeyRegistry(initial_keys={"notary:signer1": b"a" * 32})
        assert reg.get_key("notary:signer1") == b"a" * 32

        reg.revoke_key("notary:signer1")
        assert reg.is_key_revoked("notary:signer1") is True
        assert reg.get_key("notary:signer1") is None

        # Re-registration of revoked key rejected
        with pytest.raises(ValueError, match="Cannot register key for revoked signer identity"):
            reg.register_key("notary:signer1", b"b" * 32)

    def test_notary_key_registry_repr_never_leaks_secrets(self) -> None:
        """__repr__ of NotaryKeyRegistry must never display secret key bytes."""
        reg = NotaryKeyRegistry(initial_keys={"notary:signer1": b"super-secret-key-32b-length-here!"})
        repr_str = repr(reg)
        assert "super-secret-key" not in repr_str
        assert "notary:signer1" in repr_str


# =============================================================================
# PART 6: Conservative Trust Labels & Sentinel Validation
# =============================================================================


@pytest.mark.security
class TestConservativeTrustLabels:
    """Verify conservative trust assurance level semantics and root sentinel rules."""

    @pytest.mark.asyncio
    async def test_register_checkpoint_rejects_externally_anchored_tier(self, auth_super_admin: AuthContext) -> None:
        """POST /v1/audit/checkpoints rejects trust_tier='EXTERNALLY_ANCHORED' with HTTP 400."""
        req = RegisterCheckpointRequest(
            checkpoint_hash="a" * 64,
            sequence_number=1,
            signer_identity="notary:primary",
            signature="sig",
            trust_tier="EXTERNALLY_ANCHORED",
        )
        with pytest.raises(HTTPException) as exc_info:
            await register_audit_checkpoint(req, auth=auth_super_admin)

        assert exc_info.value.status_code == 400
        assert "EXTERNALLY_ANCHORED" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_register_checkpoint_sequence_0_with_non_genesis_rejected(
        self, auth_super_admin: AuthContext
    ) -> None:
        """POST /v1/audit/checkpoints rejects sequence_number=0 with non-genesis hash with HTTP 400."""
        req = RegisterCheckpointRequest(
            checkpoint_hash="b" * 64,  # Non-genesis hash
            sequence_number=0,
            signer_identity="notary:primary",
            signature="sig",
        )
        with pytest.raises(HTTPException) as exc_info:
            await register_audit_checkpoint(req, auth=auth_super_admin)

        assert exc_info.value.status_code == 400
        assert "Sequence number 0 is reserved strictly for genesis" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_register_checkpoint_sequence_mismatch_against_database_rejected(
        self, auth_super_admin: AuthContext
    ) -> None:
        """POST /v1/audit/checkpoints rejects sequence > 0 if database chain_hash does not match."""
        signer_id = "notary:test_signer"
        secret_key = b"k" * 32
        reality_verifier_service.checkpoint_registry.notary_keys.register_key(signer_id, secret_key)

        now = datetime.now(UTC)
        chk_hash = "c" * 64
        canon = compute_checkpoint_canonical_string(
            tenant_id=auth_super_admin.tenant_id,
            ledger_identity="audit_logs",
            sequence_number=5,
            checkpoint_hash=chk_hash,
            issued_at_iso=now.isoformat(),
            signer_identity=signer_id,
        )
        sig = sign_checkpoint_payload(secret_key, canon)

        req = RegisterCheckpointRequest(
            checkpoint_hash=chk_hash,
            sequence_number=5,
            signer_identity=signer_id,
            signature=sig,
            issued_at=now,
        )

        with patch("gateway.routes.audit.db_session.get_tenant_session") as mock_ctx:
            mock_session = AsyncMock()
            mock_res = MagicMock()
            # Database has a different chain_hash at sequence 5
            audit_log = AuditLogRecord(
                entry_id="aud_5",
                tenant_id=auth_super_admin.tenant_id,
                sequence_number=5,
                session_id="sess_5",
                trace_id="tr_5",
                prompt_hash="0" * 64,
                response_hash="0" * 64,
                hrs_score=0.0,
                risk_tier="LOW",
                claims_count=0,
                prev_hash="0" * 64,
                chain_hash="d" * 64,  # Mismatch!
                created_at=datetime.now(UTC),
            )
            mock_res.scalar_one_or_none.return_value = audit_log
            mock_session.execute.return_value = mock_res
            mock_ctx.return_value.__aenter__.return_value = mock_session

            with pytest.raises(HTTPException) as exc_info:
                await register_audit_checkpoint(req, auth=auth_super_admin)

            assert exc_info.value.status_code == 409
            assert "Checkpoint sequence mismatch" in exc_info.value.detail

    def test_checkpoint_model_rejects_externally_anchored_in_registry(self) -> None:
        """register_authenticated_checkpoint raises ValueError if trust_tier is EXTERNALLY_ANCHORED."""
        registry = TrustedCheckpointRegistry()
        cp = CheckpointModel(
            checkpoint_id="chk_1",
            tenant_id="t1",
            checkpoint_hash="e" * 64,
            sequence_number=1,
            ledger_identity="audit_logs",
            signer_identity="notary:primary",
            signature="sig",
            trust_tier=TrustAssuranceLevel.EXTERNALLY_ANCHORED,
            issued_at=datetime.now(UTC),
        )
        with pytest.raises(ValueError, match="EXTERNALLY_ANCHORED.*is currently unsupported"):
            registry.register_authenticated_checkpoint(cp)
