"""SQLAlchemy ORM models for MIRAGE relational entities with PostgreSQL RLS support."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
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

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hrs_score: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    claims_count: Mapped[int] = mapped_column(Integer, nullable=False)
    claims_summary: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    correction_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )
