"""Session Inspection REST Endpoints.

Implements Technical Architecture §8.2, PRD FR-AUD-01, and ADR 0005:
- GET /v1/sessions/{session_id}: Authoritative session retrieval from PostgreSQL,
  enriched with unstructured execution trace from MongoDB.
- Graceful degradation with X-Trace-Status: DEGRADED if MongoDB is unavailable.
- Strict multi-tenant isolation and IDOR protection.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from db.mongo import default_mongo_trace_service
from db.persistence import default_persistence_service
from gateway.middleware.auth import get_current_auth
from shared.logging import get_logger
from shared.schemas.auth import AuthContext, Permission, Role

router = APIRouter(prefix="/v1/sessions", tags=["Sessions"])
logger = get_logger("sessions_routes")


@router.get("/{session_id}")
async def get_session_by_id(
    session_id: str,
    response: Response,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> dict[str, Any]:
    """Retrieve complete verification session details, claim assertions, and deep trace."""
    # Check permissions (VERIFY_READ, AUDIT_READ, or SUPER_ADMIN)
    if (
        auth.role != Role.SUPER_ADMIN
        and Permission.VERIFY_READ not in auth.role.value
        and Permission.AUDIT_READ not in auth.role.value
    ):
        # Fallback to granular check if role mappings apply
        from shared.schemas.auth import ROLE_PERMISSIONS

        allowed_perms = ROLE_PERMISSIONS.get(auth.role, set())
        if Permission.VERIFY_READ not in allowed_perms and Permission.AUDIT_READ not in allowed_perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden: Insufficient permissions to view session records",
            )

    tenant_id = auth.tenant_id
    logger.info("Retrieving session record", session_id=session_id, tenant_id=tenant_id)

    # 1. Authoritative PostgreSQL retrieval (Session + Claims)
    session_record = None
    claims_records = []
    try:
        session_record, claims_records = await default_persistence_service.get_session_with_claims(
            tenant_id=tenant_id, session_id=session_id
        )
    except Exception as exc:
        logger.error("Authoritative PostgreSQL query error", error=str(exc), session_id=session_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authoritative persistence service temporarily unavailable",
        ) from exc

    if not session_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification session '{session_id}' not found for tenant",
        )

    # 2. Enrich with MongoDB execution trace
    trace_data: dict[str, Any] | None = None
    try:
        trace_data = await default_mongo_trace_service.get_trace_by_session_id(
            tenant_id=tenant_id, session_id=session_id
        )
        if not trace_data and session_record.trace_id:
            trace_data = await default_mongo_trace_service.get_trace_by_trace_id(
                tenant_id=tenant_id, trace_id=session_record.trace_id
            )
        response.headers["X-Trace-Status"] = "AVAILABLE" if trace_data else "NOT_FOUND"
    except Exception as exc:
        logger.warning(
            "MongoDB trace retrieval failed; degrading gracefully",
            session_id=session_id,
            tenant_id=tenant_id,
            error=str(exc),
        )
        response.headers["X-Trace-Status"] = "DEGRADED"
        trace_data = None

    # Format claims list
    formatted_claims = [
        {
            "id": c.id,
            "session_id": c.session_id,
            "tenant_id": c.tenant_id,
            "claim_text": c.claim_text,
            "claim_type": c.claim_type,
            "criticality": c.criticality,
            "criticality_weight": c.criticality_weight,
            "rav_score": c.rav_score,
            "scs_score": c.scs_score,
            "nli_score": c.nli_score,
            "ics_score": c.ics_score,
            "vgs_score": c.vgs_score,
            "risk_score": c.risk_score,
            "status": c.status,
            "signal_attribution": c.signal_attribution,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in claims_records
    ]

    return {
        "session_id": session_record.session_id,
        "tenant_id": session_record.tenant_id,
        "trace_id": session_record.trace_id,
        "model_id": session_record.model_id,
        "prompt_hash": session_record.prompt_hash,
        "response_hash": session_record.response_hash,
        "hrs_score": session_record.hrs_score,
        "risk_tier": session_record.risk_tier,
        "correction_applied": session_record.correction_applied,
        "created_at": session_record.created_at.isoformat() if session_record.created_at else None,
        "claims": formatted_claims,
        "trace": trace_data,
    }
