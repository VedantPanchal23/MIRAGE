"""Unit tests for the authenticated Agent and Delegation REST endpoints.

Validates authentication requirements (401), RBAC authorization (403),
successful lifecycle operations (200/201), query filtering, and not-found semantics (404).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from gateway.main import create_app
from shared.schemas.agent import (
    AgentListResponse,
    AgentResponse,
    AgentStatus,
)
from shared.schemas.auth import Role
from shared.schemas.control_plane import Decision, PolicyDecision
from shared.schemas.delegation import (
    AttenuatedCapabilitySpec,
    DelegationGrantResponse,
    DelegationStatus,
)
from tests.auth_factory import AuthTestFactory


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create a TestClient instance with the main gateway application."""
    return TestClient(create_app())


def _sample_agent_response(
    agent_id: str = "agent_test_1",
    tenant_id: str = "tenant_test",
    name: str = "research_bot",
    status_val: AgentStatus = AgentStatus.ACTIVE,
) -> AgentResponse:
    now = datetime.now(UTC)
    return AgentResponse(
        id=agent_id,
        tenant_id=tenant_id,
        name=name,
        status=status_val,
        active=(status_val == AgentStatus.ACTIVE),
        max_autonomy_level=2,
        registered_by_identity_id="usr_admin_1",
        created_at=now,
        updated_at=now,
    )


def _sample_delegation_response(
    delegation_id: str = "del_test_1",
    tenant_id: str = "tenant_test",
    status_val: DelegationStatus = DelegationStatus.PENDING,
) -> DelegationGrantResponse:
    now = datetime.now(UTC)
    return DelegationGrantResponse(
        id=delegation_id,
        tenant_id=tenant_id,
        parent_agent_id="agent_parent_1",
        parent_transaction_id="txn_parent_1",
        child_agent_id="agent_child_1",
        child_transaction_id="txn_child_1" if status_val == DelegationStatus.ACTIVE else None,
        delegated_capabilities=[
            AttenuatedCapabilitySpec(
                capability_type="database:read",
                resource_scope={"allowed_prefixes": ["db://finance"]},
                max_autonomy_level=2,
            )
        ],
        resource_scope={"allowed_prefixes": ["db://finance"]},
        max_turns=4,
        max_autonomy_level=2,
        delegation_depth=1,
        status=status_val,
        purpose="Delegated audit read",
        idempotency_key="idem_key_12345",
        expires_at=now + timedelta(minutes=5),
        created_at=now,
    )


class TestUnauthenticatedRouteProtection:
    """Endpoints must reject unauthenticated, expired, or tampered requests with 401."""

    def test_list_agents_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.get("/v1/agents")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_register_agent_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.post("/v1/agents", json={"name": "test_agent"})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_delegations_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.get("/v1/delegations")
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_delegation_unauthenticated_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/v1/delegations",
            json={
                "parent_transaction_id": "txn_p",
                "delegatee_agent_id": "ag_c",
                "delegated_capabilities": [{"capability_type": "read"}],
                "idempotency_key": "idem_123456",
                "purpose": "test",
            },
        )
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_agents_expired_jwt_rejected(self, client: TestClient) -> None:
        expired_token = AuthTestFactory.expired_jwt(tenant_id="tenant_test")
        resp = client.get("/v1/agents", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delegations_tampered_jwt_rejected(self, client: TestClient) -> None:
        tampered_token = AuthTestFactory.tampered_jwt(tenant_id="tenant_test")
        resp = client.get("/v1/delegations", headers={"Authorization": f"Bearer {tampered_token}"})
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED


class TestAgentRouteRBAC:
    """Non-administrative roles (e.g. API_CLIENT) must be forbidden (403) from mutating agent lifecycle."""

    def test_api_client_cannot_register_agent(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.API_CLIENT)
        resp = client.post(
            "/v1/agents",
            json={"name": "rogue_agent", "max_autonomy_level": 1},
            headers=headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN
        assert "not authorized" in resp.json()["detail"].lower()

    def test_api_client_cannot_activate_agent(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.API_CLIENT)
        resp = client.post(
            "/v1/agents/agent_1/activate",
            json={"reason": "Self activation"},
            headers=headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_api_client_cannot_suspend_agent(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.API_CLIENT)
        resp = client.post(
            "/v1/agents/agent_1/suspend",
            json={"reason": "Unauthorized suspension attempt"},
            headers=headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN

    def test_api_client_cannot_revoke_agent(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.API_CLIENT)
        resp = client.post(
            "/v1/agents/agent_1/revoke",
            json={"reason": "Unauthorized revocation attempt"},
            headers=headers,
        )
        assert resp.status_code == status.HTTP_403_FORBIDDEN


class TestAgentRoutesLifecycle:
    """Verify standard CRUD and lifecycle transitions for /v1/agents."""

    def test_register_agent_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.TENANT_ADMIN)
        sample = _sample_agent_response(agent_id="agent_new", name="analyst")

        with patch(
            "gateway.routes.agents.agent_governance_service.register_agent",
            new_callable=AsyncMock,
            return_value=sample,
        ) as mock_reg:
            resp = client.post(
                "/v1/agents",
                json={"name": "analyst", "max_autonomy_level": 2, "initial_status": "active"},
                headers=headers,
            )

        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["id"] == "agent_new"
        assert data["name"] == "analyst"
        assert data["status"] == "active"
        mock_reg.assert_awaited_once()

    def test_get_agent_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_agent_response(agent_id="agent_existing")

        with patch(
            "gateway.routes.agents.agent_governance_service.get_agent",
            new_callable=AsyncMock,
            return_value=sample,
        ) as mock_get:
            resp = client.get("/v1/agents/agent_existing", headers=headers)

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["id"] == "agent_existing"
        mock_get.assert_awaited_once()

    def test_get_agent_not_found(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)

        with patch(
            "gateway.routes.agents.agent_governance_service.get_agent",
            new_callable=AsyncMock,
            side_effect=HTTPException(
                status_code=404,
                detail="Agent 'agent_missing' not found in tenant 'tenant_test'",
            ),
        ):
            resp = client.get("/v1/agents/agent_missing", headers=headers)

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in resp.json()["detail"].lower()

    def test_list_agents_with_filtering_and_pagination(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_agent_response()
        list_resp = AgentListResponse(agents=[sample], total=1, limit=10, offset=0)

        with patch(
            "gateway.routes.agents.agent_governance_service.list_agents",
            new_callable=AsyncMock,
            return_value=list_resp,
        ) as mock_list:
            resp = client.get("/v1/agents?status=active&limit=10&offset=0", headers=headers)

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["total"] == 1
        assert len(data["agents"]) == 1
        assert data["agents"][0]["id"] == sample.id
        mock_list.assert_awaited_once()

    def test_activate_agent_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_agent_response(agent_id="agent_to_activate", status_val=AgentStatus.ACTIVE)

        with patch(
            "gateway.routes.agents.agent_governance_service.activate_agent",
            new_callable=AsyncMock,
            return_value=sample,
        ) as mock_act:
            resp = client.post(
                "/v1/agents/agent_to_activate/activate",
                json={"reason": "Operational readiness approved"},
                headers=headers,
            )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "active"
        mock_act.assert_awaited_once()

    def test_suspend_agent_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_agent_response(agent_id="agent_to_suspend", status_val=AgentStatus.SUSPENDED)

        with patch(
            "gateway.routes.agents.agent_governance_service.suspend_agent",
            new_callable=AsyncMock,
            return_value=sample,
        ) as mock_susp:
            resp = client.post(
                "/v1/agents/agent_to_suspend/suspend",
                json={"reason": "Security audit hold"},
                headers=headers,
            )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "suspended"
        mock_susp.assert_awaited_once()

    def test_revoke_agent_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.TENANT_ADMIN)
        sample = _sample_agent_response(agent_id="agent_to_revoke", status_val=AgentStatus.REVOKED)

        with patch(
            "gateway.routes.agents.agent_governance_service.revoke_agent",
            new_callable=AsyncMock,
            return_value=sample,
        ) as mock_rev:
            resp = client.post(
                "/v1/agents/agent_to_revoke/revoke",
                json={"reason": "Permanent decommissioning"},
                headers=headers,
            )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "revoked"
        mock_rev.assert_awaited_once()


class TestDelegationRoutesLifecycle:
    """Verify standard CRUD, activation, revocation, and operation validation for /v1/delegations."""

    def test_create_delegation_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_delegation_response(delegation_id="del_new_1")

        with patch(
            "gateway.routes.delegations.delegation_service.create_delegation_grant",
            new_callable=AsyncMock,
            return_value=sample,
        ) as mock_create:
            payload = {
                "parent_transaction_id": "txn_parent_1",
                "delegatee_agent_id": "agent_child_1",
                "delegated_capabilities": [
                    {
                        "capability_type": "database:read",
                        "resource_scope": {"allowed_prefixes": ["db://finance"]},
                        "max_autonomy_level": 2,
                    }
                ],
                "max_turns": 4,
                "duration_seconds": 300,
                "idempotency_key": "idem_new_delegation_1",
                "purpose": "Delegated subquery execution",
            }
            resp = client.post("/v1/delegations", json=payload, headers=headers)

        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["id"] == "del_new_1"
        assert data["status"] == "PENDING"
        mock_create.assert_awaited_once()

    def test_get_delegation_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_delegation_response(delegation_id="del_existing_1")

        with patch(
            "gateway.routes.delegations.delegation_service.get_delegation_grant",
            new_callable=AsyncMock,
            return_value=sample,
        ) as mock_get:
            resp = client.get("/v1/delegations/del_existing_1", headers=headers)

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["id"] == "del_existing_1"
        mock_get.assert_awaited_once()

    def test_get_delegation_not_found(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)

        with patch(
            "gateway.routes.delegations.delegation_service.get_delegation_grant",
            new_callable=AsyncMock,
            side_effect=HTTPException(status_code=404, detail="Delegation grant 'del_ghost' not found"),
        ):
            resp = client.get("/v1/delegations/del_ghost", headers=headers)

        assert resp.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in resp.json()["detail"].lower()

    def test_list_delegations_filtering(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_delegation_response()

        with patch(
            "gateway.routes.delegations.delegation_service.list_delegation_grants",
            new_callable=AsyncMock,
            return_value=[sample],
        ) as mock_list:
            resp = client.get(
                "/v1/delegations?status=PENDING&parent_transaction_id=txn_parent_1&child_agent_id=agent_child_1&limit=20&offset=0",
                headers=headers,
            )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == sample.id
        mock_list.assert_awaited_once()

    def test_activate_delegation_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_delegation_response(delegation_id="del_active_1", status_val=DelegationStatus.ACTIVE)

        with patch(
            "gateway.routes.delegations.delegation_service.activate_delegation_grant",
            new_callable=AsyncMock,
            return_value=sample,
        ) as mock_act:
            resp = client.post(
                "/v1/delegations/del_active_1/activate",
                json={"child_transaction_id": "txn_child_1"},
                headers=headers,
            )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["status"] == "ACTIVE"
        assert data["child_transaction_id"] == "txn_child_1"
        mock_act.assert_awaited_once()

    def test_revoke_delegation_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_delegation_response(delegation_id="del_rev_1", status_val=DelegationStatus.REVOKED)

        with patch(
            "gateway.routes.delegations.delegation_service.revoke_delegation_grant",
            new_callable=AsyncMock,
            return_value=sample,
        ) as mock_rev:
            resp = client.post(
                "/v1/delegations/del_rev_1/revoke",
                json={"reason": "Operator manual revocation"},
                headers=headers,
            )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.json()["status"] == "REVOKED"
        mock_rev.assert_awaited_once()

    def test_validate_delegation_operation_endpoint_success(self, client: TestClient) -> None:
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        pol_decision = PolicyDecision(
            decision=Decision.ALLOW,
            reason="Delegated operation verified within scope and autonomy ceiling",
        )

        with patch(
            "gateway.routes.delegations.delegation_service.validate_delegation_for_operation",
            new_callable=AsyncMock,
            return_value=pol_decision,
        ) as mock_val:
            payload = {
                "capability_type": "database:read",
                "resource": {"target_resource": "db://finance/ledger"},
                "requested_autonomy_level": 2,
            }
            resp = client.post(
                "/v1/delegations/del_active_1/validate",
                json=payload,
                headers=headers,
            )

        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["decision"] == "ALLOW"
        assert "verified within scope" in data["reason"]
        mock_val.assert_awaited_once()
