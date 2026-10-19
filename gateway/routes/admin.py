"""Admin API routes for Tenant Lifecycle Management."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from gateway.middleware.auth import get_current_auth
from services.tenant_service import tenant_service
from shared.schemas.auth import AuthContext
from shared.schemas.tenant import (
    TenantCreateRequest,
    TenantListResponse,
    TenantResponse,
    TenantSuspendRequest,
    TenantUpdateRequest,
)

router = APIRouter(prefix="/v1/admin", tags=["Tenant Administration"])


@router.get("/tenants", response_model=TenantListResponse)
async def list_tenants(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> TenantListResponse:
    """List tenants within the caller's authorized administrative scope."""
    return await tenant_service.list_tenants(auth=auth, limit=limit, cursor=cursor)


@router.post("/tenants", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    req: TenantCreateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> TenantResponse:
    """Provision a new tenant account with default identity, audit ledger, and budget (SUPER_ADMIN only)."""
    return await tenant_service.create_tenant(auth=auth, req=req)


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> TenantResponse:
    """Retrieve details for a specific tenant account."""
    return await tenant_service.get_tenant(auth=auth, tenant_id=tenant_id)


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: str,
    req: TenantUpdateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> TenantResponse:
    """Update permitted configuration settings for a tenant."""
    return await tenant_service.update_tenant(auth=auth, tenant_id=tenant_id, req=req)


@router.post("/tenants/{tenant_id}/suspend", response_model=TenantResponse)
async def suspend_tenant(
    tenant_id: str,
    req: TenantSuspendRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> TenantResponse:
    """Suspend a tenant account and enforce immediate authentication boundary cutoff (SUPER_ADMIN only)."""
    return await tenant_service.suspend_tenant(auth=auth, tenant_id=tenant_id, reason=req.reason)


@router.post("/tenants/{tenant_id}/reactivate", response_model=TenantResponse)
async def reactivate_tenant(
    tenant_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> TenantResponse:
    """Reactivate a suspended tenant account (SUPER_ADMIN only)."""
    return await tenant_service.reactivate_tenant(auth=auth, tenant_id=tenant_id)


@router.post("/tenants/{tenant_id}/offboard", response_model=TenantResponse)
async def offboard_tenant(
    tenant_id: str,
    req: TenantSuspendRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> TenantResponse:
    """Soft-offboard a tenant with permanent API key revocation and immutable audit trail (SUPER_ADMIN only)."""
    return await tenant_service.offboard_tenant(auth=auth, tenant_id=tenant_id, reason=req.reason)
