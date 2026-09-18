"""Security and Row-Level Security (RLS) Tests on live PostgreSQL 16 Testcontainer.

Implements Security & Access Document §9.1 & §10.2:
- Mandatory unprivileged application role (NOSUPERUSER, NOBYPASSRLS, not table owner)
- Database engine privilege enforcement: UPDATE/DELETE denied on audit_logs
- RLS cross-tenant SELECT, INSERT, UPDATE, DELETE blocks
- Connection pool isolation across alternating tenant contexts (A -> B -> A -> B)
- Revert of transaction-local setting on COMMIT and ROLLBACK
- Parameterized SQL injection resistance in tenant context setting
"""

import os
import uuid
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from db.models import VerificationSession


@pytest.mark.security
class TestPostgresRowLevelSecurity:
    """Live PostgreSQL 16 security tests verifying RLS and privilege enforcement."""

    @pytest.fixture(scope="class")
    def pg_container(self, live_postgres_database: Any) -> Any:
        """Dedicated PostgreSQL 16 container for security and RLS tests."""
        if live_postgres_database is not None:
            yield live_postgres_database
        else:
            with PostgresContainer("postgres:16-alpine") as pg:
                yield pg

    @pytest.fixture(scope="class", autouse=True)
    def setup_app_role_and_schema(self, pg_container: Any) -> Any:
        """Run migrations as admin, create unprivileged mirage_app role, grant explicit permissions."""
        admin_sync_url = pg_container.get_connection_url().replace("+psycopg2", "")

        # 1. Run migrations as admin
        os.environ["DATABASE_SYNC_URL"] = admin_sync_url
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", admin_sync_url)
        command.upgrade(cfg, "head")

        # 2. Create unprivileged application role
        admin_engine = create_engine(admin_sync_url)
        with admin_engine.connect() as conn:
            conn.execute(text("DROP ROLE IF EXISTS mirage_app;"))
            conn.execute(
                text(
                    """
                    CREATE ROLE mirage_app WITH LOGIN PASSWORD 'mirage_app_pw'
                        NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                    """
                )
            )
            conn.execute(text("GRANT CONNECT ON DATABASE test TO mirage_app;"))
            conn.execute(text("GRANT USAGE ON SCHEMA public TO mirage_app;"))
            conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO mirage_app;"))
            conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON verification_sessions TO mirage_app;"))
            conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON claims TO mirage_app;"))
            # Explicitly grant only SELECT and INSERT on audit_logs (NO UPDATE, NO DELETE)
            conn.execute(text("GRANT SELECT, INSERT ON audit_logs TO mirage_app;"))
            conn.commit()

        # Build connection URL for unprivileged mirage_app
        host = pg_container.get_container_host_ip()
        port = pg_container.get_exposed_port(5432)
        app_async_url = f"postgresql+asyncpg://mirage_app:mirage_app_pw@{host}:{port}/test"

        return app_async_url

    @pytest.fixture
    def app_sessionmaker(self, setup_app_role_and_schema: str) -> async_sessionmaker[AsyncSession]:
        """Create async sessionmaker authenticated as unprivileged mirage_app."""
        app_engine = create_async_engine(setup_app_role_and_schema, pool_size=5, max_overflow=5)
        return async_sessionmaker(bind=app_engine, class_=AsyncSession, expire_on_commit=False)

    @pytest.mark.asyncio
    async def test_1_application_role_properties(self, app_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Verify mirage_app is NOSUPERUSER, NOBYPASSRLS, and not owner of protected tables."""
        async with app_sessionmaker() as session:
            # 1. Assert role attributes
            role_res = await session.execute(
                text("SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'mirage_app'")
            )
            role_row = role_res.fetchone()
            assert role_row is not None
            assert role_row[0] == "mirage_app"
            assert role_row[1] is False  # rolsuper == False
            assert role_row[2] is False  # rolbypassrls == False

            # 2. Assert table ownership is not mirage_app
            owner_res = await session.execute(
                text(
                    """
                    SELECT tablename, tableowner
                    FROM pg_tables
                    WHERE schemaname = 'public'
                      AND tablename IN ('verification_sessions', 'claims', 'audit_logs', 'tenants');
                    """
                )
            )
            owners = owner_res.fetchall()
            assert len(owners) == 4
            for t_name, t_owner in owners:
                assert t_owner != "mirage_app", f"Table {t_name} is unexpectedly owned by mirage_app"

    @pytest.mark.asyncio
    async def test_2_audit_logs_immutability_privilege_enforcement(
        self, app_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Verify database permissions reject UPDATE and DELETE on audit_logs."""
        tenant_id = f"tenant_audit_{uuid.uuid4().hex[:6]}"
        entry_id = f"aud_{uuid.uuid4().hex[:8]}"

        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_id},
                )
                # Insert initial audit log row
                await session.execute(
                    text(
                        """
                        INSERT INTO audit_logs (
                            entry_id, tenant_id, session_id, trace_id, prompt_hash, response_hash,
                            hrs_score, risk_tier, claims_count, prev_hash, chain_hash, created_at
                        )
                        VALUES (:entry_id, :tenant, 's1', 'tr1', 'ph', 'rh', 0.1, 'LOW', 0, 'prev', 'chain', NOW())
                        """
                    ),
                    {"entry_id": entry_id, "tenant": tenant_id},
                )

        # 1. Attempt UPDATE on audit_logs -> must be rejected by PostgreSQL privileges
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_id},
                )
                with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                    await session.execute(
                        text("UPDATE audit_logs SET hrs_score = 0.99 WHERE entry_id = :entry_id"),
                        {"entry_id": entry_id},
                    )
                assert "permission denied for table audit_logs" in str(exc_info.value).lower()

        # 2. Attempt DELETE on audit_logs -> must be rejected by PostgreSQL privileges
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_id},
                )
                with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                    await session.execute(
                        text("DELETE FROM audit_logs WHERE entry_id = :entry_id"),
                        {"entry_id": entry_id},
                    )
                assert "permission denied for table audit_logs" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_3_rls_cross_tenant_select_isolation(
        self, app_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Verify RLS blocks Tenant A from seeing Tenant B rows and vice versa."""
        tenant_a = f"tenant_a_{uuid.uuid4().hex[:6]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:6]}"
        sess_a = f"sess_a_{uuid.uuid4().hex[:6]}"
        sess_b = f"sess_b_{uuid.uuid4().hex[:6]}"

        # Seed data for Tenant A
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                await session.execute(
                    text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:t, 'A', 'hA', NOW())"),
                    {"t": tenant_a},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO verification_sessions (
                            session_id, tenant_id, trace_id, model_id,
                            prompt_hash, response_hash, hrs_score, risk_tier, created_at
                        )
                        VALUES (:sess, :tenant, 'tr', 'mod', 'p_hash', 'r_hash', 0.15, 'LOW', NOW())
                        """
                    ),
                    {"sess": sess_a, "tenant": tenant_a},
                )

        # Seed data for Tenant B
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_b},
                )
                await session.execute(
                    text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:t, 'B', 'hB', NOW())"),
                    {"t": tenant_b},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO verification_sessions (
                            session_id, tenant_id, trace_id, model_id,
                            prompt_hash, response_hash, hrs_score, risk_tier, created_at
                        )
                        VALUES (:sess, :tenant, 'tr', 'mod', 'p_hash', 'r_hash', 0.85, 'HIGH', NOW())
                        """
                    ),
                    {"sess": sess_b, "tenant": tenant_b},
                )

        # Query under Tenant A context -> Tenant B rows MUST be completely invisible
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                res_all = await session.execute(select(VerificationSession))
                records = res_all.scalars().all()
                assert len(records) == 1
                assert records[0].session_id == sess_a
                assert records[0].tenant_id == tenant_a

                # Query Tenant B session ID directly -> returns None
                direct_b = await session.get(VerificationSession, sess_b)
                assert direct_b is None

        # Query under Tenant B context -> Tenant A rows MUST be completely invisible
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_b},
                )
                res_all = await session.execute(select(VerificationSession))
                records = res_all.scalars().all()
                assert len(records) == 1
                assert records[0].session_id == sess_b
                assert records[0].tenant_id == tenant_b

                # Query Tenant A session ID directly -> returns None
                direct_a = await session.get(VerificationSession, sess_a)
                assert direct_a is None

    @pytest.mark.asyncio
    async def test_4_rls_cross_tenant_insert_blocked(self, app_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Verify RLS rejects attempting to insert a row with a different tenant_id."""
        tenant_a = f"tenant_a_{uuid.uuid4().hex[:6]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:6]}"

        async with app_sessionmaker() as session:
            async with session.begin():
                # Establish Tenant A context
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )

                # Attempt to insert row for Tenant B -> must fail RLS WITH CHECK policy
                with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                    await session.execute(
                        text(
                            """
                            INSERT INTO verification_sessions (
                                session_id, tenant_id, trace_id, model_id,
                                prompt_hash, response_hash, hrs_score, risk_tier, created_at
                            )
                            VALUES ('sess_malicious', :tenant_b, 'tr', 'mod', 'ph', 'rh', 0.1, 'LOW', NOW())
                            """
                        ),
                        {"tenant_b": tenant_b},
                    )
                assert "row-level security policy" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_5_rls_cross_tenant_update_blocked(self, app_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Verify Tenant A cannot update Tenant B records."""
        tenant_a = f"tenant_a_{uuid.uuid4().hex[:6]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:6]}"
        sess_b = f"sess_target_{uuid.uuid4().hex[:6]}"

        # Seed row for Tenant B
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_b},
                )
                await session.execute(
                    text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:t, 'B', 'hb', NOW())"),
                    {"t": tenant_b},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO verification_sessions (
                            session_id, tenant_id, trace_id, model_id,
                            prompt_hash, response_hash, hrs_score, risk_tier, created_at
                        )
                        VALUES (:sess, :tenant, 'tr', 'mod', 'ph', 'rh', 0.50, 'MEDIUM', NOW())
                        """
                    ),
                    {"sess": sess_b, "tenant": tenant_b},
                )

        # Attempt UPDATE from Tenant A context -> affects 0 rows
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                res = await session.execute(
                    text("UPDATE verification_sessions SET hrs_score = 0.01 WHERE session_id = :sess"),
                    {"sess": sess_b},
                )
                assert res.rowcount == 0

        # Verify Tenant B row unchanged
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_b},
                )
                rec = await session.get(VerificationSession, sess_b)
                assert rec is not None
                assert rec.hrs_score == 0.50

    @pytest.mark.asyncio
    async def test_6_rls_cross_tenant_delete_blocked(self, app_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        """Verify Tenant A cannot delete Tenant B records."""
        tenant_a = f"tenant_a_{uuid.uuid4().hex[:6]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:6]}"
        sess_b = f"sess_target_del_{uuid.uuid4().hex[:6]}"

        # Seed row for Tenant B
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_b},
                )
                await session.execute(
                    text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:t, 'B', 'hb2', NOW())"),
                    {"t": tenant_b},
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO verification_sessions (
                            session_id, tenant_id, trace_id, model_id,
                            prompt_hash, response_hash, hrs_score, risk_tier, created_at
                        )
                        VALUES (:sess, :tenant, 'tr', 'mod', 'ph', 'rh', 0.50, 'MEDIUM', NOW())
                        """
                    ),
                    {"sess": sess_b, "tenant": tenant_b},
                )

        # Attempt DELETE from Tenant A context -> affects 0 rows
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                res = await session.execute(
                    text("DELETE FROM verification_sessions WHERE session_id = :sess"),
                    {"sess": sess_b},
                )
                assert res.rowcount == 0

        # Verify Tenant B row still exists
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_b},
                )
                rec = await session.get(VerificationSession, sess_b)
                assert rec is not None

    @pytest.mark.asyncio
    async def test_7_pooled_connection_isolation_and_revert(
        self, app_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Verify alternating tenant transactions (A -> B) on same pool never leak context and reset after commit."""
        tenant_a = f"tenant_pool_a_{uuid.uuid4().hex[:6]}"
        tenant_b = f"tenant_pool_b_{uuid.uuid4().hex[:6]}"

        # Step 1: Transaction for Tenant A -> COMMIT
        async with app_sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :t, true)"),
                    {"t": tenant_a},
                )
                curr = (await session.execute(text("SELECT current_setting('app.current_tenant_id', true)"))).scalar()
                assert curr == tenant_a

        # Step 2: Immediate check on fresh session -> setting must be empty (cleared by transaction commit)
        async with app_sessionmaker() as session:
            curr = (await session.execute(text("SELECT current_setting('app.current_tenant_id', true)"))).scalar()
            assert curr in (None, "")

        # Step 3: Transaction for Tenant B -> ROLLBACK
        async with app_sessionmaker() as session:
            try:
                async with session.begin():
                    await session.execute(
                        text("SELECT set_config('app.current_tenant_id', :t, true)"),
                        {"t": tenant_b},
                    )
                    curr = (
                        await session.execute(text("SELECT current_setting('app.current_tenant_id', true)"))
                    ).scalar()
                    assert curr == tenant_b
                    raise RuntimeError("Forced rollback")
            except RuntimeError:
                pass

        # Step 4: Immediate check on fresh session -> setting must be empty (cleared by transaction rollback)
        async with app_sessionmaker() as session:
            curr = (await session.execute(text("SELECT current_setting('app.current_tenant_id', true)"))).scalar()
            assert curr in (None, "")

        # Step 5: Alternating sequence A -> B -> A -> B across same pool
        for expected_tenant in [tenant_a, tenant_b, tenant_a, tenant_b]:
            async with app_sessionmaker() as session:
                async with session.begin():
                    await session.execute(
                        text("SELECT set_config('app.current_tenant_id', :t, true)"),
                        {"t": expected_tenant},
                    )
                    val = (
                        await session.execute(text("SELECT current_setting('app.current_tenant_id', true)"))
                    ).scalar()
                    assert val == expected_tenant

    @pytest.mark.asyncio
    async def test_8_sql_injection_resistance_in_tenant_parameter(
        self, app_sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        """Verify malicious tenant IDs cannot inject SQL through set_config parameterization."""
        malicious_inputs = [
            "tenant_a'; DROP TABLE verification_sessions; --",
            "' OR '1'='1",
            "admin' UNION SELECT * FROM users --",
            "'; SELECT set_config('app.current_tenant_id', 'super', false); --",
        ]

        for malicious_tenant in malicious_inputs:
            async with app_sessionmaker() as session:
                async with session.begin():
                    # Safely parameterize set_config
                    await session.execute(
                        text("SELECT set_config('app.current_tenant_id', :t, true)"),
                        {"t": malicious_tenant},
                    )
                    # Value must be exact literal string, not interpreted as SQL
                    val = (
                        await session.execute(text("SELECT current_setting('app.current_tenant_id', true)"))
                    ).scalar()
                    assert val == malicious_tenant

                    # Verify tables still exist
                    check_table = (
                        await session.execute(
                            text(
                                "SELECT COUNT(*) FROM information_schema.tables "
                                "WHERE table_name = 'verification_sessions'"
                            )
                        )
                    ).scalar()
                    assert check_table == 1
