"""Commercial SaaS Subscription and Billing Schemas for MIRAGE 3.0."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SubscriptionTier(StrEnum):
    """Authoritative commercial subscription tiers."""
    DEVELOPER = "developer"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(StrEnum):
    """Lifecycle status of a tenant's commercial subscription."""
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class PlanFeature(BaseModel):
    """Feature item included in a plan."""
    title: str
    description: str
    included: bool = True


class SubscriptionPlanInfo(BaseModel):
    """Public specification of a commercial subscription plan."""
    tier: SubscriptionTier
    name: str
    tagline: str
    price_dollars_monthly: float
    request_quota_monthly: int
    max_concurrent_leases: int
    budget_ceiling_usd: float
    features: list[PlanFeature]
    stripe_price_id: str | None = None


class TenantSubscriptionResponse(BaseModel):
    """Active subscription status and usage for a tenant."""
    tenant_id: str
    current_tier: SubscriptionTier
    status: SubscriptionStatus
    monthly_budget_usd: float
    spent_budget_usd: float
    remaining_headroom_usd: float
    current_cycle_requests: int
    monthly_request_quota: int
    max_concurrent_leases: int
    plans: list[SubscriptionPlanInfo]


class SubscriptionUpgradeRequest(BaseModel):
    """Request to subscribe or transition subscription tiers."""
    target_tier: SubscriptionTier
    payment_method_id: str | None = Field(
        default=None,
        description="Optional payment method ID (e.g. pm_card_visa or test token)",
    )
    return_url: str | None = Field(
        default=None,
        description="Redirect URL after external checkout session",
    )


class SubscriptionUpgradeResponse(BaseModel):
    """Result of a subscription change."""
    success: bool
    tenant_id: str
    previous_tier: SubscriptionTier
    new_tier: SubscriptionTier
    status: SubscriptionStatus
    new_budget_ceiling_usd: float
    message: str
    checkout_url: str | None = None


class StripeWebhookRequest(BaseModel):
    """Inbound webhook event from payment processor."""
    event_id: str
    event_type: str
    tenant_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
