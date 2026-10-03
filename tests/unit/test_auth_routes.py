"""Unit test for gateway authentication routes."""

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from shared.schemas.auth import Role


@pytest.fixture(scope="module")
def client() -> TestClient:
    app = create_app()
    return TestClient(app)


def test_generate_demo_token_default(client: TestClient):
    """Test generating a demo token with default parameters."""
    response = client.post("/v1/auth/demo-token", json={})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["tenant_id"] == "tenant_demo"
    assert data["role"] == Role.TENANT_ADMIN.value
    assert data["user_id"] == "demo_operator"
    assert data["expires_in"] == 86400

    # Verify the token can be used on /v1/auth/me
    token = data["access_token"]
    me_resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["tenant_id"] == "tenant_demo"
    assert me_data["role"] == Role.TENANT_ADMIN.value
    assert me_data["is_authenticated"] is True


def test_generate_demo_token_custom_role(client: TestClient):
    """Test generating a demo token for operator role."""
    response = client.post(
        "/v1/auth/demo-token",
        json={"tenant_id": "tenant_test", "role": "operator", "user_id": "test_op"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "operator"
    assert data["tenant_id"] == "tenant_test"
    assert data["user_id"] == "test_op"

    token = data["access_token"]
    me_resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["role"] == "operator"
