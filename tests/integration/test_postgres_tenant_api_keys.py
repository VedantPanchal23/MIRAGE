"""Live PostgreSQL 16 Integration Tests for Tenant Administration and API Key Lifecycle.

Implements Testing Strategy §5 & Final Phase Package 1 Deliverables:
- Migration 022 two-way upgrade/downgrade cycle on live PostgreSQL 16
- Stored procedure boundary enforcement: mirage_resolve_api_credential and mirage_resolve_jwt_identity
  strictly fail-closed when tenant status is SUSPENDED or OFFBOARDED
- Multi-tenant Row-Level Security (RLS) isolation on api_credentials
- End-to-end integration across TenantService, ApiKeyService, and authentication middleware
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from db import session as db_session
from db.models import ActorIdentity, ApiCredential, Tenant
from gateway.middleware.auth import resolve_api_key_context
from services.api_key_service import api_key_service
from services.tenant_service import tenant_service
from shared.config import get_settings
from shared.schemas.api_key import ApiKeyCreateRequest, ApiKeyRotateRequest
from shared.schemas.auth import AuthContext, Role
from shared.schemas.tenant import TenantCreateRequest, TenantStatus


@pytest.mark.integration
class TestPostgresTenantApiKeys:
    """Live PostgreSQL 16 Testcontainer verification of SaaS control-plane security."""

    @pytest.fixture(autouse=True)
    def ensure_db_schema(self, live_postgres_database: Any) -> None:
        """Ensure Alembic migrations are applied up to head."""
        if live_postgres_database is None:
            pytest.skip("Live PostgreSQL Testcontainer is required for this integration suite")

    @pytest.fixture
    def unprivileged_sessionmaker(self) -> Any:
        """Create async sessionmaker authenticated as unprivileged application role mirage_app with NOBYPASSRLS."""
        from sqlalchemy import create_engine
        from sqlalchemy.engine import make_url
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        settings = get_settings()
        sync_url = settings.database_sync_url
        parsed = make_url(sync_url)
        db_name = parsed.database or "test"

        admin_engine = create_engine(sync_url)
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mirage_app') THEN
                            CREATE ROLE mirage_app WITH LOGIN PASSWORD 'mirage_app_pw'
                                NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                        END IF;
                    END $$;
                    """
                )
            )
            conn.execute(text(f"GRANT CONNECT ON DATABASE {db_name} TO mirage_app;"))
            conn.execute(text("GRANT USAGE ON SCHEMA public TO mirage_app;"))
            conn.execute(
                text(
                    """
                    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO mirage_app;
                    """
                )
            )
            conn.commit()
        admin_engine.dispose()

        app_async_url = (
            make_url(settings.database_url)
            .set(
                username="mirage_app",
                password="mirage_app_pw",
            )
            .render_as_string(hide_password=False)
        )
        app_engine = create_async_engine(app_async_url, pool_size=5, max_overflow=5)
        return async_sessionmaker(bind=app_engine, class_=AsyncSession, expire_on_commit=False)

    def test_migration_022_upgrade_downgrade_cycle(self) -> None:
        """Verify migration 022 can be cleanly downgraded to 021 and re-upgraded to head."""
        settings = get_settings()
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", settings.database_sync_url)

        # 1. Downgrade from head (022) to 021
        command.downgrade(cfg, "-1")

        # 2. Re-upgrade to head (022)
        command.upgrade(cfg, "head")

    @pytest.mark.asyncio
    async def test_stored_procedure_fail_closed_on_tenant_suspension(self) -> None:
        """Stored procedures strictly enforce tenant ACTIVE status at the database layer."""
        suffix = uuid.uuid4().hex[:8]
        t_id = f"proc_tenant_{suffix}"
        identity_id = f"proc_id_{suffix}"
        cred_id = f"proc_key_{suffix}"
        raw_key = f"mirage_live_proc_test_{suffix}"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        # Seed tenant, actor, and credential via superadmin session
        async with db_session.get_tenant_session("default_tenant") as s:
            t = Tenant(
                id=t_id,
                name="Stored Proc Tenant",
                status=TenantStatus.ACTIVE.value,
                tier="enterprise",
                api_key_hash=hashlib.sha256(b"dummy").hexdigest(),
                scs_enabled=True,
                pii_detection_enabled=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            s.add(t)
            await s.flush()

            actor = ActorIdentity(
                id=identity_id,
                tenant_id=t_id,
                subject=f"client_{suffix}",
                principal_type="machine",
                role=Role.API_CLIENT.value,
                active=True,
            )
            s.add(actor)
            await s.flush()

            cred = ApiCredential(
                id=cred_id,
                tenant_id=t_id,
                identity_id=identity_id,
                name="Proc Key",
                key_prefix=raw_key[:16],
                key_hash=key_hash,
                scopes=["verify:read"],
                revoked_at=None,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
            s.add(cred)
            await s.commit()

        # 1. When tenant is ACTIVE, mirage_resolve_api_credential returns the credential
        async with db_session.get_tenant_session(t_id) as s:
            query = text("SELECT * FROM mirage_resolve_api_credential(:h)")
            res = await s.execute(query, {"h": key_hash})
            row = res.first()
            assert row is not None
            assert row.tenant_id == t_id
            assert row.role == Role.API_CLIENT.value

        # 2. When tenant is SUSPENDED, mirage_resolve_api_credential returns EMPTY (denied at SQL boundary)
        async with db_session.get_tenant_session("default_tenant") as s:
            await s.execute(
                text("UPDATE tenants SET status = 'SUSPENDED', suspension_reason = 'Incident' WHERE id = :tid"),
                {"tid": t_id},
            )
            await s.commit()

        async with db_session.get_tenant_session(t_id) as s:
            query = text("SELECT * FROM mirage_resolve_api_credential(:h)")
            res = await s.execute(query, {"h": key_hash})
            assert res.first() is None, "Suspended tenant credential MUST be rejected at SQL boundary"

            # Also check mirage_resolve_jwt_identity
            jwt_query = text("SELECT * FROM mirage_resolve_jwt_identity(:tid, :sub)")
            jwt_res = await s.execute(jwt_query, {"tid": t_id, "sub": f"client_{suffix}"})
            assert jwt_res.first() is None, "Suspended tenant JWT identity MUST be rejected at SQL boundary"

        # 3. When tenant is REACTIVATED, mirage_resolve_api_credential succeeds again
        async with db_session.get_tenant_session("default_tenant") as s:
            await s.execute(
                text("UPDATE tenants SET status = 'ACTIVE', suspension_reason = NULL WHERE id = :tid"),
                {"tid": t_id},
            )
            await s.commit()

        async with db_session.get_tenant_session(t_id) as s:
            query = text("SELECT * FROM mirage_resolve_api_credential(:h)")
            res = await s.execute(query, {"h": key_hash})
            assert res.first() is not None, "Reactivated tenant credential MUST be resolvable"

        # 4. When tenant is OFFBOARDED, resolution is permanently blocked
        async with db_session.get_tenant_session("default_tenant") as s:
            await s.execute(
                text("UPDATE tenants SET status = 'OFFBOARDED' WHERE id = :tid"),
                {"tid": t_id},
            )
            await s.commit()

        async with db_session.get_tenant_session(t_id) as s:
            query = text("SELECT * FROM mirage_resolve_api_credential(:h)")
            res = await s.execute(query, {"h": key_hash})
            assert res.first() is None, "Offboarded tenant credential MUST be permanently rejected"

    @pytest.mark.asyncio
    async def test_postgresql_rls_isolation_on_api_credentials(self, unprivileged_sessionmaker: Any) -> None:
        """PostgreSQL RLS ensures tenant A session cannot read or query tenant B credentials."""
        suffix = uuid.uuid4().hex[:8]
        tenant_a = f"rls_a_{suffix}"
        tenant_b = f"rls_b_{suffix}"

        # Seed Tenant A and Credential A
        async with db_session.get_tenant_session(tenant_a) as s_a:
            s_a.add(
                Tenant(
                    id=tenant_a,
                    name="Tenant A",
                    status=TenantStatus.ACTIVE.value,
                    tier="free",
                    api_key_hash=hashlib.sha256(f"api_key_{tenant_a}".encode()).hexdigest(),
                    created_at=datetime.now(UTC),
                )
            )
            await s_a.flush()

            id_a = ActorIdentity(
                id=f"id_a_{suffix}",
                tenant_id=tenant_a,
                subject="admin_a",
                principal_type="user",
                role=Role.TENANT_ADMIN.value,
                active=True,
            )
            s_a.add(id_a)
            await s_a.flush()

            cred_a = ApiCredential(
                id=f"cred_a_{suffix}",
                tenant_id=tenant_a,
                identity_id=id_a.id,
                name="Key A",
                key_prefix="mirage_live_a123",
                key_hash=hashlib.sha256(f"secret_a_{suffix}".encode()).hexdigest(),
                scopes=["*"],
            )
            s_a.add(cred_a)
            await s_a.commit()

        # Seed Tenant B and Credential B
        async with db_session.get_tenant_session(tenant_b) as s_b:
            s_b.add(
                Tenant(
                    id=tenant_b,
                    name="Tenant B",
                    status=TenantStatus.ACTIVE.value,
                    tier="free",
                    api_key_hash=hashlib.sha256(f"api_key_{tenant_b}".encode()).hexdigest(),
                    created_at=datetime.now(UTC),
                )
            )
            await s_b.flush()

            id_b = ActorIdentity(
                id=f"id_b_{suffix}",
                tenant_id=tenant_b,
                subject="admin_b",
                principal_type="user",
                role=Role.TENANT_ADMIN.value,
                active=True,
            )
            s_b.add(id_b)
            await s_b.flush()

            cred_b = ApiCredential(
                id=f"cred_b_{suffix}",
                tenant_id=tenant_b,
                identity_id=id_b.id,
                name="Key B",
                key_prefix="mirage_live_b456",
                key_hash=hashlib.sha256(f"secret_b_{suffix}".encode()).hexdigest(),
                scopes=["*"],
            )
            s_b.add(cred_b)
            await s_b.commit()

        # Query credentials from Tenant A session using unprivileged NOBYPASSRLS role
        async with unprivileged_sessionmaker() as s_a:
            async with s_a.begin():
                await s_a.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                res_a = await s_a.execute(select(ApiCredential))
                creds_in_a = list(res_a.scalars().all())
                tenant_ids_in_a = {c.tenant_id for c in creds_in_a}
                assert tenant_a in tenant_ids_in_a
                assert tenant_b not in tenant_ids_in_a, (
                    "Tenant A MUST NOT see Tenant B credentials under PostgreSQL RLS"
                )

        # Query credentials from Tenant B session using unprivileged NOBYPASSRLS role
        async with unprivileged_sessionmaker() as s_b:
            async with s_b.begin():
                await s_b.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_b},
                )
                res_b = await s_b.execute(select(ApiCredential))
                creds_in_b = list(res_b.scalars().all())
                tenant_ids_in_b = {c.tenant_id for c in creds_in_b}
                assert tenant_b in tenant_ids_in_b
                assert tenant_a not in tenant_ids_in_b, (
                    "Tenant B MUST NOT see Tenant A credentials under PostgreSQL RLS"
                )

        # Verify cross-tenant insert attempt fails-closed with RLS policy violation
        from sqlalchemy.exc import DBAPIError, ProgrammingError

        async with unprivileged_sessionmaker() as s_spoof:
            async with s_spoof.begin():
                await s_spoof.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                    await s_spoof.execute(
                        text(
                            """
                            INSERT INTO api_credentials (
                                id, tenant_id, identity_id, name, key_prefix, key_hash, scopes, created_at
                            ) VALUES (
                                'cred_spoofed', :tenant_b, :id_a, 'Spoofed Key',
                                'mirage_live_sp', 'spoofhash', '["*"]'::jsonb, NOW()
                            )
                            """
                        ),
                        {"tenant_b": tenant_b, "id_a": id_a.id},
                    )
                assert "violates row-level security policy" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_end_to_end_tenant_and_api_key_lifecycle(self) -> None:
        """End-to-end integration: provision tenant, create key, authenticate, suspend, rotate, revoke."""
        super_admin_auth = AuthContext(
            tenant_id="default_tenant",
            role=Role.SUPER_ADMIN,
            user_id="superadmin",
            identity_id="id_superadmin",
            principal_type="user",
            token_type="jwt",
        )

        suffix = uuid.uuid4().hex[:8]
        new_tenant_id = f"e2e_tenant_{suffix}"

        # 1. Provision new tenant via TenantService
        tenant_req = TenantCreateRequest(
            name="E2E Corporation",
            tenant_id=new_tenant_id,
            tier="enterprise",
        )
        tenant_resp = await tenant_service.create_tenant(auth=super_admin_auth, req=tenant_req)
        assert tenant_resp.id == new_tenant_id
        assert tenant_resp.status == TenantStatus.ACTIVE

        # 2. Issue API key via ApiKeyService
        tenant_admin_auth = AuthContext(
            tenant_id=new_tenant_id,
            role=Role.TENANT_ADMIN,
            user_id="e2e_admin",
            identity_id=None,
            principal_type="user",
            token_type="jwt",
        )
        key_req = ApiKeyCreateRequest(
            name="Primary Ingestion Key",
            scopes=["verify:read", "verify:write"],
            expires_in_days=30,
        )
        created_key = await api_key_service.create_api_key(auth=tenant_admin_auth, req=key_req)
        assert created_key.raw_key.startswith("mirage_live_")

        # 3. Authenticate with the raw key via resolve_api_key_context
        auth_ctx = await resolve_api_key_context(created_key.raw_key)
        assert auth_ctx.tenant_id == new_tenant_id
        assert auth_ctx.role == Role.API_CLIENT
        assert auth_ctx.is_authenticated is True

        # 4. Suspend tenant via TenantService
        await tenant_service.suspend_tenant(auth=super_admin_auth, tenant_id=new_tenant_id, reason="Security review")

        # 5. Immediate authentication boundary cutoff: resolve_api_key_context must fail
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await resolve_api_key_context(created_key.raw_key)
        assert exc_info.value.status_code == 401

        # 6. Reactivate tenant
        await tenant_service.reactivate_tenant(auth=super_admin_auth, tenant_id=new_tenant_id)

        # Authentication immediately succeeds again
        auth_ctx_reactivated = await resolve_api_key_context(created_key.raw_key)
        assert auth_ctx_reactivated.tenant_id == new_tenant_id

        # 7. Rotate key with immediate revocation
        rotate_req = ApiKeyRotateRequest(immediate_revocation=True)
        rotated_key = await api_key_service.rotate_api_key(
            auth=tenant_admin_auth,
            key_id=created_key.id,
            req=rotate_req,
        )

        # Old key is immediately revoked
        with pytest.raises(HTTPException) as exc_info:
            await resolve_api_key_context(created_key.raw_key)
        assert exc_info.value.status_code == 401

        # New rotated key authenticates successfully
        auth_ctx_rotated = await resolve_api_key_context(rotated_key.raw_key)
        assert auth_ctx_rotated.tenant_id == new_tenant_id

        # 8. Revoke the new key
        await api_key_service.revoke_api_key(auth=tenant_admin_auth, key_id=rotated_key.id)

        with pytest.raises(HTTPException) as exc_info:
            await resolve_api_key_context(rotated_key.raw_key)
        assert exc_info.value.status_code == 401
