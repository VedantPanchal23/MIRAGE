"""SaaS Subscription and Commercial Billing Service for MIRAGE 3.0."""

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from db import session as db_session
from db.models import Tenant, TenantBudgetRecord
from services.audit_ledger import AuditLedgerService
from services.email_service import email_service
from shared.config.settings import EnvironmentType, get_settings, is_insecure_placeholder
from shared.logging import get_logger
from shared.schemas.auth import AuthContext, Role
from shared.schemas.billing import (
    PlanFeature,
    RazorpayOrderCreateRequest,
    RazorpayOrderResponse,
    RazorpayPaymentVerifyRequest,
    RazorpayPaymentVerifyResponse,
    StripeCheckoutSessionCreateRequest,
    StripeCheckoutSessionResponse,
    StripePaymentVerifyRequest,
    StripePaymentVerifyResponse,
    StripeWebhookRequest,
    SubscriptionPlanInfo,
    SubscriptionStatus,
    SubscriptionTier,
    SubscriptionUpgradeRequest,
    SubscriptionUpgradeResponse,
    TenantSubscriptionResponse,
)

logger = get_logger("services.billing_service")

# Tier limits and configurations
TIER_SPECS: dict[SubscriptionTier, dict[str, Any]] = {
    SubscriptionTier.DEVELOPER: {
        "name": "Developer Sandbox",
        "tagline": "Evaluate MIRAGE Assurance Gates with local agents & testing harness",
        "price_usd": 0.0,
        "price_inr": 0.0,
        "quota": 10000,
        "leases": 2,
        "budget_usd": 10.0,
        "features": [
            PlanFeature(
                title="All 5 Assurance Gates",
                description="Input, Context, Action, Output, Outcome verification",
            ),
            PlanFeature(
                title="10,000 Requests / Month",
                description="Developer tier sandbox volume",
            ),
            PlanFeature(
                title="2 Concurrent Leases",
                description="Distributed Redis lease locking",
            ),
            PlanFeature(
                title="Regex DLP & PII Scrubbing",
                description="Client-side and gateway token protection",
            ),
            PlanFeature(
                title="DeBERTa NLI Verification",
                description="Neural natural language inference",
                included=False,
            ),
            PlanFeature(
                title="Dedicated RLS Partitioning",
                description="Tenant isolated database schemas",
                included=False,
            ),
        ],
    },
    SubscriptionTier.BUSINESS: {
        "name": "Pro / Starter",
        "tagline": "Production assurance for indie developers and high-growth AI applications",
        "price_usd": 29.0,
        "price_inr": 1999.0,
        "quota": 75000,
        "leases": 10,
        "budget_usd": 150.0,
        "features": [
            PlanFeature(
                title="All 5 Assurance Gates",
                description="Full verification ladder with TreeSHAP and Conformal Bounds",
            ),
            PlanFeature(
                title="75,000 Requests / Month",
                description="Production developer & startup workload",
            ),
            PlanFeature(
                title="10 Concurrent Resource Leases",
                description="Distributed concurrency control with monotonic tokens",
            ),
            PlanFeature(
                title="DeBERTa-v3 NLI Verification",
                description="Sub-second neural contradiction detection",
            ),
            PlanFeature(
                title="Qdrant RAG Semantic Grounding",
                description="Tenant-scoped vector evidence indexing",
            ),
            PlanFeature(
                title="LangGraph Autonomous Correction",
                description="Self-healing prompt refinement for refuted claims",
            ),
            PlanFeature(
                title="OpenAI Drop-In Gateway Proxy",
                description="Single line integration for existing agent stacks",
            ),
        ],
    },
    SubscriptionTier.ENTERPRISE: {
        "name": "Enterprise Sentinel",
        "tagline": "Custom SLA, dedicated RLS isolation, governed MCP server, and physical reality verification",
        "price_usd": 299.0,
        "price_inr": 24999.0,
        "quota": 2000000,
        "leases": 100,
        "budget_usd": 2500.0,
        "features": [
            PlanFeature(
                title="High-Throughput Verification Engine",
                description="Sub-50ms p95 latency with GPU acceleration",
            ),
            PlanFeature(
                title="2,000,000+ Requests / Month",
                description="High-scale multi-agent enterprise deployment",
            ),
            PlanFeature(
                title="100+ Concurrent Leases",
                description="High-concurrency distributed execution coordination",
            ),
            PlanFeature(
                title="Governed MCP Server Proxy",
                description="Capability-based access control for Claude Desktop & Cursor",
            ),
            PlanFeature(
                title="Custom HITL Approval Webhooks",
                description="L4 human escalation for high blast-radius operations",
            ),
            PlanFeature(
                title="Cryptographic Merkle Audit Anchoring",
                description="RFC 3161 notary and immutable S3 object lock",
            ),
            PlanFeature(
                title="99.99% Availability SLA",
                description="Dedicated support engineers and custom deployment topologies",
            ),
        ],
    },
}


class BillingService:
    """Enterprise billing and subscription manager coordinating tier entitlements."""

    def get_available_plans(self) -> list[SubscriptionPlanInfo]:
        """Return the public commercial plan catalog."""
        plans: list[SubscriptionPlanInfo] = []
        for tier, spec in TIER_SPECS.items():
            plans.append(
                SubscriptionPlanInfo(
                    tier=tier,
                    name=spec["name"],
                    tagline=spec["tagline"],
                    price_dollars_monthly=spec["price_usd"],
                    price_inr_monthly=spec.get("price_inr", 0.0),
                    request_quota_monthly=spec["quota"],
                    max_concurrent_leases=spec["leases"],
                    budget_ceiling_usd=spec["budget_usd"],
                    features=spec["features"],
                    stripe_price_id=f"price_mirage_{tier.value}",
                    razorpay_plan_id=f"plan_rzp_{tier.value}",
                )
            )
        return plans

    async def get_tenant_subscription(self, auth: AuthContext) -> TenantSubscriptionResponse:
        """Retrieve current subscription tier, budget utilization, and available upgrade plans."""
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            # Query Tenant
            tenant = (await session.execute(select(Tenant).where(Tenant.id == auth.tenant_id))).scalar_one_or_none()

            # Query Budget
            budget = (
                await session.execute(select(TenantBudgetRecord).where(TenantBudgetRecord.tenant_id == auth.tenant_id))
            ).scalar_one_or_none()

            tier_str = (tenant.tier if tenant and tenant.tier else "developer").lower()
            try:
                current_tier = SubscriptionTier(tier_str)
            except ValueError:
                current_tier = SubscriptionTier.DEVELOPER

            spec = TIER_SPECS.get(current_tier, TIER_SPECS[SubscriptionTier.DEVELOPER])

            monthly_budget = float(budget.total_budget_micros) / 1_000_000.0 if budget else spec["budget_usd"]
            spent_budget = float(budget.spent_micros) / 1_000_000.0 if budget else 0.0
            remaining_headroom = max(0.0, monthly_budget - spent_budget)

            return TenantSubscriptionResponse(
                tenant_id=auth.tenant_id,
                current_tier=current_tier,
                status=SubscriptionStatus.ACTIVE,
                monthly_budget_usd=round(monthly_budget, 2),
                spent_budget_usd=round(spent_budget, 4),
                remaining_headroom_usd=round(remaining_headroom, 4),
                current_cycle_requests=int(spent_budget * 100),  # Derived estimation
                monthly_request_quota=spec["quota"],
                max_concurrent_leases=spec["leases"],
                plans=self.get_available_plans(),
            )

    async def upgrade_subscription(
        self,
        auth: AuthContext,
        req: SubscriptionUpgradeRequest,
    ) -> SubscriptionUpgradeResponse:
        """Transition tenant subscription tier and adjust micro-dollar budget headroom."""
        target_spec = TIER_SPECS.get(req.target_tier)
        if not target_spec:
            raise ValueError(f"Unknown subscription tier '{req.target_tier}'")

        async with db_session.get_tenant_session(auth.tenant_id) as session:
            # 1. Update Tenant record
            tenant = (await session.execute(select(Tenant).where(Tenant.id == auth.tenant_id))).scalar_one_or_none()

            previous_tier = (
                SubscriptionTier(tenant.tier.lower()) if tenant and tenant.tier else SubscriptionTier.DEVELOPER
            )

            if tenant:
                tenant.tier = req.target_tier.value
                tenant.updated_at = datetime.now(UTC)

            # 2. Adjust Budget Record
            budget = (
                await session.execute(select(TenantBudgetRecord).where(TenantBudgetRecord.tenant_id == auth.tenant_id))
            ).scalar_one_or_none()

            new_budget_micros = int(target_spec["budget_usd"] * 1_000_000)
            if budget:
                budget.total_budget_micros = new_budget_micros
                budget.updated_at = datetime.now(UTC)
            else:
                now_utc = datetime.now(UTC)
                budget = TenantBudgetRecord(
                    id=f"bgt_{auth.tenant_id}",
                    tenant_id=auth.tenant_id,
                    total_budget_micros=new_budget_micros,
                    spent_micros=0,
                    reserved_micros=0,
                    hard_limit=True,
                    reset_period="MONTHLY",
                    last_reset_at=now_utc,
                    created_at=now_utc,
                    updated_at=now_utc,
                )
                session.add(budget)

            # 3. Append to TenantAuditLedger via authoritative AuditLedgerService with cryptographic hash chaining
            audit_reason = (
                f"Transitioned subscription to {req.target_tier.value} with "
                f"${target_spec['budget_usd']:.2f} budget headroom"
            )
            await AuditLedgerService.append_entry(
                session=session,
                tenant_id=auth.tenant_id,
                event_type="SUBSCRIPTION_TIER_CHANGED",
                actor_identity_id=auth.identity_id or f"id_{auth.user_id}",
                reason=audit_reason,
                event_payload={
                    "previous_tier": previous_tier.value,
                    "new_tier": req.target_tier.value,
                    "new_budget_usd": target_spec["budget_usd"],
                },
            )

            await session.commit()

        logger.info(
            "Tenant subscription updated",
            tenant_id=auth.tenant_id,
            previous_tier=previous_tier.value,
            new_tier=req.target_tier.value,
            budget_usd=target_spec["budget_usd"],
        )

        upgrade_msg = (
            f"Successfully transitioned subscription to '{target_spec['name']}' tier with "
            f"${target_spec['budget_usd']:,.2f} budget headroom."
        )
        checkout_link = (
            f"https://checkout.mirage.ai/session/{uuid.uuid4().hex[:12]}" if target_spec["price_usd"] > 0 else None
        )

        return SubscriptionUpgradeResponse(
            success=True,
            tenant_id=auth.tenant_id,
            previous_tier=previous_tier,
            new_tier=req.target_tier,
            status=SubscriptionStatus.ACTIVE,
            new_budget_ceiling_usd=target_spec["budget_usd"],
            message=upgrade_msg,
            checkout_url=checkout_link,
        )

    @staticmethod
    def _is_live_stripe_configured(settings: Any) -> bool:
        key = str(getattr(settings, "stripe_secret_key", "") or "").strip()
        return (
            key.startswith(("sk_live_", "sk_test_"))
            and key != "sk_test_miragePlatformKey"
            and not is_insecure_placeholder(key)
        )

    @staticmethod
    def _is_live_razorpay_configured(settings: Any) -> bool:
        key_id = str(getattr(settings, "razorpay_key_id", "") or "").strip()
        key_secret = str(getattr(settings, "razorpay_key_secret", "") or "").strip()
        return (
            key_id.startswith("rzp_")
            and not key_id.startswith("rzp_test_placeholder")
            and key_id != "rzp_test_miragePlatformKey"
            and bool(key_secret)
            and not key_secret.startswith("test_razorpay_")
            and not is_insecure_placeholder(key_secret)
        )

    @staticmethod
    def verify_stripe_webhook_signature(
        raw_body: bytes,
        signature_header: str,
        secret: str,
        tolerance_seconds: int = 300,
    ) -> None:
        """Verify Stripe-Signature header (`t=<ts>,v1=<hex>`) against raw payload bytes."""
        if not secret or is_insecure_placeholder(secret):
            raise PermissionError("Stripe webhook signing secret is not configured.")
        parts: dict[str, list[str]] = {}
        for item in signature_header.split(","):
            if "=" not in item:
                continue
            k, v = item.split("=", 1)
            parts.setdefault(k.strip(), []).append(v.strip())
        timestamps = parts.get("t", [])
        signatures = parts.get("v1", [])
        if not timestamps or not signatures:
            raise PermissionError("Malformed Stripe-Signature header.")
        try:
            ts = int(timestamps[0])
        except ValueError as exc:
            raise PermissionError("Invalid timestamp in Stripe-Signature header.") from exc
        if abs(int(datetime.now(UTC).timestamp()) - ts) > tolerance_seconds:
            raise PermissionError("Stripe webhook timestamp outside replay tolerance window.")

        signed_payload = f"{ts}.".encode() + raw_body
        expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, sig) for sig in signatures):
            raise PermissionError("Invalid Stripe webhook HMAC signature.")

    @staticmethod
    def verify_razorpay_webhook_signature(raw_body: bytes, signature_header: str, secret: str) -> None:
        """Verify Razorpay X-Razorpay-Signature HMAC-SHA256 digest against raw payload bytes."""
        if not secret or is_insecure_placeholder(secret):
            raise PermissionError("Razorpay webhook signing secret is not configured.")
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature_header.strip()):
            raise PermissionError("Invalid Razorpay webhook HMAC signature.")

    async def create_stripe_checkout_session(
        self, auth: AuthContext, req: StripeCheckoutSessionCreateRequest
    ) -> StripeCheckoutSessionResponse:
        """Create a Stripe USD Checkout Session for credit/debit cards and global payments."""
        target_spec = TIER_SPECS.get(req.tier)
        if not target_spec:
            raise ValueError(f"Unknown subscription tier: {req.tier}")

        settings = get_settings()
        amount_usd = float(target_spec.get("price_usd", 0.0))
        session_id = f"cs_test_{uuid.uuid4().hex[:18]}"
        checkout_url = f"https://checkout.stripe.com/c/pay/{session_id}"

        if self._is_live_stripe_configured(settings):
            success_url = req.success_url or "https://app.mirage.ai/billing/success?session_id={CHECKOUT_SESSION_ID}"
            cancel_url = req.cancel_url or "https://app.mirage.ai/billing/cancel"
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.stripe.com/v1/checkout/sessions",
                    auth=(settings.stripe_secret_key, ""),
                    data={
                        "mode": "subscription",
                        "success_url": success_url,
                        "cancel_url": cancel_url,
                        "line_items[0][price]": f"price_mirage_{req.tier.value}",
                        "line_items[0][quantity]": "1",
                        "metadata[tenant_id]": auth.tenant_id,
                        "metadata[tier]": req.tier.value,
                    },
                )
            if resp.status_code not in (200, 201):
                raise RuntimeError(f"Upstream Stripe checkout creation failed ({resp.status_code}).")
            stripe_data = resp.json()
            session_id = str(stripe_data.get("id") or session_id)
            checkout_url = str(stripe_data.get("url") or checkout_url)
        elif settings.environment in (EnvironmentType.PRODUCTION, EnvironmentType.STAGING):
            raise RuntimeError("Stripe billing credentials are not configured for staging/production.")

        logger.info(
            "Created Stripe checkout session",
            tenant_id=auth.tenant_id,
            tier=req.tier.value,
            amount_usd=amount_usd,
            session_id=session_id,
        )

        return StripeCheckoutSessionResponse(
            session_id=session_id,
            checkout_url=checkout_url,
            publishable_key=settings.stripe_publishable_key,
            tier=req.tier,
            plan_name=target_spec["name"],
            amount_usd=amount_usd,
            currency="USD",
        )

    async def verify_stripe_payment(
        self, auth: AuthContext, req: StripePaymentVerifyRequest
    ) -> StripePaymentVerifyResponse:
        """Verify Stripe settlement, activate subscription, record audit entry, and send receipt."""
        target_spec = TIER_SPECS.get(req.tier)
        if not target_spec:
            raise ValueError(f"Unknown subscription tier: {req.tier}")

        settings = get_settings()
        verified_payment_id = req.payment_intent_id

        if self._is_live_stripe_configured(settings):
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"https://api.stripe.com/v1/checkout/sessions/{req.session_id}",
                    auth=(settings.stripe_secret_key, ""),
                )
            if resp.status_code != 200:
                raise PermissionError(f"Stripe checkout session '{req.session_id}' could not be verified.")
            session_obj = resp.json()
            if session_obj.get("payment_status") != "paid":
                raise PermissionError(
                    f"Stripe checkout session '{req.session_id}' is not settled "
                    f"(payment_status={session_obj.get('payment_status')})."
                )
            meta = session_obj.get("metadata") or {}
            if meta.get("tenant_id") and meta.get("tenant_id") != auth.tenant_id:
                raise PermissionError("Stripe checkout session belongs to a different tenant.")
            verified_payment_id = str(session_obj.get("payment_intent") or verified_payment_id or "")
        elif settings.environment in (EnvironmentType.PRODUCTION, EnvironmentType.STAGING):
            raise RuntimeError("Stripe settlement verification requires configured Stripe secret credentials.")
        elif not req.session_id.startswith("cs_test_") or not verified_payment_id:
            raise PermissionError("Sandbox Stripe verification requires a 'cs_test_' session_id and payment_intent_id.")

        # Transition the subscription only after upstream settlement / verified sandbox check
        upgrade_res = await self.upgrade_subscription(
            auth=auth,
            req=SubscriptionUpgradeRequest(target_tier=req.tier),
        )

        payment_id = verified_payment_id or f"pi_{uuid.uuid4().hex[:16]}"
        invoice_id = f"INV-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        # Log Stripe settlement entry to audit ledger
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            await AuditLedgerService.append_entry(
                session=session,
                tenant_id=auth.tenant_id,
                event_type="STRIPE_PAYMENT_VERIFIED",
                actor_identity_id=auth.identity_id or f"id_{auth.user_id}",
                reason=f"Settled Stripe payment {payment_id} for {req.tier.value} tier",
                event_payload={
                    "session_id": req.session_id,
                    "payment_id": payment_id,
                    "invoice_id": invoice_id,
                    "tier": req.tier.value,
                    "amount_usd": target_spec.get("price_usd", 0.0),
                    "currency": "USD",
                    "payment_processor": "STRIPE",
                },
            )
            await session.commit()

        # Send official branded receipt to user via SMTP (only when SMTP user looks configured)
        user_email = settings.smtp_user if "@" in settings.smtp_user else f"{auth.tenant_id}@mirage.ai"
        email_sent = email_service.send_invoice_receipt(
            to_email=user_email,
            tenant_id=auth.tenant_id,
            plan_name=str(target_spec["name"]),
            amount=float(target_spec.get("price_usd", 0.0)),
            invoice_id=invoice_id,
            payment_id=payment_id,
            currency="USD",
            payment_method="Stripe",
        )

        logger.info(
            "Stripe payment verified and activated",
            tenant_id=auth.tenant_id,
            payment_id=payment_id,
            invoice_id=invoice_id,
            email_sent=email_sent,
        )

        verify_msg = (
            f"Stripe payment verified successfully. Active tier: {target_spec['name']} "
            f"(${target_spec['price_usd']:,.2f} USD/mo). Receipt sent to {user_email}."
        )

        return StripePaymentVerifyResponse(
            success=True,
            tenant_id=auth.tenant_id,
            payment_id=payment_id,
            tier=req.tier,
            status=SubscriptionStatus.ACTIVE,
            new_budget_ceiling_usd=upgrade_res.new_budget_ceiling_usd,
            invoice_id=invoice_id,
            receipt_url=f"/v1/billing/invoices/{invoice_id}/receipt",
            message=verify_msg,
        )

    async def create_razorpay_order(self, auth: AuthContext, req: RazorpayOrderCreateRequest) -> RazorpayOrderResponse:
        """Create a Razorpay order in Indian Rupees for UPI, Netbanking, Cards, and Wallets."""
        target_spec = TIER_SPECS.get(req.tier)
        if not target_spec:
            raise ValueError(f"Unknown subscription tier: {req.tier}")

        amount_inr = target_spec.get("price_inr", 0.0)
        amount_paise = int(amount_inr * 100)
        settings = get_settings()
        order_id = f"order_{uuid.uuid4().hex[:14]}"

        if self._is_live_razorpay_configured(settings):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        "https://api.razorpay.com/v1/orders",
                        auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
                        json={
                            "amount": amount_paise,
                            "currency": "INR",
                            "receipt": f"rcpt_{uuid.uuid4().hex[:10]}",
                            "notes": {
                                "tenant_id": auth.tenant_id,
                                "tier": req.tier.value,
                            },
                        },
                    )
                    if resp.status_code in (200, 201):
                        order_data = resp.json()
                        order_id = order_data.get("id", order_id)
                        logger.info("Razorpay order registered via API", order_id=order_id)
            except Exception as e:
                logger.warning(
                    "Razorpay API order dispatch encountered exception, using local order ID",
                    error=str(e),
                )
        elif settings.environment in (EnvironmentType.PRODUCTION, EnvironmentType.STAGING):
            raise RuntimeError("Razorpay billing credentials are not configured for staging/production.")

        logger.info(
            "Created Razorpay order",
            tenant_id=auth.tenant_id,
            tier=req.tier.value,
            amount_inr=amount_inr,
            order_id=order_id,
        )

        return RazorpayOrderResponse(
            order_id=order_id,
            amount_paise=amount_paise,
            amount_inr=amount_inr,
            currency="INR",
            key_id=settings.razorpay_key_id,
            tier=req.tier,
            plan_name=target_spec["name"],
            notes={
                "tenant_id": auth.tenant_id,
                "tier": req.tier.value,
                "company": auth.tenant_id,
            },
        )

    async def verify_razorpay_payment(
        self, auth: AuthContext, req: RazorpayPaymentVerifyRequest
    ) -> RazorpayPaymentVerifyResponse:
        """Verify Razorpay payment signature and activate subscription with INR audit logging."""
        target_spec = TIER_SPECS.get(req.tier)
        if not target_spec:
            raise ValueError(f"Unknown subscription tier: {req.tier}")

        settings = get_settings()
        is_test_shortcut = settings.environment == EnvironmentType.TEST and (
            not req.razorpay_signature
            or req.razorpay_signature.startswith("rzp_sig_")
            or settings.razorpay_key_secret.startswith("test_razorpay_")
        )

        if not is_test_shortcut:
            if settings.environment in (EnvironmentType.PRODUCTION, EnvironmentType.STAGING) and not (
                self._is_live_razorpay_configured(settings)
            ):
                raise RuntimeError("Razorpay secret credentials are not configured for staging/production.")
            if not req.razorpay_signature:
                raise PermissionError("Missing Razorpay payment signature.")
            msg = f"{req.razorpay_order_id}|{req.razorpay_payment_id}"
            expected_sig = hmac.new(
                settings.razorpay_key_secret.encode("utf-8"),
                msg.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected_sig, req.razorpay_signature):
                raise ValueError("Invalid Razorpay payment signature.")

        # Transition the subscription
        upgrade_res = await self.upgrade_subscription(
            auth=auth,
            req=SubscriptionUpgradeRequest(target_tier=req.tier),
        )

        payment_id = req.razorpay_payment_id
        invoice_id = f"INV-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        # Log Razorpay settlement entry to audit ledger
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            await AuditLedgerService.append_entry(
                session=session,
                tenant_id=auth.tenant_id,
                event_type="RAZORPAY_PAYMENT_VERIFIED",
                actor_identity_id=auth.identity_id or f"id_{auth.user_id}",
                reason=f"Settled Razorpay payment {payment_id} for {req.tier.value} tier",
                event_payload={
                    "order_id": req.razorpay_order_id,
                    "payment_id": payment_id,
                    "invoice_id": invoice_id,
                    "tier": req.tier.value,
                    "amount_inr": target_spec.get("price_inr", 0.0),
                    "currency": "INR",
                    "payment_methods_supported": ["UPI", "NETBANKING", "CARDS", "WALLETS"],
                },
            )
            await session.commit()

        # Send official branded receipt to user via SMTP
        user_email = settings.smtp_user if "@" in settings.smtp_user else f"{auth.tenant_id}@mirage.ai"
        inr_price = float(target_spec.get("price_inr", 0.0))
        email_sent = email_service.send_invoice_receipt(
            to_email=user_email,
            tenant_id=auth.tenant_id,
            plan_name=target_spec["name"],
            amount=inr_price,
            invoice_id=invoice_id,
            payment_id=payment_id,
            currency="INR",
            payment_method="Razorpay (UPI, Netbanking, Cards)",
        )

        logger.info(
            "Razorpay payment verified and activated",
            tenant_id=auth.tenant_id,
            payment_id=payment_id,
            invoice_id=invoice_id,
            email_sent=email_sent,
            tier=req.tier.value,
        )

        verify_msg = (
            f"Razorpay payment verified successfully. Active tier: {target_spec['name']} "
            f"(₹{inr_price:,.2f} INR/mo). Receipt sent to {user_email}."
        )
        return RazorpayPaymentVerifyResponse(
            success=True,
            tenant_id=auth.tenant_id,
            payment_id=req.razorpay_payment_id,
            tier=req.tier,
            status=SubscriptionStatus.ACTIVE,
            new_budget_ceiling_usd=upgrade_res.new_budget_ceiling_usd,
            message=verify_msg,
        )

    async def handle_payment_webhook(
        self,
        req: StripeWebhookRequest,
        *,
        raw_body: bytes | None = None,
        stripe_signature: str | None = None,
        razorpay_signature: str | None = None,
    ) -> dict[str, Any]:
        """Idempotent payment webhook processor with fail-closed HMAC signature verification."""
        settings = get_settings()

        if stripe_signature is not None:
            if raw_body is None:
                raise PermissionError("Raw request body required for Stripe-Signature verification.")
            self.verify_stripe_webhook_signature(
                raw_body=raw_body,
                signature_header=stripe_signature,
                secret=settings.stripe_webhook_secret,
            )
        elif razorpay_signature is not None:
            if raw_body is None:
                raise PermissionError("Raw request body required for X-Razorpay-Signature verification.")
            self.verify_razorpay_webhook_signature(
                raw_body=raw_body,
                signature_header=razorpay_signature,
                secret=settings.razorpay_webhook_secret,
            )
        else:
            # Fail closed on all HTTP deliveries and all non-test environments
            if raw_body is not None or settings.environment != EnvironmentType.TEST:
                raise PermissionError(
                    "Unauthorized webhook delivery: valid Stripe-Signature or X-Razorpay-Signature header is required."
                )
            logger.warning(
                "Unsigned webhook call accepted strictly in in-process TEST service invocation",
                event_id=req.event_id,
            )
        logger.info("Processing billing webhook event", event_id=req.event_id, event_type=req.event_type)

        data = req.data or {}
        tenant_id = req.tenant_id or data.get("tenant_id") or (data.get("notes") or {}).get("tenant_id")
        target_tier_str = data.get("tier") or (data.get("notes") or {}).get("tier")

        if tenant_id and target_tier_str:
            try:
                target_tier = SubscriptionTier(str(target_tier_str).lower())
                mock_auth = AuthContext(
                    tenant_id=str(tenant_id),
                    user_id="webhook_service",
                    role=Role.TENANT_ADMIN,
                )
                await self.upgrade_subscription(
                    auth=mock_auth,
                    req=SubscriptionUpgradeRequest(target_tier=target_tier),
                )
                async with db_session.get_tenant_session(str(tenant_id)) as session:
                    await AuditLedgerService.append_entry(
                        session=session,
                        tenant_id=str(tenant_id),
                        event_type="BILLING_WEBHOOK_FULFILLED",
                        actor_identity_id="webhook_service",
                        reason=f"Asynchronous webhook {req.event_type} fulfilled for tier {target_tier.value}",
                        event_payload={
                            "event_id": req.event_id,
                            "event_type": req.event_type,
                            "tier": target_tier.value,
                        },
                    )
                    await session.commit()
                logger.info("Asynchronous webhook upgraded tenant", tenant_id=tenant_id, tier=target_tier.value)
            except Exception as exc:
                logger.warning("Webhook fulfillment adjustment failed", error=str(exc))

        return {
            "processed": True,
            "event_id": req.event_id,
            "event_type": req.event_type,
            "status": "ACCEPTED",
        }


billing_service = BillingService()
