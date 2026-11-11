"""Shared-Resource Concurrency, Leases, and Fencing Tokens REST Endpoints."""

from fastapi import APIRouter, Query, status

from gateway.dependencies import Auth
from services.concurrency_service import concurrency_service
from shared.schemas.concurrency import (
    LeaseStatus,
    ResourceLeaseAcquireRequest,
    ResourceLeaseReleaseRequest,
    ResourceLeaseRenewRequest,
    ResourceLeaseResponse,
)

router = APIRouter(prefix="/v1/resources", tags=["Resource Concurrency"])


@router.post("/leases/acquire", response_model=ResourceLeaseResponse, status_code=status.HTTP_201_CREATED)
async def acquire_lease_endpoint(
    req: ResourceLeaseAcquireRequest,
    auth: Auth,
) -> ResourceLeaseResponse:
    """Acquire an exclusive or shared concurrency lease on a resource with a monotonic fencing token."""
    return await concurrency_service.acquire_lease(auth=auth, request=req)


@router.get("/leases", response_model=list[ResourceLeaseResponse])
async def list_leases_endpoint(
    auth: Auth,
    resource_uri: str | None = Query(default=None, description="Optional target resource URI filter"),
    holder_transaction_id: str | None = Query(default=None, description="Optional holder transaction ID filter"),
    status: LeaseStatus | None = Query(default=None, description="Optional lease status filter"),
    limit: int = Query(default=50, ge=1, le=100, description="Page limit (1-100)"),
    offset: int = Query(default=0, ge=0, description="Page offset (>=0)"),
) -> list[ResourceLeaseResponse]:
    """List resource leases for the caller's tenant with safe filtering and pagination."""
    return await concurrency_service.list_leases(
        auth=auth,
        resource_uri=resource_uri,
        holder_transaction_id=holder_transaction_id,
        status_filter=status,
        limit=limit,
        offset=offset,
    )


@router.post("/leases/{lease_id}/release", response_model=ResourceLeaseResponse)
async def release_lease_endpoint(
    lease_id: str,
    req: ResourceLeaseReleaseRequest,
    auth: Auth,
) -> ResourceLeaseResponse:
    """Safely release an acquired lease after verifying ownership and fencing token."""
    return await concurrency_service.release_lease(auth=auth, lease_id=lease_id, request=req)


@router.post("/leases/{lease_id}/renew", response_model=ResourceLeaseResponse)
async def renew_lease_endpoint(
    lease_id: str,
    req: ResourceLeaseRenewRequest,
    auth: Auth,
) -> ResourceLeaseResponse:
    """Extend the duration of an active lease before expiration."""
    return await concurrency_service.renew_lease(auth=auth, lease_id=lease_id, request=req)
