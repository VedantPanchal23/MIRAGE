"""Commercial SaaS Billing and Subscription routes for MIRAGE 3.0."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from gateway.middleware.auth import get_current_auth
from services.billing_service import billing_service
from shared.schemas.auth import AuthContext, Role
from shared.schemas.billing import (
    StripeWebhookRequest,
    SubscriptionPlanInfo,
    SubscriptionUpgradeRequest,
    SubscriptionUpgradeResponse,
    TenantSubscriptionResponse,
)

router = APIRouter(prefix="/v1/billing", tags=["Commercial SaaS Billing & Subscriptions"])


@router.get("/plans", response_model=list[SubscriptionPlanInfo])
async def list_subscription_plans() -> list[SubscriptionPlanInfo]:
    """Retrieve public commercial subscription tiers and pricing specifications."""
    return billing_service.get_available_plans()


@router.get("/subscription", response_model=TenantSubscriptionResponse)
async def get_tenant_subscription(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> TenantSubscriptionResponse:
    """Retrieve caller's active subscription tier, budget utilization, and limits."""
    return await billing_service.get_tenant_subscription(auth=auth)


@router.post("/subscribe", response_model=SubscriptionUpgradeResponse)
async def upgrade_subscription(
    req: SubscriptionUpgradeRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> SubscriptionUpgradeResponse:
    """Upgrade or modify tenant commercial subscription tier (TENANT_ADMIN or SUPER_ADMIN)."""
    if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{auth.role.value}' is not authorized to manage subscriptions. Requires TENANT_ADMIN.",
        )
    return await billing_service.upgrade_subscription(auth=auth, req=req)


@router.post("/webhook")
async def billing_webhook(req: StripeWebhookRequest) -> dict[str, str]:
    """Inbound webhook receiver for payment processor events (Stripe, LemonSqueezy, Paddle)."""
    _ = await billing_service.handle_payment_webhook(req)
    return {"status": "ok", "event_id": req.event_id}
