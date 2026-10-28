"""Typed request and response models for the MIRAGE Python SDK.

Models conform strictly to MIRAGE 3.0 gateway API contracts while tolerating
newly added server fields (extra="ignore") to maintain backwards compatibility.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------


class RiskTier(StrEnum):
    """Hallucination Risk Score operational tiers."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class VerificationStatus(StrEnum):
    """Claim-level verification status."""

    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ActionState(StrEnum):
    """Governed lifecycle state of an Action Contract."""

    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    EXECUTION_UNCERTAIN = "EXECUTION_UNCERTAIN"


class ActionType(StrEnum):
    """Categorization of state mutations."""

    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    EXECUTE = "EXECUTE"
    EGRESS = "EGRESS"


class Decision(StrEnum):
    """Policy or governance decision."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    TRANSFORM = "TRANSFORM"
    BLOCK = "BLOCK"


class ApprovalStatus(StrEnum):
    """Human approval ticket status."""

    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class ObservabilityClass(StrEnum):
    """Epistemic observability classification of target systems."""

    OBS_DIRECT = "OBS_DIRECT"
    OBS_EVENTUAL = "OBS_EVENTUAL"
    OBS_INFERRED = "OBS_INFERRED"
    OBS_BLIND = "OBS_BLIND"


class OutcomeStatus(StrEnum):
    """Canonical Gate 5 reality verification status."""

    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFIED_FAILURE = "VERIFIED_FAILURE"
    PARTIAL_ACHIEVEMENT = "PARTIAL_ACHIEVEMENT"
    UNKNOWN = "UNKNOWN"
    UNVERIFIABLE = "UNVERIFIABLE"
    SUCCESS_CONFIRMED = "SUCCESS_CONFIRMED"
    SUCCESS_EVENTUALLY_OBSERVED = "SUCCESS_EVENTUALLY_OBSERVED"
    ACKNOWLEDGED_UNVERIFIED = "ACKNOWLEDGED_UNVERIFIED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    UNOBSERVABLE = "UNOBSERVABLE"


class MCPServerTransport(StrEnum):
    """Transport protocol for MCP servers."""

    STDIO = "STDIO"
    HTTP_STREAM = "HTTP_STREAM"


class MCPTrustStatus(StrEnum):
    """Trust status for registered MCP servers."""

    PENDING_APPROVAL = "PENDING_APPROVAL"
    TRUSTED = "TRUSTED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


# -----------------------------------------------------------------------------
# Gate 4: Verification Models
# -----------------------------------------------------------------------------


class ConformalInterval(BaseModel):
    """Group-conditional conformal prediction interval."""

    model_config = ConfigDict(extra="ignore")

    lower: float = Field(ge=0.0, le=1.0)
    upper: float = Field(ge=0.0, le=1.0)
    confidence_level: float = Field(default=0.95, ge=0.5, le=0.999)
    conditional_group: str = "overall"

    @property
    def width(self) -> float:
        return round(self.upper - self.lower, 4)


class SignalAttribution(BaseModel):
    """TreeSHAP feature attributions across active verification signals."""

    model_config = ConfigDict(extra="ignore")

    rav: float = 0.0
    scs: float = 0.0
    nli: float = 0.0
    ics: float = 0.0
    vgs: float | None = None


class HRSResult(BaseModel):
    """Hallucination Risk Score result."""

    model_config = ConfigDict(extra="ignore")

    hrs: float = Field(ge=0.0, le=1.0)
    raw_score: float = Field(ge=0.0, le=1.0)
    tier: RiskTier
    conformal_interval: ConformalInterval
    signal_attribution: SignalAttribution
    claims_count: int = 0
    contradicted_claims_count: int = 0
    computation_latency_ms: float = 0.0


class Claim(BaseModel):
    """Atomic claim extracted from text."""

    model_config = ConfigDict(extra="ignore")

    claim_id: str
    text: str
    claim_type: str = "factual"
    criticality: str = "medium"
    criticality_weight: float = 0.6
    span_start: int | None = None
    span_end: int | None = None


class EvidenceChunk(BaseModel):
    """Evidence retrieved in support or refutation of a claim."""

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    document_id: str
    content: str
    similarity_score: float = 0.0
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimVerificationResult(BaseModel):
    """Verification verdict and risk scores for an individual claim."""

    model_config = ConfigDict(extra="ignore")

    claim: Claim
    status: VerificationStatus
    risk_score: float = 0.0
    rav_score: float | None = None
    scs_score: float | None = None
    nli_score: float | None = None
    ics_score: float | None = None
    vgs_score: float | None = None
    signal_attribution: dict[str, float] = Field(default_factory=dict)
    evidence_chunks: list[EvidenceChunk] = Field(default_factory=list)
    explanation: str | None = None


class VerificationMetadata(BaseModel):
    """Telemetry and execution metrics for a verification request."""

    model_config = ConfigDict(extra="ignore")

    trace_id: str
    execution_time_ms: float = 0.0
    pipeline_signals_used: list[str] = Field(default_factory=list)
    cached_scs_hit: bool = False
    correction_applied: bool = False
    correction_iterations: int = 0
    circuit_breakers_tripped: list[str] = Field(default_factory=list)


class VerificationRequest(BaseModel):
    """Request submitted to POST /v1/verify."""

    prompt: str = ""
    response: str = ""
    tenant_id: str = ""
    session_id: str | None = None
    knowledge_base_id: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    model_id: str = "allam-2-7b"
    auto_correct: bool = True


class VerificationResponse(BaseModel):
    """Response returned from POST /v1/verify."""

    model_config = ConfigDict(extra="ignore")

    request_id: str
    verified_response: str
    original_response: str
    hrs_result: HRSResult
    claims: list[ClaimVerificationResult] = Field(default_factory=list)
    metadata: VerificationMetadata


# -----------------------------------------------------------------------------
# Gate 3: Action Assurance Models
# -----------------------------------------------------------------------------


class PreconditionRule(BaseModel):
    """Pre-execution condition assertion."""

    check_type: str
    target: str
    expected_value: Any = None
    description: str = ""


class PostconditionRule(BaseModel):
    """Post-execution state assertion."""

    assertion: str
    target: str
    expected_value: Any = None
    description: str = ""


class BlastRadiusAssessment(BaseModel):
    """Blast radius accounting for an action."""

    resource_scope: str = "DEFAULT"
    estimated_dollar_cost: float = 0.0
    affected_records_count: int = 1
    reversibility: str = "REVERSIBLE"
    target_environment: str = "DEV"


class ActionProposal(BaseModel):
    """Proposal to authorize a real-world action."""

    transaction_id: str = Field(min_length=1, max_length=64)
    tool_name: str = Field(min_length=1, max_length=128)
    action_type: ActionType = ActionType.EXECUTE
    target_resource: str = Field(min_length=1, max_length=512)
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=255)
    preconditions: list[PreconditionRule] = Field(default_factory=list)
    postconditions: list[PostconditionRule] = Field(default_factory=list)
    blast_radius: BlastRadiusAssessment = Field(default_factory=BlastRadiusAssessment)


class ActionAuthorizationDecision(BaseModel):
    """Gate 3 Action Assurance decision."""

    model_config = ConfigDict(extra="ignore")

    action_id: str
    decision: Decision
    state: ActionState
    reason: str
    risk_score: int
    autonomy_level: int
    normalized_parameters: dict[str, Any] = Field(default_factory=dict)
    parameters_hash: str
    approval_id: str | None = None
    cumulative_window_risk: int = 0
    cumulative_window_cost: float = 0.0
    is_salami_slice_violation: bool = False
    fencing_token: int | None = None


class ActionExecutionRequest(BaseModel):
    """Request payload to execute an authorized action."""

    action_id: str
    approval_token: str | None = None


class ActionExecutionResult(BaseModel):
    """Result of executing an authorized action."""

    model_config = ConfigDict(extra="ignore")

    action_id: str
    transaction_id: str
    state: ActionState
    observed_output: dict[str, Any] = Field(default_factory=dict)
    taints: set[str] = Field(default_factory=set)
    postconditions_satisfied: bool = False
    postcondition_evidence: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
    outcome_status: OutcomeStatus | None = None
    outcome_id: str | None = None
    requires_outcome_assurance: bool = False

    @property
    def is_uncertain(self) -> bool:
        """Whether the action is in an unconfirmed, uncertain state."""
        return self.state == ActionState.EXECUTION_UNCERTAIN


class StrandedActionInfo(BaseModel):
    """Details of an action stranded in EXECUTING or EXECUTION_UNCERTAIN."""

    model_config = ConfigDict(extra="ignore")

    action_id: str
    transaction_id: str
    tool_name: str
    target_resource: str
    state: ActionState
    lease_fencing_token: int | None = None
    lease_holder_id: str | None = None
    created_at: str
    stranded_duration_seconds: float = 0.0
    is_lease_expired: bool = False


class ActionReconciliationRequest(BaseModel):
    """Request payload to idempotently reconcile a stranded action."""

    action_id: str
    resolution_state: ActionState
    rationale: str = Field(min_length=8)
    verified_evidence: dict[str, Any] = Field(default_factory=dict)


class ApprovalResponse(BaseModel):
    """Human approval ticket details."""

    model_config = ConfigDict(extra="ignore")

    approval_id: str
    tenant_id: str
    action_id: str
    status: ApprovalStatus
    risk_score: int
    tool_name: str
    target_resource: str
    requested_at: str
    decided_at: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None
    approval_token: str | None = None


class ApprovalDecisionRequest(BaseModel):
    """Decision payload to grant or deny a human approval ticket."""

    reason: str = Field(min_length=3)


# -----------------------------------------------------------------------------
# Gate 5: Outcome Assurance Models
# -----------------------------------------------------------------------------


class IndependentObservation(BaseModel):
    """Authoritative target-state observation payload from an independent observer."""

    model_config = ConfigDict(extra="ignore")

    observation_id: str = Field(default_factory=lambda: f"obs_{uuid.uuid4().hex[:12]}")
    source_id: str = "DATABASE"
    target_resource: str = ""
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    observed_state: dict[str, Any] = Field(default_factory=dict)
    evidence_digest: str = ""
    signature: str | None = None
    epistemic_confidence: float = 1.0

    @model_validator(mode="before")
    @classmethod
    def _populate_defaults_and_digest(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("observation_id"):
                data["observation_id"] = f"obs_{uuid.uuid4().hex[:12]}"
            if not data.get("source_id"):
                data["source_id"] = "DATABASE"
            if not data.get("observed_at"):
                data["observed_at"] = datetime.now(UTC)
            if not data.get("evidence_digest") and data.get("observed_state"):
                canonical_bytes = json.dumps(
                    data["observed_state"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                data["evidence_digest"] = hashlib.sha256(canonical_bytes).hexdigest()
        return data


class OutcomeVerificationRequest(BaseModel):
    """Request submitted to POST /v1/actions/{action_id}/outcome."""

    transaction_id: str
    action_id: str
    idempotency_key: str | None = None
    observability_class: ObservabilityClass = ObservabilityClass.OBS_DIRECT
    verifier_type: str = "DATABASE"
    expected_postconditions: dict[str, Any] = Field(default_factory=dict)
    adapter_config: dict[str, Any] = Field(default_factory=dict)
    observation: IndependentObservation | None = None
    timeout_seconds: float = 10.0
    max_poll_attempts: int = 5


class OutcomeVerificationContract(BaseModel):
    """Authoritative Gate 5 Outcome Assurance Contract."""

    model_config = ConfigDict(extra="ignore")

    outcome_id: str
    transaction_id: str
    action_id: str
    tenant_id: str
    observability_class: ObservabilityClass
    outcome_status: OutcomeStatus
    epistemic_confidence: float = Field(ge=0.0, le=1.0)
    verifier_adapter: str
    is_simulated: bool = False
    expected_postconditions: dict[str, Any] = Field(default_factory=dict)
    observed_state: dict[str, Any] = Field(default_factory=dict)
    discrepancies: list[str] = Field(default_factory=list)
    evidence_payload: dict[str, Any] = Field(default_factory=dict)
    reconciliation_notes: list[str] = Field(default_factory=list)
    verification_hash: str
    verified_at: str


# -----------------------------------------------------------------------------
# Audit Models
# -----------------------------------------------------------------------------


class AuditChainVerificationResponse(BaseModel):
    """Response returned by POST /v1/audit/verify-chain."""

    model_config = ConfigDict(extra="ignore")

    valid: bool
    tenant_id: str
    total_records_verified: int
    chain_status: str
    message: str


# -----------------------------------------------------------------------------
# MCP Registry Models
# -----------------------------------------------------------------------------


class MCPServerCreateRequest(BaseModel):
    """Payload to register an external MCP server."""

    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1024)
    transport_type: MCPServerTransport = MCPServerTransport.STDIO
    connection_config: dict[str, Any] = Field(default_factory=dict)
    permitted_capabilities: list[str] = Field(default_factory=list)
    egress_allowlist: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class MCPServerUpdateRequest(BaseModel):
    """Payload to update an external MCP server."""

    description: str | None = None
    connection_config: dict[str, Any] | None = None
    permitted_capabilities: list[str] | None = None
    egress_allowlist: list[str] | None = None
    timeout_seconds: int | None = None


class MCPTrustStatusUpdateRequest(BaseModel):
    """Payload to update trust status of an MCP server."""

    trust_status: MCPTrustStatus
    reason: str = Field(min_length=3, max_length=512)


class MCPServerResponse(BaseModel):
    """Representation of an MCP server."""

    model_config = ConfigDict(extra="ignore")

    id: str
    tenant_id: str
    name: str
    description: str = ""
    transport_type: str
    connection_config: dict[str, Any] = Field(default_factory=dict)
    trust_status: str
    permitted_capabilities: list[str] = Field(default_factory=list)
    egress_allowlist: list[str] = Field(default_factory=list)
    timeout_seconds: int = 30
    tool_count: int = 0
    created_at: datetime
    updated_at: datetime


class MCPServerListResponse(BaseModel):
    """Paginated list of registered MCP servers."""

    model_config = ConfigDict(extra="ignore")

    servers: list[MCPServerResponse] = Field(default_factory=list)
    total: int = 0
    limit: int = 50
    offset: int = 0


class MCPDiscoveredTool(BaseModel):
    """Tool discovered from an external MCP server."""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    schema_fingerprint: str = ""


class MCPToolDiscoveryResult(BaseModel):
    """Result of discovering tools from an MCP server."""

    model_config = ConfigDict(extra="ignore")

    server_id: str
    tools_discovered_count: int = 0
    tools_registered: list[str] = Field(default_factory=list)
    tools: list[MCPDiscoveredTool] = Field(default_factory=list)


class ToolResponse(BaseModel):
    """Public representation of registered tool in Gate 3 tenant registry."""

    model_config = ConfigDict(extra="ignore")

    id: str
    tenant_id: str
    name: str
    description: str = ""
    tool_type: str
    egress_type: str
    trust_level: str
    required_capability: str
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    active: bool = True
    created_at: str
