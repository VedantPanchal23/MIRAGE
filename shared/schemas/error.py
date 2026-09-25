"""Standard API Error Response Schemas conforming to Technical Architecture §8.2 and ADR 0005."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """Normalized inner error structure."""

    code: str = Field(description="Machine-readable error code")
    message: str = Field(description="Human-readable explanation of the error")
    details: dict[str, Any] | list[Any] | None = Field(default=None, description="Optional structured context or validation field errors")
    trace_id: str | None = Field(default=None, description="Distributed OpenTelemetry trace ID")
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(), description="ISO 8601 UTC timestamp")


class ErrorEnvelope(BaseModel):
    """Top-level error envelope wrapping all MIRAGE error responses."""

    error: ErrorDetail
