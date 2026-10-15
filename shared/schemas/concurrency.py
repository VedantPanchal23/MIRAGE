"""Shared-Resource Concurrency, Leases, and Fencing Tokens schemas adhering to Phase 8 architecture."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class ConcurrencyMode(StrEnum):
    """Operation serialization requirement on a shared resource."""

    EXCLUSIVE = "EXCLUSIVE"  # e.g., WRITE, DELETE, EXECUTE, mutating state
    SHARED = "SHARED"  # e.g., READ, read-only cache/inspection


class LeaseStatus(StrEnum):
    """Lifecycle status of a resource concurrency lease."""

    ACQUIRED = "ACQUIRED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ResourceLeaseAcquireRequest(BaseModel):
    """Client request to acquire a concurrency lease on a protected resource."""

    resource_uri: str = Field(..., min_length=1, max_length=512, description="Target resource URI to coordinate")
    transaction_id: str = Field(..., min_length=1, max_length=64, description="Caller's active transaction ID")
    agent_id: str = Field(..., min_length=1, max_length=64, description="Caller's agent ID")
    handoff_id: str | None = Field(default=None, max_length=64, description="Optional bound handoff ID if delegated")
    concurrency_mode: ConcurrencyMode = Field(
        default=ConcurrencyMode.EXCLUSIVE,
        description="Concurrency mode: EXCLUSIVE for mutations, SHARED for reads",
    )
    duration_seconds: int = Field(
        default=60,
        ge=5,
        le=300,
        description="Lease duration in seconds (default 60s, max 300s)",
    )

    @field_validator("resource_uri", "transaction_id", "agent_id")
    @classmethod
    def validate_non_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or purely whitespace")
        return stripped


class ResourceLeaseResponse(BaseModel):
    """Authoritative representation of a persisted resource lease and its fencing token."""

    id: str = Field(..., description="Unique lease identifier (e.g. 'lse_...')")
    tenant_id: str = Field(..., description="Authoritative tenant ID")
    resource_uri: str = Field(..., description="Canonical normalized target resource URI")
    holder_agent_id: str = Field(..., description="ID of holding agent")
    holder_transaction_id: str = Field(..., description="ID of holding transaction")
    holder_handoff_id: str | None = Field(default=None, description="Bound handoff ID if applicable")
    concurrency_mode: ConcurrencyMode = Field(..., description="Lease concurrency mode (EXCLUSIVE/SHARED)")
    fencing_token: int = Field(..., description="Monotonically increasing sequence fencing token for resource")
    status: LeaseStatus = Field(..., description="Authoritative status of the lease")
    expires_at: datetime = Field(..., description="UTC timestamp when lease expires")
    released_at: datetime | None = Field(default=None, description="UTC timestamp of release if released")
    created_at: datetime = Field(..., description="UTC creation timestamp")
    updated_at: datetime = Field(..., description="UTC last update timestamp")


class ResourceLeaseReleaseRequest(BaseModel):
    """Request payload to safely release an active lease."""

    transaction_id: str = Field(..., min_length=1, max_length=64, description="Transaction ID of legitimate holder")
    agent_id: str = Field(..., min_length=1, max_length=64, description="Agent ID of legitimate holder")
    fencing_token: int = Field(..., ge=1, description="Fencing token issued at lease acquisition")


class ResourceLeaseRenewRequest(BaseModel):
    """Request payload to extend an active lease before expiration."""

    transaction_id: str = Field(..., min_length=1, max_length=64, description="Transaction ID of legitimate holder")
    agent_id: str = Field(..., min_length=1, max_length=64, description="Agent ID of legitimate holder")
    fencing_token: int = Field(..., ge=1, description="Fencing token issued at lease acquisition")
    duration_seconds: int = Field(default=60, ge=5, le=300, description="Extension duration in seconds")
