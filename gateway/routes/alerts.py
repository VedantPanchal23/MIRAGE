"""Operator Alerts Management Endpoints.

Implements Technical Architecture §8.2, Security & Access §13.1, and ADR 0005:
- GET /v1/alerts: List active and historical alerts for the authenticated tenant
- POST /v1/alerts/{alert_id}/acknowledge: Acknowledge an alert (Operator role)
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from db.persistence import default_persistence_service
from gateway.middleware.auth import get_current_auth
from gateway.middleware.rbac import require_permission
from shared.logging import get_logger
from shared.schemas.alerts import (
    AcknowledgeAlertRequest,
    AlertsListResponse,
    OperatorAlertResponse,
)
from shared.schemas.auth import AuthContext, Permission

router = APIRouter(prefix="/v1/alerts", tags=["Alerts"])
logger = get_logger("alerts_routes")


@router.get("", response_model=AlertsListResponse)
async def list_alerts(
    tenant_id: Annotated[str, Depends(require_permission(Permission.DASHBOARD_READ))],
    alert_status: str | None = Query(None, alias="status", description="Filter by status: active, acknowledged, resolved"),
    limit: int = Query(50, ge=1, le=100, description="Max number of alerts to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
) -> dict[str, Any]:
    """List operator alerts for the authenticated tenant with active and total counts."""
    alerts, total, active_count = await default_persistence_service.list_alerts(
        tenant_id=tenant_id,
        status=alert_status,
        limit=limit,
        offset=offset,
    )

    formatted_alerts = [
        OperatorAlertResponse(
            alert_id=a.alert_id,
            tenant_id=a.tenant_id,
            alert_type=a.alert_type,
            severity=a.severity,
            title=a.title,
            description=a.description,
            threshold=a.threshold,
            current_value=a.current_value,
            status=a.status,
            created_at=a.created_at,
            acknowledged_at=a.acknowledged_at,
            acknowledged_by=a.acknowledged_by,
            resolved_at=a.resolved_at,
        )
        for a in alerts
    ]

    return {
        "tenant_id": tenant_id,
        "total_alerts": total,
        "active_alerts": active_count,
        "alerts": formatted_alerts,
    }


@router.post("/{alert_id}/acknowledge", response_model=OperatorAlertResponse)
async def acknowledge_alert(
    alert_id: str,
    tenant_id: Annotated[str, Depends(require_permission(Permission.ALERTS_ACKNOWLEDGE))],
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    body: AcknowledgeAlertRequest | None = None,
) -> OperatorAlertResponse:
    """Acknowledge an active operator alert."""
    operator_id = body.operator_id if body and body.operator_id else auth.user_id

    alert = await default_persistence_service.acknowledge_alert(
        tenant_id=tenant_id,
        alert_id=alert_id,
        operator_id=operator_id,
    )

    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert '{alert_id}' not found for tenant",
        )

    logger.info("Alert acknowledged", alert_id=alert_id, tenant_id=tenant_id, acknowledged_by=operator_id)
    return OperatorAlertResponse(
        alert_id=alert.alert_id,
        tenant_id=alert.tenant_id,
        alert_type=alert.alert_type,
        severity=alert.severity,
        title=alert.title,
        description=alert.description,
        threshold=alert.threshold,
        current_value=alert.current_value,
        status=alert.status,
        created_at=alert.created_at,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        resolved_at=alert.resolved_at,
    )
