"""Compliance and Audit Report Generation Endpoints.

Implements Technical Architecture §7.5, §8.2, PRD FR-AUD-01..04, and ADR 0005:
- POST /v1/reports/generate: Enqueue asynchronous compliance report generation (202 Accepted)
- GET /v1/reports/{report_id}: Poll report compilation status and analytical summary
- GET /v1/reports/{report_id}/pdf: Download compiled multi-session compliance PDF
- Single-session certificate PDF generation via ReportLab
"""

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from analytics.audit_service import AuditService
from analytics.pdf_service import default_pdf_generator
from db.persistence import default_persistence_service
from gateway.middleware.auth import get_current_auth
from gateway.middleware.rbac import require_permission
from services.storage import ObjectNotFoundError, default_storage_service
from shared.logging import get_logger
from shared.schemas.auth import AuthContext, Permission
from shared.schemas.reports import (
    GenerateReportRequest,
    GenerateReportResponse,
    ReportDetailResponse,
    ReportStatus,
)
from workers.tasks import generate_report_task

router = APIRouter(prefix="/v1/reports", tags=["Reports"])
logger = get_logger("reports_routes")


def _compute_idempotency_key(
    tenant_id: str,
    start_date: datetime,
    end_date: datetime,
    model_id: str | None,
    risk_tier: str | None,
) -> str:
    raw = f"{tenant_id}:{start_date.isoformat()}:{end_date.isoformat()}:{model_id or ''}:{risk_tier or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED, response_model=GenerateReportResponse)
async def generate_audit_report(
    request: GenerateReportRequest,
    tenant_id: Annotated[str, Depends(require_permission(Permission.AUDIT_EXPORT))],
) -> GenerateReportResponse:
    """Request compilation of an asynchronous multi-session compliance audit report."""

    # 1. Date Range Validation
    if request.start_date > request.end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must be less than or equal to end_date",
        )

    # 2. Compute idempotency key & check for existing in-flight/recent report
    idempotency_key = _compute_idempotency_key(
        tenant_id=tenant_id,
        start_date=request.start_date,
        end_date=request.end_date,
        model_id=request.model_id,
        risk_tier=request.risk_tier,
    )

    try:
        existing = await default_persistence_service.get_report_by_idempotency_key(
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            window_hours=1,
        )
        if existing:
            logger.info("Found existing recent report matching idempotency key", report_id=existing.report_id)
            return GenerateReportResponse(
                report_id=existing.report_id,
                tenant_id=tenant_id,
                status=ReportStatus(existing.status),
                poll_url=f"/v1/reports/{existing.report_id}",
                download_url=f"/v1/reports/{existing.report_id}/pdf",
                created_at=existing.created_at,
            )
    except Exception as exc:
        logger.warning("Idempotency lookup warning, proceeding with creation", error=str(exc))

    # 3. Create PENDING report record in PostgreSQL
    try:
        report = await default_persistence_service.create_report(
            tenant_id=tenant_id,
            title=request.title,
            start_date=request.start_date,
            end_date=request.end_date,
            model_id=request.model_id,
            risk_tier=request.risk_tier,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        logger.error("Failed to create report record in PostgreSQL", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authoritative persistence unavailable to enqueue report",
        ) from exc

    # 4. Dispatch Celery task to RabbitMQ Quorum queue
    from workers.celery_app import is_broker_reachable

    if is_broker_reachable():
        try:
            generate_report_task.apply_async(
                kwargs={
                    "tenant_id": tenant_id,
                    "report_id": report.report_id,
                    "title": request.title,
                    "start_date_iso": request.start_date.isoformat(),
                    "end_date_iso": request.end_date.isoformat(),
                    "model_id": request.model_id,
                    "risk_tier": request.risk_tier,
                },
                queue="mirage.reports",
                routing_key="report.task",
                retry=False,
            )
        except Exception as exc:
            logger.info("Celery broker dispatch warning, report remains in PENDING state", error=str(exc))
    else:
        logger.info("Celery broker offline, report queued in PENDING state")

    return GenerateReportResponse(
        report_id=report.report_id,
        tenant_id=tenant_id,
        status=ReportStatus.PENDING,
        poll_url=f"/v1/reports/{report.report_id}",
        download_url=f"/v1/reports/{report.report_id}/pdf",
        created_at=report.created_at,
    )


@router.get("/{report_id}", response_model=ReportDetailResponse)
async def get_report_detail(
    report_id: str,
    tenant_id: Annotated[str, Depends(require_permission(Permission.AUDIT_READ))],
) -> ReportDetailResponse:
    """Retrieve audit report metadata, execution status, and aggregated risk summary."""
    report = await default_persistence_service.get_report_by_id(tenant_id=tenant_id, report_id=report_id)

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found for tenant",
        )

    return ReportDetailResponse(
        report_id=report.report_id,
        tenant_id=report.tenant_id,
        title=report.title,
        status=report.status,
        start_date=report.start_date,
        end_date=report.end_date,
        model_id=report.model_id,
        risk_tier=report.risk_tier,
        summary=report.summary or {},
        storage_key=report.storage_key,
        created_at=report.created_at,
        completed_at=report.completed_at,
        download_url=f"/v1/reports/{report.report_id}/pdf",
    )


@router.get("/{report_id}/pdf")
async def download_report_pdf(
    report_id: str,
    tenant_id: Annotated[str, Depends(require_permission(Permission.AUDIT_EXPORT))],
) -> Response:
    """Download the generated compliance audit PDF from object storage."""
    report = await default_persistence_service.get_report_by_id(tenant_id=tenant_id, report_id=report_id)

    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' not found for tenant",
        )

    if report.status != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report generation is currently '{report.status}'. PDF is only available when status is COMPLETED.",
        )

    storage_key = f"{tenant_id}/{report_id}.pdf"
    try:
        pdf_bytes, content_type = default_storage_service.get_object(
            bucket="mirage-audit",
            key=storage_key,
        )
    except ObjectNotFoundError:
        # Fallback to generating on the fly if stored artifact was pruned or local test
        sessions = await default_persistence_service.get_sessions_for_audit(
            tenant_id=tenant_id,
            start_date=report.start_date,
            end_date=report.end_date,
            model_id=report.model_id,
            risk_tier=report.risk_tier,
        )
        session_dicts = [
            {
                "session_id": s.session_id,
                "created_at": s.created_at.isoformat() if s.created_at else "",
                "model_id": s.model_id,
                "hrs_score": s.hrs_score,
                "risk_tier": s.risk_tier,
                "correction_applied": s.correction_applied,
            }
            for s in sessions
        ]
        pdf_bytes = default_pdf_generator.generate_aggregate_audit_report_pdf(
            report_id=report.report_id,
            tenant_id=tenant_id,
            title=report.title,
            start_date=report.start_date,
            end_date=report.end_date,
            summary=report.summary or {},
            sessions=session_dicts,
            model_id=report.model_id,
            risk_tier=report.risk_tier,
        )
        content_type = "application/pdf"

    return Response(
        content=pdf_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="mirage_audit_{report_id}.pdf"'},
    )
