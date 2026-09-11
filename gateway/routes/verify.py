"""Direct verification endpoint (POST /v1/verify) wired to VerificationOrchestrator."""

from typing import Annotated

from fastapi import APIRouter, Depends

from gateway.middleware.auth import get_current_tenant
from gateway.middleware.rate_limiter import rate_limiter
from shared.logging import get_logger
from shared.schemas import VerificationRequest, VerificationResponse
from workers.orchestrator import VerificationOrchestrator

router = APIRouter(prefix="/v1", tags=["Verification"])
logger = get_logger("verify_route")
orchestrator = VerificationOrchestrator()


@router.post("/verify", response_model=VerificationResponse)
async def verify_completion(
    request: VerificationRequest,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> VerificationResponse:
    """Verify factual consistency and hallucination risk of a generated completion."""
    # Enforce rate limits
    rate_limiter.check_rate_limit(tenant_id)

    logger.info("Executing verification request via orchestrator", tenant_id=tenant_id)
    return await orchestrator.verify_request(request)
