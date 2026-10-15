"""Agent Handoff schemas governing cross-agent execution delegation and context passing."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class HandoffStatus(StrEnum):
    """Authoritative lifecycle status of a cross-agent handoff."""

    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AgentHandoffCreateRequest(BaseModel):
    """Client request payload to initiate a governed handoff from a parent execution."""

    parent_transaction_id: str = Field(..., min_length=1, max_length=64, description="Originating transaction ID")
    child_agent_id: str = Field(..., min_length=1, max_length=64, description="Target delegatee agent ID")
    delegation_id: str = Field(..., min_length=1, max_length=64, description="Bound delegation grant ID")
    purpose: str = Field(..., min_length=1, max_length=500, description="Explicit operational purpose for handoff")
    permitted_scope: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional further attenuated resource scope for this specific handoff",
    )
    duration_seconds: int = Field(
        default=300,
        ge=10,
        le=86400,
        description="Handoff acceptance lifespan in seconds (default 5m, max 24h)",
    )
    idempotency_key: str = Field(
        ...,
        min_length=8,
        max_length=255,
        description="Client-supplied idempotency key ensuring at-most-once handoff creation",
    )

    @field_validator("parent_transaction_id", "child_agent_id", "delegation_id", "purpose", "idempotency_key")
    @classmethod
    def validate_non_whitespace(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Field cannot be empty or purely whitespace")
        return stripped


class AgentHandoffResponse(BaseModel):
    """Authoritative representation of a persisted tenant-scoped agent handoff."""

    id: str = Field(..., description="Unique handoff identifier (e.g. 'hnd_...')")
    tenant_id: str = Field(..., description="Authoritative tenant ID")
    parent_transaction_id: str = Field(..., description="Originating transaction ID")
    parent_agent_id: str = Field(..., description="Originating delegating agent ID")
    child_agent_id: str = Field(..., description="Target delegatee agent ID")
    delegation_id: str = Field(..., description="Bound delegation grant ID")
    child_transaction_id: str | None = Field(
        default=None,
        description="ID of the spawned child transaction once accepted, else None",
    )
    status: HandoffStatus = Field(..., description="Current lifecycle status of the handoff")
    purpose: str = Field(..., description="Declared operational purpose")
    permitted_scope: dict[str, Any] = Field(default_factory=dict, description="Permitted resource scope")
    inherited_taint_flags: list[str] = Field(
        default_factory=list,
        description="Server-side inherited taints from parent transaction",
    )
    idempotency_key: str = Field(..., description="Tenant-scoped idempotency key")
    expires_at: datetime = Field(..., description="UTC expiration timestamp")
    accepted_at: datetime | None = Field(default=None, description="UTC acceptance timestamp")
    completed_at: datetime | None = Field(default=None, description="UTC completion timestamp")
    cancelled_at: datetime | None = Field(default=None, description="UTC cancellation timestamp")
    cancellation_reason: str | None = Field(default=None, description="Reason for cancellation if cancelled")
    created_at: datetime = Field(..., description="UTC creation timestamp")
    updated_at: datetime = Field(..., description="UTC last update timestamp")


class AgentHandoffAcceptRequest(BaseModel):
    """Payload provided by the delegatee agent or operator when accepting a handoff."""

    input_context: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-authoritative task input or initialization context for child execution",
    )


class AgentHandoffAcceptResponse(BaseModel):
    """Response returned upon successfully accepting a handoff and spawning child execution."""

    handoff: AgentHandoffResponse = Field(..., description="Updated handoff record in ACCEPTED state")
    child_transaction_id: str = Field(..., description="ID of the newly spawned child transaction")
    inherited_taint_flags: list[str] = Field(..., description="Taints applied to child transaction")
    allocated_turns: int = Field(..., description="Turn budget allocated to child execution")


class AgentHandoffCancelRequest(BaseModel):
    """Payload for cancelling a pending or active handoff."""

    reason: str = Field(..., min_length=1, max_length=512, description="Audit justification for handoff cancellation")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Cancellation reason cannot be empty or whitespace")
        return stripped


def is_terminal_handoff_status(status_val: HandoffStatus | str) -> bool:
    """Return True if the handoff status is permanently terminal."""
    val = status_val.value if isinstance(status_val, HandoffStatus) else str(status_val).upper()
    return val in {
        HandoffStatus.COMPLETED.value,
        HandoffStatus.CANCELLED.value,
        HandoffStatus.REJECTED.value,
        HandoffStatus.EXPIRED.value,
        HandoffStatus.REVOKED.value,
    }


def is_valid_handoff_transition(current_status: HandoffStatus | str, target_status: HandoffStatus | str) -> bool:
    """Validate handoff lifecycle state machine rules.

    State Machine:
      PENDING -> ACCEPTED, CANCELLED, REJECTED, EXPIRED, REVOKED
      ACCEPTED -> COMPLETED, CANCELLED, REVOKED
      Terminal states cannot transition.
    """
    curr = current_status.value if isinstance(current_status, HandoffStatus) else str(current_status).upper()
    tgt = target_status.value if isinstance(target_status, HandoffStatus) else str(target_status).upper()

    if curr == tgt:
        return True

    allowed_transitions: dict[str, set[str]] = {
        HandoffStatus.PENDING.value: {
            HandoffStatus.ACCEPTED.value,
            HandoffStatus.CANCELLED.value,
            HandoffStatus.REJECTED.value,
            HandoffStatus.EXPIRED.value,
            HandoffStatus.REVOKED.value,
        },
        HandoffStatus.ACCEPTED.value: {
            HandoffStatus.COMPLETED.value,
            HandoffStatus.CANCELLED.value,
            HandoffStatus.REVOKED.value,
        },
    }

    return tgt in allowed_transitions.get(curr, set())
