"""Live PostgreSQL Integration Tests for Persistence, Transaction Integrity, and Concurrency.

Implements Testing Strategy §5 & Development Workflow §2:
- Mandatory execution against a live PostgreSQL 16 Testcontainer
- Two-way Alembic migration cycle (001 -> 002 -> 001 -> 002)
- Atomic relational persistence of VerificationSession, ClaimRecord, and AuditLogRecord
- Persistence survival across engine/process restarts
- Authoritative database queries surviving process-local cache clears
- Multi-point failure injection proving zero orphaned records on rollback
- Concurrent audit write serialization preventing hash-chain branching
"""

import asyncio
import os
import uuid
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from analytics.store import default_session_store
from db.models import AuditLogRecord, ClaimRecord, VerificationSession
from db.persistence import DatabasePersistenceError, PostgresPersistenceService
from db.session import (
    create_app_engine,
    get_tenant_session,
    reset_sessionmaker,
)
from shared.config import get_settings
from shared.schemas import (
    Claim,
    ClaimCriticality,
    ClaimType,
    ClaimVerificationResult,
    VerificationStatus,
)


@pytest.mark.integration
class TestPostgresPersistence:
    """Live PostgreSQL 16 integration tests verifying persistence and transaction integrity."""

    @pytest.fixture(scope="class")
    def pg_container(self, live_postgres_database: Any) -> Any:
        """Use the live PostgreSQL 16 container for persistence integration testing."""
        if live_postgres_database is not None:
            yield live_postgres_database
        else:
            with PostgresContainer("postgres:16-alpine") as pg:
                yield pg

    @pytest.fixture(scope="class", autouse=True)
    def setup_database_schema(self, pg_container: Any) -> None:
        """Run two-way Alembic migration cycle on the live container."""
        sync_url = pg_container.get_connection_url().replace("+psycopg2", "")
        async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://")

        # 1. Test two-way migration cycle (001 -> 002 -> 001 -> 002)
        os.environ["DATABASE_SYNC_URL"] = sync_url
        os.environ["DATABASE_URL"] = async_url
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", sync_url)

        command.upgrade(cfg, "head")
        command.downgrade(cfg, "-1")
        command.upgrade(cfg, "head")

        # Rebind application sessionmaker to the container
        settings = get_settings()
        settings.database_url = async_url
        settings.database_sync_url = sync_url
        new_engine = create_app_engine(async_url, poolclass=NullPool)
        reset_sessionmaker(new_engine)

    @pytest.mark.asyncio
    async def test_a_verification_persistence_happy_path(self) -> None:
        """Test A: Verify atomic persistence of VerificationSession, ClaimRecord, and AuditLogRecord."""
        svc = PostgresPersistenceService()
        tenant_id = f"tenant_persist_{uuid.uuid4().hex[:8]}"
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"

        verified_claims = [
            ClaimVerificationResult(
                claim=Claim(
                    claim_id=f"c_{uuid.uuid4().hex[:8]}",
                    text="The human heart has four chambers.",
                    claim_type=ClaimType.FACTUAL,
                    criticality=ClaimCriticality.HIGH,
                ),
                status=VerificationStatus.SUPPORTED,
                risk_score=0.05,
                rav_score=0.92,
                scs_score=0.95,
                nli_score=0.98,
            ),
            ClaimVerificationResult(
                claim=Claim(
                    claim_id=f"c_{uuid.uuid4().hex[:8]}",
                    text="The vena cava carries oxygenated blood.",
                    claim_type=ClaimType.FACTUAL,
                    criticality=ClaimCriticality.HIGH,
                ),
                status=VerificationStatus.CONTRADICTED,
                risk_score=0.88,
                rav_score=0.15,
                scs_score=0.20,
                nli_score=0.10,
            ),
        ]

        sess_rec, claims_recs, audit_rec = await svc.persist_verification_transaction(
            session_id=session_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            model_id="test-model-70b",
            prompt="Describe human circulation.",
            response="The human heart has four chambers. The vena cava carries oxygenated blood.",
            hrs_score=0.465,
            risk_tier="MEDIUM",
            verified_claims=verified_claims,
            correction_applied=False,
        )

        assert sess_rec.session_id == session_id
        assert len(claims_recs) == 2
        assert audit_rec.chain_hash is not None
        assert audit_rec.prev_hash == "0" * 64

        # Independently query PostgreSQL to verify records exist
        async with get_tenant_session(tenant_id) as session:
            db_sess = await session.get(VerificationSession, session_id)
            assert db_sess is not None
            assert db_sess.tenant_id == tenant_id
            assert db_sess.hrs_score == 0.465
            assert db_sess.risk_tier == "MEDIUM"

            claims_stmt = select(ClaimRecord).where(ClaimRecord.session_id == session_id)
            db_claims = (await session.execute(claims_stmt)).scalars().all()
            assert len(db_claims) == 2
            assert {c.claim_text for c in db_claims} == {
                "The human heart has four chambers.",
                "The vena cava carries oxygenated blood.",
            }

            audit_stmt = select(AuditLogRecord).where(AuditLogRecord.session_id == session_id)
            db_audit = (await session.execute(audit_stmt)).scalars().one_or_none()
            assert db_audit is not None
            assert db_audit.tenant_id == tenant_id
            assert db_audit.chain_hash == audit_rec.chain_hash

    @pytest.mark.asyncio
    async def test_b_persistence_survives_process_restart(self, pg_container: Any) -> None:
        """Test B: Verify that persisted data survives engine destruction and process recreation."""
        svc = PostgresPersistenceService()
        tenant_id = f"tenant_restart_{uuid.uuid4().hex[:8]}"
        session_id = f"sess_restart_{uuid.uuid4().hex[:10]}"

        await svc.persist_verification_transaction(
            session_id=session_id,
            tenant_id=tenant_id,
            trace_id=f"tr_{uuid.uuid4().hex[:8]}",
            model_id="test-model",
            prompt="Prompt before restart.",
            response="Response before restart.",
            hrs_score=0.12,
            risk_tier="LOW",
            verified_claims=[],
        )

        # 1. Destroy and dispose current engine
        from db.session import engine

        await engine.dispose()

        # 2. Recreate brand new engine and sessionmaker pointing to same DB
        sync_url = pg_container.get_connection_url().replace("+psycopg2", "")
        async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://")
        fresh_engine = create_app_engine(async_url, poolclass=NullPool)
        reset_sessionmaker(fresh_engine)

        # 3. Query PostgreSQL: record must still exist
        fresh_svc = PostgresPersistenceService()
        recovered_sess = await fresh_svc.get_session_by_id(tenant_id=tenant_id, session_id=session_id)
        assert recovered_sess is not None
        assert recovered_sess.session_id == session_id
        assert recovered_sess.hrs_score == 0.12

    @pytest.mark.asyncio
    async def test_c_authoritative_state_survives_cache_wipe(self) -> None:
        """Test C: Verify that PostgreSQL is authoritative even when local process cache is cleared."""
        svc = PostgresPersistenceService()
        tenant_id = f"tenant_cache_{uuid.uuid4().hex[:8]}"
        session_id = f"sess_cache_{uuid.uuid4().hex[:10]}"

        await svc.persist_verification_transaction(
            session_id=session_id,
            tenant_id=tenant_id,
            trace_id="tr_cache",
            model_id="model_cache",
            prompt="Cache test prompt",
            response="Cache test response",
            hrs_score=0.25,
            risk_tier="LOW",
            verified_claims=[],
        )

        # Clear process-local cache
        default_session_store.clear_local_cache()
        assert len(default_session_store.sessions) == 0

        # Authoritative queries to PostgreSQL still return all data
        total, items = await default_session_store.list_sessions_authoritative(tenant_id=tenant_id)
        assert total >= 1
        assert any(item["session_id"] == session_id for item in items)

        stats = await default_session_store.get_stats_authoritative(tenant_id=tenant_id)
        assert stats["total_requests"] >= 1
        assert stats["tier_counts"]["LOW"] >= 1

    @pytest.mark.asyncio
    async def test_d_transaction_rollback_on_session_failure(self) -> None:
        """Test D1: Verify that a duplicate session insertion rolls back and leaves no partial state."""
        tenant_id = f"tenant_fail_sess_{uuid.uuid4().hex[:8]}"
        session_id = f"sess_fail_{uuid.uuid4().hex[:8]}"
        svc = PostgresPersistenceService()

        # Insert first session
        await svc.persist_verification_transaction(
            session_id=session_id,
            tenant_id=tenant_id,
            trace_id="tr1",
            model_id="m1",
            prompt="p1",
            response="r1",
            hrs_score=0.1,
            risk_tier="LOW",
            verified_claims=[],
        )

        # Attempt to insert same session_id again -> raises DatabasePersistenceError
        with pytest.raises(DatabasePersistenceError):
            await svc.persist_verification_transaction(
                session_id=session_id,
                tenant_id=tenant_id,
                trace_id="tr2",
                model_id="m2",
                prompt="p2",
                response="r2",
                hrs_score=0.9,
                risk_tier="HIGH",
                verified_claims=[],
            )

        # Verify only the first session exists, and original state is intact
        recovered = await svc.get_session_by_id(tenant_id=tenant_id, session_id=session_id)
        assert recovered is not None
        assert recovered.hrs_score == 0.1

    @pytest.mark.asyncio
    async def test_d_transaction_rollback_on_claim_failure(self) -> None:
        """Test D2: Verify that a failure during claim insertion rolls back session and audit."""
        tenant_id = f"tenant_fail_claim_{uuid.uuid4().hex[:8]}"
        session_id = f"sess_fail_claim_{uuid.uuid4().hex[:8]}"
        svc = PostgresPersistenceService()

        # Two claims with duplicate claim_id trigger unique constraint violation on claims_pkey
        dup_id = f"c_dup_{uuid.uuid4().hex[:6]}"
        bad_claims = [
            ClaimVerificationResult(
                claim=Claim(claim_id=dup_id, text="Claim 1"),
                status=VerificationStatus.SUPPORTED,
                risk_score=0.1,
            ),
            ClaimVerificationResult(
                claim=Claim(claim_id=dup_id, text="Claim 2 with duplicate ID"),
                status=VerificationStatus.SUPPORTED,
                risk_score=0.1,
            ),
        ]

        with pytest.raises(DatabasePersistenceError):
            await svc.persist_verification_transaction(
                session_id=session_id,
                tenant_id=tenant_id,
                trace_id="tr",
                model_id="mod",
                prompt="p",
                response="r",
                hrs_score=0.1,
                risk_tier="LOW",
                verified_claims=bad_claims,
            )

        # Assert zero records exist in all 3 tables for this session
        async with get_tenant_session(tenant_id) as session:
            sess_cnt = (
                await session.execute(select(func.count()).where(VerificationSession.session_id == session_id))
            ).scalar()
            claim_cnt = (
                await session.execute(select(func.count()).where(ClaimRecord.session_id == session_id))
            ).scalar()
            audit_cnt = (
                await session.execute(select(func.count()).where(AuditLogRecord.session_id == session_id))
            ).scalar()

            assert sess_cnt == 0
            assert claim_cnt == 0
            assert audit_cnt == 0

    @pytest.mark.asyncio
    async def test_d_transaction_rollback_on_audit_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test D3: Verify that an error during audit log insertion rolls back session and claims."""
        tenant_id = f"tenant_fail_audit_{uuid.uuid4().hex[:8]}"
        session_id = f"sess_fail_audit_{uuid.uuid4().hex[:8]}"
        svc = PostgresPersistenceService()

        # Seed an audit record with a fixed chain_hash
        fixed_hash = "f" * 64
        async with get_tenant_session(tenant_id) as session:
            await svc.ensure_tenant_exists(session, tenant_id)
            await session.execute(
                text(
                    """
                    INSERT INTO audit_logs (
                        entry_id, tenant_id, session_id, trace_id, prompt_hash, response_hash,
                        hrs_score, risk_tier, claims_count, prev_hash, chain_hash, created_at
                    )
                    VALUES ('aud_pre', :tenant, 's_pre', 'tr', 'ph', 'rh', 0.1, 'LOW', 0, '0', :fixed, NOW())
                    """
                ),
                {"tenant": tenant_id, "fixed": fixed_hash},
            )

        # Force compute_sha256 in persistence to return the colliding hash
        monkeypatch.setattr("db.persistence.compute_sha256", lambda _: fixed_hash)
        with pytest.raises(DatabasePersistenceError):
            await svc.persist_verification_transaction(
                session_id=session_id,
                tenant_id=tenant_id,
                trace_id="tr",
                model_id="mod",
                prompt="p",
                response="r",
                hrs_score=0.1,
                risk_tier="LOW",
                verified_claims=[],
            )

        # Assert session was rolled back: 0 orphaned sessions
        async with get_tenant_session(tenant_id) as session:
            sess_cnt = (
                await session.execute(select(func.count()).where(VerificationSession.session_id == session_id))
            ).scalar()
            assert sess_cnt == 0

    @pytest.mark.asyncio
    async def test_e_concurrent_audit_writes_serialize_unbroken_chain(self) -> None:
        """Test E: Concurrent persistence transactions for the same tenant form a single unbroken hash chain."""
        svc = PostgresPersistenceService()
        tenant_id = f"tenant_concurrent_{uuid.uuid4().hex[:8]}"
        concurrency = 8

        async def _persist_single(idx: int) -> None:
            await svc.persist_verification_transaction(
                session_id=f"sess_con_{idx}_{uuid.uuid4().hex[:6]}",
                tenant_id=tenant_id,
                trace_id=f"tr_{idx}",
                model_id="concurrent-model",
                prompt=f"Concurrent prompt {idx}",
                response=f"Concurrent response {idx}",
                hrs_score=0.10 + (idx * 0.05),
                risk_tier="LOW",
                verified_claims=[],
            )

        # Launch all 8 persistence transactions simultaneously
        tasks = [_persist_single(i) for i in range(concurrency)]
        await asyncio.gather(*tasks)

        # Verify unbroken linear hash chain directly from PostgreSQL
        chain_res = await svc.verify_audit_hash_chain(tenant_id=tenant_id)
        assert chain_res["valid"] is True
        assert chain_res["chain_status"] == "VERIFIED_UNBROKEN"
        assert chain_res["total_records_verified"] == concurrency
