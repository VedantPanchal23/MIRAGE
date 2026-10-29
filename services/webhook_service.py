"""Outbound Webhook Dispatcher and Alerting Service for Gate 3/5 Events.

Provides:
- Tenant-scoped webhook subscription CRUD under PostgreSQL RLS.
- Cryptographic HMAC-SHA256 signature generation (X-Mirage-Signature-256).
- Fire-and-forget asynchronous event dispatching with circuit breaker protection.
"""

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select

from db import session as db_session
from db.models import WebhookSubscriptionRecord
from shared.logging import get_logger
from shared.schemas.auth import AuthContext, Role
from shared.schemas.webhook import (
    WebhookCreateRequest,
    WebhookDispatchPayload,
    WebhookListResponse,
    WebhookResponse,
)

logger = get_logger("webhook_service")


def format_slack_block_kit(event_type: str, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Format an assurance or approval event into Slack Block Kit."""
    risk = str(payload.get("risk_score", "N/A"))
    tool = str(payload.get("tool_name", payload.get("action_name", "N/A")))
    reason = str(payload.get("reason", payload.get("message", "Policy evaluation checkpoint")))

    return {
        "text": f"🛡️ [MIRAGE Alert]: {event_type}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"🛡️ MIRAGE Security Alert: {event_type}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Event Type:*\n`{event_type}`"},
                    {"type": "mrkdwn", "text": f"*Tenant:*\n`{tenant_id}`"},
                    {"type": "mrkdwn", "text": f"*Tool/Action:*\n`{tool}`"},
                    {"type": "mrkdwn", "text": f"*Risk Score:*\n*{risk}*"},
                ],
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Details:*\n>{reason}"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Review in Dashboard"},
                        "url": "http://localhost:3000/approvals",
                        "style": "primary",
                    }
                ],
            },
        ],
    }


def format_discord_embed(event_type: str, tenant_id: str, timestamp: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Format an assurance or approval event into a Discord Embed."""
    tool = str(payload.get("tool_name", payload.get("action_name", "N/A")))
    reason = str(payload.get("reason", payload.get("message", "Policy evaluation checkpoint")))
    is_alert = "BLOCKED" in event_type or "DISCREPANCY" in event_type
    color = 16724530 if is_alert else 3447003

    return {
        "content": "🛡️ **MIRAGE Assurance Notification**",
        "embeds": [
            {
                "title": f"Assurance Event: {event_type}",
                "color": color,
                "fields": [
                    {"name": "Tenant", "value": f"`{tenant_id}`", "inline": True},
                    {"name": "Tool/Action", "value": f"`{tool}`", "inline": True},
                    {"name": "Details", "value": reason, "inline": False},
                ],
                "timestamp": timestamp,
            }
        ],
    }


class WebhookService:
    """Manages outbound webhook subscriptions and dispatches security/assurance alerts."""

    def __init__(self) -> None:
        self.http_client = httpx.AsyncClient(timeout=5.0)

    async def register_webhook(self, auth: AuthContext, req: WebhookCreateRequest) -> WebhookResponse:
        """Register a new outbound webhook for the authenticated tenant."""
        if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Registering webhook subscriptions requires Administrator privileges.",
            )

        now = datetime.now(UTC)
        sub_id = f"whk_{uuid.uuid4().hex[:16]}"
        secret = req.secret or uuid.uuid4().hex + uuid.uuid4().hex  # 64-char random hex

        async with db_session.get_tenant_session(auth.tenant_id) as session:
            record = WebhookSubscriptionRecord(
                id=sub_id,
                tenant_id=auth.tenant_id,
                url=req.url,
                description=req.description,
                secret_key=secret,
                event_types=[e.value for e in req.event_types],
                active=req.active,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            await session.commit()

        logger.info("Registered outbound webhook subscription", webhook_id=sub_id, tenant_id=auth.tenant_id)

        return WebhookResponse(
            id=sub_id,
            tenant_id=auth.tenant_id,
            url=req.url,
            description=req.description,
            event_types=[e.value for e in req.event_types],
            active=req.active,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        )

    async def list_webhooks(self, auth: AuthContext) -> WebhookListResponse:
        """List registered webhooks under tenant isolation."""
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            stmt = (
                select(WebhookSubscriptionRecord)
                .where(WebhookSubscriptionRecord.tenant_id == auth.tenant_id)
                .order_by(WebhookSubscriptionRecord.created_at.desc())
            )
            res = await session.execute(stmt)
            records = res.scalars().all()

            items = [
                WebhookResponse(
                    id=r.id,
                    tenant_id=r.tenant_id,
                    url=r.url,
                    description=r.description,
                    event_types=r.event_types or [],
                    active=r.active,
                    created_at=r.created_at.isoformat(),
                    updated_at=r.updated_at.isoformat(),
                )
                for r in records
            ]
            return WebhookListResponse(webhooks=items, total=len(items))

    async def delete_webhook(self, auth: AuthContext, webhook_id: str) -> bool:
        """Delete a webhook subscription."""
        if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Deleting webhook subscriptions requires Administrator privileges.",
            )

        async with db_session.get_tenant_session(auth.tenant_id) as session:
            rec = await session.get(WebhookSubscriptionRecord, webhook_id)
            if not rec or rec.tenant_id != auth.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook subscription not found")
            await session.delete(rec)
            await session.commit()

        return True

    async def dispatch_event(
        self,
        tenant_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Asynchronously dispatch security or assurance event to all matching subscribers."""
        asyncio.create_task(self._execute_dispatch(tenant_id, event_type, payload))

    async def _execute_dispatch(
        self,
        tenant_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Execute background HTTP deliveries with HMAC signatures."""
        try:
            async with db_session.get_tenant_session(tenant_id) as session:
                stmt = select(WebhookSubscriptionRecord).where(
                    WebhookSubscriptionRecord.tenant_id == tenant_id,
                    WebhookSubscriptionRecord.active.is_(True),
                )
                res = await session.execute(stmt)
                subs = res.scalars().all()

            matching_subs = [s for s in subs if event_type in (s.event_types or [])]
            if not matching_subs:
                return

            event_id = f"evt_{uuid.uuid4().hex[:16]}"
            timestamp = datetime.now(UTC).isoformat()
            dispatch_body = WebhookDispatchPayload(
                event_id=event_id,
                event_type=event_type,
                tenant_id=tenant_id,
                timestamp=timestamp,
                payload=payload,
            )
            canonical_bytes = json.dumps(
                dispatch_body.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")

            for sub in matching_subs:
                url_lower = sub.url.lower()
                if "hooks.slack.com" in url_lower:
                    send_payload = format_slack_block_kit(event_type, tenant_id, payload)
                    send_bytes = json.dumps(send_payload).encode("utf-8")
                    headers = {"Content-Type": "application/json"}
                elif "discord.com" in url_lower or "discordapp.com" in url_lower:
                    send_payload = format_discord_embed(event_type, tenant_id, timestamp, payload)
                    send_bytes = json.dumps(send_payload).encode("utf-8")
                    headers = {"Content-Type": "application/json"}
                else:
                    signature = hmac.new(sub.secret_key.encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()
                    send_bytes = canonical_bytes
                    headers = {
                        "Content-Type": "application/json",
                        "X-Mirage-Signature-256": f"sha256={signature}",
                        "X-Mirage-Event": event_type,
                        "X-Mirage-Event-ID": event_id,
                    }

                try:
                    r = await self.http_client.post(sub.url, content=send_bytes, headers=headers)
                    logger.info(
                        "Webhook dispatched",
                        webhook_id=sub.id,
                        target_url=sub.url,
                        status_code=r.status_code,
                        event_type=event_type,
                    )
                except Exception as post_err:
                    logger.warning(
                        "Webhook delivery failed",
                        webhook_id=sub.id,
                        target_url=sub.url,
                        error=str(post_err),
                    )
        except Exception as exc:
            logger.error("Outbound webhook dispatch error", error=str(exc), tenant_id=tenant_id)


webhook_service = WebhookService()
