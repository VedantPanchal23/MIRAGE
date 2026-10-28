"""Typed schemas for Outbound Webhook Subscriptions and Event Payloads."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WebhookEventType(StrEnum):
    """Supported outbound event types."""

    ACTION_AWAITING_APPROVAL = "ACTION_AWAITING_APPROVAL"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    OUTCOME_DISCREPANCY = "OUTCOME_DISCREPANCY"
    AUDIT_ALERT = "AUDIT_ALERT"


class WebhookCreateRequest(BaseModel):
    """Payload to register an outbound webhook."""

    url: str = Field(min_length=8, max_length=1024, description="Target HTTP/HTTPS URL")
    description: str = Field(default="", max_length=512)
    event_types: list[WebhookEventType] = Field(
        default_factory=lambda: [
            WebhookEventType.ACTION_AWAITING_APPROVAL,
            WebhookEventType.ACTION_BLOCKED,
            WebhookEventType.OUTCOME_DISCREPANCY,
        ]
    )
    secret: str | None = Field(default=None, min_length=16, max_length=128, description="Custom secret for HMAC")
    active: bool = True


class WebhookResponse(BaseModel):
    """Public representation of registered webhook."""

    model_config = ConfigDict(extra="ignore")

    id: str
    tenant_id: str
    url: str
    description: str = ""
    event_types: list[str] = Field(default_factory=list)
    active: bool = True
    created_at: str
    updated_at: str


class WebhookListResponse(BaseModel):
    """List of registered webhooks for a tenant."""

    model_config = ConfigDict(extra="ignore")

    webhooks: list[WebhookResponse] = Field(default_factory=list)
    total: int = 0


class WebhookDispatchPayload(BaseModel):
    """Envelope dispatched to external webhook endpoints with HMAC-SHA256 signature."""

    event_id: str
    event_type: str
    tenant_id: str
    timestamp: str
    payload: dict[str, Any]
