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
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


class AuditLogRecord(Base):
    """Immutable audit entry with cryptographic hash chaining."""

    __tablename__ = "audit_logs"
    __table_args__ = (UniqueConstraint("tenant_id", "sequence_number", name="uq_audit_logs_tenant_sequence"),)

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"), default=1)
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

    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
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
    trust_tier: Mapped[str] = mapped_column(String(32), default="LOCAL_UNANCHORED", nullable=False)
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
