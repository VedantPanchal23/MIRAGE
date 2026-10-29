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
    price_inr_monthly: float = 0.0
    request_quota_monthly: int
    max_concurrent_leases: int
    budget_ceiling_usd: float
    features: list[PlanFeature]
    stripe_price_id: str | None = None
    razorpay_plan_id: str | None = None


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


class StripeCheckoutSessionCreateRequest(BaseModel):
    """Request to generate a Stripe USD Checkout Session."""

    tier: SubscriptionTier
    success_url: str | None = None
    cancel_url: str | None = None


class StripeCheckoutSessionResponse(BaseModel):
    """Authoritative Stripe checkout session details."""

    session_id: str
    checkout_url: str
    publishable_key: str
    tier: SubscriptionTier
    plan_name: str
    amount_usd: float
    currency: str = "USD"


class StripePaymentVerifyRequest(BaseModel):
    """Payload sent by client to verify Stripe session payment and activate tier."""

    session_id: str
    tier: SubscriptionTier
    payment_intent_id: str | None = None


class StripePaymentVerifyResponse(BaseModel):
    """Result of verifying a Stripe transaction."""

    success: bool
    tenant_id: str
    payment_id: str
    tier: SubscriptionTier
    status: SubscriptionStatus
    new_budget_ceiling_usd: float
    invoice_id: str
    receipt_url: str | None = None
    message: str


class InvoiceReceipt(BaseModel):
    """Authoritative B2B Tax Invoice & Payment Receipt."""

    invoice_id: str
    receipt_number: str
    tenant_id: str
    customer_email: str
    tier: SubscriptionTier
    plan_name: str
    amount_usd: float
    currency: str = "USD"
    payment_method: str = "STRIPE_CARD"
    payment_id: str
    session_id: str
    issued_at: str
    status: str = "PAID"
    receipt_html: str


class RazorpayOrderCreateRequest(BaseModel):
    """Request to generate a Razorpay Indian Rupee order for UPI/Netbanking/Cards."""

    tier: SubscriptionTier
    currency: str = Field(default="INR", description="Three-letter currency code (INR)")


class RazorpayOrderResponse(BaseModel):
    """Authoritative Razorpay order details for client-side checkout integration."""

    order_id: str
    amount_paise: int
    amount_inr: float
    currency: str = "INR"
    key_id: str
    tier: SubscriptionTier
    plan_name: str
    notes: dict[str, str] = Field(default_factory=dict)


class RazorpayPaymentVerifyRequest(BaseModel):
    """Payload sent by client following successful Razorpay checkout."""

    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    tier: SubscriptionTier


class RazorpayPaymentVerifyResponse(BaseModel):
    """Result of verifying a Razorpay transaction."""

    success: bool
    tenant_id: str
    payment_id: str
    tier: SubscriptionTier
    status: SubscriptionStatus
    new_budget_ceiling_usd: float
    message: str
