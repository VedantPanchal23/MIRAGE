"""SQLAlchemy ORM models for MIRAGE relational entities with PostgreSQL RLS support."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


class Tenant(Base):
    """Tenant account details and configuration."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    tier: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    scs_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    pii_detection_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    sessions: Mapped[list["VerificationSession"]] = relationship("VerificationSession", back_populates="tenant")
    alerts: Mapped[list["OperatorAlert"]] = relationship("OperatorAlert", back_populates="tenant")
    reports: Mapped[list["AuditReport"]] = relationship("AuditReport", back_populates="tenant")
    kb_documents: Mapped[list["KBDocumentRecord"]] = relationship("KBDocumentRecord", back_populates="tenant")


class User(Base):
    """Authoritative human principal registered by the control plane."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "external_subject", name="uq_users_tenant_subject"),)


class Agent(Base):
    """Tenant-scoped governed agent identity."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_autonomy_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_agents_tenant_name"),)


class ActorIdentity(Base):
    """A verifiable user, API client, service, or agent principal."""

    __tablename__ = "actor_identities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "subject", name="uq_actor_identities_tenant_subject"),)


class ApiCredential(Base):
    """Hashed, revocable API credential bound to one authoritative actor identity."""

    __tablename__ = "api_credentials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actor_identities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


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


class Budget(Base):
    """Authoritative bounds consumed by a governed AI transaction."""

    __tablename__ = "budgets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False)
    max_tool_calls: Mapped[int] = mapped_column(Integer, nullable=False)
    max_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False)
    max_risk: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class AITransaction(Base):
    """Core ledger record for the governed iterative transaction envelope."""

    __tablename__ = "ai_transactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_identity_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("actor_identities.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True
    )
    parent_transaction_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="RESTRICT"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    taint_flags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    context_sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    policy_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("policies.id", ondelete="RESTRICT"), nullable=True
    )
    budget_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("budgets.id", ondelete="RESTRICT"), nullable=True
    )
    final_disposition: Mapped[str | None] = mapped_column(String(32), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_transactions_tenant_idempotency"),)


class VerificationSession(Base):
    """Execution session for a single prompt-response verification workflow."""

    __tablename__ = "verification_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    response_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hrs_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    correction_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="sessions")
    claims: Mapped[list["ClaimRecord"]] = relationship(
        "ClaimRecord", back_populates="session", cascade="all, delete-orphan"
    )


class ClaimRecord(Base):
    """Decomposed atomic claim, associated signal scores, and classification status."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("verification_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    criticality: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    criticality_weight: Mapped[float] = mapped_column(Float, default=0.6, nullable=False)
    rav_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scs_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    nli_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ics_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vgs_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_attribution: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    session: Mapped["VerificationSession"] = relationship("VerificationSession", back_populates="claims")


class AuditLogRecord(Base):
    """Immutable audit entry with cryptographic hash chaining."""

    __tablename__ = "audit_logs"
    __table_args__ = (UniqueConstraint("tenant_id", "sequence_number", name="uq_audit_logs_tenant_sequence"),)

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sequence_number: Mapped[int | None] = mapped_column(BigInteger, default=None, nullable=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hrs_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    claims_count: Mapped[int] = mapped_column(Integer, nullable=False)
    claims_summary: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    correction_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    actor_identity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    capability_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )


class TenantAuditLedger(Base):
    """Authoritative per-tenant ledger head for serialized transaction locking and sequence tracking."""

    __tablename__ = "tenant_audit_ledgers"

    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    head_entry_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    head_chain_hash: Mapped[str] = mapped_column(String(64), default="0" * 64, nullable=False)
    sequence_number: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class AuditCheckpointRecord(Base):
    """Authoritative persistent record of verified and signed trust anchors / checkpoints."""

    __tablename__ = "audit_checkpoints"
    __table_args__ = (UniqueConstraint("tenant_id", "checkpoint_hash", name="uq_audit_checkpoints_tenant_hash"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checkpoint_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ledger_identity: Mapped[str] = mapped_column(String(64), default="audit_logs", nullable=False)
    signer_identity: Mapped[str] = mapped_column(String(128), nullable=False)
    signature: Mapped[str] = mapped_column(String(256), nullable=False)
    trust_tier: Mapped[str] = mapped_column(String(32), default="LOCAL_CHECKPOINT", nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class OperatorAlert(Base):
    """Operator notifications triggered by drift or operational metric breaches."""

    __tablename__ = "operator_alerts"

    alert_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="alerts")


class AuditReport(Base):
    """Aggregated compliance and verification audit report metadata."""

    __tablename__ = "audit_reports"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    risk_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="reports")


class KBDocumentRecord(Base):
    """Knowledge base document metadata for deduplication and tenant isolation."""

    __tablename__ = "kb_documents"
    __table_args__ = (UniqueConstraint("tenant_id", "filename", name="uq_kb_documents_tenant_filename"),)

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    chunks_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    collection_name: Mapped[str] = mapped_column(String(128), default="default_kb", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="INDEXED", nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="kb_documents")


class GovernedMemory(Base):
    """Authoritative persistent semantic and episodic memory with provenance and attestation."""

    __tablename__ = "governed_memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), default="ORGANIZATIONAL", nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attestation_status: Mapped[str] = mapped_column(String(32), default="NONE", nullable=False)
    attested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    taint: Mapped[str] = mapped_column(String(64), default="TAINT_INTERNAL", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    ttl_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class ToolDefinition(Base):
    """Governed tool registration with egress classification and capability requirements."""

    __tablename__ = "tool_registry"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
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


class OutputAssuranceRecord(Base):
    """Authoritative persistent record of Gate 4 Output Assurance evaluations."""

    __tablename__ = "output_assurance_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False)
    original_output: Mapped[str] = mapped_column(Text, nullable=False)
    final_output: Mapped[str] = mapped_column(Text, nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    final_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    conformal_bounds: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    signal_attributions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    claims_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    safety_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    factual_result: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    budget_consumed: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    tier_path: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    escalation_reasons: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    was_corrected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    correction_history: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    audit_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class OutcomeVerificationRecord(Base):
    """Authoritative persistent record of Gate 5 Outcome Assurance & Reality Verifications."""

    __tablename__ = "outcome_verification_records"
    __table_args__ = (UniqueConstraint("tenant_id", "action_id", name="uq_outcome_records_tenant_action"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("ai_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("action_contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observability_class: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    epistemic_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    verifier_adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expected_postconditions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    observed_state: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    discrepancies: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    evidence_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    reconciliation_notes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    verification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    target_environment: Mapped[str] = mapped_column(String(32), default="DEFAULT", nullable=False)
    contract_binding_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )



