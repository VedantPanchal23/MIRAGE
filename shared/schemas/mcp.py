"""Schemas for Governed MCP (Model Context Protocol) Server Registry & Tools."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MCPServerTransport(StrEnum):
    """Supported transport mechanisms for external MCP servers."""

    STDIO = "STDIO"
    HTTP_STREAM = "HTTP_STREAM"


class MCPTrustStatus(StrEnum):
    """Lifecycle trust status for registered external MCP servers."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    TRUSTED = "TRUSTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class MCPServerCreateRequest(BaseModel):
    """Payload to register an external MCP server."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, description="Unique server name within tenant")
    description: str = Field(default="", max_length=1024, description="Description of server purpose")
    transport_type: MCPServerTransport = Field(
        default=MCPServerTransport.STDIO,
        description="Transport mechanism (STDIO or HTTP_STREAM)",
    )
    connection_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Transport-specific configuration (command/args for STDIO, url/headers for HTTP_STREAM)",
    )
    permitted_capabilities: list[str] = Field(
        default_factory=list,
        description="Explicit capabilities that tools from this server are allowed to claim",
    )
    egress_allowlist: list[str] = Field(
        default_factory=list,
        description="Permitted destination CIDRs/domains for HTTP or executables for STDIO",
    )
    timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        description="Execution timeout in seconds for operations on this server",
    )


class MCPServerUpdateRequest(BaseModel):
    """Payload to update an external MCP server."""

    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=1024)
    connection_config: dict[str, Any] | None = None
    permitted_capabilities: list[str] | None = None
    egress_allowlist: list[str] | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)


class MCPTrustStatusUpdateRequest(BaseModel):
    """Payload to transition trust status of an MCP server."""

    model_config = ConfigDict(extra="forbid")

    trust_status: MCPTrustStatus = Field(description="Target trust status")
    reason: str = Field(min_length=3, max_length=512, description="Audit justification for transition")


class MCPServerResponse(BaseModel):
    """Safe public representation of a registered MCP server."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    description: str
    transport_type: str
    connection_config: dict[str, Any]
    trust_status: str
    permitted_capabilities: list[str]
    egress_allowlist: list[str]
    timeout_seconds: int
    tool_count: int = 0
    created_at: datetime
    updated_at: datetime


class MCPServerListResponse(BaseModel):
    """Paginated list of registered MCP servers."""

    items: list[MCPServerResponse]
    total: int


class MCPDiscoveredTool(BaseModel):
    """Tool definition discovered via MCP tools/list protocol."""

    name: str = Field(description="Raw remote tool name")
    namespaced_name: str = Field(description="Namespaced tool name: {server_id}:{tool_name}")
    description: str = Field(default="")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    schema_fingerprint: str = Field(description="SHA-256 fingerprint of the parameter schema")
    required_capability: str = Field(description="Assigned required capability")


class MCPToolDiscoveryResult(BaseModel):
    """Outcome of MCP tool discovery and synchronization."""

    server_id: str
    server_name: str
    tools_discovered: list[MCPDiscoveredTool]
    tools_registered: int
