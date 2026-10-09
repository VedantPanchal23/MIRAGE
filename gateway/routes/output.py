"""Gate 4 Output Assurance API routes.

Implements Input_Output_Assurance.md §5, API_Specification.md §4, and Security.md §3.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from gateway.middleware.auth import get_current_auth
from gateway.middleware.rate_limiter import rate_limiter
from services.output_assurance import output_assurance_service
from shared.logging import get_logger
from shared.schemas.auth import ROLE_PERMISSIONS, AuthContext, Permission
from shared.schemas.output import OutputAssuranceContract, OutputAssuranceRequest

router = APIRouter(prefix="/v1/output", tags=["Output Assurance"])
logger = get_logger("output_assurance_route")


@router.post("/assure", response_model=OutputAssuranceContract)
async def assure_output_endpoint(
    request: OutputAssuranceRequest,
    http_req: Request,
    http_resp: Response,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> OutputAssuranceContract:
    """Evaluate and assure AI generated completion at Gate 4 before release."""
    # 1. RBAC check: Caller must have VERIFY_WRITE permission
    allowed_permissions = ROLE_PERMISSIONS.get(auth.role, set())
    if Permission.VERIFY_WRITE not in allowed_permissions:
        logger.warning(
            "Access denied: role lacks verify:write for Gate 4",
            tenant_id=auth.tenant_id,
            role=auth.role.value,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Role '{auth.role.value}' lacks permission '{Permission.VERIFY_WRITE.value}'",
        )

    # 2. Rate limiting check per tenant
    tier = getattr(auth, "tier", "free")
    rl_res = await rate_limiter.check_rate_limit(auth.tenant_id, tier=tier)
    http_resp.headers["X-RateLimit-Limit"] = str(rl_res.limit)
    http_resp.headers["X-RateLimit-Remaining"] = str(rl_res.remaining)
    http_resp.headers["X-RateLimit-Reset"] = str(rl_res.reset_time)

    # 3. Authoritative tenant context
    http_req.state.tenant_id = auth.tenant_id
    http_req.state.role = auth.role.value

    logger.info("Executing Gate 4 Output Assurance", tenant_id=auth.tenant_id, txn_id=request.transaction_id)
    return await output_assurance_service.assure_output(request, auth)


@router.get("/{output_id}", response_model=dict[str, Any])
async def get_output_assurance_endpoint(
    output_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> dict[str, Any]:
    """Retrieve persisted Gate 4 Output Assurance record by ID with strict tenant scoping."""
    allowed_permissions = ROLE_PERMISSIONS.get(auth.role, set())
    if Permission.VERIFY_READ not in allowed_permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Role '{auth.role.value}' lacks permission '{Permission.VERIFY_READ.value}'",
        )

    record = await output_assurance_service.get_output_assurance_record(output_id, auth)
    return {
        "id": record.id,
        "tenant_id": record.tenant_id,
        "transaction_id": record.transaction_id,
        "model_id": record.model_id,
        "model_version": record.model_version,
        "original_output": record.original_output,
        "final_output": record.final_output,
        "output_hash": record.output_hash,
        "verification_status": record.verification_status,
        "final_decision": record.final_decision,
        "risk_tier": record.risk_tier,
        "risk_score": record.risk_score,
        "conformal_bounds": record.conformal_bounds,
        "signal_attributions": record.signal_attributions,
        "claims": record.claims_payload,
        "safety_result": record.safety_result,
        "factual_result": record.factual_result,
        "budget_consumed": record.budget_consumed,
        "tier_path": record.tier_path,
        "escalation_reasons": record.escalation_reasons,
        "was_corrected": record.was_corrected,
        "correction_history": record.correction_history,
        "audit_hash": record.audit_hash,
        "created_at": record.created_at.isoformat(),
        "verified_at": record.verified_at.isoformat(),
    }
