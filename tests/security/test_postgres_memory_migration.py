"""Live PostgreSQL 16 Migration & Schema Catalog Validation Suite for Phase 7.

Validates the actual database state after migration 017_phase7_governed_memory_lifecycle:
1. Column Verification: Proves all 17 new Phase 7 columns are present in `information_schema.columns`.
2. Index Verification: Proves performance and partial unique indexes exist in `pg_indexes`.
3. Row-Level Security (RLS): Verifies RLS is enabled and forced on `governed_memories`.
4. Idempotency Constraint: Proves duplicate idempotency keys within a tenant are rejected.
5. Migration Cycle: Verifies clean downgrade to 016 and re-upgrade to 017 via Alembic.
"""

import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


@pytest.mark.security
class TestPostgresMemoryMigration:
    """Empirical PostgreSQL 16 schema behavior and migration constraint verification for Phase 7."""

    @pytest.fixture(scope="class")
    def sync_engine(self, live_postgres_database: Any) -> Any:
        """Create sync engine for direct PostgreSQL catalog and constraint testing."""
        _ = live_postgres_database
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        assert sync_url is not None, "DATABASE_SYNC_URL must be configured by live_postgres_database fixture"
        engine = create_engine(sync_url)
        yield engine
        engine.dispose()

    def test_all_17_governed_memory_columns_exist(self, sync_engine: Any) -> None:
        """Inspects information_schema.columns to prove all 17 Phase 7 columns exist."""
        expected_columns = {
            "memory_category",
            "purpose",
            "lifecycle_state",
            "trust_level",
            "version",
            "superseded_by_id",
            "retention_policy",
            "retention_exception_reason",
            "source_type",
            "source_uri",
            "source_transaction_id",
            "source_action_id",
            "derivation_chain",
            "propagation_status",
            "propagation_details",
            "dispute_reason",
            "idempotency_key",
        }

        with sync_engine.connect() as conn:
            query = text(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'governed_memories';
                """
            )
            rows = conn.execute(query).mappings().all()
            actual_columns = {r["column_name"] for r in rows}

            missing = expected_columns - actual_columns
            assert not missing, f"Missing columns in governed_memories: {missing}"

    def test_governed_memory_indexes_exist(self, sync_engine: Any) -> None:
        """Inspects pg_indexes to verify Phase 7 performance and partial unique indexes."""
        expected_indexes = {
            "ix_governed_memories_tenant_purpose",
            "ix_governed_memories_tenant_lifecycle",
            "ix_governed_memories_tenant_expires",
            "ix_governed_memories_tenant_category",
            "uq_governed_memories_tenant_idempotency",
        }

        with sync_engine.connect() as conn:
            query = text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'governed_memories';
                """
            )
            rows = conn.execute(query).mappings().all()
            actual_indexes = {r["indexname"] for r in rows}

            missing = expected_indexes - actual_indexes
            assert not missing, f"Missing indexes in governed_memories: {missing}"

    def test_governed_memory_rls_is_enabled_and_forced(self, sync_engine: Any) -> None:
        """Inspects pg_class to prove RLS is enabled and forced on governed_memories."""
        with sync_engine.connect() as conn:
            query = text(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE relname = 'governed_memories';
                """
            )
            row = conn.execute(query).mappings().one()
            assert row["relrowsecurity"] is True, "RLS must be enabled on governed_memories"
            assert row["relforcerowsecurity"] is True, "RLS must be forced on governed_memories"

    def test_idempotency_key_uniqueness_per_tenant(self, sync_engine: Any) -> None:
        """Proves partial unique index uq_governed_memories_tenant_idempotency rejects duplicates."""
        tenant_id = f"t_idem_{uuid.uuid4().hex[:8]}"
        other_tenant = f"t_idem_other_{uuid.uuid4().hex[:8]}"
        idem_key = f"key_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)

        with sync_engine.connect() as conn:
            # Seed tenant records
            conn.execute(
                text(
                    "INSERT INTO tenants (id, name, api_key_hash, created_at) "
                    "VALUES (:t, 'Idem Test', :h, :now)"
                ),
                {"t": tenant_id, "h": f"h_{tenant_id}", "now": now},
            )
            conn.execute(
                text(
                    "INSERT INTO tenants (id, name, api_key_hash, created_at) "
                    "VALUES (:t, 'Other Idem Test', :h, :now)"
                ),
                {"t": other_tenant, "h": f"h_{other_tenant}", "now": now},
            )
            conn.commit()

            # Insert first memory with idempotency key
            mem1_id = f"mem_{uuid.uuid4().hex}"
            conn.execute(
                text(
                    """
                    INSERT INTO governed_memories (
                        id, tenant_id, owner_id, memory_type, scope, content, content_hash,
                        attestation_status, taint, confidence, created_at, updated_at,
                        idempotency_key, memory_category, purpose, lifecycle_state, trust_level,
                        version, retention_policy, propagation_status
                    ) VALUES (
                        :id, :tenant, 'owner', 'ADVISORY', 'ORGANIZATIONAL', 'content 1', 'hash1',
                        'NONE', 'TAINT_INTERNAL', 0.8, :now, :now,
                        :idem, 'USER_FACT', 'GENERAL', 'ACTIVE', 'PROVISIONAL',
                        1, 'STANDARD', 'PROPAGATED'
                    )
                    """
                ),
                {"id": mem1_id, "tenant": tenant_id, "now": now, "idem": idem_key},
            )
            conn.commit()

            # Insert duplicate under SAME tenant -> must raise IntegrityError
            mem2_id = f"mem_{uuid.uuid4().hex}"
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        """
                        INSERT INTO governed_memories (
                            id, tenant_id, owner_id, memory_type, scope, content, content_hash,
                            attestation_status, taint, confidence, created_at, updated_at,
                            idempotency_key, memory_category, purpose, lifecycle_state, trust_level,
                            version, retention_policy, propagation_status
                        ) VALUES (
                            :id, :tenant, 'owner', 'ADVISORY', 'ORGANIZATIONAL', 'content 2', 'hash2',
                            'NONE', 'TAINT_INTERNAL', 0.8, :now, :now,
                            :idem, 'USER_FACT', 'GENERAL', 'ACTIVE', 'PROVISIONAL',
                            1, 'STANDARD', 'PROPAGATED'
                        )
                        """
                    ),
                    {"id": mem2_id, "tenant": tenant_id, "now": now, "idem": idem_key},
                )
            conn.rollback()

            # Insert same idempotency key under DIFFERENT tenant -> must SUCCEED
            mem3_id = f"mem_{uuid.uuid4().hex}"
            conn.execute(
                text(
                    """
                    INSERT INTO governed_memories (
                        id, tenant_id, owner_id, memory_type, scope, content, content_hash,
                        attestation_status, taint, confidence, created_at, updated_at,
                        idempotency_key, memory_category, purpose, lifecycle_state, trust_level,
                        version, retention_policy, propagation_status
                    ) VALUES (
                        :id, :tenant, 'owner', 'ADVISORY', 'ORGANIZATIONAL', 'content 3', 'hash3',
                        'NONE', 'TAINT_INTERNAL', 0.8, :now, :now,
                        :idem, 'USER_FACT', 'GENERAL', 'ACTIVE', 'PROVISIONAL',
                        1, 'STANDARD', 'PROPAGATED'
                    )
                    """
                ),
                {"id": mem3_id, "tenant": other_tenant, "now": now, "idem": idem_key},
            )
            conn.commit()

    def test_migration_downgrade_and_reupgrade_cycle(self, sync_engine: Any) -> None:
        """Tests that Alembic migration 017 downgrades cleanly to 016 and re-upgrades to head."""
        alembic_cfg = Config("alembic.ini")

        # 1. Downgrade to 016
        command.downgrade(alembic_cfg, "016_phase6_outcome_assurance")

        # Verify columns removed
        with sync_engine.connect() as conn:
            query = text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'governed_memories' AND column_name = 'memory_category';
                """
            )
            row = conn.execute(query).mappings().one_or_none()
            assert row is None, "memory_category should be absent after downgrade to 016"

        # 2. Re-upgrade to head (017)
        command.upgrade(alembic_cfg, "head")

        # Verify column restored
        with sync_engine.connect() as conn:
            query = text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'governed_memories' AND column_name = 'memory_category';
                """
            )
            row = conn.execute(query).mappings().one_or_none()
            assert row is not None, "memory_category should be present after re-upgrade to head"
