"""Agent Lifecycle Governance and Authenticated Identity schemas adhering to Phase 8 architecture."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentStatus(StrEnum):
    """Authoritative lifecycle status of a governed AI agent."""

    REGISTERED = "registered"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class AgentRegistrationRequest(BaseModel):
    """Schema for registering a new tenant-scoped governed agent."""

    name: str = Field(..., min_length=1, max_length=255, description="Unique agent name within tenant")
    max_autonomy_level: int = Field(default=0, ge=0, le=5, description="Maximum autonomy ceiling (L0-L5)")
    initial_status: AgentStatus = Field(
        default=AgentStatus.REGISTERED,
        description="Initial lifecycle status upon registration",
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Arbitrary non-authoritative metadata")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Agent name cannot be empty or purely whitespace")
        return stripped

    @field_validator("initial_status")
    @classmethod
    def validate_initial_status(cls, v: AgentStatus) -> AgentStatus:
        if v not in {AgentStatus.REGISTERED, AgentStatus.ACTIVE}:
            raise ValueError("Initial status on registration must be 'registered' or 'active'")
        return v


class AgentResponse(BaseModel):
    """Authoritative representation of a persisted governed agent."""

    id: str = Field(..., description="Unique agent identifier")
    tenant_id: str = Field(..., description="Owning tenant identifier")
    name: str = Field(..., description="Agent name unique within tenant")
    status: AgentStatus = Field(..., description="Authoritative lifecycle status")
    active: bool = Field(..., description="Legacy boolean compatibility flag (True only when status is ACTIVE)")
    max_autonomy_level: int = Field(..., description="Maximum autonomy ceiling (L0-L5)")
    registered_by_identity_id: str | None = Field(
        default=None, description="Actor identity ID that registered the agent"
    )
    suspended_at: datetime | None = Field(default=None, description="UTC timestamp of suspension if suspended")
    revoked_at: datetime | None = Field(default=None, description="UTC timestamp of revocation if revoked")
    suspension_reason: str | None = Field(default=None, description="Reason for suspension")
    revocation_reason: str | None = Field(default=None, description="Reason for permanent revocation")
    created_at: datetime = Field(..., description="UTC creation timestamp")
    updated_at: datetime = Field(..., description="UTC last update timestamp")


class AgentTransitionRequest(BaseModel):
    """Request payload for mutating agent lifecycle status."""

    reason: str = Field(..., min_length=1, max_length=512, description="Audit justification for state transition")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Transition reason cannot be empty or whitespace")
        return stripped


class AgentListResponse(BaseModel):
    """Paginated list of tenant agents."""

    agents: list[AgentResponse] = Field(default_factory=list, description="List of agent records")
    total: int = Field(..., ge=0, description="Total matching agents in tenant")
    limit: int = Field(..., ge=1, le=100, description="Page limit")
    offset: int = Field(..., ge=0, description="Page offset")


def is_terminal_agent_status(status: AgentStatus | str) -> bool:
    """Return True if agent status is permanently terminal and cannot be reactivated."""
    val = status.value if isinstance(status, AgentStatus) else str(status).lower()
    return val == AgentStatus.REVOKED.value


def is_agent_transition_allowed(current_status: AgentStatus | str, target_status: AgentStatus | str) -> bool:
    """Validate lifecycle state machine transition rules.

    State Machine:
      REGISTERED -> ACTIVE, REVOKED
      ACTIVE -> SUSPENDED, REVOKED
      SUSPENDED -> ACTIVE, REVOKED
      REVOKED -> (None - terminal!)
    """
    curr = AgentStatus(current_status) if not isinstance(current_status, AgentStatus) else current_status
    tgt = AgentStatus(target_status) if not isinstance(target_status, AgentStatus) else target_status

    if curr == tgt:
        return True  # Idempotent no-op

    if curr == AgentStatus.REVOKED:
        return False  # Terminal! Cannot transition out of REVOKED

    allowed: dict[AgentStatus, set[AgentStatus]] = {
        AgentStatus.REGISTERED: {AgentStatus.ACTIVE, AgentStatus.REVOKED},
        AgentStatus.ACTIVE: {AgentStatus.SUSPENDED, AgentStatus.REVOKED},
        AgentStatus.SUSPENDED: {AgentStatus.ACTIVE, AgentStatus.REVOKED},
    }
    return tgt in allowed.get(curr, set())
