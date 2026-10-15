"""Hierarchical Outcome Assurance schemas for MIRAGE Phase 8.

Implements cross-agent outcome aggregation contracts governing parent and child executions,
handoff lifecycle states, Gate 5 Reality Verification aggregation, and late-arrival detection.
"""

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class HierarchicalOutcomeStatus(StrEnum):
    """Authoritative qualification status of an aggregated parent-child transaction tree."""

    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    PENDING_CHILD_WORK = "PENDING_CHILD_WORK"
    AWAITING_OUTCOME_VERIFICATION = "AWAITING_OUTCOME_VERIFICATION"
    HIERARCHICAL_FAILURE = "HIERARCHICAL_FAILURE"
    PARTIAL_ACHIEVEMENT = "PARTIAL_ACHIEVEMENT"
    CANCELLED = "CANCELLED"
    UNVERIFIABLE = "UNVERIFIABLE"
    UNKNOWN = "UNKNOWN"


def compute_hierarchical_evaluation_hash(
    parent_transaction_id: str,
    tenant_id: str,
    hierarchical_status: str,
    epistemic_confidence: float,
    child_count: int,
    handoff_count: int,
    timestamp_iso: str,
) -> str:
    """Computes authoritative SHA-256 fingerprint over canonical evaluation payload."""
    payload = {
        "parent_transaction_id": parent_transaction_id,
        "tenant_id": tenant_id,
        "hierarchical_status": hierarchical_status,
        "epistemic_confidence": round(epistemic_confidence, 4),
        "child_count": child_count,
        "handoff_count": handoff_count,
        "evaluated_at": timestamp_iso,
    }
    canonical_bytes = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


class ActionOutcomeSummary(BaseModel):
    """Summary of an individual action and its Gate 5 reality verification status."""

    model_config = ConfigDict(frozen=True)

    action_id: str = Field(..., description="ActionContract ID")
    transaction_id: str = Field(..., description="Originating transaction ID")
    tool_name: str = Field(..., description="Name of the tool invoked")
    target_resource: str = Field(..., description="Resource URI affected")
    requires_outcome_assurance: bool = Field(
        ...,
        description="Whether this action required independent Gate 5 outcome verification",
    )
    action_state: str = Field(..., description="State of the ActionContract (e.g. EXECUTED, BLOCKED, FAILED)")
    outcome_status: str | None = Field(
        default=None,
        description="Gate 5 verification status (e.g. VERIFIED_SUCCESS, PENDING_VERIFICATION, VERIFIED_FAILURE)",
    )
    epistemic_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Epistemic confidence of independent reality observation",
    )
    observability_class: str | None = Field(
        default=None,
        description="Observability classification of target resource (OBS_DIRECT, OBS_EVENTUAL, etc.)",
    )
    discrepancies: list[str] = Field(
        default_factory=list,
        description="Discrepancies detected between model claims and actual observed state",
    )


class ChildExecutionSummary(BaseModel):
    """Summary of a delegated child transaction, its execution status, and verified outcomes."""

    model_config = ConfigDict(frozen=True)

    child_transaction_id: str = Field(..., description="Child transaction ID")
    parent_transaction_id: str = Field(..., description="Parent transaction ID")
    agent_id: str | None = Field(default=None, description="Child agent identity ID")
    state: str = Field(..., description="Current transaction state of the child")
    final_disposition: str | None = Field(default=None, description="Final disposition of the child if terminal")
    execution_completed: bool = Field(
        ...,
        description="Whether the child agent completed tool execution (distinct from outcome verification)",
    )
    outcomes_verified: bool = Field(
        ...,
        description="Whether all consequential actions in child execution have been independently verified",
    )
    total_actions: int = Field(default=0, ge=0, description="Total action contracts proposed by child")
    verified_success_actions: int = Field(default=0, ge=0, description="Actions with VERIFIED_SUCCESS outcomes")
    pending_verification_actions: int = Field(
        default=0,
        ge=0,
        description="Actions executed but awaiting Gate 5 outcome verification",
    )
    failed_actions: int = Field(default=0, ge=0, description="Actions that failed execution or verification")
    unverifiable_actions: int = Field(
        default=0,
        ge=0,
        description="Actions on unobservable sinks where outcome cannot be confirmed",
    )
    action_summaries: list[ActionOutcomeSummary] = Field(
        default_factory=list,
        description="List of action outcome summaries under this child execution",
    )


class HandoffSummary(BaseModel):
    """Summary of a cross-agent handoff offer in the transaction hierarchy."""

    model_config = ConfigDict(frozen=True)

    handoff_id: str = Field(..., description="Unique handoff identifier")
    parent_transaction_id: str = Field(..., description="Originating parent transaction ID")
    parent_agent_id: str = Field(..., description="Parent delegating agent ID")
    child_agent_id: str = Field(..., description="Target delegatee child agent ID")
    delegation_id: str = Field(..., description="Bound delegation grant ID")
    child_transaction_id: str | None = Field(default=None, description="Spawned child transaction ID if accepted")
    status: str = Field(..., description="Current handoff lifecycle status (PENDING, ACCEPTED, etc.)")
    purpose: str = Field(..., description="Operational purpose of handoff")
    expires_at: datetime = Field(..., description="UTC expiration of handoff offer")
    accepted_at: datetime | None = Field(default=None, description="UTC acceptance timestamp")
    completed_at: datetime | None = Field(default=None, description="UTC completion timestamp")
    cancelled_at: datetime | None = Field(default=None, description="UTC cancellation timestamp")


class HierarchicalOutcomeResponse(BaseModel):
    """Authoritative API response detailing the aggregated hierarchical outcome of a transaction tree."""

    model_config = ConfigDict(frozen=True)

    parent_transaction_id: str = Field(..., description="Root or evaluated parent transaction ID")
    tenant_id: str = Field(..., description="Tenant isolation boundary")
    parent_state: str = Field(..., description="Current transaction state of the parent")
    parent_disposition: str | None = Field(default=None, description="Final disposition of the parent if terminal")
    is_parent_terminal: bool = Field(..., description="True if parent is already in an immutable terminal state")
    hierarchical_status: HierarchicalOutcomeStatus = Field(
        ...,
        description="Aggregated outcome status across parent and child work",
    )
    epistemic_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Aggregate calibrated epistemic confidence across verified hierarchy",
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of hierarchical evaluation",
    )
    total_child_transactions: int = Field(default=0, ge=0, description="Total child transactions in lineage")
    active_child_transactions: int = Field(default=0, ge=0, description="Number of child transactions still active")
    total_handoffs: int = Field(default=0, ge=0, description="Total handoffs issued by parent")
    pending_handoffs: int = Field(default=0, ge=0, description="Number of handoffs still awaiting acceptance")
    parent_actions: list[ActionOutcomeSummary] = Field(
        default_factory=list,
        description="Action outcomes directly executed by the parent transaction",
    )
    child_executions: list[ChildExecutionSummary] = Field(
        default_factory=list,
        description="Execution and verification summaries for each child transaction",
    )
    handoffs: list[HandoffSummary] = Field(
        default_factory=list,
        description="Summaries of all cross-agent handoffs in the hierarchy",
    )
    discrepancies: list[str] = Field(
        default_factory=list,
        description="Detected invariant violations, unverified claims, or late-arrival conflicts",
    )
    reconciliation_notes: list[str] = Field(
        default_factory=list,
        description="Epistemic caveats and governance notes explaining the aggregation disposition",
    )
    evaluation_hash: str = Field(
        ...,
        description="Cryptographic SHA-256 seal of the hierarchical evaluation result",
    )
