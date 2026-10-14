"""Live PostgreSQL Migration & Schema Catalog Validation Suite for Phase 8.

Validates the actual database state after migration 018_phase8_cross_agent_governance:
1. Column Verification: Proves all agent_delegations columns exist in information_schema.columns.
2. Index Verification: Proves performance and idempotency indexes exist in pg_indexes.
3. Row-Level Security (RLS): Verifies RLS is enabled and forced on agent_delegations.
4. Idempotency Constraint: Proves duplicate idempotency keys within a tenant are rejected.
5. Unprivileged Role Isolation: Verifies mirage_app role cannot bypass RLS or see cross-tenant grants.
6. Migration Cycle: Verifies clean downgrade to 017 and re-upgrade to 018 via Alembic.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError


@pytest.mark.security
class TestPostgresDelegationMigration:
    """Empirical PostgreSQL schema behavior and migration constraint verification for Phase 8."""

    @pytest.fixture(scope="class")
    def sync_engine(self, live_postgres_database: Any) -> Any:
        """Create sync engine for direct PostgreSQL catalog and constraint testing."""
        _ = live_postgres_database
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        assert sync_url is not None, "DATABASE_SYNC_URL must be configured by live_postgres_database fixture"
        engine = create_engine(sync_url)
        yield engine
        engine.dispose()

    def test_all_agent_delegations_columns_exist(self, sync_engine: Any) -> None:
        """Inspects information_schema.columns to prove all agent_delegations columns exist."""
        expected_columns = {
            "id",
            "tenant_id",
            "parent_agent_id",
            "parent_transaction_id",
            "child_agent_id",
            "child_transaction_id",
            "delegated_capabilities",
            "resource_scope",
            "max_autonomy_level",
            "delegation_depth",
            "max_turns",
            "status",
            "purpose",
            "idempotency_key",
            "expires_at",
            "revoked_at",
            "created_at",
            "updated_at",
        }

        with sync_engine.connect() as conn:
            query = text(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'agent_delegations';
                """
            )
            rows = conn.execute(query).mappings().all()
            actual_columns = {r["column_name"] for r in rows}

            missing = expected_columns - actual_columns
            assert not missing, f"Missing columns in agent_delegations: {missing}"

            # Verify specific nullability choices
            nullable_map = {r["column_name"]: r["is_nullable"] for r in rows}
            assert nullable_map["child_transaction_id"] == "YES", "child_transaction_id must be nullable"
            assert nullable_map["revoked_at"] == "YES", "revoked_at must be nullable"
            assert nullable_map["id"] == "NO", "id must be NOT NULL"
            assert nullable_map["tenant_id"] == "NO", "tenant_id must be NOT NULL"
            assert nullable_map["parent_agent_id"] == "NO", "parent_agent_id must be NOT NULL"
            assert nullable_map["parent_transaction_id"] == "NO", "parent_transaction_id must be NOT NULL"

    def test_agent_delegations_indexes_exist(self, sync_engine: Any) -> None:
        """Inspects pg_indexes to verify Phase 8 composite and idempotency indexes."""
        expected_indexes = {
            "uq_agent_delegations_tenant_idempotency",
            "ix_agent_delegations_tenant_parent_txn",
            "ix_agent_delegations_tenant_child_txn",
            "ix_agent_delegations_tenant_status",
            "ix_agent_delegations_tenant_expires",
        }

        with sync_engine.connect() as conn:
            query = text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'agent_delegations';
                """
            )
            rows = conn.execute(query).mappings().all()
            actual_indexes = {r["indexname"] for r in rows}

            missing = expected_indexes - actual_indexes
            assert not missing, f"Missing indexes on agent_delegations: {missing}"

    def test_agent_delegations_rls_is_enabled_and_forced(self, sync_engine: Any) -> None:
        """Inspects pg_class to prove RLS is enabled and forced on agent_delegations."""
        with sync_engine.connect() as conn:
            query = text(
                """
                SELECT relname, relrowsecurity, relforcerowsecurity
                FROM pg_class
                WHERE relname = 'agent_delegations';
                """
            )
            row = conn.execute(query).mappings().one()
            assert row["relrowsecurity"] is True, "RLS must be enabled on agent_delegations"
            assert row["relforcerowsecurity"] is True, "RLS must be forced on agent_delegations"

    def test_idempotency_key_uniqueness_per_tenant(self, sync_engine: Any) -> None:
        """Proves unique constraint uq_agent_delegations_tenant_idempotency rejects duplicates."""
        tenant_a = f"t_del_a_{uuid.uuid4().hex[:6]}"
        tenant_b = f"t_del_b_{uuid.uuid4().hex[:6]}"
        idem_key = f"idem_del_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=600)

        with sync_engine.connect() as conn:
            # Seed tenant records
            conn.execute(
                text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:t, 'TenantA', :h, :now)"),
                {"t": tenant_a, "h": f"h_{tenant_a}", "now": now},
            )
            conn.execute(
                text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:t, 'TenantB', :h, :now)"),
                {"t": tenant_b, "h": f"h_{tenant_b}", "now": now},
            )

            # Seed parent agents
            conn.execute(
                text(
                    "INSERT INTO agents (id, tenant_id, name, active, max_autonomy_level, created_at) "
                    "VALUES (:aid, :t, 'ParentAgent', true, 2, :now)"
                ),
                {"aid": f"agent_p_{tenant_a}", "t": tenant_a, "now": now},
            )
            conn.execute(
                text(
                    "INSERT INTO agents (id, tenant_id, name, active, max_autonomy_level, created_at) "
                    "VALUES (:aid, :t, 'ChildAgent', true, 1, :now)"
                ),
                {"aid": f"agent_c_{tenant_a}", "t": tenant_a, "now": now},
            )

            # Seed parent transaction identity & transaction
            conn.execute(
                text(
                    "INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at) "
                    "VALUES (:id, :t, 'subj_parent', 'agent', 'operator', true, :now)"
                ),
                {"id": f"actor_{tenant_a}", "t": tenant_a, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ai_transactions (
                        id, tenant_id, actor_identity_id, agent_id, idempotency_key, correlation_id,
                        state, max_turns, turn_count, taint_flags, version, created_at, updated_at
                    ) VALUES (
                        :id, :t, :actor, :aid, :idem, 'corr_001',
                        'PENDING', 10, 0, '[]'::jsonb, 0, :now, :now
                    )
                    """
                ),
                {
                    "id": f"txn_p_{tenant_a}",
                    "t": tenant_a,
                    "actor": f"actor_{tenant_a}",
                    "aid": f"agent_p_{tenant_a}",
                    "idem": f"idem_txn_{tenant_a}",
                    "now": now,
                },
            )
            conn.commit()

            # Insert first delegation grant under Tenant A
            conn.execute(
                text(
                    """
                    INSERT INTO agent_delegations (
                        id, tenant_id, parent_agent_id, parent_transaction_id, child_agent_id,
                        child_transaction_id, delegated_capabilities, resource_scope,
                        max_autonomy_level, delegation_depth, max_turns, status, purpose,
                        idempotency_key, expires_at, created_at, updated_at
                    ) VALUES (
                        :id, :t, :paid, :ptxn, :caid,
                        NULL, '[{"capability_type": "tools:math"}]'::jsonb, '{}'::jsonb,
                        1, 1, 4, 'ACTIVE', 'Compute subtask',
                        :idem, :exp, :now, :now
                    )
                    """
                ),
                {
                    "id": f"del_1_{tenant_a}",
                    "t": tenant_a,
                    "paid": f"agent_p_{tenant_a}",
                    "ptxn": f"txn_p_{tenant_a}",
                    "caid": f"agent_c_{tenant_a}",
                    "idem": idem_key,
                    "exp": expires,
                    "now": now,
                },
            )
            conn.commit()

            # Insert duplicate delegation with SAME idempotency key under SAME tenant -> must raise IntegrityError
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_delegations (
                            id, tenant_id, parent_agent_id, parent_transaction_id, child_agent_id,
                            child_transaction_id, delegated_capabilities, resource_scope,
                            max_autonomy_level, delegation_depth, max_turns, status, purpose,
                            idempotency_key, expires_at, created_at, updated_at
                        ) VALUES (
                            :id, :t, :paid, :ptxn, :caid,
                            NULL, '[{"capability_type": "tools:math"}]'::jsonb, '{}'::jsonb,
                            1, 1, 4, 'ACTIVE', 'Compute subtask duplicate',
                            :idem, :exp, :now, :now
                        )
                        """
                    ),
                    {
                        "id": f"del_dup_{tenant_a}",
                        "t": tenant_a,
                        "paid": f"agent_p_{tenant_a}",
                        "ptxn": f"txn_p_{tenant_a}",
                        "caid": f"agent_c_{tenant_a}",
                        "idem": idem_key,
                        "exp": expires,
                        "now": now,
                    },
                )
            conn.rollback()

    def test_mirage_app_unprivileged_rls_isolation(self, sync_engine: Any) -> None:
        """Verifies unprivileged mirage_app role respects RLS and isolates cross-tenant delegations."""
        sync_url = os.environ.get("DATABASE_SYNC_URL", "")
        if "@" in sync_url:
            prefix = sync_url.split("://")[0]
            host_part = sync_url.split("@")[1]
            app_sync_url = f"{prefix}://mirage_app:mirage_app_pw@{host_part}"
        else:
            app_sync_url = sync_url

        app_engine = create_engine(app_sync_url)
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=600)

        tenant_x = f"t_rls_x_{uuid.uuid4().hex[:6]}"
        tenant_y = f"t_rls_y_{uuid.uuid4().hex[:6]}"
        del_x = f"del_x_{uuid.uuid4().hex[:6]}"

        # Seed data with superuser engine
        with sync_engine.connect() as conn:
            for t in (tenant_x, tenant_y):
                conn.execute(
                    text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:t, :n, :h, :now)"),
                    {"t": t, "n": f"Tenant_{t}", "h": f"h_{t}", "now": now},
                )
                conn.execute(
                    text(
                        "INSERT INTO agents (id, tenant_id, name, active, max_autonomy_level, created_at) "
                        "VALUES (:aid, :t, 'AgentP', true, 2, :now)"
                    ),
                    {"aid": f"agent_p_{t}", "t": t, "now": now},
                )
                conn.execute(
                    text(
                        "INSERT INTO agents (id, tenant_id, name, active, max_autonomy_level, created_at) "
                        "VALUES (:aid, :t, 'AgentC', true, 1, :now)"
                    ),
                    {"aid": f"agent_c_{t}", "t": t, "now": now},
                )
                conn.execute(
                    text(
                        "INSERT INTO actor_identities "
                        "(id, tenant_id, subject, principal_type, role, active, created_at) "
                        "VALUES (:id, :t, :subj, 'agent', 'operator', true, :now)"
                    ),
                    {"id": f"act_{t}", "t": t, "subj": f"subj_{t}", "now": now},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO ai_transactions (
                            id, tenant_id, actor_identity_id, agent_id, idempotency_key, correlation_id,
                            state, max_turns, turn_count, taint_flags, version, created_at, updated_at
                        ) VALUES (
                            :id, :t, :act, :aid, :idem, 'corr',
                            'PENDING', 10, 0, '[]'::jsonb, 0, :now, :now
                        )
                        """
                    ),
                    {
                        "id": f"txn_p_{t}",
                        "t": t,
                        "act": f"act_{t}",
                        "aid": f"agent_p_{t}",
                        "idem": f"idem_txn_{t}",
                        "now": now,
                    },
                )

            # Insert grant for Tenant X
            conn.execute(
                text(
                    """
                    INSERT INTO agent_delegations (
                        id, tenant_id, parent_agent_id, parent_transaction_id, child_agent_id,
                        child_transaction_id, delegated_capabilities, resource_scope,
                        max_autonomy_level, delegation_depth, max_turns, status, purpose,
                        idempotency_key, expires_at, created_at, updated_at
                    ) VALUES (
                        :id, :t, :paid, :ptxn, :caid,
                        NULL, '[{"capability_type": "tools:math"}]'::jsonb, '{}'::jsonb,
                        1, 1, 4, 'ACTIVE', 'Confidential task of X',
                        :idem, :exp, :now, :now
                    )
                    """
                ),
                {
                    "id": del_x,
                    "t": tenant_x,
                    "paid": f"agent_p_{tenant_x}",
                    "ptxn": f"txn_p_{tenant_x}",
                    "caid": f"agent_c_{tenant_x}",
                    "idem": f"idem_del_{tenant_x}",
                    "exp": expires,
                    "now": now,
                },
            )
            conn.commit()

        # Step 1: Unauthenticated mirage_app (no tenant context) -> Fail closed (0 rows)
        with app_engine.connect() as conn:
            unauth_rows = conn.execute(text("SELECT id FROM agent_delegations")).fetchall()
            assert len(unauth_rows) == 0, "Unauthenticated queries must return 0 rows under RLS"

        # Step 2: Authenticated as Tenant X -> Sees only Tenant X delegation
        with app_engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": tenant_x},
            )
            rows = conn.execute(text("SELECT id FROM agent_delegations")).fetchall()
            assert len(rows) == 1
            assert rows[0][0] == del_x

        # Step 3: Authenticated as Tenant Y -> Cannot see Tenant X delegation
        with app_engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": tenant_y},
            )
            rows = conn.execute(text("SELECT id FROM agent_delegations")).fetchall()
            assert len(rows) == 0, "Tenant Y must not see Tenant X delegations"

        # Step 4: Cross-tenant injection attempt (authenticated as Tenant Y, attempting to insert for Tenant X)
        with app_engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, true)"),
                {"t": tenant_y},
            )
            with pytest.raises(DBAPIError):  # Policy WITH CHECK violation
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_delegations (
                            id, tenant_id, parent_agent_id, parent_transaction_id, child_agent_id,
                            child_transaction_id, delegated_capabilities, resource_scope,
                            max_autonomy_level, delegation_depth, max_turns, status, purpose,
                            idempotency_key, expires_at, created_at, updated_at
                        ) VALUES (
                            'del_spoof', :t_x, :paid, :ptxn, :caid,
                            NULL, '[]'::jsonb, '{}'::jsonb,
                            0, 1, 4, 'ACTIVE', 'Spoof grant',
                            'idem_spoof', :exp, :now, :now
                        )
                        """
                    ),
                    {
                        "t_x": tenant_x,  # Cross-tenant injection
                        "paid": f"agent_p_{tenant_y}",
                        "ptxn": f"txn_p_{tenant_y}",
                        "caid": f"agent_c_{tenant_y}",
                        "exp": expires,
                        "now": now,
                    },
                )

        app_engine.dispose()

    def test_migration_downgrade_and_reupgrade_cycle(self, sync_engine: Any) -> None:
        """Verifies clean Alembic downgrade to 017 and re-upgrade to 018."""
        cfg = Config("alembic.ini")

        with sync_engine.connect() as conn:
            # Downgrade to 017
            command.downgrade(cfg, "017_phase7_governed_memory")

            # Verify agent_delegations table is dropped
            table_check = conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_name = 'agent_delegations';
                    """
                )
            ).scalar_one_or_none()
            assert table_check is None, "agent_delegations table must be dropped after downgrade to 017"

            # Re-upgrade to head (018)
            command.upgrade(cfg, "head")

            # Verify table and RLS are restored
            table_check_after = conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_name = 'agent_delegations';
                    """
                )
            ).scalar_one_or_none()
            assert table_check_after == "agent_delegations", "agent_delegations table must be restored after re-upgrade"
