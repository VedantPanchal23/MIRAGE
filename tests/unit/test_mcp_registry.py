"""Unit tests for Governed MCP Server Registry and Lifecycle Management."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from db.models import MCPServer, Tenant, ToolDefinition
from services.mcp_client import GovernedMCPClient
from services.mcp_registry_service import MCPRegistryService
from shared.schemas.auth import AuthContext, Role
from shared.schemas.mcp import (
    MCPDiscoveredTool,
    MCPServerCreateRequest,
    MCPServerTransport,
    MCPTrustStatus,
    MCPTrustStatusUpdateRequest,
)


@pytest.fixture
def super_admin_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        role=Role.SUPER_ADMIN,
        user_id="usr_super",
        identity_id="id_super",
        principal_type="user",
        token_type="jwt",
    )


@pytest.fixture
def tenant_admin_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        role=Role.TENANT_ADMIN,
        user_id="usr_tenant_admin",
        identity_id="id_tenant_admin",
        principal_type="user",
        token_type="jwt",
    )


@pytest.fixture
def viewer_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        role=Role.VIEWER,
        user_id="usr_viewer",
        identity_id="id_viewer",
        principal_type="user",
        token_type="jwt",
    )


@pytest.mark.asyncio
async def test_register_stdio_mcp_server_success(tenant_admin_auth: AuthContext) -> None:
    """Register STDIO external MCP server in PENDING_APPROVAL status."""
    service = MCPRegistryService()
    req = MCPServerCreateRequest(
        name="Local Data Analysis Server",
        description="Subprocess analytics tools",
        transport_type=MCPServerTransport.STDIO,
        connection_config={"command": "python", "args": ["-m", "analytics_mcp"]},
        permitted_capabilities=["analytics:read", "analytics:write"],
        egress_allowlist=["python"],
        timeout_seconds=45,
    )

    mock_session = AsyncMock()
    tenant = Tenant(id="tenant_alpha", name="Alpha Corp", status="ACTIVE")
    mock_session.get.return_value = tenant

    # Name uniqueness check returns None (no existing)
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = None

    # Audit query mock
    mock_audit_res = MagicMock()
    mock_audit_res.first.return_value = ("0" * 64, 0)

    def execute_side_effect(stmt: Any) -> Any:
        stmt_str = str(stmt).lower()
        if "audit_logs" in stmt_str:
            return mock_audit_res
        return mock_res

    mock_session.execute.side_effect = execute_side_effect

    res = await service.register_server(auth=tenant_admin_auth, req=req, session=mock_session)

    assert res.name == "Local Data Analysis Server"
    assert res.transport_type == "STDIO"
    assert res.trust_status == MCPTrustStatus.PENDING_APPROVAL.value
    assert res.timeout_seconds == 45
    assert res.permitted_capabilities == ["analytics:read", "analytics:write"]
    assert mock_session.add.call_count >= 2  # MCPServer + AuditLogRecord


@pytest.mark.asyncio
async def test_register_http_mcp_server_ssrf_rejection(tenant_admin_auth: AuthContext) -> None:
    """HTTP MCP server pointing to internal loopback or metadata is strictly rejected."""
    service = MCPRegistryService()
    req = MCPServerCreateRequest(
        name="Malicious Internal Probe",
        transport_type=MCPServerTransport.HTTP_STREAM,
        connection_config={"url": "http://127.0.0.1:8080/mcp"},
    )

    mock_session = AsyncMock()
    with pytest.raises(HTTPException) as exc_info:
        await service.register_server(auth=tenant_admin_auth, req=req, session=mock_session)

    assert exc_info.value.status_code == 400
    assert "SSRF" in exc_info.value.detail or "prohibited" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_register_mcp_server_viewer_forbidden(viewer_auth: AuthContext) -> None:
    """Unprivileged VIEWER role cannot register MCP servers."""
    service = MCPRegistryService()
    req = MCPServerCreateRequest(
        name="Viewer Server",
        transport_type=MCPServerTransport.STDIO,
        connection_config={"command": "python"},
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.register_server(auth=viewer_auth, req=req, session=AsyncMock())

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_mcp_server_trust_lifecycle_transitions(tenant_admin_auth: AuthContext) -> None:
    """Test full valid trust status transitions and tool deactivation upon suspension/revocation."""
    service = MCPRegistryService()
    server = MCPServer(
        id="mcp_srv_01",
        tenant_id="tenant_alpha",
        name="Data Server",
        transport_type="STDIO",
        connection_config={"command": "python"},
        trust_status=MCPTrustStatus.PENDING_APPROVAL.value,
        timeout_seconds=30,
    )

    tool = ToolDefinition(
        id="tool_01",
        tenant_id="tenant_alpha",
        mcp_server_id="mcp_srv_01",
        name="mcp_srv_01:query_db",
        required_capability="db:read",
        active=True,
    )

    mock_session = AsyncMock()

    # 1. Transition PENDING_APPROVAL -> TRUSTED
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = server
    mock_res.scalars.return_value.all.return_value = [tool]
    mock_res.scalar.return_value = 1
    mock_audit = MagicMock()
    mock_audit.first.return_value = ("0" * 64, 1)

    def exec_side_effect(stmt: Any) -> Any:
        s_str = str(stmt).lower()
        if "audit_logs" in s_str:
            return mock_audit
        return mock_res

    mock_session.execute.side_effect = exec_side_effect

    req_trust = MCPTrustStatusUpdateRequest(
        trust_status=MCPTrustStatus.TRUSTED,
        reason="Admin approval after code review",
    )
    res_trust = await service.set_trust_status(
        auth=tenant_admin_auth, server_id="mcp_srv_01", req=req_trust, session=mock_session
    )
    assert res_trust.trust_status == "TRUSTED"
    assert server.trust_status == "TRUSTED"

    # 2. Transition TRUSTED -> SUSPENDED (deactivates tool)
    req_suspend = MCPTrustStatusUpdateRequest(
        trust_status=MCPTrustStatus.SUSPENDED,
        reason="Security anomaly investigated",
    )
    res_suspend = await service.set_trust_status(
        auth=tenant_admin_auth, server_id="mcp_srv_01", req=req_suspend, session=mock_session
    )
    assert res_suspend.trust_status == "SUSPENDED"
    assert tool.active is False  # Tool immediately deactivated (fail-closed)

    # 3. Transition SUSPENDED -> REVOKED (permanent)
    req_revoke = MCPTrustStatusUpdateRequest(
        trust_status=MCPTrustStatus.REVOKED,
        reason="Permanent server decommissioning",
    )
    res_revoke = await service.set_trust_status(
        auth=tenant_admin_auth, server_id="mcp_srv_01", req=req_revoke, session=mock_session
    )
    assert res_revoke.trust_status == "REVOKED"
    assert tool.active is False

    # 4. Attempting to transition from REVOKED is rejected
    req_revive = MCPTrustStatusUpdateRequest(
        trust_status=MCPTrustStatus.TRUSTED,
        reason="Attempting to resurrect revoked server",
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.set_trust_status(
            auth=tenant_admin_auth, server_id="mcp_srv_01", req=req_revive, session=mock_session
        )
    assert exc_info.value.status_code == 400
    assert "permanently REVOKED" in exc_info.value.detail


@pytest.mark.asyncio
async def test_discover_and_sync_tools_requires_trusted(tenant_admin_auth: AuthContext) -> None:
    """Tool discovery is denied if server is not in TRUSTED status."""
    service = MCPRegistryService()
    server = MCPServer(
        id="mcp_srv_untrusted",
        tenant_id="tenant_alpha",
        name="Untrusted Server",
        trust_status=MCPTrustStatus.PENDING_APPROVAL.value,
    )

    mock_session = AsyncMock()
    mock_res = MagicMock()
    mock_res.scalar_one_or_none.return_value = server
    mock_session.execute.return_value = mock_res

    with pytest.raises(HTTPException) as exc_info:
        await service.discover_and_sync_tools(
            auth=tenant_admin_auth, server_id="mcp_srv_untrusted", session=mock_session
        )

    assert exc_info.value.status_code == 400
    assert "Only 'TRUSTED' servers may discover tools" in exc_info.value.detail


@pytest.mark.asyncio
async def test_discover_and_sync_tools_success(tenant_admin_auth: AuthContext) -> None:
    """Synchronize discovered tools and register them in tool_registry with schema fingerprints."""
    mock_mcp_client = AsyncMock(spec=GovernedMCPClient)
    mock_mcp_client.list_tools.return_value = [
        MCPDiscoveredTool(
            name="query_records",
            namespaced_name="mcp_srv_trusted:query_records",
            description="Query corporate records",
            input_schema={"type": "object", "properties": {"table": {"type": "string"}}},
            schema_fingerprint="sha256_mock_fingerprint",
            required_capability="mcp:db:read",
        )
    ]

    service = MCPRegistryService(mcp_client=mock_mcp_client)
    server = MCPServer(
        id="mcp_srv_trusted",
        tenant_id="tenant_alpha",
        name="trusted_db_mcp",
        transport_type="STDIO",
        trust_status=MCPTrustStatus.TRUSTED.value,
        permitted_capabilities=["mcp:db:read"],
    )

    mock_session = AsyncMock()
    mock_srv_res = MagicMock()
    mock_srv_res.scalar_one_or_none.return_value = server

    mock_tool_res = MagicMock()
    mock_tool_res.scalar_one_or_none.return_value = None

    mock_audit = MagicMock()
    mock_audit.first.return_value = ("0" * 64, 1)

    call_count = 0

    def exec_side_effect(stmt: Any) -> Any:
        nonlocal call_count
        call_count += 1
        s_str = str(stmt).lower()
        if "audit_logs" in s_str:
            return mock_audit
        if call_count == 1:
            return mock_srv_res
        return mock_tool_res

    mock_session.execute.side_effect = exec_side_effect

    res = await service.discover_and_sync_tools(
        auth=tenant_admin_auth, server_id="mcp_srv_trusted", session=mock_session
    )

    assert res.server_id == "mcp_srv_trusted"
    assert len(res.tools_discovered) == 1
    assert res.tools_registered == 1
    assert res.tools_discovered[0].namespaced_name == "mcp_srv_trusted:query_records"
    assert res.tools_discovered[0].schema_fingerprint == "sha256_mock_fingerprint"
