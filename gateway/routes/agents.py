"""Agent Lifecycle Governance and Management REST endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from gateway.middleware.auth import get_current_auth
from services.agent_governance import agent_governance_service
from shared.schemas.agent import (
    AgentListResponse,
    AgentRegistrationRequest,
    AgentResponse,
    AgentStatus,
    AgentTransitionRequest,
)
from shared.schemas.auth import AuthContext

router = APIRouter(prefix="/v1", tags=["Agent Governance"])


@router.post("/agents", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def register_agent_endpoint(
    req: AgentRegistrationRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AgentResponse:
    """Register a new governed agent within the caller's authenticated tenant."""
    return await agent_governance_service.register_agent(auth=auth, request=req)


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent_endpoint(
    agent_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AgentResponse:
    """Retrieve an agent by ID within the caller's authenticated tenant."""
    return await agent_governance_service.get_agent(auth=auth, agent_id=agent_id)


@router.get("/agents", response_model=AgentListResponse)
async def list_agents_endpoint(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    status: AgentStatus | None = Query(default=None, description="Optional status filter"),
    limit: int = Query(default=50, ge=1, le=100, description="Page limit (1-100)"),
    offset: int = Query(default=0, ge=0, description="Page offset (>=0)"),
) -> AgentListResponse:
    """List agents in the caller's tenant with bounded pagination and optional status filter."""
    return await agent_governance_service.list_agents(
        auth=auth,
        status_filter=status,
        limit=limit,
        offset=offset,
    )


@router.post("/agents/{agent_id}/activate", response_model=AgentResponse)
async def activate_agent_endpoint(
    agent_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    req: AgentTransitionRequest | None = None,
) -> AgentResponse:
    """Activate an agent within the caller's authenticated tenant."""
    reason = req.reason if req else "Agent activation"
    return await agent_governance_service.activate_agent(auth=auth, agent_id=agent_id, reason=reason)


@router.post("/agents/{agent_id}/suspend", response_model=AgentResponse)
async def suspend_agent_endpoint(
    agent_id: str,
    req: AgentTransitionRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AgentResponse:
    """Suspend an active agent within the caller's authenticated tenant with required reason."""
    return await agent_governance_service.suspend_agent(auth=auth, agent_id=agent_id, reason=req.reason)


@router.post("/agents/{agent_id}/revoke", response_model=AgentResponse)
async def revoke_agent_endpoint(
    agent_id: str,
    req: AgentTransitionRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> AgentResponse:
    """Permanently revoke an agent within the caller's authenticated tenant with required reason."""
    return await agent_governance_service.revoke_agent(auth=auth, agent_id=agent_id, reason=req.reason)
