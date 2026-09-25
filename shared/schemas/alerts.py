"""Pydantic schemas for Operator Alerts per Technical Architecture §8.2 and ADR 0005."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AlertStatus(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AlertSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OperatorAlertResponse(BaseModel):
    """Schema representing an operator alert."""

    alert_id: str = Field(description="Unique alert identifier")
    tenant_id: str = Field(description="Tenant identifier")
    alert_type: str = Field(description="Type/category of the alert (e.g. rolling_hrs_breach, circuit_breaker_open)")
    severity: str = Field(description="Alert severity tier: low, medium, high, critical")
    title: str = Field(description="Human-readable title")
    description: str = Field(description="Detailed alert description")
    threshold: float | None = Field(default=None, description="Configured trigger threshold")
    current_value: float | None = Field(default=None, description="Observed value triggering the alert")
    status: str = Field(description="Lifecycle status: active, acknowledged, resolved")
    created_at: datetime = Field(description="Timestamp when alert was triggered")
    acknowledged_at: datetime | None = Field(default=None, description="Timestamp of acknowledgment")
    acknowledged_by: str | None = Field(default=None, description="User identifier who acknowledged")
    resolved_at: datetime | None = Field(default=None, description="Timestamp when resolved")


class AcknowledgeAlertRequest(BaseModel):
    """Optional payload when acknowledging an operator alert."""

    operator_id: str | None = Field(default=None, description="Operator user identifier (defaults to JWT sub)")
    notes: str | None = Field(default=None, description="Optional acknowledgment notes")


class AlertsListResponse(BaseModel):
    """Paginated or listed response for operator alerts."""

    tenant_id: str
    total_alerts: int
    active_alerts: int
    alerts: list[OperatorAlertResponse]
