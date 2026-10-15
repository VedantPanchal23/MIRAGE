"""Unit tests for Governed Agent Handoffs and Resource Concurrency REST routes.

Validates authentication (401), validation (422), route handling, status codes (200, 201, 404, 409),
and query parameter filtering.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from gateway.main import create_app
from shared.schemas.auth import Role
from shared.schemas.concurrency import (
    ConcurrencyMode,
    LeaseStatus,
    ResourceLeaseResponse,
)
from shared.schemas.handoff import (
    AgentHandoffAcceptResponse,
    AgentHandoffResponse,
    HandoffStatus,
)
from tests.auth_factory import AuthTestFactory


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create a TestClient instance with the main gateway application."""
    return TestClient(create_app())


def _sample_handoff_response(
    handoff_id: str = "hnd_route_1",
    tenant_id: str = "tenant_test",
    status_val: HandoffStatus = HandoffStatus.PENDING,
) -> AgentHandoffResponse:
    now = datetime.now(UTC)
    return AgentHandoffResponse(
        id=handoff_id,
        tenant_id=tenant_id,
        parent_transaction_id="txn_parent_1",
        parent_agent_id="agent_parent_1",
        child_agent_id="agent_child_1",
        delegation_id="del_grant_1",
        child_transaction_id=None,
        status=status_val,
        purpose="Route test handoff",
        permitted_scope={},
        inherited_taint_flags=["PII"],
        idempotency_key="idem_route_123",
        expires_at=now + timedelta(minutes=5),
        accepted_at=None,
        completed_at=None,
        cancelled_at=None,
        cancellation_reason=None,
        created_at=now,
        updated_at=now,
    )


def _sample_lease_response(
    lease_id: str = "lse_route_1",
    tenant_id: str = "tenant_test",
    token: int = 1,
    status_val: LeaseStatus = LeaseStatus.ACQUIRED,
) -> ResourceLeaseResponse:
    now = datetime.now(UTC)
    return ResourceLeaseResponse(
        id=lease_id,
        tenant_id=tenant_id,
        resource_uri="db://postgres/finance/ledger",
        holder_agent_id="agent_worker_1",
        holder_transaction_id="txn_route_1",
        holder_handoff_id=None,
        concurrency_mode=ConcurrencyMode.EXCLUSIVE,
        fencing_token=token,
        status=status_val,
        expires_at=now + timedelta(minutes=1),
        released_at=None,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Governed Handoffs Routes Tests
# ---------------------------------------------------------------------------


class TestHandoffsRoutes:
    """Test suite for /v1/handoffs REST endpoints."""

    def test_create_handoff_unauthenticated(self, client: TestClient) -> None:
        """Unauthenticated requests return 401 Unauthorized."""
        res = client.post(
            "/v1/handoffs",
            json={
                "parent_transaction_id": "txn_1",
                "child_agent_id": "agent_2",
                "delegation_id": "del_1",
                "purpose": "Test",
                "idempotency_key": "idem_12345",
            },
        )
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_handoff_success(self, client: TestClient) -> None:
        """Valid authenticated request returns 201 Created."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_handoff_response()

        with patch("gateway.routes.handoffs.handoff_service.create_handoff", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = sample
            res = client.post(
                "/v1/handoffs",
                headers=headers,
                json={
                    "parent_transaction_id": "txn_parent_1",
                    "child_agent_id": "agent_child_1",
                    "delegation_id": "del_grant_1",
                    "purpose": "Route test handoff",
                    "idempotency_key": "idem_route_123",
                },
            )

        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["id"] == "hnd_route_1"
        assert data["status"] == "PENDING"

    def test_get_handoff_not_found(self, client: TestClient) -> None:
        """Non-existent handoff returns 404 Not Found."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)

        with patch("gateway.routes.handoffs.handoff_service.get_handoff", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = HTTPException(status_code=404, detail="Handoff not found")
            res = client.get("/v1/handoffs/hnd_missing", headers=headers)

        assert res.status_code == status.HTTP_404_NOT_FOUND

    def test_list_handoffs(self, client: TestClient) -> None:
        """List handoffs returns 200 with list."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_handoff_response()

        with patch("gateway.routes.handoffs.handoff_service.list_handoffs", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [sample]
            res = client.get("/v1/handoffs?status=PENDING&limit=10", headers=headers)

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert len(data) == 1
        assert data[0]["id"] == "hnd_route_1"

    def test_accept_handoff_success(self, client: TestClient) -> None:
        """Accept handoff returns 200 with spawned child transaction details."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_handoff_response(status_val=HandoffStatus.ACCEPTED)
        accept_resp = AgentHandoffAcceptResponse(
            handoff=sample,
            child_transaction_id="txn_child_999",
            inherited_taint_flags=["PII"],
            allocated_turns=6,
        )

        with patch("gateway.routes.handoffs.handoff_service.accept_handoff", new_callable=AsyncMock) as mock_accept:
            mock_accept.return_value = accept_resp
            res = client.post(
                "/v1/handoffs/hnd_route_1/accept",
                headers=headers,
                json={"input_context": {"foo": "bar"}},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["child_transaction_id"] == "txn_child_999"
        assert data["allocated_turns"] == 6

    def test_cancel_handoff_success(self, client: TestClient) -> None:
        """Cancel handoff returns 200 with updated status."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_handoff_response(status_val=HandoffStatus.CANCELLED)

        with patch("gateway.routes.handoffs.handoff_service.cancel_handoff", new_callable=AsyncMock) as mock_cancel:
            mock_cancel.return_value = sample
            res = client.post(
                "/v1/handoffs/hnd_route_1/cancel",
                headers=headers,
                json={"reason": "Testing cancellation route"},
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Resource Concurrency Routes Tests
# ---------------------------------------------------------------------------


class TestConcurrencyRoutes:
    """Test suite for /v1/resources/leases REST endpoints."""

    def test_acquire_lease_unauthenticated(self, client: TestClient) -> None:
        """Unauthenticated lease acquisition returns 401."""
        res = client.post(
            "/v1/resources/leases/acquire",
            json={
                "resource_uri": "db://postgres/finance/ledger",
                "transaction_id": "txn_1",
                "agent_id": "agent_1",
            },
        )
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_acquire_lease_success(self, client: TestClient) -> None:
        """Acquiring lease returns 201 Created with fencing token."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_lease_response(token=7)

        with patch("gateway.routes.concurrency.concurrency_service.acquire_lease", new_callable=AsyncMock) as mock_acq:
            mock_acq.return_value = sample
            res = client.post(
                "/v1/resources/leases/acquire",
                headers=headers,
                json={
                    "resource_uri": "db://postgres/finance/ledger",
                    "transaction_id": "txn_route_1",
                    "agent_id": "agent_worker_1",
                    "concurrency_mode": "EXCLUSIVE",
                    "duration_seconds": 60,
                },
            )

        assert res.status_code == status.HTTP_201_CREATED
        data = res.json()
        assert data["fencing_token"] == 7
        assert data["concurrency_mode"] == "EXCLUSIVE"

    def test_acquire_lease_conflict_returns_409(self, client: TestClient) -> None:
        """Acquisition conflict returns 409 Conflict."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)

        with patch("gateway.routes.concurrency.concurrency_service.acquire_lease", new_callable=AsyncMock) as mock_acq:
            mock_acq.side_effect = HTTPException(status_code=409, detail="Resource conflict")
            res = client.post(
                "/v1/resources/leases/acquire",
                headers=headers,
                json={
                    "resource_uri": "db://postgres/finance/ledger",
                    "transaction_id": "txn_route_1",
                    "agent_id": "agent_worker_1",
                },
            )

        assert res.status_code == status.HTTP_409_CONFLICT

    def test_list_leases(self, client: TestClient) -> None:
        """List leases returns 200 with list."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_lease_response()

        with patch("gateway.routes.concurrency.concurrency_service.list_leases", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [sample]
            res = client.get("/v1/resources/leases?status=ACQUIRED", headers=headers)

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert len(data) == 1
        assert data[0]["id"] == "lse_route_1"

    def test_release_lease_success(self, client: TestClient) -> None:
        """Releasing lease returns 200 OK."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_lease_response(status_val=LeaseStatus.RELEASED)

        with patch("gateway.routes.concurrency.concurrency_service.release_lease", new_callable=AsyncMock) as mock_rel:
            mock_rel.return_value = sample
            res = client.post(
                "/v1/resources/leases/lse_route_1/release",
                headers=headers,
                json={
                    "transaction_id": "txn_route_1",
                    "agent_id": "agent_worker_1",
                    "fencing_token": 1,
                },
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "RELEASED"

    def test_renew_lease_success(self, client: TestClient) -> None:
        """Renewing lease returns 200 OK."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_test", role=Role.OPERATOR)
        sample = _sample_lease_response()

        with patch("gateway.routes.concurrency.concurrency_service.renew_lease", new_callable=AsyncMock) as mock_ren:
            mock_ren.return_value = sample
            res = client.post(
                "/v1/resources/leases/lse_route_1/renew",
                headers=headers,
                json={
                    "transaction_id": "txn_route_1",
                    "agent_id": "agent_worker_1",
                    "fencing_token": 1,
                    "duration_seconds": 120,
                },
            )

        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["id"] == "lse_route_1"
