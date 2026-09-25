"""Audit, Compliance Verification, and Operator Query Routes.

Implements PRD FR-AUD-01..04 & Security & Access Document §10:
- POST /v1/audit/verify-chain: Cryptographic SHA-256 hash chain verification
- GET /v1/audit/report/{session_id}: Exportable compliance audit report
- GET /v1/audit/export: GDPR Right to Portability (JSONL export)
- POST /v1/audit/query: Natural language operator query
"""

from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from analytics.audit_service import AuditService
from gateway.middleware.rbac import Permission, require_permission
from shared.logging import get_logger

router = APIRouter(prefix="/v1/audit", tags=["Audit & Compliance"])
logger = get_logger("audit_routes")


class NLQueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query text, e.g. 'Show critical risk sessions'")


@router.post("/verify-chain")
async def verify_audit_chain(
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    """Verify the cryptographic SHA-256 hash chain across all audit logs for the calling tenant."""
    try:
        res = await AuditService.verify_audit_hash_chain_authoritative(tenant_id=tenant_id)
        if res.get("chain_status") != "EMPTY" or not res.get("valid"):
            return res
    except Exception as exc:
        logger.warning("PostgreSQL audit chain check unavailable, falling back to local store", error=str(exc))

    return AuditService.verify_audit_hash_chain(tenant_id=tenant_id)


@router.get("/report/{session_id}")
async def get_compliance_report(
    session_id: str,
    _tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    """Generate a compliance verification certificate and report for an inspected session."""
    report = AuditService.generate_compliance_report(session_id=session_id)
    return report


@router.get("/report/{session_id}/pdf")
async def get_compliance_report_pdf(
    session_id: str,
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> Response:
    """Generate and stream a single-session compliance verification certificate as PDF."""
    from analytics.pdf_service import default_pdf_generator
    from db.persistence import default_persistence_service

    session_record = None
    claims_records = []
    try:
        session_record, claims_records = await default_persistence_service.get_session_with_claims(
            tenant_id=tenant_id, session_id=session_id
        )
    except Exception as exc:
        logger.warning("Postgres lookup for session certificate fallback", error=str(exc))

    if session_record:
        session_data = {
            "session_id": session_record.session_id,
            "tenant_id": session_record.tenant_id,
            "model_id": session_record.model_id,
            "timestamp": session_record.created_at.isoformat() if session_record.created_at else "",
            "hrs_score": session_record.hrs_score,
            "risk_tier": session_record.risk_tier,
            "correction_applied": session_record.correction_applied,
            "claims": [
                {
                    "text": c.claim_text,
                    "status": c.status,
                    "risk_score": c.risk_score,
                }
                for c in claims_records
            ],
            "signal_attribution": claims_records[0].signal_attribution if claims_records else {},
        }
    else:
        session_data = AuditService.generate_compliance_report(session_id=session_id)

    pdf_bytes = default_pdf_generator.generate_session_certificate_pdf(session_data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate_{session_id}.pdf"'},
    )


@router.get("/export")
async def export_tenant_audit_logs(
    tenant_id: str = Depends(require_permission(Permission.AUDIT_EXPORT)),
) -> Response:
    """Export all audit logs and verification records for tenant in JSON Lines format (GDPR Art. 20)."""
    lines: list[str] = []
    try:
        lines = await AuditService.export_tenant_data_jsonl_authoritative(tenant_id=tenant_id)
    except Exception as exc:
        logger.warning("PostgreSQL export query failed, checking local store", error=str(exc))

    if not lines:
        lines = AuditService.export_tenant_data_jsonl(tenant_id=tenant_id)

    jsonl_content = "\n".join(lines)
    return Response(
        content=jsonl_content,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f"attachment; filename=mirage_audit_{tenant_id}.jsonl",
        },
    )


@router.post("/query")
async def query_audit_logs(
    request: NLQueryRequest,
    tenant_id: str = Depends(require_permission(Permission.AUDIT_READ)),
) -> dict[str, Any]:
    """Natural language query endpoint for searching audit records (PRD FR-AUD-03)."""
    matches = AuditService.natural_language_query(query=request.query, tenant_id=tenant_id)
    return {
        "query": request.query,
        "tenant_id": tenant_id,
        "total_matches": len(matches),
        "results": matches,
    }
