from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


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


class ModelRegistryRecord(Base):
    """Authoritative registry record for an AI model and capability profile."""

    __tablename__ = "model_registry"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    family: Mapped[str] = mapped_column(String(64), default="general", nullable=False)
    tier: Mapped[str] = mapped_column(String(32), default="CAPABLE", nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, default=128000, nullable=False)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    supports_structured_output: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supports_system_prompt: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_zero_retention: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reliability_index: Mapped[float] = mapped_column(Float, default=0.85, nullable=False)
    expected_latency_ms: Mapped[float] = mapped_column(Float, default=800.0, nullable=False)
    deployment_type: Mapped[str] = mapped_column(String(64), default="cloud_shared", nullable=False)
    privacy_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    privacy_attestation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    privacy_attestation_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    privacy_policy_version: Mapped[str | None] = mapped_column(String(32), default="v1.0", nullable=True)
    attestation_issuer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attestation_signature: Mapped[str | None] = mapped_column(String(256), nullable=True)
    endpoint_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class ModelPricingProfileRecord(Base):
    """Versioned pricing profile for a registered AI model."""

    __tablename__ = "model_pricing_profiles"
    __table_args__ = (UniqueConstraint("model_id", "effective_date", name="uq_model_pricing_model_effective"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("model_registry.id", ondelete="CASCADE"), nullable=False, index=True
    )
    effective_date: Mapped[str] = mapped_column(String(32), default="2026-01-01", nullable=False)
    currency: Mapped[str] = mapped_column(String(16), default="USD", nullable=False)
    input_cost_per_million_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    output_cost_per_million_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    cached_input_cost_per_million_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class TenantBudgetRecord(Base):
    """Authoritative tenant-level budget configuration, reserved funds, and spend ledger."""

    __tablename__ = "tenant_budgets"
    __table_args__ = (
        CheckConstraint("reserved_micros >= 0", name="ck_tenant_budget_reserved_non_negative"),
        CheckConstraint("spent_micros >= 0", name="ck_tenant_budget_spent_non_negative"),
        CheckConstraint("allocated_micros >= 0", name="ck_tenant_budget_allocated_non_negative"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    currency: Mapped[str] = mapped_column(String(16), default="USD", nullable=False)
    total_budget_micros: Mapped[int] = mapped_column(BigInteger, default=100000000, nullable=False)
    allocated_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reserved_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    spent_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reset_period: Mapped[str] = mapped_column(String(32), default="MONTHLY", nullable=False)
    reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hard_limit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class BudgetReservationRecord(Base):
    """Atomic preflight worst-case reservation bound to an AI Transaction."""

    __tablename__ = "budget_reservations"
    __table_args__ = (UniqueConstraint("tenant_id", "reservation_key", name="uq_budget_reservations_tenant_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reservation_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    amount_micros: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="RESERVED", nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    selected_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TransactionCostRecord(Base):
    """Itemized audit record of durable billable cost incurred by an AI Transaction."""

    __tablename__ = "transaction_cost_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "transaction_id", "attempt_number", name="uq_transaction_cost_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    pricing_profile_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    stage: Mapped[str] = mapped_column(String(64), default="PRIMARY_INFERENCE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )


class AccountingIncidentRecord(Base):
    """Authoritative durable record of accounting anomalies, drift, and post-execution failures."""

    __tablename__ = "accounting_incidents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reservation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    transaction_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expected_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    actual_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProviderInvocationRecord(Base):
    """Authoritative durable record of each downstream LLM provider dispatch attempt."""

    __tablename__ = "provider_invocations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reservation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )


class InquiryRecord(Base):
    """Enterprise contact and demo inquiries submitted via commercial storefront."""

    __tablename__ = "inquiries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    team_size: Mapped[str] = mapped_column(String(64), default="1-10", nullable=False)
    use_case: Mapped[str] = mapped_column(String(128), default="Agent Governance", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )


class WebhookSubscriptionRecord(Base):
    """Tenant-scoped outbound webhook subscription for alerts and Gate 3/5 notifications."""

    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    secret_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_types: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC), nullable=False
    )
