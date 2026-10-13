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
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError


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

    def test_clean_schema_migration_rls_and_unprivileged_app_role_isolation(self, sync_engine: Any) -> None:
        """Starts from clean schema, runs real migrations, verifies RLS, and proves isolation under mirage_app."""
        _ = sync_engine
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        assert sync_url is not None
        clean_db_name = f"test_clean_mem_rls_{uuid.uuid4().hex[:8]}"

        # Step 1: Create a brand new clean database as admin
        admin_engine = create_engine(sync_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {clean_db_name};"))

        try:
            # Step 2: Configure alembic to upgrade the clean database to head
            clean_sync_url = sync_url.rsplit("/", 1)[0] + f"/{clean_db_name}"
            orig_sync_env = os.environ.get("DATABASE_SYNC_URL")
            try:
                os.environ["DATABASE_SYNC_URL"] = clean_sync_url
                cfg = Config("alembic.ini")
                cfg.set_main_option("sqlalchemy.url", clean_sync_url)
                command.upgrade(cfg, "head")
            finally:
                if orig_sync_env is not None:
                    os.environ["DATABASE_SYNC_URL"] = orig_sync_env

            # Step 3: Inspect pg_class & pg_policies on clean database as admin
            clean_engine = create_engine(clean_sync_url)
            with clean_engine.connect() as conn:
                class_info = (
                    conn.execute(
                        text(
                            """
                            SELECT relrowsecurity, relforcerowsecurity
                            FROM pg_class
                            WHERE relname = 'governed_memories';
                            """
                        )
                    )
                    .mappings()
                    .one()
                )
                assert class_info["relrowsecurity"] is True, "RLS not enabled on governed_memories in clean database"
                assert (
                    class_info["relforcerowsecurity"] is True
                ), "RLS not FORCED on governed_memories in clean database"

                policy_info = (
                    conn.execute(
                        text(
                            """
                            SELECT policyname, tablename, cmd, qual, with_check
                            FROM pg_policies
                            WHERE tablename = 'governed_memories' AND policyname = 'tenant_isolation_governed_memories';
                            """
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                assert policy_info is not None, "Policy tenant_isolation_governed_memories missing in clean database"
                assert policy_info["cmd"] == "ALL", "Policy on governed_memories must be for ALL commands"

                # Verify mirage_app role properties
                role_info = (
                    conn.execute(
                        text(
                            """
                            SELECT rolname, rolsuper, rolbypassrls
                            FROM pg_roles
                            WHERE rolname = 'mirage_app';
                            """
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                assert role_info is not None, "mirage_app role must exist after migration"
                assert role_info["rolsuper"] is False, "mirage_app must be NOSUPERUSER"
                assert role_info["rolbypassrls"] is False, "mirage_app must be NOBYPASSRLS"

                # Grant connect on clean database to mirage_app
                conn.execute(text(f"GRANT CONNECT ON DATABASE {clean_db_name} TO mirage_app;"))
                conn.commit()
            clean_engine.dispose()

            # Step 4: Connect strictly as unprivileged mirage_app
            if "@" in clean_sync_url:
                prefix = clean_sync_url.split("://")[0]
                host_part = clean_sync_url.split("@")[1]
                app_sync_url = f"{prefix}://mirage_app:mirage_app_pw@{host_part}"
            else:
                app_sync_url = clean_sync_url

            app_engine = create_engine(app_sync_url)
            tenant_a = f"t_clean_mem_a_{uuid.uuid4().hex[:6]}"
            tenant_b = f"t_clean_mem_b_{uuid.uuid4().hex[:6]}"
            mem_a = f"mem_clean_a_{uuid.uuid4().hex[:6]}"
            mem_b = f"mem_clean_b_{uuid.uuid4().hex[:6]}"

            # Test A: Unauthenticated (no tenant context set) -> Fail closed
            with app_engine.connect() as conn:
                unauth_mems = conn.execute(text("SELECT id FROM governed_memories")).fetchall()
                assert len(unauth_mems) == 0

            # Test B: Seed Tenant A and insert memory under Tenant A context
            with app_engine.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :t, true)"),
                    {"t": tenant_a},
                )
                conn.execute(
                    text(
                        "INSERT INTO tenants (id, name, api_key_hash, created_at) "
                        "VALUES (:t, 'TenantA', 'h_a', NOW())"
                    ),
                    {"t": tenant_a},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO governed_memories (
                            id, tenant_id, owner_id, memory_type, scope, content, content_hash,
                            attestation_status, taint, confidence, created_at, updated_at,
                            memory_category, purpose, lifecycle_state, trust_level,
                            version, retention_policy, propagation_status
                        ) VALUES (
                            :id, :t, 'owner_a', 'ADVISORY', 'ORGANIZATIONAL', 'Secret of A', 'hash_a',
                            'NONE', 'TAINT_INTERNAL', 0.8, NOW(), NOW(),
                            'USER_FACT', 'GENERAL', 'ACTIVE', 'PROVISIONAL',
                            1, 'STANDARD', 'PROPAGATED'
                        )
                        """
                    ),
                    {"id": mem_a, "t": tenant_a},
                )
                conn.commit()

            # Test C: Seed Tenant B and insert memory under Tenant B context
            with app_engine.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :t, true)"),
                    {"t": tenant_b},
                )
                conn.execute(
                    text(
                        "INSERT INTO tenants (id, name, api_key_hash, created_at) "
                        "VALUES (:t, 'TenantB', 'h_b', NOW())"
                    ),
                    {"t": tenant_b},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO governed_memories (
                            id, tenant_id, owner_id, memory_type, scope, content, content_hash,
                            attestation_status, taint, confidence, created_at, updated_at,
                            memory_category, purpose, lifecycle_state, trust_level,
                            version, retention_policy, propagation_status
                        ) VALUES (
                            :id, :t, 'owner_b', 'ADVISORY', 'ORGANIZATIONAL', 'Secret of B', 'hash_b',
                            'NONE', 'TAINT_INTERNAL', 0.8, NOW(), NOW(),
                            'USER_FACT', 'GENERAL', 'ACTIVE', 'PROVISIONAL',
                            1, 'STANDARD', 'PROPAGATED'
                        )
                        """
                    ),
                    {"id": mem_b, "t": tenant_b},
                )
                conn.commit()

            # Test D: Strict isolation checks under Tenant A context
            with app_engine.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :t, true)"),
                    {"t": tenant_a},
                )
                # 1. SELECT isolation: Tenant A cannot see Tenant B's memory
                mems = conn.execute(text("SELECT id FROM governed_memories")).scalars().all()
                assert mems == [mem_a], f"Tenant A saw unexpected memories: {mems}"

                # 2. Cross-tenant UPDATE attack -> 0 rows affected
                upd = conn.execute(
                    text("UPDATE governed_memories SET content = 'Tampered' WHERE id = :id"),
                    {"id": mem_b},
                )
                assert upd.rowcount == 0

                # 3. Cross-tenant DELETE attack -> 0 rows affected
                dele = conn.execute(
                    text("DELETE FROM governed_memories WHERE id = :id"),
                    {"id": mem_b},
                )
                assert dele.rowcount == 0

                # 4. Caller-controlled tenant ID spoofing on INSERT -> rejected by RLS WITH CHECK
                with pytest.raises((ProgrammingError, DBAPIError, IntegrityError)) as exc_info:
                    conn.execute(
                        text(
                            """
                            INSERT INTO governed_memories (
                                id, tenant_id, owner_id, memory_type, scope, content, content_hash,
                                attestation_status, taint, confidence, created_at, updated_at,
                                memory_category, purpose, lifecycle_state, trust_level,
                                version, retention_policy, propagation_status
                            ) VALUES (
                                'mem_spoofed', :forged_t, 'owner', 'ADVISORY', 'ORGANIZATIONAL', 'Spoofed', 'h',
                                'NONE', 'TAINT_INTERNAL', 0.8, NOW(), NOW(),
                                'USER_FACT', 'GENERAL', 'ACTIVE', 'PROVISIONAL',
                                1, 'STANDARD', 'PROPAGATED'
                            )
                            """
                        ),
                        {"forged_t": tenant_b},
                    )
                err_msg = str(exc_info.value).lower()
                assert "row-level security" in err_msg or "check violation" in err_msg
                conn.rollback()

            app_engine.dispose()
        finally:
            with admin_engine.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {clean_db_name} WITH (FORCE);"))
            admin_engine.dispose()
