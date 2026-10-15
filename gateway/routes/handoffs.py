"""Cross-Agent Governed Handoff REST Endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from gateway.middleware.auth import get_current_auth
from services.handoff_service import handoff_service
from shared.schemas.auth import AuthContext
from shared.schemas.handoff import (
    AgentHandoffAcceptRequest,
    AgentHandoffAcceptResponse,
    AgentHandoffCancelRequest,
    AgentHandoffCreateRequest,
    AgentHandoffResponse,
    HandoffStatus,
)

router = APIRouter(prefix="/v1", tags=["Governed Handoffs"])


@router.post("/handoffs", response_model=AgentHandoffResponse, status_code=status.HTTP_201_CREATED)
async def create_handoff_endpoint(
    req: AgentHandoffCreateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AgentHandoffResponse:
    """Create a new governed agent handoff after ancestor delegation and eligibility validation."""
    return await handoff_service.create_handoff(auth=auth, request=req)


@router.get("/handoffs/{handoff_id}", response_model=AgentHandoffResponse)
async def get_handoff_endpoint(
    handoff_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AgentHandoffResponse:
    """Retrieve an authoritative agent handoff by ID within the caller's tenant."""
    return await handoff_service.get_handoff(auth=auth, handoff_id=handoff_id)


@router.get("/handoffs", response_model=list[AgentHandoffResponse])
async def list_handoffs_endpoint(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    status: HandoffStatus | None = Query(default=None, description="Optional handoff status filter"),
    parent_transaction_id: str | None = Query(default=None, description="Optional parent transaction filter"),
    child_agent_id: str | None = Query(default=None, description="Optional child agent filter"),
    limit: int = Query(default=50, ge=1, le=100, description="Page limit (1-100)"),
    offset: int = Query(default=0, ge=0, description="Page offset (>=0)"),
) -> list[AgentHandoffResponse]:
    """List agent handoffs for the caller's tenant with safe filtering and pagination."""
    return await handoff_service.list_handoffs(
        auth=auth,
        status_filter=status,
        parent_transaction_id=parent_transaction_id,
        child_agent_id=child_agent_id,
        limit=limit,
        offset=offset,
    )


@router.post("/handoffs/{handoff_id}/accept", response_model=AgentHandoffAcceptResponse)
async def accept_handoff_endpoint(
    handoff_id: str,
    req: AgentHandoffAcceptRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AgentHandoffAcceptResponse:
    """Accept a pending handoff, dynamically binding delegation authority and spawning the child transaction."""
    return await handoff_service.accept_handoff(auth=auth, handoff_id=handoff_id, request=req)


@router.post("/handoffs/{handoff_id}/cancel", response_model=AgentHandoffResponse)
async def cancel_handoff_endpoint(
    handoff_id: str,
    req: AgentHandoffCancelRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AgentHandoffResponse:
    """Cancel a pending agent handoff with an explicit audit reason."""
    return await handoff_service.cancel_handoff(auth=auth, handoff_id=handoff_id, request=req)
