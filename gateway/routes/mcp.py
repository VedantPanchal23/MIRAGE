"""API routes for Governed MCP (Model Context Protocol) Server Registry & Tools."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from gateway.middleware.auth import get_current_auth
from services.mcp_registry_service import MCPRegistryService
from shared.schemas.auth import AuthContext
from shared.schemas.mcp import (
    MCPServerCreateRequest,
    MCPServerListResponse,
    MCPServerResponse,
    MCPToolDiscoveryResult,
    MCPTrustStatusUpdateRequest,
)

router = APIRouter(prefix="/v1/mcp", tags=["Governed MCP Integration"])
mcp_registry_service = MCPRegistryService()


@router.post("/servers", response_model=MCPServerResponse, status_code=status.HTTP_201_CREATED)
async def register_mcp_server(
    req: MCPServerCreateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> MCPServerResponse:
    """Register an external MCP server in PENDING_APPROVAL status (TENANT_ADMIN or SUPER_ADMIN)."""
    return await mcp_registry_service.register_server(auth=auth, req=req)


@router.get("/servers", response_model=MCPServerListResponse)
async def list_mcp_servers(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MCPServerListResponse:
    """List registered MCP servers for the authenticated tenant."""
    return await mcp_registry_service.list_servers(auth=auth, limit=limit, offset=offset)


@router.get("/servers/{server_id}", response_model=MCPServerResponse)
async def get_mcp_server(
    server_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> MCPServerResponse:
    """Retrieve details for a specific MCP server under tenant isolation."""
    return await mcp_registry_service.get_server(auth=auth, server_id=server_id)


@router.put("/servers/{server_id}/trust", response_model=MCPServerResponse)
async def update_mcp_server_trust(
    server_id: str,
    req: MCPTrustStatusUpdateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> MCPServerResponse:
    """Transition MCP server trust status (PENDING_APPROVAL -> TRUSTED, SUSPENDED, REVOKED)."""
    return await mcp_registry_service.set_trust_status(auth=auth, server_id=server_id, req=req)


@router.post("/servers/{server_id}/discover", response_model=MCPToolDiscoveryResult)
async def discover_mcp_tools(
    server_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> MCPToolDiscoveryResult:
    """Discover tools from a TRUSTED MCP server, calculate schema fingerprints, and register in tool_registry."""
    return await mcp_registry_service.discover_and_sync_tools(auth=auth, server_id=server_id)
