"""Regression tests for the public gateway authentication surface."""

import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create an application client without a credential issuer."""
    return TestClient(create_app())


def test_demo_token_issuer_is_not_exposed(client: TestClient) -> None:
    """The former unauthenticated privilege issuer must remain absent."""
    response = client.post(
        "/v1/auth/demo-token",
        json={"tenant_id": "victim", "role": "super_admin", "user_id": "attacker"},
    )
    assert response.status_code == 404


def test_auth_me_requires_a_credential(client: TestClient) -> None:
    """Identity inspection cannot establish anonymous authorization."""
    response = client.get("/v1/auth/me")
    assert response.status_code == 401
