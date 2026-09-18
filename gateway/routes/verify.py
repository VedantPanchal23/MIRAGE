"""Direct verification endpoint (POST /v1/verify) wired to VerificationOrchestrator.

Implements Security & Access Document §2.1, §3.1, §13.2:
- Mandatory cryptographic authentication
- Strict tenant binding (authenticated tenant is authoritative, prevents cross-tenant IDOR)
- RBAC enforcement (VERIFY_WRITE permission required)
- Tiered rate limiting per authenticated tenant
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from gateway.middleware.auth import get_current_auth
from gateway.middleware.rate_limiter import rate_limiter
from shared.logging import get_logger
from shared.schemas.auth import ROLE_PERMISSIONS, AuthContext, Permission
from shared.schemas.verification import VerificationRequest, VerificationResponse
from workers.orchestrator import VerificationOrchestrator

router = APIRouter(prefix="/v1", tags=["Verification"])
logger = get_logger("verify_route")
orchestrator = VerificationOrchestrator()


@router.post("/verify", response_model=VerificationResponse)
async def verify_completion(
    request: VerificationRequest,
    http_req: Request,
    http_resp: Response,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> VerificationResponse:
    """Verify factual consistency and hallucination risk of a generated completion."""
    # 1. RBAC Check: Ensure caller possesses VERIFY_WRITE permission
    allowed_permissions = ROLE_PERMISSIONS.get(auth.role, set())
    if Permission.VERIFY_WRITE not in allowed_permissions:
        logger.warning(
            "Access denied: role lacks verify:write",
            tenant_id=auth.tenant_id,
            role=auth.role.value,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Role '{auth.role.value}' lacks permission '{Permission.VERIFY_WRITE.value}'",
        )

    # 2. Strict Tenant Binding: Authenticated tenant is strictly authoritative
    if request.tenant_id and request.tenant_id != auth.tenant_id:
        logger.warning(
            "Cross-tenant verification attempt rejected",
            authenticated_tenant=auth.tenant_id,
            payload_tenant=request.tenant_id,
            role=auth.role.value,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Mismatched tenant: authenticated as '{auth.tenant_id}', "
                f"but payload requested '{request.tenant_id}'. Cross-tenant operations are prohibited."
            ),
        )

    # 3. Authoritative binding onto payload and request state
    request.tenant_id = auth.tenant_id
    http_req.state.tenant_id = auth.tenant_id
    http_req.state.role = auth.role.value

    # 4. Enforce rate limits against authoritative tenant
    tier = getattr(auth, "tier", "free")
    rl_res = await rate_limiter.check_rate_limit(auth.tenant_id, tier=tier)
    http_resp.headers["X-RateLimit-Limit"] = str(rl_res.limit)
    http_resp.headers["X-RateLimit-Remaining"] = str(rl_res.remaining)
    http_resp.headers["X-RateLimit-Reset"] = str(rl_res.reset_time)

    logger.info("Executing verification request via orchestrator", tenant_id=auth.tenant_id)
    return await orchestrator.verify_request(request)
