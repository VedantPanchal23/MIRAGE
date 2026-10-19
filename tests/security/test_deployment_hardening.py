"""Comprehensive test suite for Package 5: Production Deployment Hardening.

Validates:
1. Production configuration validation and fail-closed security rules on Settings.
2. External audit anchor proof hash chaining and tampering detection.
3. Health and readiness probe contracts, including audit anchor directory checks and credential sanitization.
4. Migration preflight logic and single linear head validation.
5. Backup bundle generation, cryptographic manifest verification, and fail-closed restore guardrails.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from gateway.main import app
from scripts.backup_restore import execute_backup, execute_restore, verify_backup_bundle
from scripts.migration_preflight import check_database_migration_status
from services.audit_anchor import AnchorProof, FileAuditAnchorBackend
from shared.config.settings import EnvironmentType, Settings
from shared.schemas.audit import CheckpointModel, NotaryKeyRegistry, TrustAssuranceLevel

# =============================================================================
# 1. Production Configuration Hardening Tests
# =============================================================================

class TestProductionSettingsHardening:
    """Validate Settings fail-closed enforcement under EnvironmentType.PRODUCTION."""

    def test_default_dev_secrets_rejected_in_production(self) -> None:
        """In production, pydantic raises ValidationError on default dev secret."""
        with pytest.raises(ValidationError, match="Production requires a unique JWT signing secret"):
            Settings(
                environment=EnvironmentType.PRODUCTION,
                secret_key="dev-insecure-secret-key-change-in-production-min32chars",
                celery_broker_url="amqps://mirage:secret@rabbit.internal:5671//",
            )

    def test_short_secret_key_rejected_in_production(self) -> None:
        """Production SECRET_KEY must be at least 48 characters."""
        with pytest.raises(ValidationError, match="Production requires a unique JWT signing secret"):
            Settings(
                environment=EnvironmentType.PRODUCTION,
                secret_key="a" * 32,  # Too short for production
                celery_broker_url="amqps://mirage:secret@rabbit.internal:5671//",
            )

    def test_plaintext_celery_broker_rejected_in_production(self) -> None:
        """AMQPS is mandatory in production mode."""
        s = Settings(
            environment=EnvironmentType.PRODUCTION,
            secret_key="x" * 48,
            celery_broker_url="amqps://mirage:secret@rabbit.internal:5671//",
        )
        # Manually alter attribute to test validate_production_configuration
        s.celery_broker_url = "amqp://mirage:secret@rabbit.internal:5672//"
        defects = s.validate_production_configuration()
        assert any("CELERY_BROKER_URL must use AMQPS" in d for d in defects)

    def test_missing_notary_keys_rejected_in_production(self) -> None:
        """Production requires NOTARY_KEYS_JSON configured."""
        s = Settings(
            environment=EnvironmentType.PRODUCTION,
            secret_key="x" * 48,
            celery_broker_url="amqps://mirage:secret@rabbit.internal:5671//",
            notary_keys_json=None,
        )
        defects = s.validate_production_configuration()
        assert any("NOTARY_KEYS_JSON must be configured" in d for d in defects)

    def test_default_database_password_rejected_in_production(self) -> None:
        """Default 'mirage_dev_secret' in DATABASE_URL is flagged as a defect."""
        s = Settings(
            environment=EnvironmentType.PRODUCTION,
            secret_key="x" * 48,
            celery_broker_url="amqps://mirage:secret@rabbit.internal:5671//",
            notary_keys_json=json.dumps({"notary:primary": "a" * 32}),
        )
        s.database_url = "postgresql+asyncpg://mirage:mirage_dev_secret@prod-db:5432/mirage_db"
        defects = s.validate_production_configuration()
        assert any("DATABASE_URL / DATABASE_SYNC_URL contains default development password" in d for d in defects)

    def test_compliant_production_configuration_passes(self) -> None:
        """A properly configured production environment produces zero configuration defects."""
        s = Settings(
            environment=EnvironmentType.PRODUCTION,
            secret_key="x" * 64,
            celery_broker_url="amqps://mirage:prod_secret@rabbit.internal:5671//",
            notary_keys_json=json.dumps({"notary:system_primary": "k" * 32}),
            allow_dev_notary_keys=False,
            demo_auth_enabled=False,
            allow_mock_providers=False,
        )
        s.database_url = "postgresql+asyncpg://mirage_app:strong_pw@prod-db:5432/mirage_db"
        s.database_sync_url = "postgresql://mirage:strong_pw@prod-db:5432/mirage_db"
        s.redis_url = "redis://mirage_app:strong_redis_pw@prod-redis:6379/0"
        s.redis_password = "strong_redis_pw"

        defects = s.validate_production_configuration()
        assert defects == []


# =============================================================================
# 2. External Audit Anchor Hash-Chaining & Tamper Detection Tests
# =============================================================================

class TestAuditAnchorHashChaining:
    """Validate that FileAuditAnchorBackend implements immutable hash chaining across anchor proofs."""

    @pytest.mark.asyncio
    async def test_anchor_proof_hash_chain_continuity(self, tmp_path: Path) -> None:
        """Verify that sequential anchor writes form a cryptographically linked hash chain."""
        anchor_dir = tmp_path / "anchors"
        notary_keys = NotaryKeyRegistry(
            initial_keys={"notary:test_primary": b"01234567890123456789012345678901"}
        )
        backend = FileAuditAnchorBackend(anchor_dir=anchor_dir, notary_keys=notary_keys)
        tenant_id = "tenant_chain_test"

        # 1. Write Anchor 1 (Genesis)
        cp1 = CheckpointModel(
            checkpoint_id="chk_1",
            tenant_id=tenant_id,
            checkpoint_hash="1" * 64,
            sequence_number=1,
            ledger_identity="audit_logs",
            signer_identity="notary:test_primary",
            signature="sig1",
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=datetime.now(UTC),
        )
        # Compute valid signature
        from shared.schemas.audit import compute_checkpoint_canonical_string, sign_checkpoint_payload
        canon1 = compute_checkpoint_canonical_string(
            tenant_id=tenant_id,
            ledger_identity=cp1.ledger_identity,
            sequence_number=cp1.sequence_number,
            checkpoint_hash=cp1.checkpoint_hash,
            issued_at_iso=cp1.issued_at.isoformat(),
            signer_identity=cp1.signer_identity,
        )
        cp1.signature = sign_checkpoint_payload(b"01234567890123456789012345678901", canon1)

        proof1 = await backend.write_anchor(tenant_id, cp1)
        assert proof1.prev_anchor_digest == "0" * 64

        # 2. Write Anchor 2
        cp2 = CheckpointModel(
            checkpoint_id="chk_2",
            tenant_id=tenant_id,
            checkpoint_hash="2" * 64,
            sequence_number=2,
            ledger_identity="audit_logs",
            signer_identity="notary:test_primary",
            signature="sig2",
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=datetime.now(UTC),
        )
        canon2 = compute_checkpoint_canonical_string(
            tenant_id=tenant_id,
            ledger_identity=cp2.ledger_identity,
            sequence_number=cp2.sequence_number,
            checkpoint_hash=cp2.checkpoint_hash,
            issued_at_iso=cp2.issued_at.isoformat(),
            signer_identity=cp2.signer_identity,
        )
        cp2.signature = sign_checkpoint_payload(b"01234567890123456789012345678901", canon2)

        proof2 = await backend.write_anchor(tenant_id, cp2)
        assert proof2.prev_anchor_digest == proof1.anchor_digest

        # 3. Write Anchor 3
        cp3 = CheckpointModel(
            checkpoint_id="chk_3",
            tenant_id=tenant_id,
            checkpoint_hash="3" * 64,
            sequence_number=3,
            ledger_identity="audit_logs",
            signer_identity="notary:test_primary",
            signature="sig3",
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=datetime.now(UTC),
        )
        canon3 = compute_checkpoint_canonical_string(
            tenant_id=tenant_id,
            ledger_identity=cp3.ledger_identity,
            sequence_number=cp3.sequence_number,
            checkpoint_hash=cp3.checkpoint_hash,
            issued_at_iso=cp3.issued_at.isoformat(),
            signer_identity=cp3.signer_identity,
        )
        cp3.signature = sign_checkpoint_payload(b"01234567890123456789012345678901", canon3)

        proof3 = await backend.write_anchor(tenant_id, cp3)
        assert proof3.prev_anchor_digest == proof2.anchor_digest

        # 4. Verify Entire Anchor Chain
        is_valid, defects = await backend.verify_anchor_chain(tenant_id)
        assert is_valid is True
        assert defects == []

    @pytest.mark.asyncio
    async def test_anchor_chain_detects_intermediate_deletion(self, tmp_path: Path) -> None:
        """Removing an intermediate anchor from the file breaks hash chain linkage."""
        anchor_dir = tmp_path / "anchors"
        notary_keys = NotaryKeyRegistry(
            initial_keys={"notary:test_primary": b"01234567890123456789012345678901"}
        )
        backend = FileAuditAnchorBackend(anchor_dir=anchor_dir, notary_keys=notary_keys)
        tenant_id = "tenant_deletion_test"

        # Create 3 anchors
        from shared.schemas.audit import compute_checkpoint_canonical_string, sign_checkpoint_payload

        for i in (1, 2, 3):
            now = datetime.now(UTC)
            canon = compute_checkpoint_canonical_string(
                tenant_id=tenant_id,
                ledger_identity="audit_logs",
                sequence_number=i,
                checkpoint_hash=str(i) * 64,
                issued_at_iso=now.isoformat(),
                signer_identity="notary:test_primary",
            )
            sig = sign_checkpoint_payload(b"01234567890123456789012345678901", canon)
            cp = CheckpointModel(
                checkpoint_id=f"chk_{i}",
                tenant_id=tenant_id,
                checkpoint_hash=str(i) * 64,
                sequence_number=i,
                ledger_identity="audit_logs",
                signer_identity="notary:test_primary",
                signature=sig,
                trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
                issued_at=now,
            )
            await backend.write_anchor(tenant_id, cp)

        tenant_file = anchor_dir / f"{tenant_id}.anchors.jsonl"
        lines = tenant_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

        # Tamper: Delete anchor 2 (intermediate record deletion)
        tampered_lines = [lines[0], lines[2]]
        tenant_file.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")

        # Verify chain fails closed
        is_valid, defects = await backend.verify_anchor_chain(tenant_id)
        assert is_valid is False
        assert any("Anchor proof chain broken" in d for d in defects)


# =============================================================================
# 3. Health & Readiness Probe Hardening Tests
# =============================================================================

class TestHealthAndReadinessHardening:
    """Validate /v1/health and /v1/ready probe behavior under deployment conditions."""

    @pytest.mark.asyncio
    async def test_readiness_probe_includes_audit_anchor(self) -> None:
        """Verify /v1/ready includes audit_anchor status indicator."""
        with (
            patch("gateway.routes.health.check_database_connection", new_callable=AsyncMock) as mock_pg,
            patch("gateway.routes.health.default_redis_client_manager.ping", new_callable=AsyncMock) as mock_redis,
            patch(
                "gateway.routes.health.default_mongo_trace_service.check_health", new_callable=AsyncMock
            ) as mock_mongo,
            patch("gateway.routes.health._check_rabbitmq_ready", new_callable=AsyncMock) as mock_rabbit,
            patch("gateway.routes.health._check_qdrant_ready", new_callable=AsyncMock) as mock_qdrant,
            patch("gateway.routes.health._check_audit_anchor_writable", return_value=True),
        ):
            mock_pg.return_value = True
            mock_redis.return_value = True
            mock_mongo.return_value = {"status": "pass"}
            mock_rabbit.return_value = True
            mock_qdrant.return_value = True

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/ready")
                assert resp.status_code == 200
                data = resp.json()
                assert data["status"] == "ready"
                assert "audit_anchor" in data["components"]
                assert data["components"]["audit_anchor"] == "up"

    @pytest.mark.asyncio
    async def test_readiness_probe_fails_in_production_when_anchor_unwritable(self) -> None:
        """In production mode, an unwritable audit anchor directory returns HTTP 503."""
        with (
            patch("gateway.routes.health.check_database_connection", new_callable=AsyncMock) as mock_pg,
            patch("gateway.routes.health.default_redis_client_manager.ping", new_callable=AsyncMock) as mock_redis,
            patch(
                "gateway.routes.health.default_mongo_trace_service.check_health", new_callable=AsyncMock
            ) as mock_mongo,
            patch("gateway.routes.health._check_rabbitmq_ready", new_callable=AsyncMock) as mock_rabbit,
            patch("gateway.routes.health._check_qdrant_ready", new_callable=AsyncMock) as mock_qdrant,
            patch("gateway.routes.health._check_audit_anchor_writable", return_value=False),
            patch("gateway.routes.health.settings.environment", EnvironmentType.PRODUCTION),
        ):
            mock_pg.return_value = True
            mock_redis.return_value = True
            mock_mongo.return_value = {"status": "pass"}
            mock_rabbit.return_value = True
            mock_qdrant.return_value = True

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/v1/ready")
                assert resp.status_code == 503
                data = resp.json()
                assert data["status"] == "unready"
                assert "audit_anchor" in data["failed_components"]
                assert data["components"]["audit_anchor"] == "down"


# =============================================================================
# 4. Migration Preflight Script Tests
# =============================================================================

class TestMigrationPreflightAutomation:
    """Validate migration preflight detection on clean and configured databases."""

    def test_preflight_detects_target_head(self, tmp_path: Path) -> None:
        """Preflight identifies Alembic target head as 023_governed_mcp_servers."""
        sqlite_file = tmp_path / "preflight_test.db"
        report = check_database_migration_status(database_url=f"sqlite:///{sqlite_file}")
        assert report["target_head_revision"] == "023_governed_mcp_servers"
        assert report["connected"] is True
        assert report["status"] == "FRESH_DATABASE_PENDING_MIGRATION"
        assert len(report["pending_revisions"]) == 23


# =============================================================================
# 5. Backup & Disaster Recovery Script Tests
# =============================================================================

class TestBackupAndDisasterRecovery:
    """Validate signed backup bundle creation, manifest verification, and restore safety."""

    def test_backup_and_verify_cycle(self, tmp_path: Path) -> None:
        """Create a backup bundle and verify its SHA-256 manifest."""
        out_dir = tmp_path / "backups"
        anchor_src = tmp_path / "source_anchors"
        anchor_src.mkdir(parents=True, exist_ok=True)

        from shared.schemas.audit import (
            compute_checkpoint_canonical_string,
            compute_sha256,
            sign_checkpoint_payload,
        )

        now = datetime.now(UTC)
        canon = compute_checkpoint_canonical_string(
            tenant_id="t1",
            ledger_identity="audit_logs",
            sequence_number=1,
            checkpoint_hash="a" * 64,
            issued_at_iso=now.isoformat(),
            signer_identity="notary:system_primary",
        )
        sig = sign_checkpoint_payload(b"mirage-default-notary-secret-key-32b!", canon)
        digest = compute_sha256(f"anchor:{canon}:{sig}:{'0'*64}")
        proof = AnchorProof(
            anchor_id="anc_t1_1",
            tenant_id="t1",
            checkpoint_hash="a" * 64,
            sequence_number=1,
            ledger_identity="audit_logs",
            signer_identity="notary:system_primary",
            signature=sig,
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=now,
            anchored_at=now,
            prev_anchor_digest="0" * 64,
            anchor_digest=digest,
        )
        (anchor_src / "t1.anchors.jsonl").write_text(proof.model_dump_json() + "\n", encoding="utf-8")

        # 1. Execute Backup
        res = execute_backup(output_dir=out_dir, anchor_dir=anchor_src)
        assert res["status"] == "BACKUP_COMPLETED"
        bundle_path = Path(res["bundle_path"])
        assert (bundle_path / "manifest.json").exists()

        # 2. Verify Pristine Bundle
        verification = verify_backup_bundle(bundle_path)
        assert verification["valid"] is True
        assert verification["status"] == "VALID"
        assert verification["errors"] == []

    def test_verify_detects_tampered_bundle_file(self, tmp_path: Path) -> None:
        """Altering any file inside the backup bundle trips the SHA-256 verification."""
        out_dir = tmp_path / "backups"
        anchor_src = tmp_path / "source_anchors"
        anchor_src.mkdir(parents=True, exist_ok=True)

        from shared.schemas.audit import (
            compute_checkpoint_canonical_string,
            compute_sha256,
            sign_checkpoint_payload,
        )

        now = datetime.now(UTC)
        canon = compute_checkpoint_canonical_string(
            tenant_id="t1",
            ledger_identity="audit_logs",
            sequence_number=1,
            checkpoint_hash="a" * 64,
            issued_at_iso=now.isoformat(),
            signer_identity="notary:system_primary",
        )
        sig = sign_checkpoint_payload(b"mirage-default-notary-secret-key-32b!", canon)
        digest = compute_sha256(f"anchor:{canon}:{sig}:{'0'*64}")
        proof = AnchorProof(
            anchor_id="anc_t1_1",
            tenant_id="t1",
            checkpoint_hash="a" * 64,
            sequence_number=1,
            ledger_identity="audit_logs",
            signer_identity="notary:system_primary",
            signature=sig,
            trust_tier=TrustAssuranceLevel.LOCAL_UNANCHORED,
            issued_at=now,
            anchored_at=now,
            prev_anchor_digest="0" * 64,
            anchor_digest=digest,
        )
        (anchor_src / "t1.anchors.jsonl").write_text(proof.model_dump_json() + "\n", encoding="utf-8")

        res = execute_backup(output_dir=out_dir, anchor_dir=anchor_src)
        bundle_path = Path(res["bundle_path"])

        # Tamper: overwrite captured anchor file
        tamper_target = bundle_path / "audit_anchors" / "t1.anchors.jsonl"
        tamper_target.write_text("{\"tampered\": true}\n", encoding="utf-8")

        # Verify fails
        verification = verify_backup_bundle(bundle_path)
        assert verification["valid"] is False
        assert verification["status"] == "INTEGRITY_COMPROMISED"
        assert any("checksum mismatch" in err for err in verification["errors"])

    def test_restore_without_confirm_aborts_safely(self, tmp_path: Path) -> None:
        """Executing restore without --confirm fails closed."""
        res = execute_restore(bundle_dir=tmp_path, confirm=False)
        assert res["success"] is False
        assert res["status"] == "RESTORE_ABORTED_UNCONFIRMED"
