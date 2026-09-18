"""Dashboard and analytics REST endpoints for executive monitoring and longitudinal drift inspection."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from analytics.store import default_session_store
from gateway.middleware.auth import get_current_auth
from shared.logging import get_logger
from shared.schemas.auth import AuthContext, Role

router = APIRouter(tags=["Dashboard & Drift Analytics"])
logger = get_logger("dashboard_route")


@router.get("/v1/dashboard/stats")
async def get_dashboard_stats(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    tenant_id: str | None = Query(None, description="Optional tenant ID filter"),
) -> dict[str, Any]:
    """Retrieve executive summary metrics, risk tier distributions, and drift status."""
    if tenant_id and tenant_id != auth.tenant_id and auth.role != Role.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Tenant '{auth.tenant_id}' cannot access stats for tenant '{tenant_id}'",
        )
    target_tenant = tenant_id or auth.tenant_id
    logger.info("Fetching dashboard stats", target_tenant=target_tenant)

    try:
        authoritative_stats = await default_session_store.get_stats_authoritative(tenant_id=target_tenant)
        if authoritative_stats.get("total_requests", 0) > 0:
            return authoritative_stats
    except Exception as exc:
        logger.debug("Authoritative stats query fallback to local cache", error=str(exc))

    return default_session_store.get_stats(tenant_id=target_tenant)


@router.get("/v1/dashboard/sessions")
async def get_dashboard_sessions(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    tenant_id: str | None = Query(None, description="Filter by tenant ID"),
    risk_tier: str | None = Query(None, description="Filter by risk tier: LOW, MEDIUM, HIGH, CRITICAL"),
    min_hrs: float | None = Query(None, description="Filter by minimum HRS score"),
    max_hrs: float | None = Query(None, description="Filter by maximum HRS score"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
) -> dict[str, Any]:
    """Retrieve paginated verification sessions with full claim breakdowns and TreeSHAP attributions."""
    if tenant_id and tenant_id != auth.tenant_id and auth.role != Role.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Tenant '{auth.tenant_id}' cannot access sessions for tenant '{tenant_id}'",
        )
    target_tenant = tenant_id or auth.tenant_id

    try:
        total, items = await default_session_store.list_sessions_authoritative(
            tenant_id=target_tenant,
            risk_tier=risk_tier,
            min_hrs=min_hrs,
            max_hrs=max_hrs,
            page=page,
            page_size=page_size,
        )
        if total > 0:
            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": items,
            }
    except Exception as exc:
        logger.debug("Authoritative sessions query fallback to local cache", error=str(exc))

    total, items = default_session_store.list_sessions(
        tenant_id=target_tenant,
        risk_tier=risk_tier,
        min_hrs=min_hrs,
        max_hrs=max_hrs,
        page=page,
        page_size=page_size,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


@router.get("/v1/drift")
async def get_drift_report(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    tenant_id: str | None = Query(None, description="Tenant ID to inspect"),
    days: int = Query(30, ge=1, le=180, description="Window in days for time-series"),
) -> dict[str, Any]:
    """Retrieve longitudinal HRS drift analysis (PSI, KS test) and daily trend time-series."""
    if tenant_id and tenant_id != auth.tenant_id and auth.role != Role.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Tenant '{auth.tenant_id}' cannot access drift report for tenant '{tenant_id}'",
        )
    target_tenant = tenant_id or auth.tenant_id
    drift_rep = default_session_store.drift_tracker.get_drift_report(target_tenant)

    try:
        time_series = await default_session_store.get_time_series_authoritative(tenant_id=target_tenant, days=days)
    except Exception as exc:
        logger.debug("Authoritative time series query fallback to local cache", error=str(exc))
        time_series = default_session_store.get_time_series(tenant_id=target_tenant, days=days)

    return {
        "tenant_id": target_tenant,
        "days": days,
        "drift_report": {
            "psi": drift_rep.psi,
            "ks_statistic": drift_rep.ks_statistic,
            "ks_pvalue": drift_rep.ks_pvalue,
            "status": drift_rep.status.value,
            "alert_triggered": drift_rep.alert_triggered,
            "alert_reason": drift_rep.alert_reason,
            "baseline_sample_count": drift_rep.baseline_sample_count,
            "current_sample_count": drift_rep.current_sample_count,
            "baseline_mean_hrs": drift_rep.baseline_mean_hrs,
            "current_mean_hrs": drift_rep.current_mean_hrs,
            "rolling_7d_delta": drift_rep.rolling_7d_delta,
            "bin_proportions_baseline": drift_rep.bin_proportions_baseline,
            "bin_proportions_current": drift_rep.bin_proportions_current,
        },
        "time_series": time_series,
    }
