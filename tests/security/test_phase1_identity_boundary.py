"""P0 regression coverage for the MIRAGE 3.0 identity boundary."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gateway.main import create_app
from gateway.middleware import auth as auth_module
from shared.config import EnvironmentType


def test_original_demo_super_admin_exploit_is_unavailable() -> None:
    """No request can obtain a caller-selected privileged JWT from the gateway."""
    client = TestClient(create_app())
    result = client.post(
        "/v1/auth/demo-token",
        json={"tenant_id": "tenant_a", "role": "super_admin", "user_id": "attacker"},
    )
    assert result.status_code == 404


@pytest.mark.asyncio
async def test_known_legacy_admin_key_is_not_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The literal legacy super-admin key cannot authenticate in runtime mode."""
    monkeypatch.setattr(auth_module.settings, "environment", EnvironmentType.PRODUCTION)
    with pytest.raises(HTTPException) as raised:
        await auth_module.resolve_api_key_context("mrg_test_admin_000000000000000000000000")
    assert raised.value.status_code in {401, 503}


def test_identity_headers_cannot_replace_credential() -> None:
    """Tenant, role, capability, and agent headers cannot create a principal."""
    client = TestClient(create_app())
    response = client.get(
        "/v1/auth/me",
        headers={
            "X-Tenant-ID": "tenant_a",
            "X-Role": "super_admin",
            "X-Agent-ID": "agent_a",
            "X-Capability": "anything",
        },
    )
    assert response.status_code == 401
