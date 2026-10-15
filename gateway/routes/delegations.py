"""Cross-Agent Delegation Governance REST endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from gateway.middleware.auth import get_current_auth
from services.delegation_service import delegation_service
from shared.schemas.auth import AuthContext
from shared.schemas.control_plane import PolicyDecision
from shared.schemas.delegation import (
    DelegationActivationRequest,
    DelegationGrantRequest,
    DelegationGrantResponse,
    DelegationOperationValidationRequest,
    DelegationRevocationRequest,
    DelegationStatus,
)

router = APIRouter(prefix="/v1", tags=["Delegation Governance"])


@router.post("/delegations", response_model=DelegationGrantResponse, status_code=status.HTTP_201_CREATED)
async def create_delegation_endpoint(
    req: DelegationGrantRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> DelegationGrantResponse:
    """Create a new pending delegation grant after strict authority attenuation and confinement checks."""
    return await delegation_service.create_delegation_grant(auth=auth, request=req)


@router.get("/delegations/{delegation_id}", response_model=DelegationGrantResponse)
async def get_delegation_endpoint(
    delegation_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> DelegationGrantResponse:
    """Retrieve an authoritative delegation grant by ID within the caller's tenant."""
    return await delegation_service.get_delegation_grant(auth=auth, delegation_id=delegation_id)


@router.get("/delegations", response_model=list[DelegationGrantResponse])
async def list_delegations_endpoint(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    status: DelegationStatus | None = Query(default=None, description="Optional status filter"),
    parent_transaction_id: str | None = Query(default=None, description="Optional parent transaction filter"),
    child_agent_id: str | None = Query(default=None, description="Optional child agent filter"),
    limit: int = Query(default=50, ge=1, le=100, description="Page limit (1-100)"),
    offset: int = Query(default=0, ge=0, description="Page offset (>=0)"),
) -> list[DelegationGrantResponse]:
    """List delegation grants for the caller's tenant with safe filtering and pagination."""
    return await delegation_service.list_delegation_grants(
        auth=auth,
        status_filter=status,
        parent_transaction_id=parent_transaction_id,
        child_agent_id=child_agent_id,
        limit=limit,
        offset=offset,
    )


@router.post("/delegations/{delegation_id}/activate", response_model=DelegationGrantResponse)
async def activate_delegation_endpoint(
    delegation_id: str,
    req: DelegationActivationRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> DelegationGrantResponse:
    """Atomically bind a pending delegation grant to a child transaction and transition to ACTIVE."""
    return await delegation_service.activate_delegation_grant(
        auth=auth,
        delegation_id=delegation_id,
        child_transaction_id=req.child_transaction_id,
    )


@router.post("/delegations/{delegation_id}/revoke", response_model=DelegationGrantResponse)
async def revoke_delegation_endpoint(
    delegation_id: str,
    req: DelegationRevocationRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> DelegationGrantResponse:
    """Explicitly revoke an active or pending delegation grant with required audit reason."""
    return await delegation_service.revoke_delegation_grant(
        auth=auth,
        delegation_id=delegation_id,
        reason=req.reason,
    )


@router.post("/delegations/{delegation_id}/validate", response_model=PolicyDecision)
async def validate_delegation_operation_endpoint(
    delegation_id: str,
    req: DelegationOperationValidationRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> PolicyDecision:
    """Evaluate whether an active delegation grant authorizes a specific operation and scope."""
    return await delegation_service.validate_delegation_for_operation(
        auth=auth,
        delegation_id=delegation_id,
        capability_type=req.capability_type,
        resource=req.resource,
        requested_autonomy_level=req.requested_autonomy_level,
    )
