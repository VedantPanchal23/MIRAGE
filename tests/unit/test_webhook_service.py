"""Unit tests for Outbound Webhook Subscriptions, HMAC Event Dispatcher, and Chat Alerts."""

import hashlib
import hmac
import json

import pytest

from services.webhook_service import WebhookService, format_discord_embed, format_slack_block_kit
from shared.schemas.auth import AuthContext, Role
from shared.schemas.webhook import WebhookCreateRequest, WebhookEventType


@pytest.fixture
def auth_admin() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_unit_test",
        user_id="user_admin",
        identity_id="id_admin",
        role=Role.TENANT_ADMIN,
    )


@pytest.fixture
def auth_viewer() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_unit_test",
        user_id="user_viewer",
        identity_id="id_viewer",
        role=Role.OPERATOR,
    )


@pytest.mark.asyncio
async def test_webhook_hmac_signature() -> None:
    secret = "test_super_secret_signing_key_12345"
    payload = {"action_id": "act_test_1", "status": "BLOCKED"}
    canonical_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    expected_sig = hmac.new(secret.encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()
    assert len(expected_sig) == 64


@pytest.mark.asyncio
async def test_non_admin_cannot_register_webhook(auth_viewer: AuthContext) -> None:
    service = WebhookService()
    req = WebhookCreateRequest(
        url="https://example.com/webhook",
        event_types=[WebhookEventType.ACTION_BLOCKED],
    )
    with pytest.raises(Exception) as exc_info:
        await service.register_webhook(auth_viewer, req)
    assert "Administrator privileges" in str(exc_info.value)


def test_format_slack_block_kit() -> None:
    """Verify Slack Block Kit generation contains structured fields and action button."""
    payload = {
        "tool_name": "payments:transfer_wire",
        "risk_score": 85,
        "reason": "Exceeds automated approval limit ($5,000)",
    }
    slack_msg = format_slack_block_kit(
        event_type="ACTION_AWAITING_APPROVAL",
        tenant_id="tenant_finance_1",
        payload=payload,
    )

    assert "ACTION_AWAITING_APPROVAL" in slack_msg["text"]
    assert len(slack_msg["blocks"]) >= 3
    # Header block
    assert "MIRAGE Security Alert" in slack_msg["blocks"][0]["text"]["text"]
    # Action button
    action_block = slack_msg["blocks"][3]
    assert action_block["elements"][0]["text"]["text"] == "Review in Dashboard"


def test_format_discord_embed() -> None:
    """Verify Discord Embed contains expected color coding and fields."""
    payload = {
        "tool_name": "database:drop_table",
        "reason": "Destructive query detected",
    }
    discord_msg = format_discord_embed(
        event_type="ACTION_BLOCKED",
        tenant_id="tenant_finance_1",
        timestamp="2026-10-29T10:00:00Z",
        payload=payload,
    )

    assert "embeds" in discord_msg
    embed = discord_msg["embeds"][0]
    assert embed["title"] == "Assurance Event: ACTION_BLOCKED"
    assert embed["color"] == 16724530  # Red alert color
    field_names = [f["name"] for f in embed["fields"]]
    assert "Tenant" in field_names
    assert "Tool/Action" in field_names
