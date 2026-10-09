"""Canonical Gate 5 Outcome Assurance and Reality Verification schemas for MIRAGE 3.0.

Implements Reality_Verification.md, Input_Output_Assurance.md §6, and AI_Action_Contract.md.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ObservabilityClass(StrEnum):
    """Canonical epistemic observability classification defined in Reality_Verification.md §4."""

    OBS_DIRECT = "OBS_DIRECT"  # Synchronously observable (e.g. direct SQL read, consistent GET API)
    OBS_EVENTUAL = "OBS_EVENTUAL"  # Asynchronously observable with propagation lag (e.g. S3, queues, indexing)
    OBS_INFERRED = "OBS_INFERRED"  # Transport-acknowledged only (e.g. HTTP 200, Stripe intent, Jira webhook)
    OBS_BLIND = "OBS_BLIND"  # Write-only sinks without readback API (e.g. UDP syslog, unmonitored SMTP)


class OutcomeStatus(StrEnum):
    """Canonical outcome status defined in Reality_Verification.md §6.1."""

    SUCCESS_CONFIRMED = "SUCCESS_CONFIRMED"  # Postconditions directly observed and verified in target state
    SUCCESS_EVENTUALLY_OBSERVED = "SUCCESS_EVENTUALLY_OBSERVED"  # Postconditions confirmed via eventual polling
    ACKNOWLEDGED_UNVERIFIED = "ACKNOWLEDGED_UNVERIFIED"  # Transport ACK received, sink state uninspected
    FAILED = "FAILED"  # Target state rejected mutation, error raised, or postconditions violated
    PARTIAL = "PARTIAL"  # Multi-step batch where subset of actions succeeded and subset failed
    UNKNOWN = "UNKNOWN"  # Ambiguous network timeout, probe failure, or unverifiable transient state
    UNOBSERVABLE = "UNOBSERVABLE"  # Write-only sink; confidence is strictly zero


class OutcomeVerifierType(StrEnum):
    """Pluggable adapter types for reality verification."""

    DATABASE = "DATABASE"
    HTTP_RESOURCE = "HTTP_RESOURCE"
    ASYNC_EVENT = "ASYNC_EVENT"
    SIMULATED = "SIMULATED"


class OutcomeVerificationRequest(BaseModel):
    """Request payload to perform Gate 5 reality verification on an action."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str = Field(..., description="Parent AI Transaction ID")
    action_id: str = Field(..., description="ActionContract ID to verify")
    idempotency_key: str | None = Field(default=None, description="Client or caller-provided idempotency key")
    observability_class: ObservabilityClass = Field(
        default=ObservabilityClass.OBS_DIRECT,
        description="Target resource observability class",
    )
    verifier_type: OutcomeVerifierType = Field(
        default=OutcomeVerifierType.DATABASE,
        description="Adapter engine to run verification probe",
    )
    expected_postconditions: dict[str, Any] = Field(
        default_factory=dict,
        description="Expected state invariants or values to assert against actual reality",
    )
    adapter_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Adapter-specific connection/query configuration",
    )
    timeout_seconds: float = Field(
        default=10.0,
        ge=0.1,
        le=60.0,
        description="Maximum wall-clock seconds for reality verification probe",
    )
    max_poll_attempts: int = Field(
        default=5,
        ge=1,
        le=30,
        description="Max polling iterations for OBS_EVENTUAL resources",
    )
    poll_interval_seconds: float = Field(
        default=0.5,
        ge=0.05,
        le=10.0,
        description="Interval between polling probes for OBS_EVENTUAL resources",
    )


class OutcomeVerificationContract(BaseModel):
    """Authoritative Gate 5 Outcome Assurance Contract documenting reality verification result."""

    model_config = ConfigDict(frozen=True)

    outcome_id: str = Field(..., description="Unique outcome verification identifier (outc_...)")
    transaction_id: str = Field(..., description="Parent AI Transaction ID")
    action_id: str = Field(..., description="Target ActionContract ID")
    tenant_id: str = Field(..., description="Authoritative tenant isolation ID")
    observability_class: ObservabilityClass = Field(..., description="Observability class of target")
    outcome_status: OutcomeStatus = Field(..., description="Canonical outcome qualification status")
    epistemic_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Calibrated epistemic confidence in verified state",
    )
    verifier_adapter: str = Field(..., description="Adapter engine name used for measurement")
    is_simulated: bool = Field(
        default=False,
        description="Whether verification probe ran against a simulated or mock environment",
    )
    expected_postconditions: dict[str, Any] = Field(
        default_factory=dict,
        description="Postconditions checked against reality",
    )
    observed_state: dict[str, Any] = Field(
        default_factory=dict,
        description="Actual state measured from target system",
    )
    discrepancies: list[str] = Field(
        default_factory=list,
        description="List of detected invariant violations or state mismatches",
    )
    evidence_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw verification evidence collected by adapter probe",
    )
    reconciliation_notes: list[str] = Field(
        default_factory=list,
        description="Reconciliation notes and epistemic caveats",
    )
    verification_hash: str = Field(
        ...,
        description="SHA-256 cryptographic seal over outcome contract components",
    )
    idempotency_key: str = Field(
        default="",
        description="Idempotency key associated with verification request",
    )
    target_environment: str = Field(
        default="DEFAULT",
        description="Target deployment environment (DEV, STAGING, PROD)",
    )
    contract_binding_hash: str | None = Field(
        default=None,
        description="SHA-256 binding fingerprint of parent ActionContract",
    )
    schema_version: str = Field(
        default="mirage.outcome.v1",
        description="Canonical schema version identifier for verification payload",
    )
    verified_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="UTC timestamp of outcome verification",
    )


class OutcomeReconciliationRequest(BaseModel):
    """Request payload to reconcile model output text against verified outcome state."""

    model_config = ConfigDict(extra="forbid")

    response_text: str = Field(..., description="Model generated response text to evaluate")
    outcome_id: str = Field(..., description="Verified Outcome ID to cross-check against")
    transaction_id: str | None = Field(
        default=None,
        description="Parent AI Transaction ID for correlation binding",
    )
    action_id: str | None = Field(
        default=None,
        description="ActionContract ID for correlation binding",
    )


class OutcomeReconciliationResult(BaseModel):
    """Result of Gate 5 cross-checking model claims against verified real-world outcome."""

    is_consistent: bool = Field(..., description="Whether model claims match reality")
    epistemic_conflict_detected: bool = Field(
        ...,
        description="Whether model asserted confirmation on unverified/unobservable actions",
    )
    conflict_reasons: list[str] = Field(default_factory=list, description="Specific discrepancies detected")
    recommended_disposition: str = Field(
        ...,
        description="Recommended action: PERMIT, REWRITE_WITH_CAVEAT, or REJECT",
    )
