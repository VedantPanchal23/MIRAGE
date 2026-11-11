from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import Tenant


from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


class Policy(Base):
    """Versioned native typed policy definition with explicit lifecycle."""

    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "name", "version", name="uq_policies_tenant_name_version"),)


class Capability(Base):
    """Scoped, revocable authority granted to an actor or agent."""

    __tablename__ = "capabilities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identity_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("actor_identities.id", ondelete="CASCADE"), nullable=True
    )
    agent_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True)
    capability_type: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    max_autonomy_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class GovernedMemory(Base):
    """Authoritative persistent semantic and episodic memory with provenance and attestation."""

    __tablename__ = "governed_memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_category: Mapped[str] = mapped_column(String(32), default="USER_FACT", nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(64), default="GENERAL", nullable=False, index=True)
    lifecycle_state: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False, index=True)
    trust_level: Mapped[str] = mapped_column(String(32), default="PROVISIONAL", nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="ORGANIZATIONAL", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    superseded_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attestation_status: Mapped[str] = mapped_column(String(32), default="NONE", nullable=False)
    attested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    taint: Mapped[str] = mapped_column(String(64), default="TAINT_INTERNAL", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    retention_policy: Mapped[str] = mapped_column(String(32), default="STANDARD", nullable=False)
    retention_exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(64), default="USER_INPUT", nullable=False)
    source_uri: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_action_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    derivation_chain: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    propagation_status: Mapped[str] = mapped_column(String(32), default="PROPAGATED", nullable=False)
    propagation_details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    dispute_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_governed_memories_tenant_purpose", "tenant_id", "purpose"),
        Index("ix_governed_memories_tenant_lifecycle", "tenant_id", "lifecycle_state"),
        Index("ix_governed_memories_tenant_expires", "tenant_id", "expires_at"),
        Index("ix_governed_memories_tenant_category", "tenant_id", "memory_category"),
        Index(
            "uq_governed_memories_tenant_idempotency",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class MCPServer(Base):
    """Governed external MCP server registration with trust status and egress boundaries."""

    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    transport_type: Mapped[str] = mapped_column(String(32), default="STDIO", nullable=False)
    connection_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    trust_status: Mapped[str] = mapped_column(String(32), default="PENDING_APPROVAL", nullable=False, index=True)
    permitted_capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    egress_allowlist: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_mcp_servers_tenant_name"),
        Index("ix_mcp_servers_tenant_status", "tenant_id", "trust_status"),
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="mcp_servers")
    tools: Mapped[list["ToolDefinition"]] = relationship(
        "ToolDefinition", back_populates="mcp_server", cascade="all, delete-orphan"
    )


class ToolDefinition(Base):
    """Governed tool registration with egress classification and capability requirements."""

    __tablename__ = "tool_registry"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mcp_server_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    tool_type: Mapped[str] = mapped_column(String(32), default="NATIVE", nullable=False)
    egress_type: Mapped[str] = mapped_column(String(32), default="INTERNAL_ISOLATED", nullable=False)
    trust_level: Mapped[str] = mapped_column(String(32), default="VERIFIED", nullable=False)
    required_capability: Mapped[str] = mapped_column(String(128), nullable=False)
    parameters_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_tool_registry_tenant_name"),)

    mcp_server: Mapped["MCPServer | None"] = relationship("MCPServer", back_populates="tools")


class ActionContract(Base):
    """First-class AI Action Contract tracking proposed, authorized, and executed actions."""

    __tablename__ = "action_contracts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_identity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actor_identities.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True
    )
    tool_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tool_registry.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), default="EXECUTE", nullable=False)
    target_resource: Mapped[str] = mapped_column(String(512), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    normalized_parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    required_capability: Mapped[str] = mapped_column(String(128), nullable=False)
    taint_flags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blast_radius: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(String(32), default="PROPOSED", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    preconditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    postconditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    observed_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_outcome_assurance: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    outcome_contract: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    outcome_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    fencing_token: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_action_contracts_tenant_idempotency"),)


class ActionApproval(Base):
    """Governed human-in-the-loop (L4) approval ticket with parameter hash locking."""

    __tablename__ = "action_approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("action_contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    required_role: Mapped[str] = mapped_column(String(32), default="SUPER_ADMIN", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentDelegation(Base):
    """First-class durable delegation grant governing cross-agent authority attenuation."""

    __tablename__ = "agent_delegations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    parent_transaction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    child_agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    child_transaction_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    delegated_capabilities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    resource_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    max_autonomy_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delegation_depth: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_agent_delegations_tenant_idempotency"),
        Index("ix_agent_delegations_tenant_parent_txn", "tenant_id", "parent_transaction_id"),
        Index("ix_agent_delegations_tenant_child_txn", "tenant_id", "child_transaction_id"),
        Index("ix_agent_delegations_tenant_status", "tenant_id", "status"),
        Index("ix_agent_delegations_tenant_expires", "tenant_id", "expires_at"),
    )


class AgentHandoff(Base):
    """First-class durable cross-agent handoff record tracking delegation transfer."""

    __tablename__ = "agent_handoffs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_transaction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    parent_agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    child_agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    delegation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_delegations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    child_transaction_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    permitted_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    inherited_taint_flags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_agent_handoffs_tenant_idempotency"),
        Index("ix_agent_handoffs_tenant_parent_txn", "tenant_id", "parent_transaction_id"),
        Index("ix_agent_handoffs_tenant_child_agent", "tenant_id", "child_agent_id"),
        Index("ix_agent_handoffs_tenant_delegation", "tenant_id", "delegation_id"),
        Index("ix_agent_handoffs_tenant_status", "tenant_id", "status"),
    )


class ResourceLease(Base):
    """First-class durable resource lease for concurrency control and fencing token issuance."""

    __tablename__ = "resource_leases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_uri: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    holder_agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    holder_transaction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    holder_handoff_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agent_handoffs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    concurrency_mode: Mapped[str] = mapped_column(String(32), default="EXCLUSIVE", nullable=False)
    fencing_token: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACQUIRED", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        Index("ix_resource_leases_tenant_resource_status", "tenant_id", "resource_uri", "status"),
        Index("ix_resource_leases_tenant_holder_txn", "tenant_id", "holder_transaction_id"),
        Index("ix_resource_leases_tenant_expires", "tenant_id", "expires_at"),
        UniqueConstraint("tenant_id", "resource_uri", "fencing_token", name="uq_resource_leases_tenant_resource_token"),
        Index(
            "uq_resource_leases_tenant_resource_exclusive_active",
            "tenant_id",
            "resource_uri",
            unique=True,
            postgresql_where=text("status = 'ACQUIRED' AND concurrency_mode = 'EXCLUSIVE'"),
        ),
    )
