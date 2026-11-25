"""GDPR Data Subject Access Request (DSAR) & Privacy Retention Routes for MIRAGE 3.0."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse

from db import session as db_session
from gateway.middleware.rbac import require_permission
from services.audit_ledger import AuditLedgerService
from services.compliance_dossier_service import ComplianceDossierService
from shared.config.settings import get_settings
from shared.schemas.auth import Permission

router = APIRouter(prefix="/v1/privacy", tags=["Privacy, GDPR & Compliance"])
_dossier_service = ComplianceDossierService()


@router.get("/retention")
async def get_privacy_retention_schedule(
    tenant_id: Annotated[str, Depends(require_permission(Permission.AUDIT_READ))],
) -> dict[str, Any]:
    """Return authoritative tenant data retention, PII handling, and WORM anchoring schedule."""
    settings = get_settings()
    return {
        "tenant_id": tenant_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "stores": {
            "postgresql_authoritative": {
                "isolation": "Row-Level Security (FORCE ROW LEVEL SECURITY, NOBYPASSRLS)",
                "retention_policy": "Active tenant lifetime; offboard revokes credentials cleanly",
            },
            "mongodb_execution_traces": {
                "ttl_days": settings.mongo_retention_days,
                "isolation": "Per-tenant collection partitioning",
            },
            "external_audit_anchors": {
                "backend": settings.audit_anchor_backend,
                "retention_days": settings.audit_anchor_retention_days,
                "immutability": (
                    "AWS S3 Object Lock COMPLIANCE mode"
                    if settings.audit_anchor_backend == "s3_object_lock"
                    else "Append-only HMAC-SHA256 JSONL files"
                ),
            },
        },
        "gdpr_rights_supported": [
            "Right to Access / Portability (/v1/privacy/export)",
            "Cryptographic Audit Ledger Export (/v1/audit/export)",
            "Right to Erasure / Tenant Offboard (/v1/admin/tenants/{tenant_id}/offboard)",
        ],
    }


@router.get("/export")
async def export_tenant_dsar_bundle(
    tenant_id: Annotated[str, Depends(require_permission(Permission.AUDIT_EXPORT))],
    export_format: Annotated[str, Query(alias="format", pattern="^(json|zip)$")] = "json",
) -> Response:
    """Export authoritative GDPR Data Subject & Compliance Dossier (JSON summary or ZIP archive)."""
    async with db_session.get_tenant_session(tenant_id) as session:
        if export_format == "zip":
            zip_bytes = await _dossier_service.generate_dossier_zip(session=session, tenant_id=tenant_id)
            await AuditLedgerService.append_entry(
                session=session,
                tenant_id=tenant_id,
                event_type="DSAR_DOSSIER_EXPORTED",
                actor_identity_id=f"rbac:{tenant_id}",
                reason="Generated GDPR / regulatory compliance ZIP dossier",
                event_payload={"format": "zip", "bytes": len(zip_bytes)},
            )
            await session.commit()
            return Response(
                content=zip_bytes,
                media_type="application/zip",
                headers={
                    "Content-Disposition": f'attachment; filename="mirage_dsar_{tenant_id}.zip"',
                },
            )

        chain_status = await AuditLedgerService.verify_chain(session=session, tenant_id=tenant_id)
        settings = get_settings()
        await AuditLedgerService.append_entry(
            session=session,
            tenant_id=tenant_id,
            event_type="DSAR_METADATA_EXPORTED",
            actor_identity_id=f"rbac:{tenant_id}",
            reason="Exported GDPR privacy & audit integrity summary",
            event_payload={"format": "json"},
        )
        await session.commit()

        payload: dict[str, Any] = {
            "tenant_id": tenant_id,
            "exported_at": datetime.now(UTC).isoformat(),
            "framework_alignment": ["GDPR", "EU AI Act Art. 12/14/50", "SOC 2", "ISO 42001"],
            "audit_chain_integrity": chain_status,
            "retention_days": {
                "traces_mongodb": settings.mongo_retention_days,
                "audit_anchors": settings.audit_anchor_retention_days,
            },
            "download_zip_url": "/v1/privacy/export?format=zip",
        }
        return JSONResponse(status_code=status.HTTP_200_OK, content=payload)
