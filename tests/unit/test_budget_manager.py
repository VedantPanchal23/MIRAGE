"""Unit tests for MIRAGE 3.0 Budget Manager service and API routes."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from gateway.main import app
from services.budget_manager import budget_manager_service
from shared.schemas.auth import Role
from shared.schemas.budget import (
    BudgetReservationRequest,
    BudgetResetPeriod,
    BudgetSettlementRequest,
    ReservationStatus,
)
from tests.auth_factory import AuthTestFactory


@pytest.mark.unit
@pytest.mark.asyncio
async def test_budget_manager_get_and_update_tenant_budget() -> None:
    """Verify tenant budget creation, retrieval, and updating."""
    tenant_id = f"t_bm_test_{uuid.uuid4().hex[:8]}"

    # Default creation
    budget = await budget_manager_service.get_tenant_budget(tenant_id)
    assert budget.tenant_id == tenant_id
    assert budget.total_budget_micros == 100_000_000  # $100 default
    assert budget.spent_micros == 0
    assert budget.reserved_micros == 0
    assert budget.available_micros == 100_000_000
    assert budget.hard_limit is True

    # Update limit
    updated = await budget_manager_service.update_tenant_budget(
        tenant_id=tenant_id,
        total_budget_micros=250_000_000,
        hard_limit=True,
        reset_period=BudgetResetPeriod.MONTHLY,
    )
    assert updated.total_budget_micros == 250_000_000
    assert updated.available_micros == 250_000_000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_budget_manager_reserve_settle_lifecycle() -> None:
    """Verify complete atomic reservation and settlement lifecycle."""
    tenant_id = f"t_res_set_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_{uuid.uuid4().hex[:12]}"
    res_key = f"key_{uuid.uuid4().hex[:8]}"

    # Initial budget: set to 10,000 micros ($0.01)
    await budget_manager_service.update_tenant_budget(
        tenant_id=tenant_id,
        total_budget_micros=10_000,
        hard_limit=True,
    )

    # 1. Reserve 4,000 micros
    res_req = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id=tx_id,
        estimated_cost_micros=4_000,
        reservation_key=res_key,
        timeout_seconds=300,
    )
    reservation = await budget_manager_service.reserve_budget(res_req)
    assert reservation.amount_micros == 4_000
    assert reservation.status == ReservationStatus.RESERVED

    # Check budget headroom
    b1 = await budget_manager_service.get_tenant_budget(tenant_id)
    assert b1.reserved_micros == 4_000
    assert b1.spent_micros == 0
    assert b1.available_micros == 6_000

    # 2. Idempotent reservation replay
    replay = await budget_manager_service.reserve_budget(res_req)
    assert replay.id == reservation.id
    assert replay.amount_micros == 4_000

    # 3. Settle with actual cost of 3,200 micros
    set_req = BudgetSettlementRequest(
        reservation_id=reservation.id,
        actual_cost_micros=3_200,
        model_id="mock-capable",
        provider="mock",
        prompt_tokens=100,
        completion_tokens=50,
        cached_tokens=0,
        stage="PRIMARY_INFERENCE",
    )
    cost_record = await budget_manager_service.settle_budget(tenant_id, set_req)
    assert cost_record.cost_micros == 3_200
    assert cost_record.transaction_id == tx_id
    assert cost_record.model_id == "mock-capable"

    # Check budget after settlement: reserved should be 0, spent 3,200, available 6,800
    b2 = await budget_manager_service.get_tenant_budget(tenant_id)
    assert b2.reserved_micros == 0
    assert b2.spent_micros == 3_200
    assert b2.available_micros == 6_800


@pytest.mark.unit
@pytest.mark.asyncio
async def test_budget_manager_hard_limit_rejection() -> None:
    """Preflight reservation must fail closed with 402 when budget headroom is exceeded."""
    tenant_id = f"t_exh_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_{uuid.uuid4().hex[:12]}"

    # Set total budget to 5,000 micros
    await budget_manager_service.update_tenant_budget(
        tenant_id=tenant_id,
        total_budget_micros=5_000,
        hard_limit=True,
    )

    # Attempt to reserve 8,000 micros -> 402 Payment Required
    res_req = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id=tx_id,
        estimated_cost_micros=8_000,
        reservation_key="key_exceed",
    )
    with pytest.raises(HTTPException) as exc_info:
        await budget_manager_service.reserve_budget(res_req)
    assert exc_info.value.status_code == 402
    assert "Budget limit exceeded" in str(exc_info.value.detail)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_budget_manager_release_reservation() -> None:
    """Releasing reservation restores headroom without recording spend."""
    tenant_id = f"t_rel_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_{uuid.uuid4().hex[:12]}"

    await budget_manager_service.update_tenant_budget(
        tenant_id=tenant_id,
        total_budget_micros=20_000,
        hard_limit=True,
    )

    res_req = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id=tx_id,
        estimated_cost_micros=7_500,
        reservation_key="key_release",
    )
    res = await budget_manager_service.reserve_budget(res_req)

    # Check reservation holds funds
    b1 = await budget_manager_service.get_tenant_budget(tenant_id)
    assert b1.reserved_micros == 7_500
    assert b1.available_micros == 12_500

    # Release reservation
    await budget_manager_service.release_reservation(tenant_id, res.id)

    # Headroom restored
    b2 = await budget_manager_service.get_tenant_budget(tenant_id)
    assert b2.reserved_micros == 0
    assert b2.spent_micros == 0
    assert b2.available_micros == 20_000


@pytest.mark.unit
@pytest.mark.asyncio
async def test_budget_manager_reconciles_orphaned_reservations() -> None:
    """Expired reservations are reconciled and reserved balance returned to tenant."""
    tenant_id = f"t_rec_{uuid.uuid4().hex[:8]}"
    tx_id = f"tx_{uuid.uuid4().hex[:12]}"

    await budget_manager_service.update_tenant_budget(
        tenant_id=tenant_id,
        total_budget_micros=50_000,
        hard_limit=True,
    )

    # Create reservation with timeout of 10 seconds
    res_req = BudgetReservationRequest(
        tenant_id=tenant_id,
        transaction_id=tx_id,
        estimated_cost_micros=15_000,
        reservation_key="key_orphan",
        timeout_seconds=10,
    )
    res = await budget_manager_service.reserve_budget(res_req)

    b1 = await budget_manager_service.get_tenant_budget(tenant_id)
    assert b1.reserved_micros == 15_000

    # Manually backdate expiration in DB to simulate timeout
    from sqlalchemy import update

    from db import session as db_session
    from db.models import BudgetReservationRecord

    async with db_session.get_system_session() as session:
        past_time = datetime.now(UTC) - timedelta(minutes=10)
        await session.execute(
            update(BudgetReservationRecord).where(BudgetReservationRecord.id == res.id).values(expires_at=past_time)
        )
        await session.commit()

    # Run reconciliation sweep
    reconciled_count = await budget_manager_service.reconcile_orphaned_reservations()
    assert reconciled_count >= 1

    # Check tenant budget restored
    b2 = await budget_manager_service.get_tenant_budget(tenant_id)
    assert b2.reserved_micros == 0
    assert b2.available_micros == 50_000


@pytest.mark.unit
def test_budget_api_endpoints() -> None:
    """Test /v1/budgets/tenant and /v1/budgets/reconcile HTTP endpoints with authentication."""
    tenant_id = "default_tenant"
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
    client = TestClient(app)

    # 1. GET /v1/budgets/tenant
    resp = client.get("/v1/budgets/tenant", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant_id"] == tenant_id
    assert "total_budget_micros" in data
    assert "available_micros" in data

    # 2. PUT /v1/budgets/tenant
    update_payload = {
        "total_budget_micros": 500_000_000,
        "hard_limit": True,
        "reset_period": "MONTHLY",
    }
    resp = client.put("/v1/budgets/tenant", json=update_payload, headers=headers)
    assert resp.status_code == 200
    updated_data = resp.json()
    assert updated_data["total_budget_micros"] == 500_000_000
    assert updated_data["hard_limit"] is True

    # 3. Viewer cannot update budget (403 Forbidden)
    viewer_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.VIEWER)
    resp = client.put("/v1/budgets/tenant", json=update_payload, headers=viewer_headers)
    assert resp.status_code == 403
