"""Schemas for Tenant Administration and Lifecycle Management."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TenantStatus(StrEnum):
    """Authoritative lifecycle status for tenants."""

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class TenantCreateRequest(BaseModel):
    """Payload to create a new tenant account (Super Admin only)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255, description="Tenant corporate name")
    tenant_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Optional custom tenant identifier (defaults to slugified or generated id)",
    )
    tier: str = Field(default="free", min_length=1, max_length=32, description="Subscription or entitlement tier")
    scs_enabled: bool = Field(default=True, description="Enable Semantic Consistency Scoring")
    pii_detection_enabled: bool = Field(default=True, description="Enable automated PII detection and masking")
    admin_user_id: str | None = Field(default=None, description="Optional initial tenant administrator identity")


class TenantUpdateRequest(BaseModel):
    """Payload to update permitted tenant settings."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    tier: str | None = Field(default=None, min_length=1, max_length=32)
    scs_enabled: bool | None = None
    pii_detection_enabled: bool | None = None


class TenantSuspendRequest(BaseModel):
    """Payload to suspend a tenant."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=3, max_length=1000, description="Audit-logged justification for suspension")


class TenantResponse(BaseModel):
    """Authoritative tenant account representation."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: TenantStatus
    tier: str
    scs_enabled: bool | None = True
    pii_detection_enabled: bool | None = True
    suspension_reason: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class TenantListResponse(BaseModel):
    """Paginated list of tenant accounts."""

    tenants: list[TenantResponse]
    total: int
    next_cursor: str | None = None
