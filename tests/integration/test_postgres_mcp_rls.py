"""Live PostgreSQL 16 Integration Tests for Governed MCP Servers and RLS Isolation.

Implements Testing Strategy §5 & Final Phase Package 2 Deliverables:
- Migration 023 two-way upgrade/downgrade cycle on live PostgreSQL 16
- Multi-tenant Row-Level Security (RLS) isolation on mcp_servers table using unprivileged role mirage_app (NOBYPASSRLS)
- Fail-closed RLS query behavior when app.current_tenant_id is unset or invalid
- Foreign key constraints and cascade semantics between mcp_servers and tool_registry
- Live integration with MCPRegistryService and cryptographic audit log emission
"""

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from db import session as db_session
from db.models import MCPServer, Tenant, ToolDefinition
from services.mcp_registry_service import mcp_registry_service
from shared.config import get_settings
from shared.schemas.auth import AuthContext, Role
from shared.schemas.mcp import (
    MCPDiscoveredTool,
    MCPServerCreateRequest,
    MCPServerTransport,
    MCPTrustStatus,
    MCPTrustStatusUpdateRequest,
)
from shared.schemas.tenant import TenantStatus


@pytest.mark.integration
class TestPostgresMCPRLS:
    """Live PostgreSQL 16 Testcontainer verification of Governed MCP multi-tenancy and RLS."""

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

        app_async_url = make_url(settings.database_url).set(
            username="mirage_app",
            password="mirage_app_pw",
        ).render_as_string(hide_password=False)
        app_engine = create_async_engine(app_async_url, pool_size=5, max_overflow=5)
        return async_sessionmaker(bind=app_engine, class_=AsyncSession, expire_on_commit=False)

    def test_migration_023_upgrade_downgrade_cycle(self) -> None:
        """Verify migration 023 can be cleanly downgraded to 022 and re-upgraded to head."""
        settings = get_settings()
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", settings.database_sync_url)

        # 1. Downgrade from head (023) to 022
        command.downgrade(cfg, "-1")

        # 2. Re-upgrade to head (023)
        command.upgrade(cfg, "head")

    @pytest.mark.asyncio
    async def test_postgresql_rls_isolation_on_mcp_servers(
        self, unprivileged_sessionmaker: Any
    ) -> None:
        """PostgreSQL RLS ensures tenant A session cannot read or mutate tenant B MCP servers."""
        suffix = uuid.uuid4().hex[:8]
        tenant_a = f"rls_mcp_a_{suffix}"
        tenant_b = f"rls_mcp_b_{suffix}"
        server_a_id = f"mcp_srv_a_{suffix}"
        server_b_id = f"mcp_srv_b_{suffix}"

        # Seed Tenants and MCP servers via privileged session
        async with db_session.get_tenant_session("default_tenant") as s:
            s.add(
                Tenant(
                    id=tenant_a,
                    name="MCP Tenant A",
                    status=TenantStatus.ACTIVE.value,
                    tier="enterprise",
                    api_key_hash=hashlib.sha256(f"key_{tenant_a}".encode()).hexdigest(),
                    created_at=datetime.now(UTC),
                )
            )
            s.add(
                Tenant(
                    id=tenant_b,
                    name="MCP Tenant B",
                    status=TenantStatus.ACTIVE.value,
                    tier="enterprise",
                    api_key_hash=hashlib.sha256(f"key_{tenant_b}".encode()).hexdigest(),
                    created_at=datetime.now(UTC),
                )
            )
            await s.flush()

            srv_a = MCPServer(
                id=server_a_id,
                tenant_id=tenant_a,
                name="Server Alpha",
                transport_type="HTTP_STREAM",
                connection_config={"url": "https://api.alpha.example.com/stream"},
                trust_status=MCPTrustStatus.TRUSTED.value,
                permitted_capabilities=["weather:read"],
                egress_allowlist=["api.alpha.example.com"],
                timeout_seconds=30,
            )
            srv_b = MCPServer(
                id=server_b_id,
                tenant_id=tenant_b,
                name="Server Bravo",
                transport_type="HTTP_STREAM",
                connection_config={"url": "https://api.bravo.example.com/stream"},
                trust_status=MCPTrustStatus.PENDING_APPROVAL.value,
                permitted_capabilities=["finance:read"],
                egress_allowlist=["api.bravo.example.com"],
                timeout_seconds=45,
            )
            s.add(srv_a)
            s.add(srv_b)
            await s.commit()

        # 1. Query under unprivileged mirage_app role with app.current_tenant_id = tenant_a
        async with unprivileged_sessionmaker() as s_a:
            async with s_a.begin():
                await s_a.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                res_a = await s_a.execute(select(MCPServer))
                servers_in_a = list(res_a.scalars().all())
                server_ids_a = {srv.id for srv in servers_in_a}
                assert server_a_id in server_ids_a
                assert (
                    server_b_id not in server_ids_a
                ), "Tenant A MUST NOT see Tenant B's MCP server under RLS"

        # 2. Query under unprivileged mirage_app role with app.current_tenant_id = tenant_b
        async with unprivileged_sessionmaker() as s_b:
            async with s_b.begin():
                await s_b.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_b},
                )
                res_b = await s_b.execute(select(MCPServer))
                servers_in_b = list(res_b.scalars().all())
                server_ids_b = {srv.id for srv in servers_in_b}
                assert server_b_id in server_ids_b
                assert (
                    server_a_id not in server_ids_b
                ), "Tenant B MUST NOT see Tenant A's MCP server under RLS"

        # 3. Fail-closed: Query under unprivileged mirage_app role with NO tenant set (empty string)
        async with unprivileged_sessionmaker() as s_none:
            async with s_none.begin():
                await s_none.execute(
                    text("SELECT set_config('app.current_tenant_id', '', true)")
                )
                res_none = await s_none.execute(select(MCPServer))
                servers_none = list(res_none.scalars().all())
                # Should not see any server belonging to tenant_a or tenant_b
                assert server_a_id not in {srv.id for srv in servers_none}
                assert server_b_id not in {srv.id for srv in servers_none}

        # 4. Cross-tenant mutation rejection: Tenant A attempting to insert row for Tenant B
        async with unprivileged_sessionmaker() as s_bad:
            async with s_bad.begin():
                await s_bad.execute(
                    text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
                    {"tenant": tenant_a},
                )
                bad_server = MCPServer(
                    id=f"bad_srv_{suffix}",
                    tenant_id=tenant_b,  # Tampered tenant ID
                    name="Malicious Injected Server",
                    transport_type="HTTP_STREAM",
                    connection_config={"url": "https://attacker.example.com"},
                    trust_status=MCPTrustStatus.PENDING_APPROVAL.value,
                    timeout_seconds=30,
                )
                s_bad.add(bad_server)
                with pytest.raises(DBAPIError) as exc_info:
                    await s_bad.flush()
                assert "violates row-level security policy" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_tool_registry_mcp_foreign_key_and_cascade(self) -> None:
        """Verify foreign key linking tool_registry to mcp_servers with ON DELETE CASCADE."""
        suffix = uuid.uuid4().hex[:8]
        tenant_id = f"fk_tenant_{suffix}"
        server_id = f"fk_srv_{suffix}"
        tool_id = f"fk_tool_{suffix}"

        async with db_session.get_tenant_session("default_tenant") as s:
            s.add(
                Tenant(
                    id=tenant_id,
                    name="FK Tenant",
                    status=TenantStatus.ACTIVE.value,
                    tier="free",
                    api_key_hash=hashlib.sha256(b"fk").hexdigest(),
                    created_at=datetime.now(UTC),
                )
            )
            await s.flush()

            srv = MCPServer(
                id=server_id,
                tenant_id=tenant_id,
                name="Cascading Server",
                transport_type="HTTP_STREAM",
                connection_config={"url": "https://mcp.cascade.test"},
                trust_status=MCPTrustStatus.TRUSTED.value,
                timeout_seconds=30,
            )
            s.add(srv)
            await s.flush()

            tool = ToolDefinition(
                id=tool_id,
                tenant_id=tenant_id,
                name="cascaded_action",
                tool_type="MCP",
                egress_type="EXTERNAL_NETWORK",
                trust_level="VERIFIED",
                required_capability="cascade:action",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                mcp_server_id=server_id,
            )
            s.add(tool)
            await s.commit()

        # Verify tool is linked
        async with db_session.get_tenant_session(tenant_id) as s:
            loaded_tool = await s.get(ToolDefinition, tool_id)
            assert loaded_tool is not None
            assert loaded_tool.mcp_server_id == server_id

            # Delete the MCP Server
            loaded_srv = await s.get(MCPServer, server_id)
            assert loaded_srv is not None
            await s.delete(loaded_srv)
            await s.commit()

        # Verify ToolDefinition was cascaded
        async with db_session.get_tenant_session(tenant_id) as s:
            deleted_tool = await s.get(ToolDefinition, tool_id)
            assert deleted_tool is None, "ToolDefinition MUST be deleted via ON DELETE CASCADE"

    @pytest.mark.asyncio
    async def test_end_to_end_mcp_registry_service_and_audit(self) -> None:
        """Verify MCPRegistryService registration, trust transitions, tool sync and audit log chaining."""
        suffix = uuid.uuid4().hex[:8]
        tenant_id = f"e2e_tenant_{suffix}"

        async with db_session.get_tenant_session("default_tenant") as s:
            s.add(
                Tenant(
                    id=tenant_id,
                    name="E2E Tenant",
                    status=TenantStatus.ACTIVE.value,
                    tier="enterprise",
                    api_key_hash=hashlib.sha256(b"e2e").hexdigest(),
                    created_at=datetime.now(UTC),
                )
            )
            await s.commit()

        auth = AuthContext(
            tenant_id=tenant_id,
            actor_id=f"actor_{suffix}",
            role=Role.TENANT_ADMIN,
            scopes=["config:write", "verify:read"],
        )

        from unittest.mock import patch

        async with db_session.get_tenant_session(tenant_id) as session:
            # 1. Register server
            create_req = MCPServerCreateRequest(
                name="Production MCP Server",
                description="Governed external analytics MCP server",
                transport_type=MCPServerTransport.HTTP_STREAM,
                connection_config={"url": "https://analytics.example.com/mcp"},
                permitted_capabilities=["analytics:query", "analytics:export"],
                egress_allowlist=["analytics.example.com"],
                timeout_seconds=25,
            )
            with patch("services.mcp_registry_service.validate_safe_provider_url", return_value="https://analytics.example.com/mcp"):
                server_res = await mcp_registry_service.register_server(
                    auth, create_req, session=session
                )
            assert server_res.id is not None
            assert server_res.trust_status == MCPTrustStatus.PENDING_APPROVAL.value

            # 2. Update trust status to TRUSTED
            trusted_res = await mcp_registry_service.set_trust_status(
                auth,
                server_res.id,
                MCPTrustStatusUpdateRequest(
                    trust_status=MCPTrustStatus.TRUSTED,
                    reason="Security review completed and approved",
                ),
                session=session,
            )
            assert trusted_res.trust_status == MCPTrustStatus.TRUSTED.value

            # 3. Synchronize discovered tools via mocked MCP client
            mock_discovered = [
                MCPDiscoveredTool(
                    name="run_query",
                    description="Execute governed analytics query",
                    namespaced_name=f"{server_res.id}:run_query",
                    schema_fingerprint="abc123def456",
                    input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                    required_capability="analytics:query",
                )
            ]
            mcp_registry_service.mcp_client.list_tools = AsyncMock(return_value=mock_discovered)
            sync_res = await mcp_registry_service.discover_and_sync_tools(
                auth, server_res.id, session=session
            )
            assert sync_res.tools_registered == 1
            assert len(sync_res.tools_discovered) == 1
            assert sync_res.tools_discovered[0].name == "run_query"
            assert sync_res.tools_discovered[0].namespaced_name == f"{server_res.id}:run_query"
            assert sync_res.tools_discovered[0].required_capability == "analytics:query"

            # 4. Suspend server and verify tool is deactivated
            suspended_res = await mcp_registry_service.set_trust_status(
                auth,
                server_res.id,
                MCPTrustStatusUpdateRequest(
                    trust_status=MCPTrustStatus.SUSPENDED,
                    reason="Investigating anomalies",
                ),
                session=session,
            )
            assert suspended_res.trust_status == MCPTrustStatus.SUSPENDED.value

            tool_stmt = select(ToolDefinition).where(
                ToolDefinition.mcp_server_id == server_res.id,
                ToolDefinition.tenant_id == tenant_id,
            )
            tool_rows = (await session.execute(tool_stmt)).scalars().all()
            assert len(tool_rows) == 1
            assert tool_rows[0].active is False, "Tools must be deactivated when server is suspended"

            # 5. Verify audit logs were persisted in audit_logs with SHA-256 chain
            audit_stmt = text(
                """
                SELECT event_type, reason, prev_hash, chain_hash
                FROM audit_logs
                WHERE tenant_id = :tid
                ORDER BY created_at ASC
                """
            )
            audit_records = (await session.execute(audit_stmt, {"tid": tenant_id})).fetchall()
            assert len(audit_records) >= 3, "Audit logs must record registration, trust update, and tool sync"

            # Check that hash chaining is non-trivial and populated
            for record in audit_records:
                assert record.chain_hash is not None
                assert len(record.chain_hash) == 64  # SHA-256 hex string
