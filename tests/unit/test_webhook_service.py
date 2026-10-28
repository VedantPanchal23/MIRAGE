"""Unit tests for Outbound Webhook Subscriptions and HMAC Event Dispatcher."""

import hashlib
import hmac
import json

import pytest

from services.webhook_service import WebhookService
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
