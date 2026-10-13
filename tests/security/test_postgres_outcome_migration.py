"""Live PostgreSQL 16 Migration & Schema Catalog Validation Suite.

Replaces static source inspection (`inspect.getsource`) with empirical validation on live PostgreSQL:
1. System Catalog Verification: inspects `pg_constraint` and `information_schema.key_column_usage`
   to prove `uq_outcome_records_tenant_action` exists with columns `(tenant_id, action_id)`.
2. Duplicate Rejection: proves PostgreSQL engine rejects duplicate `(tenant_id, action_id)`
   records with a real `UniqueViolation` / `IntegrityError`.
3. Tenant-Scoped Isolation: proves identical `action_id` across distinct tenants succeeds.
4. Legacy Preflight Audit: validates preflight query detecting duplicate records.
5. Row-Level Security (RLS): validates `relrowsecurity` and `relforcerowsecurity` in `pg_class`
   and policy definition in `pg_policies`.
6. Migration Rollback & Re-upgrade Cycle: tests clean downgrade and re-upgrade via Alembic.
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
class TestPostgresOutcomeMigration:
    """Empirical PostgreSQL 16 schema behavior and migration constraint verification."""

    @pytest.fixture(scope="class")
    def sync_engine(self, live_postgres_database: Any) -> Any:
        """Create sync engine for direct PostgreSQL catalog and constraint testing."""
        _ = live_postgres_database
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        assert sync_url is not None, "DATABASE_SYNC_URL must be configured by live_postgres_database fixture"
        engine = create_engine(sync_url)
        yield engine
        engine.dispose()

    def test_real_pg_catalog_unique_constraint_exists(self, sync_engine: Any) -> None:
        """Inspects pg_constraint to prove uq_outcome_records_tenant_action exists on outcome_verification_records."""
        with sync_engine.connect() as conn:
            # 1. Inspect pg_constraint for unique constraint
            constraint_query = text(
                """
                SELECT conname, contype, conrelid::regclass::text as table_name
                FROM pg_constraint
                WHERE conname = 'uq_outcome_records_tenant_action';
                """
            )
            row = conn.execute(constraint_query).mappings().one_or_none()
            assert row is not None, "uq_outcome_records_tenant_action not found in pg_constraint!"
            assert row["conname"] == "uq_outcome_records_tenant_action"
            assert row["contype"] == "u", "Constraint type must be 'u' (unique) in pg_constraint"
            assert row["table_name"] == "outcome_verification_records"

            # 2. Inspect column order in information_schema.key_column_usage
            col_query = text(
                """
                SELECT column_name, ordinal_position
                FROM information_schema.key_column_usage
                WHERE constraint_name = 'uq_outcome_records_tenant_action'
                ORDER BY ordinal_position;
                """
            )
            cols = [r["column_name"] for r in conn.execute(col_query).mappings().all()]
            assert cols == ["tenant_id", "action_id"], (
                f"Expected constraint columns ['tenant_id', 'action_id'], found {cols}"
            )

    def test_real_pg_rejection_of_duplicate_tenant_action(self, sync_engine: Any) -> None:
        """Proves PostgreSQL engine rejects duplicate (tenant_id, action_id) pairs with IntegrityError."""
        t_id = "test_tenant"
        action_id = f"act_dup_test_{uuid.uuid4().hex[:8]}"
        txn_id = f"txn_dup_test_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)

        with sync_engine.connect() as conn:
            tool_id = "tool_payment_mock"
            actor_id = "actor_test_mig"
            conn.execute(
                text(
                    """
                    INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at)
                    VALUES (:aid, :tenant, 'sub_mig_test', 'SERVICE', 'API_CLIENT', true, :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"aid": actor_id, "tenant": t_id, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO tool_registry (
                        id, tenant_id, name, description, tool_type, egress_type, trust_level,
                        required_capability, parameters_schema, config, active, created_at, updated_at
                    ) VALUES (
                        :tool_id, :tenant, 'test_tool', 'desc', 'NATIVE', 'INTERNAL_ISOLATED', 'VERIFIED',
                        'cap:test', '{}'::jsonb, '{}'::jsonb, true, :now, :now
                    ) ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"tool_id": tool_id, "tenant": t_id, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ai_transactions (
                        id, tenant_id, actor_identity_id, idempotency_key, correlation_id, state,
                        max_turns, turn_count, taint_flags, context_sources, version, created_at, updated_at
                    ) VALUES (
                        :tid, :tenant, :act_id, :idem_txn, 'corr_1', 'EXECUTING',
                        10, 1, '[]'::jsonb, '[]'::jsonb, 0, :now, :now
                    );
                    """
                ),
                {"tid": txn_id, "tenant": t_id, "act_id": actor_id, "idem_txn": f"idem_txn_{txn_id}", "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO action_contracts (
                        id, tenant_id, transaction_id, actor_identity_id, tool_id, tool_name,
                        target_resource, parameters_hash, required_capability, taint_flags,
                        blast_radius, state, idempotency_key, preconditions, postconditions, created_at
                    ) VALUES (
                        :aid, :tenant, :tid, :act_id, :tool_id, 'test_tool',
                        'https://api.test/v1', 'phash_1', 'cap:test', '[]'::jsonb,
                        '{}'::jsonb, 'COMPLETED', :idem, '[]'::jsonb, '[]'::jsonb, :now
                    );
                    """
                ),
                {
                    "aid": action_id,
                    "tenant": t_id,
                    "tid": txn_id,
                    "act_id": actor_id,
                    "tool_id": tool_id,
                    "idem": f"idem_{action_id}",
                    "now": now,
                },
            )
            conn.commit()

            # Insert first outcome verification record
            outc1_id = f"outc_{uuid.uuid4().hex[:12]}"
            conn.execute(
                text(
                    """
                    INSERT INTO outcome_verification_records (
                        id, tenant_id, transaction_id, action_id, observability_class,
                        outcome_status, epistemic_confidence, verifier_adapter, is_simulated,
                        expected_postconditions, observed_state, discrepancies, evidence_payload,
                        reconciliation_notes, verification_hash, target_environment, created_at, verified_at
                    ) VALUES (
                        :oid, :tenant, :tid, :aid, 'OBS_DIRECT',
                        'SUCCESS_CONFIRMED', 1.0, 'DatabaseStateAdapter', false,
                        '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, '{}'::jsonb,
                        '[]'::jsonb, 'hash_orig', 'PROD', :now, :now
                    );
                    """
                ),
                {"oid": outc1_id, "tenant": t_id, "tid": txn_id, "aid": action_id, "now": now},
            )
            conn.commit()

            # Attempt to insert second outcome verification record with SAME tenant_id and action_id
            outc2_id = f"outc_{uuid.uuid4().hex[:12]}"
            with pytest.raises(IntegrityError) as exc_info:
                conn.execute(
                    text(
                        """
                        INSERT INTO outcome_verification_records (
                            id, tenant_id, transaction_id, action_id, observability_class,
                            outcome_status, epistemic_confidence, verifier_adapter, is_simulated,
                            expected_postconditions, observed_state, discrepancies, evidence_payload,
                            reconciliation_notes, verification_hash, target_environment, created_at, verified_at
                        ) VALUES (
                            :oid, :tenant, :tid, :aid, 'OBS_DIRECT',
                            'SUCCESS_CONFIRMED', 1.0, 'DatabaseStateAdapter', false,
                            '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, '{}'::jsonb,
                            '[]'::jsonb, 'hash_second', 'PROD', :now, :now
                        );
                        """
                    ),
                    {"oid": outc2_id, "tenant": t_id, "tid": txn_id, "aid": action_id, "now": now},
                )
                conn.commit()

            assert "uq_outcome_records_tenant_action" in str(exc_info.value)
            conn.rollback()

    def test_real_pg_tenant_scoped_uniqueness_permits_different_tenants(self, sync_engine: Any) -> None:
        """Identical action_id across different tenants succeeds, proving tenant-scoped uniqueness."""
        shared_action_id = f"act_shared_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)

        with sync_engine.connect() as conn:
            # Seed transaction and action in tenant_valid
            txn_beta = f"txn_beta_{uuid.uuid4().hex[:8]}"
            conn.execute(
                text(
                    """
                    INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at)
                    VALUES ('actor_beta', 'tenant_valid', 'sub_beta', 'SERVICE', 'API_CLIENT', true, :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO tool_registry (
                        id, tenant_id, name, description, tool_type, egress_type, trust_level,
                        required_capability, parameters_schema, config, active, created_at, updated_at
                    ) VALUES (
                        'tool_beta', 'tenant_valid', 'test_tool_beta', 'desc', 'NATIVE', 'INTERNAL_ISOLATED',
                        'VERIFIED', 'cap:test', '{}'::jsonb, '{}'::jsonb, true, :now, :now
                    ) ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ai_transactions (
                        id, tenant_id, actor_identity_id, idempotency_key, correlation_id, state,
                        max_turns, turn_count, taint_flags, context_sources, version, created_at, updated_at
                    ) VALUES (
                        :tid, 'tenant_valid', 'actor_beta', :idem_txn, 'corr_beta', 'EXECUTING',
                        10, 1, '[]'::jsonb, '[]'::jsonb, 0, :now, :now
                    );
                    """
                ),
                {"tid": txn_beta, "idem_txn": f"idem_txn_{txn_beta}", "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO action_contracts (
                        id, tenant_id, transaction_id, actor_identity_id, tool_id, tool_name,
                        target_resource, parameters_hash, required_capability, taint_flags,
                        blast_radius, state, idempotency_key, preconditions, postconditions, created_at
                    ) VALUES (
                        :aid, 'tenant_valid', :tid, 'actor_beta', 'tool_beta', 'test_tool',
                        'https://api.test/v1', 'phash_1', 'cap:test', '[]'::jsonb,
                        '{}'::jsonb, 'COMPLETED', :idem, '[]'::jsonb, '[]'::jsonb, :now
                    );
                    """
                ),
                {"aid": shared_action_id, "tid": txn_beta, "idem": f"idem_{shared_action_id}_beta", "now": now},
            )

            # Insert into tenant_valid with the shared action_id
            outc_beta = f"outc_beta_{uuid.uuid4().hex[:8]}"
            conn.execute(
                text(
                    """
                    INSERT INTO outcome_verification_records (
                        id, tenant_id, transaction_id, action_id, observability_class,
                        outcome_status, epistemic_confidence, verifier_adapter, is_simulated,
                        expected_postconditions, observed_state, discrepancies, evidence_payload,
                        reconciliation_notes, verification_hash, target_environment, created_at, verified_at
                    ) VALUES (
                        :oid, 'tenant_valid', :tid, :aid, 'OBS_DIRECT',
                        'SUCCESS_CONFIRMED', 1.0, 'DatabaseStateAdapter', false,
                        '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, '{}'::jsonb,
                        '[]'::jsonb, 'hash_beta', 'PROD', :now, :now
                    );
                    """
                ),
                {"oid": outc_beta, "tid": txn_beta, "aid": shared_action_id, "now": now},
            )
            conn.commit()

            # Verify it was inserted successfully
            res = conn.execute(
                text("SELECT id FROM outcome_verification_records WHERE id = :oid"),
                {"oid": outc_beta},
            ).scalar_one_or_none()
            assert res == outc_beta

    def test_real_pg_legacy_preflight_duplicate_detection_query(self, sync_engine: Any) -> None:
        """Verifies preflight query detecting potential duplicate legacy records before applying constraint."""
        with sync_engine.connect() as conn:
            dup_check = conn.execute(
                text(
                    """
                    SELECT tenant_id, action_id, COUNT(*) as cnt
                    FROM outcome_verification_records
                    GROUP BY tenant_id, action_id
                    HAVING COUNT(*) > 1;
                    """
                )
            ).all()
            # On a properly constrained database, there must be ZERO duplicate groups
            assert len(dup_check) == 0

    def test_real_pg_rls_policies_attached_and_forced(self, sync_engine: Any) -> None:
        """Verifies relrowsecurity=true, relforcerowsecurity=true, and tenant policy exists."""
        with sync_engine.connect() as conn:
            # 1. Inspect pg_class flags
            class_info = (
                conn.execute(
                    text(
                        """
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = 'outcome_verification_records';
                    """
                    )
                )
                .mappings()
                .one()
            )
            assert class_info["relrowsecurity"] is True, "RLS must be enabled on outcome_verification_records"
            assert class_info["relforcerowsecurity"] is True, "RLS must be FORCED on outcome_verification_records"

            # 2. Inspect pg_policies
            pol = (
                conn.execute(
                    text(
                        """
                    SELECT policyname, tablename, cmd
                    FROM pg_policies
                    WHERE tablename = 'outcome_verification_records';
                    """
                    )
                )
                .mappings()
                .one_or_none()
            )
            assert pol is not None, "RLS policy not found on outcome_verification_records"
            assert pol["policyname"] == "tenant_isolation_outcome_verification_records"
            assert pol["cmd"] == "ALL"

    def test_migration_downgrade_and_reupgrade_cycle(self, sync_engine: Any) -> None:
        """Executes Alembic downgrade and upgrade to verify reversible schema migration."""
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", sync_url)

        # 1. Downgrade migration 009 (reverts to 008)
        command.downgrade(cfg, "008_gate4_output_assurance")

        with sync_engine.connect() as conn:
            table_check = conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'outcome_verification_records'
                    );
                    """
                )
            ).scalar()
            assert table_check is False, "outcome_verification_records table should be dropped after downgrade"

        # 2. Re-upgrade to head
        command.upgrade(cfg, "head")

        with sync_engine.connect() as conn:
            table_check_after = conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'public'
                        AND table_name = 'outcome_verification_records'
                    );
                    """
                )
            ).scalar()
            assert table_check_after is True, "outcome_verification_records table must be restored after upgrade"

            # Check constraint restored
            constraint_restored = conn.execute(
                text(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conname = 'uq_outcome_records_tenant_action';
                    """
                )
            ).scalar_one_or_none()
            assert constraint_restored == "uq_outcome_records_tenant_action"

    def test_phase6_migration_016_downgrade_and_reupgrade_cycle(self, sync_engine: Any) -> None:
        """Executes Alembic downgrade of migration 016 to 015 and re-upgrade to head."""
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", sync_url)

        # 1. Downgrade migration 016 (reverts to 015_routing_remediation)
        command.downgrade(cfg, "015_routing_remediation")

        with sync_engine.connect() as conn:
            # Check Phase 6 columns were dropped from outcome_verification_records
            col_check = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'outcome_verification_records'
                    AND column_name IN ('evidence_source', 'evidence_digest', 'observed_at', 'verification_deadline');
                    """
                )
            ).scalars().all()
            assert len(col_check) == 0, f"Expected Phase 6 columns dropped, found {col_check}"

            # Check Phase 6 columns were dropped from action_contracts
            act_col_check = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'action_contracts'
                    AND column_name IN ('requires_outcome_assurance', 'outcome_contract', 'outcome_status');
                    """
                )
            ).scalars().all()
            assert len(act_col_check) == 0, f"Expected Phase 6 action columns dropped, found {act_col_check}"

        # 2. Re-upgrade to head (016)
        command.upgrade(cfg, "head")

        with sync_engine.connect() as conn:
            # Check Phase 6 columns restored
            col_restored = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'outcome_verification_records'
                    AND column_name IN ('evidence_source', 'evidence_digest', 'observed_at', 'verification_deadline');
                    """
                )
            ).scalars().all()
            assert set(col_restored) == {"evidence_source", "evidence_digest", "observed_at", "verification_deadline"}

            act_col_restored = conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'action_contracts'
                    AND column_name IN ('requires_outcome_assurance', 'outcome_contract', 'outcome_status');
                    """
                )
            ).scalars().all()
            assert set(act_col_restored) == {"requires_outcome_assurance", "outcome_contract", "outcome_status"}

    def test_clean_schema_migration_rls_and_unprivileged_app_role_isolation(self, sync_engine: Any) -> None:
        """Starts from clean schema, runs real migrations, verifies RLS, and proves isolation under mirage_app."""
        _ = sync_engine
        sync_url = os.environ.get("DATABASE_SYNC_URL")
        assert sync_url is not None
        clean_db_name = f"test_clean_rls_{uuid.uuid4().hex[:8]}"

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
                for tbl in ("action_contracts", "outcome_verification_records"):
                    class_info = (
                        conn.execute(
                            text(
                                f"""
                                SELECT relrowsecurity, relforcerowsecurity
                                FROM pg_class
                                WHERE relname = '{tbl}';
                                """
                            )
                        )
                        .mappings()
                        .one()
                    )
                    assert class_info["relrowsecurity"] is True, f"RLS not enabled on {tbl} in clean database"
                    assert class_info["relforcerowsecurity"] is True, f"RLS not FORCED on {tbl} in clean database"

                    policy_info = (
                        conn.execute(
                            text(
                                f"""
                                SELECT policyname, tablename, cmd, qual, with_check
                                FROM pg_policies
                                WHERE tablename = '{tbl}' AND policyname = 'tenant_isolation_{tbl}';
                                """
                            )
                        )
                        .mappings()
                        .one_or_none()
                    )
                    assert policy_info is not None, f"Policy tenant_isolation_{tbl} missing in clean database"
                    assert policy_info["cmd"] == "ALL", f"Policy on {tbl} must be for ALL commands"

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

                # Grant connect on clean database to mirage_app (database-level connect privilege)
                conn.execute(text(f"GRANT CONNECT ON DATABASE {clean_db_name} TO mirage_app;"))
                conn.commit()
            clean_engine.dispose()

            # Step 4: Connect strictly as unprivileged mirage_app (no test fixture grants!)
            if "@" in clean_sync_url:
                prefix = clean_sync_url.split("://")[0]
                host_part = clean_sync_url.split("@")[1]
                app_sync_url = f"{prefix}://mirage_app:mirage_app_pw@{host_part}"
            else:
                app_sync_url = clean_sync_url

            app_engine = create_engine(app_sync_url)
            tenant_a = f"t_clean_a_{uuid.uuid4().hex[:6]}"
            tenant_b = f"t_clean_b_{uuid.uuid4().hex[:6]}"
            act_a = f"act_clean_a_{uuid.uuid4().hex[:6]}"
            act_b = f"act_clean_b_{uuid.uuid4().hex[:6]}"
            txn_a = f"txn_clean_a_{uuid.uuid4().hex[:6]}"
            txn_b = f"txn_clean_b_{uuid.uuid4().hex[:6]}"
            outc_a = f"outc_clean_a_{uuid.uuid4().hex[:6]}"
            outc_b = f"outc_clean_b_{uuid.uuid4().hex[:6]}"

            # Test A: Unauthenticated (no tenant context set) -> Fail closed
            with app_engine.connect() as conn:
                unauth_acts = conn.execute(text("SELECT id FROM action_contracts")).fetchall()
                assert len(unauth_acts) == 0
                unauth_outc = conn.execute(text("SELECT id FROM outcome_verification_records")).fetchall()
                assert len(unauth_outc) == 0

            # Test B: Seed Tenant A and insert under Tenant A context
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
                        INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at)
                        VALUES ('actor_a', :t, 'sub_a', 'USER', 'ADMIN', true, NOW())
                        """
                    ),
                    {"t": tenant_a},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO tool_registry (
                            id, tenant_id, name, description, tool_type, egress_type, trust_level,
                            required_capability, parameters_schema, config, active, created_at, updated_at
                        ) VALUES (
                            'tool_a', :t, 'tool_a', 'desc', 'NATIVE', 'INTERNAL_ISOLATED', 'VERIFIED',
                            'EXECUTE', '{}', '{}', true, NOW(), NOW()
                        )
                        """
                    ),
                    {"t": tenant_a},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO ai_transactions (
                            id, tenant_id, actor_identity_id, idempotency_key, correlation_id,
                            state, max_turns, turn_count, taint_flags, context_sources, created_at, updated_at
                        ) VALUES (
                            :txn, :t, 'actor_a', 'idem_txn_a', 'corr_a',
                            'IN_FLIGHT', 10, 0, '[]', '[]', NOW(), NOW()
                        )
                        """
                    ),
                    {"txn": txn_a, "t": tenant_a},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO action_contracts (
                            id, tenant_id, transaction_id, actor_identity_id, tool_id, tool_name,
                            action_type, target_resource, parameters, normalized_parameters, parameters_hash,
                            required_capability, taint_flags, risk_score, blast_radius, state, idempotency_key,
                            preconditions, postconditions, requires_outcome_assurance, outcome_status, created_at
                        ) VALUES (
                            :act, :t, :txn, 'actor_a', 'tool_a', 'exec_action',
                            'EXECUTE', 'db://target', '{}', '{}', 'hash_a',
                            'EXECUTE', '[]', 50, '{}', 'EXECUTED', 'idem_act_a',
                            '[]', '[]', true, 'PENDING_VERIFICATION', NOW()
                        )
                        """
                    ),
                    {"act": act_a, "t": tenant_a, "txn": txn_a},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO outcome_verification_records (
                            id, tenant_id, transaction_id, action_id, observability_class,
                            outcome_status, epistemic_confidence, verifier_adapter, is_simulated,
                            expected_postconditions, observed_state, discrepancies, evidence_payload,
                            reconciliation_notes, verification_hash, target_environment, created_at, verified_at
                        ) VALUES (
                            :outc, :t, :txn, :act, 'OBS_DIRECT',
                            'VERIFIED_SUCCESS', 1.0, 'IndependentObserverAdapter', false,
                            '{}', '{}', '[]', '{}', '[]', 'hash_outc_a', 'DEFAULT', NOW(), NOW()
                        )
                        """
                    ),
                    {"outc": outc_a, "t": tenant_a, "txn": txn_a, "act": act_a},
                )
                conn.commit()

            # Test C: Seed Tenant B under Tenant B context
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
                        INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at)
                        VALUES ('actor_b', :t, 'sub_b', 'USER', 'ADMIN', true, NOW())
                        """
                    ),
                    {"t": tenant_b},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO tool_registry (
                            id, tenant_id, name, description, tool_type, egress_type, trust_level,
                            required_capability, parameters_schema, config, active, created_at, updated_at
                        ) VALUES (
                            'tool_b', :t, 'tool_b', 'desc', 'NATIVE', 'INTERNAL_ISOLATED', 'VERIFIED',
                            'EXECUTE', '{}', '{}', true, NOW(), NOW()
                        )
                        """
                    ),
                    {"t": tenant_b},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO ai_transactions (
                            id, tenant_id, actor_identity_id, idempotency_key, correlation_id,
                            state, max_turns, turn_count, taint_flags, context_sources, created_at, updated_at
                        ) VALUES (
                            :txn, :t, 'actor_b', 'idem_txn_b', 'corr_b',
                            'IN_FLIGHT', 10, 0, '[]', '[]', NOW(), NOW()
                        )
                        """
                    ),
                    {"txn": txn_b, "t": tenant_b},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO action_contracts (
                            id, tenant_id, transaction_id, actor_identity_id, tool_id, tool_name,
                            action_type, target_resource, parameters, normalized_parameters, parameters_hash,
                            required_capability, taint_flags, risk_score, blast_radius, state, idempotency_key,
                            preconditions, postconditions, requires_outcome_assurance, outcome_status, created_at
                        ) VALUES (
                            :act, :t, :txn, 'actor_b', 'tool_b', 'exec_action',
                            'EXECUTE', 'db://target_b', '{}', '{}', 'hash_b',
                            'EXECUTE', '[]', 60, '{}', 'EXECUTED', 'idem_act_b',
                            '[]', '[]', true, 'PENDING_VERIFICATION', NOW()
                        )
                        """
                    ),
                    {"act": act_b, "t": tenant_b, "txn": txn_b},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO outcome_verification_records (
                            id, tenant_id, transaction_id, action_id, observability_class,
                            outcome_status, epistemic_confidence, verifier_adapter, is_simulated,
                            expected_postconditions, observed_state, discrepancies, evidence_payload,
                            reconciliation_notes, verification_hash, target_environment, created_at, verified_at
                        ) VALUES (
                            :outc, :t, :txn, :act, 'OBS_DIRECT',
                            'VERIFIED_FAILURE', 0.9, 'IndependentObserverAdapter', false,
                            '{}', '{}', '[]', '{}', '[]', 'hash_outc_b', 'DEFAULT', NOW(), NOW()
                        )
                        """
                    ),
                    {"outc": outc_b, "t": tenant_b, "txn": txn_b, "act": act_b},
                )
                conn.commit()

            # Test D: Isolation Checks under Tenant A context
            with app_engine.connect() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :t, true)"),
                    {"t": tenant_a},
                )
                # 1. SELECT isolation
                acts = conn.execute(text("SELECT id FROM action_contracts")).scalars().all()
                assert acts == [act_a], f"Tenant A saw unexpected actions: {acts}"
                outcs = conn.execute(text("SELECT id FROM outcome_verification_records")).scalars().all()
                assert outcs == [outc_a], f"Tenant A saw unexpected outcomes: {outcs}"

                # 2. Cross-tenant UPDATE attack -> 0 rows affected
                upd = conn.execute(
                    text("UPDATE outcome_verification_records SET outcome_status = 'VERIFIED_SUCCESS' WHERE id = :id"),
                    {"id": outc_b},
                )
                assert upd.rowcount == 0

                # 3. Cross-tenant DELETE attack -> 0 rows affected
                dele = conn.execute(
                    text("DELETE FROM action_contracts WHERE id = :id"),
                    {"id": act_b},
                )
                assert dele.rowcount == 0

                with pytest.raises((ProgrammingError, DBAPIError, IntegrityError)) as exc_info:
                    conn.execute(
                        text(
                            """
                            INSERT INTO outcome_verification_records (
                                id, tenant_id, transaction_id, action_id, observability_class,
                                outcome_status, epistemic_confidence, verifier_adapter, is_simulated,
                                expected_postconditions, observed_state, discrepancies, evidence_payload,
                                reconciliation_notes, verification_hash, target_environment, created_at, verified_at
                            ) VALUES (
                                'outc_spoofed', :forged_t, :txn, :act, 'OBS_DIRECT',
                                'VERIFIED_SUCCESS', 1.0, 'IndependentObserverAdapter', false,
                                '{}', '{}', '[]', '{}', '[]', 'hash_spoof', 'DEFAULT', NOW(), NOW()
                            )
                            """
                        ),
                        {"forged_t": tenant_b, "txn": txn_a, "act": act_a},
                    )
                err_msg = str(exc_info.value).lower()
                assert "row-level security" in err_msg or "check violation" in err_msg
                conn.rollback()

                # 5. Parameter injection attempt into set_config cannot bypass isolation
                malicious = f"{tenant_a}'; DROP TABLE action_contracts; --"
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :t, true)"),
                    {"t": malicious},
                )
                curr = conn.execute(text("SELECT current_setting('app.current_tenant_id', true)")).scalar()
                assert curr == malicious
                tbl_cnt = conn.execute(text("SELECT COUNT(*) FROM action_contracts")).scalar()
                assert tbl_cnt == 0

            app_engine.dispose()
        finally:
            with admin_engine.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {clean_db_name} WITH (FORCE);"))
            admin_engine.dispose()
