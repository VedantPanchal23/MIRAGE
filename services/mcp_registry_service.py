"""Governed External MCP Server Registry and Lifecycle Service.

Provides:
1. Registration, retrieval, updating, and revocation of external MCP servers.
2. Multi-tenant isolation with PostgreSQL Row-Level Security (RLS).
3. Trust status transitions (PENDING_APPROVAL -> TRUSTED, SUSPENDED, REVOKED).
4. Synchronized tool discovery, schema fingerprinting, and namespaced registration in tool_registry.
5. Cryptographic audit logging with SHA-256 hash chains.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import AuditLogRecord, MCPServer, Tenant, ToolDefinition
from services.mcp_client import GovernedMCPClient
from services.providers.ssrf_validator import SSRFValidationError, validate_safe_provider_url
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.mcp import (
    MCPServerCreateRequest,
    MCPServerListResponse,
    MCPServerResponse,
    MCPServerTransport,
    MCPToolDiscoveryResult,
    MCPTrustStatus,
    MCPTrustStatusUpdateRequest,
)
from shared.schemas.tenant import TenantStatus

logger = get_logger("mcp_registry_service")


class MCPRegistryService:
    """Authoritative registry and governance service for external MCP servers."""

    def __init__(self, mcp_client: GovernedMCPClient | None = None) -> None:
        self.mcp_client = mcp_client or GovernedMCPClient()

    async def register_server(
        self,
        auth: AuthContext,
        req: MCPServerCreateRequest,
        session: AsyncSession | None = None,
    ) -> MCPServerResponse:
        """Register an external MCP server in PENDING_APPROVAL status."""
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only SUPER_ADMIN or TENANT_ADMIN can register external MCP servers",
            )

        tenant_id = auth.tenant_id
        now = datetime.now(UTC)

        # Validate transport and connection configuration
        if req.transport_type == MCPServerTransport.HTTP_STREAM:
            url = req.connection_config.get("url")
            if not url or not isinstance(url, str):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="HTTP_STREAM transport requires a valid 'url' in connection_config",
                )
            try:
                validate_safe_provider_url(url, allow_local=False, resolve_dns=True)
            except SSRFValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Connection URL rejected by SSRF egress policy: {exc}",
                ) from exc
        elif req.transport_type == MCPServerTransport.STDIO:
            command = req.connection_config.get("command")
            if not command or not isinstance(command, str):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="STDIO transport requires a valid 'command' executable in connection_config",
                )

        server_id = f"mcp_srv_{uuid.uuid4().hex[:12]}"

        async def _execute(s: AsyncSession) -> MCPServerResponse:
            # Verify tenant status
            tenant = await s.get(Tenant, tenant_id)
            if not tenant:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant '{tenant_id}' not found")
            if tenant.status != TenantStatus.ACTIVE.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Cannot register MCP server: tenant '{tenant_id}' is {tenant.status.lower()}",
                )

            # Check uniqueness of server name within tenant
            existing_stmt = select(MCPServer).where(
                MCPServer.tenant_id == tenant_id,
                MCPServer.name == req.name,
            )
            existing = (await s.execute(existing_stmt)).scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"MCP server with name '{req.name}' already registered for tenant '{tenant_id}'",
                )

            server = MCPServer(
                id=server_id,
                tenant_id=tenant_id,
                name=req.name,
                description=req.description,
                transport_type=req.transport_type.value,
                connection_config=req.connection_config,
                trust_status=MCPTrustStatus.PENDING_APPROVAL.value,
                permitted_capabilities=req.permitted_capabilities,
                egress_allowlist=req.egress_allowlist,
                timeout_seconds=req.timeout_seconds,
                created_at=now,
                updated_at=now,
            )
            s.add(server)
            await s.flush()

            # Record audit event
            await self._record_audit(
                session=s,
                tenant_id=tenant_id,
                action="MCP_SERVER_REGISTERED",
                actor_id=auth.identity_id or auth.user_id,
                details={
                    "server_id": server_id,
                    "name": req.name,
                    "transport_type": req.transport_type.value,
                    "trust_status": MCPTrustStatus.PENDING_APPROVAL.value,
                },
            )
            await s.flush()

            return self._to_response(server, tool_count=0)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(tenant_id) as s:
            return await _execute(s)

    async def get_server(
        self,
        auth: AuthContext,
        server_id: str,
        session: AsyncSession | None = None,
    ) -> MCPServerResponse:
        """Retrieve MCP server details by ID under tenant isolation."""

        async def _execute(s: AsyncSession) -> MCPServerResponse:
            stmt = select(MCPServer).where(
                MCPServer.tenant_id == auth.tenant_id,
                MCPServer.id == server_id,
            )
            server = (await s.execute(stmt)).scalar_one_or_none()
            if not server:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"MCP server '{server_id}' not found",
                )

            count_stmt = select(func.count(ToolDefinition.id)).where(
                ToolDefinition.tenant_id == auth.tenant_id,
                ToolDefinition.mcp_server_id == server_id,
            )
            tool_count = (await s.execute(count_stmt)).scalar() or 0
            return self._to_response(server, tool_count=tool_count)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def list_servers(
        self,
        auth: AuthContext,
        limit: int = 50,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> MCPServerListResponse:
        """List registered MCP servers for the tenant."""

        async def _execute(s: AsyncSession) -> MCPServerListResponse:
            total_stmt = select(func.count(MCPServer.id)).where(MCPServer.tenant_id == auth.tenant_id)
            total = (await s.execute(total_stmt)).scalar() or 0

            list_stmt = (
                select(MCPServer)
                .where(MCPServer.tenant_id == auth.tenant_id)
                .order_by(MCPServer.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            servers = (await s.execute(list_stmt)).scalars().all()

            responses: list[MCPServerResponse] = []
            for srv in servers:
                count_stmt = select(func.count(ToolDefinition.id)).where(
                    ToolDefinition.tenant_id == auth.tenant_id,
                    ToolDefinition.mcp_server_id == srv.id,
                )
                tool_count = (await s.execute(count_stmt)).scalar() or 0
                responses.append(self._to_response(srv, tool_count=tool_count))

            return MCPServerListResponse(items=responses, total=total)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def set_trust_status(
        self,
        auth: AuthContext,
        server_id: str,
        req: MCPTrustStatusUpdateRequest,
        session: AsyncSession | None = None,
    ) -> MCPServerResponse:
        """Transition MCP server trust status and enforce tool deactivation upon suspension/revocation."""
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only SUPER_ADMIN or TENANT_ADMIN can modify MCP server trust status",
            )

        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> MCPServerResponse:
            stmt = (
                select(MCPServer)
                .where(
                    MCPServer.tenant_id == auth.tenant_id,
                    MCPServer.id == server_id,
                )
                .with_for_update()
            )
            server = (await s.execute(stmt)).scalar_one_or_none()
            if not server:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"MCP server '{server_id}' not found",
                )

            current_status = server.trust_status
            target_status = req.trust_status.value

            # Terminal revocation check
            if current_status == MCPTrustStatus.REVOKED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"MCP server '{server_id}' is permanently REVOKED and cannot be modified",
                )

            # Valid transitions:
            # PENDING_APPROVAL -> TRUSTED, REVOKED
            # TRUSTED -> SUSPENDED, REVOKED
            # SUSPENDED -> TRUSTED, REVOKED
            valid_transitions = {
                MCPTrustStatus.PENDING_APPROVAL.value: {MCPTrustStatus.TRUSTED.value, MCPTrustStatus.REVOKED.value},
                MCPTrustStatus.TRUSTED.value: {MCPTrustStatus.SUSPENDED.value, MCPTrustStatus.REVOKED.value},
                MCPTrustStatus.SUSPENDED.value: {MCPTrustStatus.TRUSTED.value, MCPTrustStatus.REVOKED.value},
            }

            if target_status not in valid_transitions.get(current_status, set()):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid trust status transition: '{current_status}' -> '{target_status}'",
                )

            server.trust_status = target_status
            server.updated_at = now

            # If SUSPENDED or REVOKED: immediately deactivate all registered tools for this server
            if target_status in {MCPTrustStatus.SUSPENDED.value, MCPTrustStatus.REVOKED.value}:
                tools_stmt = select(ToolDefinition).where(
                    ToolDefinition.tenant_id == auth.tenant_id,
                    ToolDefinition.mcp_server_id == server_id,
                )
                tools = (await s.execute(tools_stmt)).scalars().all()
                for tool in tools:
                    tool.active = False
                    tool.updated_at = now
                logger.info(
                    "Deactivated %d tools for MCP server %s due to %s",
                    len(tools),
                    server_id,
                    target_status,
                )
            elif target_status == MCPTrustStatus.TRUSTED.value:
                # Re-activate tools
                tools_stmt = select(ToolDefinition).where(
                    ToolDefinition.tenant_id == auth.tenant_id,
                    ToolDefinition.mcp_server_id == server_id,
                )
                tools = (await s.execute(tools_stmt)).scalars().all()
                for tool in tools:
                    tool.active = True
                    tool.updated_at = now

            await self._record_audit(
                session=s,
                tenant_id=auth.tenant_id,
                action="MCP_SERVER_TRUST_UPDATED",
                actor_id=auth.identity_id or auth.user_id,
                details={
                    "server_id": server_id,
                    "previous_status": current_status,
                    "target_status": target_status,
                    "reason": req.reason,
                },
            )
            await s.flush()

            count_stmt = select(func.count(ToolDefinition.id)).where(
                ToolDefinition.tenant_id == auth.tenant_id,
                ToolDefinition.mcp_server_id == server_id,
            )
            tool_count = (await s.execute(count_stmt)).scalar() or 0
            return self._to_response(server, tool_count=tool_count)

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def discover_and_sync_tools(
        self,
        auth: AuthContext,
        server_id: str,
        session: AsyncSession | None = None,
    ) -> MCPToolDiscoveryResult:
        """Discover tools from remote MCP server and register them in tool_registry under tenant isolation."""
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only SUPER_ADMIN or TENANT_ADMIN can discover and register MCP tools",
            )

        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> MCPToolDiscoveryResult:
            stmt = select(MCPServer).where(
                MCPServer.tenant_id == auth.tenant_id,
                MCPServer.id == server_id,
            )
            server = (await s.execute(stmt)).scalar_one_or_none()
            if not server:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"MCP server '{server_id}' not found",
                )

            if server.trust_status != MCPTrustStatus.TRUSTED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Cannot discover tools: MCP server '{server_id}' status is '{server.trust_status}'. "
                    f"Only '{MCPTrustStatus.TRUSTED.value}' servers may discover tools.",
                )

            # Query remote server via GovernedMCPClient
            discovered_tools = await self.mcp_client.list_tools(server)

            registered_count = 0
            for d_tool in discovered_tools:
                # Upsert into tool_registry
                exist_stmt = select(ToolDefinition).where(
                    ToolDefinition.tenant_id == auth.tenant_id,
                    ToolDefinition.name == d_tool.namespaced_name,
                )
                existing_tool = (await s.execute(exist_stmt)).scalar_one_or_none()

                if existing_tool:
                    existing_tool.description = d_tool.description
                    existing_tool.parameters_schema = d_tool.input_schema
                    existing_tool.required_capability = d_tool.required_capability
                    existing_tool.config = {
                        "schema_fingerprint": d_tool.schema_fingerprint,
                        "raw_tool_name": d_tool.name,
                    }
                    existing_tool.active = True
                    existing_tool.updated_at = now
                else:
                    new_tool = ToolDefinition(
                        id=f"tool_{uuid.uuid4().hex[:12]}",
                        tenant_id=auth.tenant_id,
                        mcp_server_id=server.id,
                        name=d_tool.namespaced_name,
                        description=d_tool.description,
                        tool_type="MCP",
                        egress_type=(
                            "EXTERNAL_NETWORK"
                            if server.transport_type == MCPServerTransport.HTTP_STREAM.value
                            else "LOCAL_SUBPROCESS"
                        ),
                        trust_level="UNTRUSTED",
                        required_capability=d_tool.required_capability,
                        parameters_schema=d_tool.input_schema,
                        config={
                            "schema_fingerprint": d_tool.schema_fingerprint,
                            "raw_tool_name": d_tool.name,
                        },
                        active=True,
                        created_at=now,
                        updated_at=now,
                    )
                    s.add(new_tool)
                    registered_count += 1

            await self._record_audit(
                session=s,
                tenant_id=auth.tenant_id,
                action="MCP_TOOLS_SYNCHRONIZED",
                actor_id=auth.identity_id or auth.user_id,
                details={
                    "server_id": server_id,
                    "tools_discovered": len(discovered_tools),
                    "new_tools_registered": registered_count,
                },
            )
            await s.flush()

            return MCPToolDiscoveryResult(
                server_id=server.id,
                server_name=server.name,
                tools_discovered=discovered_tools,
                tools_registered=registered_count,
            )

        if session is not None:
            return await _execute(session)
        async with db_session.get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def _record_audit(
        self,
        session: AsyncSession,
        tenant_id: str,
        action: str,
        actor_id: str,
        details: dict[str, Any],
    ) -> None:
        """Record an MCP audit event in the cryptographic hash chain."""
        now = datetime.now(UTC)
        seq_stmt = (
            select(AuditLogRecord.chain_hash, AuditLogRecord.sequence_number)
            .where(AuditLogRecord.tenant_id == tenant_id)
            .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
            .limit(1)
        )
        res = await session.execute(seq_stmt)
        latest_row = res.first()
        prev_hash = latest_row[0] if latest_row and latest_row[0] is not None else ("0" * 64)
        prev_seq = latest_row[1] if latest_row and len(latest_row) > 1 and latest_row[1] is not None else 0
        seq = prev_seq + 1
        entry_id = f"aud_{uuid.uuid4().hex}"
        chain_hash = compute_sha256(f"{prev_hash}:{entry_id}:{action}:{now.isoformat()}")

        rec = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=seq,
            session_id=f"sess_{tenant_id}",
            trace_id="control-plane",
            prompt_hash=compute_sha256(""),
            response_hash=compute_sha256(""),
            hrs_score=0.0,
            risk_tier="CONTROL_PLANE",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type=f"MCP_{action}",
            actor_identity_id=actor_id,
            transaction_id=None,
            decision="ALLOWED",
            policy_reference="mcp_governance_policy",
            reason=f"MCP lifecycle operation: {action}",
            event_payload=details,
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
        session.add(rec)

    def _to_response(self, server: MCPServer, tool_count: int) -> MCPServerResponse:
        """Format safe public response with redacted secret tokens."""
        clean_config = dict(server.connection_config or {})
        if "auth_token" in clean_config and clean_config["auth_token"]:
            clean_config["auth_token"] = "REDACTED"
        if "env" in clean_config and isinstance(clean_config["env"], dict):
            # Redact any env vars containing secret keywords
            clean_env = {}
            for k, v in clean_config["env"].items():
                if any(sec in k.upper() for sec in ("KEY", "SECRET", "PASS", "TOKEN")):
                    clean_env[k] = "REDACTED"
                else:
                    clean_env[k] = v
            clean_config["env"] = clean_env

        return MCPServerResponse(
            id=server.id,
            tenant_id=server.tenant_id,
            name=server.name,
            description=server.description or "",
            transport_type=server.transport_type,
            connection_config=clean_config,
            trust_status=server.trust_status,
            permitted_capabilities=server.permitted_capabilities or [],
            egress_allowlist=server.egress_allowlist or [],
            timeout_seconds=server.timeout_seconds or 30,
            tool_count=tool_count,
            created_at=server.created_at or datetime.now(UTC),
            updated_at=server.updated_at or datetime.now(UTC),
        )


mcp_registry_service = MCPRegistryService()
