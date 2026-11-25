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


class TenantRegistrationRequest(BaseModel):
    """Self-service registration payload for enterprise B2B SaaS onboarding."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=255, description="Organization or Company Name")
    admin_email: str = Field(..., min_length=5, max_length=255, description="Administrator contact email")
    tenant_id: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Optional custom tenant identifier",
    )
    tier: str = Field(
        default="business",
        description="Subscription tier: developer, business, or enterprise",
    )


class TenantRegistrationResponse(BaseModel):
    """Response returned upon successful self-service tenant registration."""

    tenant_id: str
    name: str
    tier: str
    admin_user_id: str
    admin_identity_id: str
    api_key: str
    api_key_id: str
    access_token: str
    token_type: str = "bearer"
    created_at: datetime


class TenantUserCreateRequest(BaseModel):
    """Invite or provision a tenant team user with scoped RBAC role and initial API key."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=5, max_length=255)
    display_name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(
        default="operator",
        description="Assigned tenant RBAC role: tenant_admin, operator, viewer, api_client",
    )
    scopes: list[str] = Field(default_factory=lambda: ["*"])


class TenantUserUpdateRequest(BaseModel):
    """Update role or active status for a tenant user."""

    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    active: bool | None = None


class TenantUserResponse(BaseModel):
    """Safe representation of a tenant user."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    external_subject: str
    display_name: str
    role: str
    active: bool
    created_at: datetime


class TenantUserCreatedResponse(TenantUserResponse):
    """Response returned once when provisioning a tenant user and their initial API credential."""

    identity_id: str
    api_key: str
    api_key_id: str
    api_key_prefix: str


class TenantUserListResponse(BaseModel):
    """List of tenant users within administrative scope."""

    users: list[TenantUserResponse]
    total: int
