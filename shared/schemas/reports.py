"""Pydantic schemas for Compliance and Audit Reports per Technical Architecture §8.2 and ADR 0005."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ReportStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GenerateReportRequest(BaseModel):
    """Payload to request compilation of a multi-session compliance audit report."""

    title: str = Field(default="Compliance Audit Report", description="Human-readable title for the report")
    start_date: datetime = Field(description="Start timestamp of audit evaluation window")
    end_date: datetime = Field(description="End timestamp of audit evaluation window")
    model_id: str | None = Field(default=None, description="Optional filter by model identifier")
    risk_tier: str | None = Field(default=None, description="Optional filter by risk tier (low, medium, high, critical)")


class GenerateReportResponse(BaseModel):
    """Asynchronous acceptance response returned when a report compilation task is enqueued."""

    report_id: str = Field(description="Unique report identifier")
    tenant_id: str = Field(description="Tenant identifier")
    status: ReportStatus = Field(description="Initial lifecycle status (PENDING)")
    poll_url: str = Field(description="Endpoint URL to check report compilation progress")
    download_url: str = Field(description="Endpoint URL to download compiled PDF")
    created_at: datetime = Field(description="Creation timestamp")


class ReportDetailResponse(BaseModel):
    """Detailed metadata and analytical summary of an audit report."""

    report_id: str
    tenant_id: str
    title: str
    status: str
    start_date: datetime
    end_date: datetime
    model_id: str | None = None
    risk_tier: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict, description="Aggregated metrics summary")
    storage_key: str | None = Field(default=None, description="Object storage key for the generated artifact")
    created_at: datetime
    completed_at: datetime | None = None
    download_url: str
