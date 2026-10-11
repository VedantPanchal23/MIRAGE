"""Typed contracts for MIRAGE 3.0 Budget Management, Reservations, and Cost Records."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class BudgetResetPeriod(StrEnum):
    """Intervals for recurring tenant budget refreshes."""

    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    NEVER = "NEVER"


class ReservationStatus(StrEnum):
    """Lifecycle state of an atomic preflight budget reservation."""

    RESERVED = "RESERVED"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class TenantBudget(BaseModel):
    """Authoritative tenant-level cumulative and period budget ledger."""

    id: str = Field(..., description="Unique budget ID")
    tenant_id: str = Field(..., description="Target tenant ID")
    currency: str = Field(default="USD", description="Billing currency")
    total_budget_micros: int = Field(..., ge=0, description="Total budget limit in micros ($1 = 1,000,000 micros)")
    allocated_micros: int = Field(default=0, ge=0, description="Allocated budget in micros")
    reserved_micros: int = Field(default=0, ge=0, description="Currently reserved in-flight micros")
    spent_micros: int = Field(default=0, ge=0, description="Durable finalized spend in micros")
    available_micros: int = Field(default=0, description="Headroom: total - spent - reserved")
    reset_period: BudgetResetPeriod = Field(default=BudgetResetPeriod.MONTHLY)
    reset_at: datetime | None = Field(default=None)
    hard_limit: bool = Field(default=True, description="If True, blocks operations when available_micros <= 0")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TenantBudgetUpdateRequest(BaseModel):
    """Payload to configure or modify a tenant's budget bounds."""

    total_budget_micros: int = Field(..., ge=0, description="New total budget in micros")
    hard_limit: bool = Field(default=True, description="Strict enforcement flag")
    is_active: bool = Field(default=True, description="Whether budget is enabled")
    reset_period: BudgetResetPeriod = Field(default=BudgetResetPeriod.MONTHLY)


class BudgetReservationRequest(BaseModel):
    """Preflight worst-case reservation request before LLM inference or verification."""

    tenant_id: str = Field(..., description="Tenant requesting inference")
    transaction_id: str = Field(..., description="Correlated AI Transaction ID")
    estimated_cost_micros: int = Field(..., gt=0, description="Upper-bound cost reservation in micros")
    reservation_key: str = Field(..., description="Idempotency key for this reservation")
    timeout_seconds: int = Field(default=300, ge=10, le=3600, description="Reservation TTL before expiration")


class BudgetReservation(BaseModel):
    """Active or finalized reservation record."""

    id: str = Field(..., description="Reservation ID")
    tenant_id: str = Field(..., description="Tenant ID")
    transaction_id: str = Field(..., description="AI Transaction ID")
    reservation_key: str = Field(..., description="Reservation idempotency key")
    amount_micros: int = Field(..., ge=0, description="Reserved amount in micros")
    status: ReservationStatus = Field(default=ReservationStatus.RESERVED)
    expires_at: datetime = Field(...)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    settled_at: datetime | None = Field(default=None)


class BudgetSettlementRequest(BaseModel):
    """Final settlement payload after actual token usage is reported by provider."""

    reservation_id: str = Field(..., description="Reservation ID to settle")
    actual_cost_micros: int = Field(..., ge=0, description="Final actual cost in micros")
    model_id: str = Field(..., description="Model executed")
    provider: str = Field(..., description="Provider executed")
    prompt_tokens: int = Field(..., ge=0, description="Input prompt tokens consumed")
    completion_tokens: int = Field(..., ge=0, description="Output tokens generated")
    cached_tokens: int = Field(default=0, ge=0, description="Tokens read from prompt cache")
    stage: str = Field(default="PRIMARY_INFERENCE", description="Assurance stage incurring cost")


class TransactionCostRecordSchema(BaseModel):
    """Itemized audit record of billable execution cost for a transaction."""

    id: str = Field(..., description="Cost record ID")
    tenant_id: str = Field(..., description="Tenant ID")
    transaction_id: str = Field(..., description="AI Transaction ID")
    model_id: str = Field(..., description="Model ID")
    provider: str = Field(..., description="Provider name")
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    cached_tokens: int = Field(default=0, ge=0)
    cost_micros: int = Field(..., ge=0, description="Final cost in micros")
    stage: str = Field(default="PRIMARY_INFERENCE")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
