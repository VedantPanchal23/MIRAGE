"""Typed Phase 1 control-plane contracts and Dynamic Information Flow Control (DIFC) lattice."""

from collections.abc import Iterable
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Decision(StrEnum):
    """Deterministic policy and input-assurance decision space."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    TRANSFORM = "TRANSFORM"
    ESCALATE = "ESCALATE"
    BLOCK = "BLOCK"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


class TaintLatticeLevel(IntEnum):
    """Formal security lattice levels for Dynamic Information Flow Control (DIFC).

    PUBLIC < INTERNAL < CONFIDENTIAL < RESTRICTED_PII < SECRET_CREDENTIAL
    """

    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED_PII = 3
    SECRET_CREDENTIAL = 4


class Taint(StrEnum):
    """Canonical information-flow taints available in Phase 1."""

    UNTRUSTED = "TAINT_UNTRUSTED"
    PUBLIC = "TAINT_PUBLIC"
    INTERNAL = "TAINT_INTERNAL"
    CONFIDENTIAL = "TAINT_CONFIDENTIAL"
    RESTRICTED_PII = "TAINT_RESTRICTED_PII"
    SECRET_CREDENTIAL = "TAINT_SECRET_CREDENTIAL"
    CONCURRENT_RESTRICTION = "TAINT_CONCURRENT_RESTRICTION"


_TAINT_TO_LATTICE: dict[Taint, TaintLatticeLevel] = {
    Taint.PUBLIC: TaintLatticeLevel.PUBLIC,
    Taint.INTERNAL: TaintLatticeLevel.INTERNAL,
    Taint.CONFIDENTIAL: TaintLatticeLevel.CONFIDENTIAL,
    Taint.RESTRICTED_PII: TaintLatticeLevel.RESTRICTED_PII,
    Taint.SECRET_CREDENTIAL: TaintLatticeLevel.SECRET_CREDENTIAL,
}


def taint_to_lattice_level(taint: Taint | str) -> TaintLatticeLevel:
    """Map a taint enum/string to its corresponding formal lattice level."""
    if isinstance(taint, str):
        try:
            taint = Taint(taint)
        except ValueError:
            return TaintLatticeLevel.PUBLIC
    return _TAINT_TO_LATTICE.get(taint, TaintLatticeLevel.PUBLIC)


def compute_lattice_high_water_mark(taints: Iterable[Taint | str]) -> TaintLatticeLevel:
    """Compute the supremum (join) lattice level across all active taints."""
    max_level = TaintLatticeLevel.PUBLIC
    for item in taints:
        level = taint_to_lattice_level(item)
        if level > max_level:
            max_level = level
    return max_level


def is_dangerous_triad_active(taints: Iterable[Taint | str]) -> bool:
    """Detect whether concurrent untrusted content and confidential/secret data are present.

    ADR-0008 & Security.md Section 4.1:
    When TAINT_UNTRUSTED coincides with TAINT_CONFIDENTIAL, TAINT_RESTRICTED_PII,
    or TAINT_SECRET_CREDENTIAL, the dangerous triad is active.
    """
    taint_set = {item.value if isinstance(item, Taint) else str(item) for item in taints}
    has_untrusted = Taint.UNTRUSTED.value in taint_set
    has_confidential = bool(
        taint_set
        & {
            Taint.CONFIDENTIAL.value,
            Taint.RESTRICTED_PII.value,
            Taint.SECRET_CREDENTIAL.value,
        }
    )
    return has_untrusted and has_confidential


def normalize_taints(taints: Iterable[Taint | str]) -> set[Taint]:
    """Coerce strings to Taint enums and automatically interlock concurrent restrictions."""
    result: set[Taint] = set()
    for item in taints:
        try:
            result.add(item if isinstance(item, Taint) else Taint(str(item)))
        except ValueError:
            continue
    if is_dangerous_triad_active(result):
        result.add(Taint.CONCURRENT_RESTRICTION)
    return result


class TransactionState(StrEnum):
    """Explicit governed transaction lifecycle states."""

    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    ASSEMBLING_CONTEXT = "ASSEMBLING_CONTEXT"
    TURN_REASONING = "TURN_REASONING"
    AUTHORIZING_ACTION = "AUTHORIZING_ACTION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING_TOOL = "EXECUTING_TOOL"
    VERIFYING_OUTCOME = "VERIFYING_OUTCOME"
    UPDATING_CONTEXT = "UPDATING_CONTEXT"
    VERIFYING_OUTPUT = "VERIFYING_OUTPUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    PARTIAL = "PARTIAL"


class PolicyRule(BaseModel):
    """Declarative typed rules within an active Policy."""

    effect: Decision = Decision.ALLOW
    max_risk: int = Field(default=100, ge=0, le=100)
    require_approval: bool = False
    deny_indicators: list[str] = Field(default_factory=list)
    disallowed_taints: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    """Auditable deterministic policy result."""

    decision: Decision
    reason: str
    policy_id: str | None = None
    policy_version: int | None = None


class InputAssuranceRequest(BaseModel):
    """Input to the deterministic Gate 1 checks."""

    content: str = Field(min_length=1, max_length=100_000)
    declared_confidential: bool = False
    policy_id: str | None = None
    initial_risk: int = Field(default=0, ge=0, le=100)


class InputAssuranceResult(BaseModel):
    """Gate 1 outcome and immutable starting taints."""

    decision: PolicyDecision
    taints: set[Taint] = Field(default_factory=set)
    risk: int = Field(ge=0, le=100)
    indicators: list[str] = Field(default_factory=list)


class TransactionCreateRequest(InputAssuranceRequest):
    """Creation request for a governed AI transaction."""

    idempotency_key: str = Field(min_length=8, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=255)
    max_turns: int = Field(default=4, ge=1, le=64)
    agent_id: str | None = None
    parent_transaction_id: str | None = None
    budget_id: str | None = None


class TransactionTransitionRequest(BaseModel):
    """An optimistic-concurrency transaction state transition."""

    target_state: TransactionState
    expected_version: int = Field(ge=0)
    add_taints: set[Taint] = Field(default_factory=set)
    reason: str = Field(min_length=1, max_length=1000)
    output_id: str | None = Field(default=None, description="Optional bound Gate 4 OutputAssuranceRecord ID")
    expected_output_hash: str | None = Field(default=None, description="Optional bound output SHA-256 hash")


class TransactionCancelRequest(BaseModel):
    """Explicit request to abort/cancel an active transaction."""

    reason: str = Field(default="Cancelled by client", min_length=1, max_length=1000)


class TransactionResponse(BaseModel):
    """Public representation of the governed transaction core ledger."""

    id: str
    tenant_id: str
    actor_identity_id: str
    state: TransactionState
    turn_count: int
    max_turns: int
    taints: set[Taint]
    version: int
    final_disposition: str | None
    policy_id: str | None
    correlation_id: str


class CapabilityValidationRequest(BaseModel):
    """Action Assurance capability check contract."""

    capability_id: str
    capability_type: str
    resource: dict[str, Any] = Field(default_factory=dict)
    requested_autonomy_level: int = Field(default=0, ge=0, le=4)
    transaction_id: str | None = None
