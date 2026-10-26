"""Unit tests for SaaS Subscription and Commercial Billing Service."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Tenant, TenantBudgetRecord
from services.billing_service import BillingService
from shared.schemas.auth import AuthContext, Role
from shared.schemas.billing import (
    StripeWebhookRequest,
    SubscriptionStatus,
    SubscriptionTier,
    SubscriptionUpgradeRequest,
)


@pytest.fixture
def tenant_admin_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_fintech",
        role=Role.TENANT_ADMIN,
        user_id="fintech_admin_usr",
        identity_id="id_fintech_admin",
        principal_type="user",
        token_type="jwt",
    )


def test_get_available_plans() -> None:
    """Verify commercial plan catalog contains Developer, Business, and Enterprise tiers."""
    service = BillingService()
    plans = service.get_available_plans()
    assert len(plans) == 3

    tiers = [p.tier for p in plans]
    assert SubscriptionTier.DEVELOPER in tiers
    assert SubscriptionTier.BUSINESS in tiers
    assert SubscriptionTier.ENTERPRISE in tiers

    biz_plan = next(p for p in plans if p.tier == SubscriptionTier.BUSINESS)
    assert biz_plan.price_dollars_monthly == 299.0
    assert biz_plan.budget_ceiling_usd == 500.0
    assert biz_plan.request_quota_monthly == 50000

    ent_plan = next(p for p in plans if p.tier == SubscriptionTier.ENTERPRISE)
    assert ent_plan.price_dollars_monthly == 1499.0
    assert ent_plan.budget_ceiling_usd == 5000.0
    assert ent_plan.request_quota_monthly == 500000


@pytest.mark.asyncio
async def test_get_tenant_subscription(tenant_admin_auth: AuthContext) -> None:
    """Verify retrieving active tenant subscription, budget spend, and headroom."""
    service = BillingService()

    mock_tenant = Tenant(
        id="tenant_fintech",
        name="Fintech Corp",
        tier="business",
        status="ACTIVE",
    )
    mock_budget = TenantBudgetRecord(
        id="bg_123",
        tenant_id="tenant_fintech",
        total_budget_micros=500_000_000,
        spent_micros=25_000_000,
        reserved_micros=0,
        hard_limit=True,
    )

    mock_session = AsyncMock()
    mock_res_tenant = MagicMock()
    mock_res_tenant.scalar_one_or_none.return_value = mock_tenant

    mock_res_budget = MagicMock()
    mock_res_budget.scalar_one_or_none.return_value = mock_budget

    mock_session.execute = AsyncMock(side_effect=[mock_res_tenant, mock_res_budget])

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session
        sub = await service.get_tenant_subscription(auth=tenant_admin_auth)

        assert sub.tenant_id == "tenant_fintech"
        assert sub.current_tier == SubscriptionTier.BUSINESS
        assert sub.status == SubscriptionStatus.ACTIVE
        assert sub.monthly_budget_usd == 500.0
        assert sub.spent_budget_usd == 25.0
        assert sub.remaining_headroom_usd == 475.0
        assert len(sub.plans) == 3


@pytest.mark.asyncio
async def test_upgrade_subscription_success(tenant_admin_auth: AuthContext) -> None:
    """Verify upgrading subscription adjusts tenant tier, budget ceiling, and appends audit entry."""
    service = BillingService()

    mock_tenant = Tenant(
        id="tenant_fintech",
        name="Fintech Corp",
        tier="business",
        status="ACTIVE",
    )
    mock_budget = TenantBudgetRecord(
        id="bg_123",
        tenant_id="tenant_fintech",
        total_budget_micros=500_000_000,
        spent_micros=0,
    )

    mock_session = AsyncMock()
    mock_res_tenant = MagicMock()
    mock_res_tenant.scalar_one_or_none.return_value = mock_tenant

    mock_res_budget = MagicMock()
    mock_res_budget.scalar_one_or_none.return_value = mock_budget

    mock_session.execute = AsyncMock(side_effect=[mock_res_tenant, mock_res_budget])

    req = SubscriptionUpgradeRequest(target_tier=SubscriptionTier.ENTERPRISE)

    with patch("db.session.get_tenant_session") as mock_get_sess, \
         patch("services.audit_ledger.AuditLedgerService.append_entry", new_callable=AsyncMock) as mock_append_entry:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        resp = await service.upgrade_subscription(auth=tenant_admin_auth, req=req)

        assert resp.success is True
        assert resp.new_tier == SubscriptionTier.ENTERPRISE
        assert resp.new_budget_ceiling_usd == 5000.0
        assert mock_tenant.tier == "enterprise"
        assert mock_budget.total_budget_micros == 5_000_000_000
        mock_append_entry.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_payment_webhook() -> None:
    """Verify inbound payment webhook processor accepts valid event payloads."""
    service = BillingService()
    req = StripeWebhookRequest(
        event_id="evt_test_9941a",
        event_type="invoice.payment_succeeded",
        tenant_id="tenant_fintech",
        data={"amount_paid": 29900},
    )
    res = await service.handle_payment_webhook(req)
    assert res["processed"] is True
    assert res["status"] == "ACCEPTED"
    assert res["event_id"] == "evt_test_9941a"
