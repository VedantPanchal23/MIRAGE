from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .core import Tenant


from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


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
    execution_trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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
    evidence_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    evidence_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    escalation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


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
