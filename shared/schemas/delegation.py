"""Phase 8 Cross-Agent Delegation and Distributed Governance schemas.

Implements Phase 8 Batch 1: Delegation contracts, authority attenuation specifications,
and grant response envelopes.

Security Principles:
- Schema validation alone does NOT authorize a delegation.
- Authoritative validation against parent active capabilities, tenant context,
  and depth limits must occur in the Delegation Service.
- Never treat caller-provided capability lists, taint labels, tenant IDs,
  or identity IDs as proof of authorization.
- Persisted contracts must never embed signing keys, credentials, or secrets.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class DelegationStatus(StrEnum):
    """Governed lifecycle state of an agent delegation grant."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class AttenuatedCapabilitySpec(BaseModel):
    """Specification of a scoped, attenuated capability granted to a delegatee agent.

    The granted capability must be a strict subset of the parent's active capability.
    """

    capability_type: str = Field(
        min_length=1,
        max_length=128,
        description="Authoritative capability type (e.g., 'tools:file_read', 'tools:math')",
    )
    resource_scope: dict[str, Any] = Field(
        default_factory=dict,
        description="Attenuated resource allowlist or scope dictionary (e.g., {'allowed_prefixes': ['/tmp/']})",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution constraints (e.g., {'max_amount': 100})",
    )
    max_autonomy_level: int = Field(
        default=0,
        ge=0,
        le=4,
        description="Bounded autonomy ceiling (0=L0 manual to 4=L4 human approval; L5 is prohibited)",
    )

    @field_validator("capability_type")
    @classmethod
    def validate_capability_type(cls, val: str) -> str:
        stripped = val.strip()
        if not stripped:
            raise ValueError("capability_type cannot be empty or whitespace")
        return stripped


class DelegationGrantRequest(BaseModel):
    """Request to create an attenuated delegation grant from a parent transaction."""

    parent_transaction_id: str = Field(
        min_length=1,
        max_length=64,
        description="ID of the active parent transaction delegating authority",
    )
    delegatee_agent_id: str = Field(
        min_length=1,
        max_length=64,
        description="ID of the registered agent receiving the delegated authority",
    )
    delegated_capabilities: list[AttenuatedCapabilitySpec] = Field(
        min_length=1,
        description="List of attenuated capabilities granted to the delegatee",
    )
    max_turns: int = Field(
        default=4,
        ge=1,
        le=32,
        description="Turn budget allocated to the child transaction (bounded by parent remaining turns)",
    )
    duration_seconds: int = Field(
        default=300,
        ge=10,
        le=86400,
        description="Lifespan of the delegation grant in seconds (default: 5 minutes, max: 24 hours)",
    )
    idempotency_key: str = Field(
        min_length=8,
        max_length=255,
        description="Client-supplied idempotency key ensuring at-most-once grant creation",
    )
    purpose: str = Field(
        min_length=1,
        max_length=500,
        description="Explicit business/operational intent for the delegation",
    )

    @field_validator("delegated_capabilities")
    @classmethod
    def validate_no_duplicate_capabilities(cls, caps: list[AttenuatedCapabilitySpec]) -> list[AttenuatedCapabilitySpec]:
        seen: set[str] = set()
        for cap in caps:
            if cap.capability_type in seen:
                raise ValueError(
                    f"Duplicate capability_type '{cap.capability_type}' in delegation request is ambiguous"
                )
            seen.add(cap.capability_type)
        return caps

    @field_validator("parent_transaction_id", "delegatee_agent_id", "purpose")
    @classmethod
    def validate_non_whitespace(cls, val: str) -> str:
        stripped = val.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or whitespace only")
        return stripped


class DelegationGrantResponse(BaseModel):
    """Authoritative representation of a persisted, tenant-bound delegation grant."""

    id: str = Field(description="Unique delegation grant identifier (e.g. 'del_...')")
    tenant_id: str = Field(description="Authoritative tenant identifier")
    parent_agent_id: str = Field(description="ID of the delegating agent")
    parent_transaction_id: str = Field(description="ID of the parent transaction")
    child_agent_id: str = Field(description="ID of the delegatee agent")
    child_transaction_id: str | None = Field(
        default=None,
        description="ID of the child transaction if spawned, otherwise None",
    )
    delegated_capabilities: list[AttenuatedCapabilitySpec] = Field(
        description="Authoritatively recorded attenuated capabilities"
    )
    resource_scope: dict[str, Any] = Field(
        default_factory=dict,
        description="Consolidated resource scope allowlist for the grant",
    )
    max_turns: int = Field(description="Allocated turn budget")
    max_autonomy_level: int = Field(description="Ceiling autonomy level across all granted capabilities")
    delegation_depth: int = Field(ge=1, description="Nesting depth of the delegation grant (root child = 1)")
    status: DelegationStatus = Field(description="Current lifecycle status of the delegation grant")
    purpose: str = Field(description="Declared operational purpose")
    idempotency_key: str = Field(description="Tenant-scoped idempotency key")
    expires_at: datetime = Field(description="UTC timestamp when the delegation grant expires")
    revoked_at: datetime | None = Field(default=None, description="UTC timestamp of explicit revocation, if revoked")
    created_at: datetime = Field(description="UTC timestamp of grant creation")


class DelegationActivationRequest(BaseModel):
    """Request payload to bind a pending delegation grant to a child transaction."""

    child_transaction_id: str = Field(
        min_length=1,
        max_length=255,
        description="ID of the spawned child transaction to bind to this grant",
    )

    @field_validator("child_transaction_id")
    @classmethod
    def validate_non_whitespace(cls, val: str) -> str:
        stripped = val.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or whitespace only")
        return stripped


class DelegationRevocationRequest(BaseModel):
    """Request payload to explicitly revoke an active or pending delegation grant."""

    reason: str = Field(
        min_length=1,
        max_length=1000,
        description="Mandatory operational or security reason for grant revocation",
    )

    @field_validator("reason")
    @classmethod
    def validate_non_whitespace(cls, val: str) -> str:
        stripped = val.strip()
        if not stripped:
            raise ValueError("Reason cannot be empty or whitespace only")
        return stripped


class DelegationOperationValidationRequest(BaseModel):
    """Request payload to evaluate delegation validity for a specific operation."""

    capability_type: str = Field(min_length=1, max_length=255, description="Required capability type")
    resource: dict[str, Any] = Field(default_factory=dict, description="Target resource and parameters")
    requested_autonomy_level: int = Field(default=0, ge=0, le=4, description="Requested autonomy level")
