"""Model Routing and Model Registry API routes for MIRAGE 3.0."""

from fastapi import APIRouter, Depends, HTTPException, status

from gateway.middleware.auth import get_current_auth
from services.model_router import model_router_service
from shared.schemas.auth import AuthContext, Role
from shared.schemas.model_router import (
    ModelCapabilityProfile,
    RoutingDecision,
    RoutingRequest,
)

router = APIRouter(prefix="/v1/models", tags=["Model Router & Registry"])


@router.get(
    "",
    response_model=list[ModelCapabilityProfile],
    summary="List all registered models and capability profiles",
)
async def list_models(
    _auth: AuthContext = Depends(get_current_auth),
) -> list[ModelCapabilityProfile]:
    """Retrieve all operational AI models and their multi-dimensional capability profiles."""
    return await model_router_service.list_models()


@router.post(
    "/route",
    response_model=RoutingDecision,
    summary="Evaluate assurance constraints and select optimal model",
)
async def route_model(
    request: RoutingRequest,
    auth: AuthContext = Depends(get_current_auth),
) -> RoutingDecision:
    """Dynamically route request to optimal model enforcing Gate 1 taints, Gate 3 risk, and budgets."""
    if auth.role != Role.SUPER_ADMIN and request.tenant_id != auth.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant mismatch: Token tenant '{auth.tenant_id}' cannot route on behalf of '{request.tenant_id}'",
        )
    return await model_router_service.route(request)
