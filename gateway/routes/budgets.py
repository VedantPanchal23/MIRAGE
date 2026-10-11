"""Tenant Budget and Cost Optimization API routes for MIRAGE 3.0."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from gateway.middleware.auth import get_current_auth
from services.budget_manager import budget_manager_service
from shared.schemas.auth import AuthContext, Role
from shared.schemas.budget import TenantBudget, TenantBudgetUpdateRequest

router = APIRouter(prefix="/v1/budgets", tags=["Budget Manager & Cost Optimization"])


@router.get(
    "/tenant",
    response_model=TenantBudget,
    summary="Get tenant budget ledger and remaining headroom",
)
async def get_tenant_budget(
    tenant_id: str | None = Query(default=None, description="Optional tenant ID (SUPER_ADMIN only)"),
    auth: AuthContext = Depends(get_current_auth),
) -> TenantBudget:
    """Retrieve tenant budget configuration, spent micros, reserved micros, and available headroom."""
    target_tenant = auth.tenant_id
    if tenant_id and tenant_id != auth.tenant_id:
        if auth.role != Role.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only SUPER_ADMIN can query budgets of other tenants",
            )
        target_tenant = tenant_id

    return await budget_manager_service.get_tenant_budget(target_tenant)


@router.put(
    "/tenant",
    response_model=TenantBudget,
    summary="Update tenant budget bounds and limits",
)
async def update_tenant_budget(
    request: TenantBudgetUpdateRequest,
    tenant_id: str | None = Query(default=None, description="Optional tenant ID (SUPER_ADMIN only)"),
    auth: AuthContext = Depends(get_current_auth),
) -> TenantBudget:
    """Configure total budget limit, hard limit enforcement, and reset cycle."""
    if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{auth.role.value}' is not authorized to update budget allocations",
        )

    target_tenant = auth.tenant_id
    if tenant_id and tenant_id != auth.tenant_id:
        if auth.role != Role.SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only SUPER_ADMIN can configure budgets for other tenants",
            )
        target_tenant = tenant_id

    return await budget_manager_service.update_tenant_budget(
        tenant_id=target_tenant,
        total_budget_micros=request.total_budget_micros,
        hard_limit=request.hard_limit,
        reset_period=request.reset_period,
    )


@router.post(
    "/reconcile",
    summary="Reconcile expired orphaned reservations",
)
async def reconcile_reservations(
    auth: AuthContext = Depends(get_current_auth),
) -> dict[str, int]:
    """Execute background sweep to release expired in-flight budget reservations."""
    if auth.role != Role.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only SUPER_ADMIN can trigger global reservation reconciliation sweeps",
        )
    count = await budget_manager_service.reconcile_orphaned_reservations()
    return {"reconciled_reservations": count}
