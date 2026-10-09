"""Gate 3 Action Assurance, Tool Governance, and Action Contract REST endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from db import session as db_session
from db.models import ActionContract
from gateway.middleware.auth import get_current_auth
from services.action_governor import ActionGovernorService
from shared.schemas.action import (
    ActionAuthorizationDecision,
    ActionBatchProposal,
    ActionExecutionRequest,
    ActionExecutionResult,
    ActionProposal,
    ApprovalDecisionRequest,
    ApprovalResponse,
    BatchAuthorizationDecision,
    ToolRegistrationRequest,
    ToolResponse,
)
from shared.schemas.auth import AuthContext

router = APIRouter(prefix="/v1", tags=["Action Assurance & Tool Governance"])
governor_service = ActionGovernorService()


# -----------------------------------------------------------------------------
# Tool Registry Endpoints
# -----------------------------------------------------------------------------

@router.post("/tools", response_model=ToolResponse, status_code=201)
async def register_tool_endpoint(
    req: ToolRegistrationRequest, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> ToolResponse:
    """Register or update a governed tool with egress classification and capability requirements."""
    return await governor_service.register_tool(auth, req)


@router.get("/tools", response_model=list[ToolResponse])
async def list_tools_endpoint(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    active_only: bool = Query(default=True),
) -> list[ToolResponse]:
    """List registered tools for the authorized tenant."""
    return await governor_service.list_tools(auth, active_only=active_only)


# -----------------------------------------------------------------------------
# Gate 3 Action Assurance & Proposal Endpoints
# -----------------------------------------------------------------------------

@router.post("/actions/propose", response_model=ActionAuthorizationDecision)
async def propose_action_endpoint(
    req: ActionProposal, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> ActionAuthorizationDecision:
    """Propose an action contract and evaluate Gate 3 Action Assurance controls."""
    return await governor_service.propose_and_authorize_action(auth, req)


@router.post("/actions/authorize", response_model=ActionAuthorizationDecision)
async def authorize_action_endpoint(
    req: ActionProposal, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> ActionAuthorizationDecision:
    """Evaluate Gate 3 Action Assurance controls without immediate tool execution."""
    return await governor_service.propose_and_authorize_action(auth, req)


@router.post("/actions/batch", response_model=BatchAuthorizationDecision)
async def batch_propose_endpoint(
    req: ActionBatchProposal, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> BatchAuthorizationDecision:
    """Evaluate an atomic batch of parallel actions under all-or-nothing semantics."""
    return await governor_service.propose_and_authorize_batch(auth, req)


@router.get("/actions/{action_id}")
async def get_action_contract_endpoint(
    action_id: str, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> dict[str, Any]:
    """Inspect the lifecycle state, parameters hash, and audit details of an Action Contract."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = select(ActionContract).where(
            ActionContract.tenant_id == auth.tenant_id,
            ActionContract.id == action_id,
        )
        res = await session.execute(stmt)
        contract = res.scalar_one_or_none()
        if not contract:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action contract not found")

        return {
            "id": contract.id,
            "tenant_id": contract.tenant_id,
            "transaction_id": contract.transaction_id,
            "tool_name": contract.tool_name,
            "action_type": contract.action_type,
            "target_resource": contract.target_resource,
            "parameters": contract.normalized_parameters,
            "parameters_hash": contract.parameters_hash,
            "required_capability": contract.required_capability,
            "risk_score": contract.risk_score,
            "blast_radius": contract.blast_radius,
            "state": contract.state,
            "approval_id": contract.approval_id,
            "observed_result": contract.observed_result,
            "error_message": contract.error_message,
            "created_at": contract.created_at.isoformat(),
            "authorized_at": contract.authorized_at.isoformat() if contract.authorized_at else None,
            "completed_at": contract.completed_at.isoformat() if contract.completed_at else None,
        }


# -----------------------------------------------------------------------------
# Tool Proxy Execution Endpoints
# -----------------------------------------------------------------------------

@router.post("/actions/execute", response_model=ActionExecutionResult)
async def execute_action_endpoint(
    req: ActionExecutionRequest, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> ActionExecutionResult:
    """Execute an authorized action contract strictly through the Tool Proxy."""
    return await governor_service.execute_action(auth, req)


# -----------------------------------------------------------------------------
# Human Approval (L4) Endpoints
# -----------------------------------------------------------------------------

@router.get("/approvals/pending", response_model=list[ApprovalResponse])
async def list_pending_approvals_endpoint(
    auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> list[ApprovalResponse]:
    """List pending L4 human approvals for the authorized tenant."""
    return await governor_service.list_pending_approvals(auth)


@router.post("/approvals/{approval_id}/grant", response_model=ApprovalResponse)
async def grant_approval_endpoint(
    approval_id: str,
    req: ApprovalDecisionRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> ApprovalResponse:
    """Grant a pending human approval ticket. Agents cannot self-grant approvals."""
    return await governor_service.grant_approval(auth, approval_id, req.reason)


@router.post("/approvals/{approval_id}/deny", response_model=ApprovalResponse)
async def deny_approval_endpoint(
    approval_id: str,
    req: ApprovalDecisionRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> ApprovalResponse:
    """Deny a pending human approval ticket."""
    return await governor_service.deny_approval(auth, approval_id, req.reason)
