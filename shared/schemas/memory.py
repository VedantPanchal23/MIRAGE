"""Authoritative schemas and typed contracts for Phase 7 Governed Memory.

MIRAGE memory is governed state, not unrestricted conversation storage.
Memory may influence future decisions only when its provenance, tenant,
purpose, permissions, freshness, and applicable policy permit that use.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from shared.schemas.audit import compute_sha256
from shared.schemas.control_plane import Taint


class MemoryCategory(StrEnum):
    """Semantic category distinguishing factual provenance and verifiability."""

    USER_FACT = "USER_FACT"
    VERIFIED_OBSERVATION = "VERIFIED_OBSERVATION"
    GENERATED_SUMMARY = "GENERATED_SUMMARY"
    INFERRED_PREFERENCE = "INFERRED_PREFERENCE"
    OPERATIONAL_STATE = "OPERATIONAL_STATE"
    UNTRUSTED_RETRIEVED = "UNTRUSTED_RETRIEVED"


class TrustLevel(StrEnum):
    """Verifiability and authority tier of stored memory."""

    VERIFIED = "VERIFIED"
    PROVISIONAL = "PROVISIONAL"
    UNTRUSTED = "UNTRUSTED"
    DISPUTED = "DISPUTED"
    REVOKED = "REVOKED"


class MemoryLifecycleState(StrEnum):
    """Explicit lifecycle state of memory record."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISPUTED = "DISPUTED"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class RetentionPolicy(StrEnum):
    """Retention rule governing durability and legal hold immunity."""

    STANDARD = "STANDARD"
    LEGAL_HOLD = "LEGAL_HOLD"
    EPHEMERAL = "EPHEMERAL"
    INDEFINITE = "INDEFINITE"


class MemoryPurpose(StrEnum):
    """Authorized usage purpose for memory retrieval and reasoning."""

    GENERAL = "GENERAL"
    USER_PROFILE = "USER_PROFILE"
    TASK_GROUNDING = "TASK_GROUNDING"
    OPERATIONAL_RECOVERY = "OPERATIONAL_RECOVERY"
    ANALYTICS = "ANALYTICS"


class PropagationStatus(StrEnum):
    """Synchronization status across secondary storage engines."""

    PROPAGATED = "PROPAGATED"
    PENDING = "PENDING"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"


class MemoryScope(StrEnum):
    """Visibility boundary for governed memory."""

    ORGANIZATIONAL = "ORGANIZATIONAL"
    AGENT = "AGENT"
    USER = "USER"


class AttestationStatus(StrEnum):
    """Cryptographic or human attestation tier for memory and evidence."""

    NONE = "NONE"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"
    PIPELINE_SIGNED = "PIPELINE_SIGNED"


class DerivationStep(BaseModel):
    """Traceable transformation event in memory lineage."""

    step_type: str = Field(description="e.g. EXTRACTION, SUMMARIZATION, VERIFICATION, DISPUTE")
    agent_id: str | None = None
    transaction_id: str | None = None
    action_id: str | None = None
    description: str = Field(min_length=1, max_length=1000)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


def compute_memory_integrity_hash(
    tenant_id: str,
    content: str,
    version: int,
    category: str,
    purpose: str,
) -> str:
    """Compute deterministic SHA-256 integrity digest binding content, version, and governance metadata."""
    payload = f"{tenant_id}:{category}:{purpose}:{version}:{content.strip()}"
    return compute_sha256(payload)


class GovernedMemoryCreateRequest(BaseModel):
    """Creation contract for Phase 7 Governed Memory."""

    content: str = Field(min_length=1, max_length=50_000, description="Raw memory text")
    memory_category: MemoryCategory = Field(default=MemoryCategory.USER_FACT)
    purpose: MemoryPurpose = Field(default=MemoryPurpose.GENERAL)
    scope: MemoryScope = Field(default=MemoryScope.ORGANIZATIONAL)
    owner_id: str = Field(default="system")
    memory_type: str = Field(default="ADVISORY", description="'ATTESTED' or 'ADVISORY'")
    attestation_status: AttestationStatus = Field(default=AttestationStatus.NONE)
    attested_by: str | None = None
    pipeline_signature: str | None = Field(
        default=None,
        description="Optional cryptographic pipeline signature if claimed signed by a trusted ingestion pipeline",
    )
    trust_level: TrustLevel | None = Field(
        default=None,
        description="Requested initial trust level; unprivileged callers cannot assign VERIFIED",
    )
    declared_taint: Taint = Field(default=Taint.INTERNAL)
    ttl_seconds: int | None = Field(default=None, ge=1)
    retention_policy: RetentionPolicy = Field(default=RetentionPolicy.STANDARD)
    retention_exception_reason: str | None = None
    source_type: str = Field(default="USER_INPUT", description="USER_INPUT, TOOL_OBSERVATION, MODEL_GENERATION, etc.")
    source_uri: str | None = None
    source_transaction_id: str | None = None
    source_action_id: str | None = None
    derivation_chain: list[DerivationStep] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, max_length=255)
    metadata_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def validate_content_non_empty(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Memory content cannot be whitespace only")
        return trimmed


class GovernedMemoryUpdateRequest(BaseModel):
    """Update contract creating a new version while preserving superseded lineage."""

    content: str = Field(min_length=1, max_length=50_000)
    purpose: MemoryPurpose | None = None
    declared_taint: Taint | None = None
    ttl_seconds: int | None = Field(default=None, ge=1)
    retention_policy: RetentionPolicy | None = None
    update_reason: str = Field(min_length=1, max_length=500, description="Audit justification for update")
    expected_version: int | None = Field(default=None, description="Optimistic concurrency control check")


class GovernedMemoryDisputeRequest(BaseModel):
    """Contract for formally disputing stored memory and downgrading confidence."""

    dispute_reason: str = Field(min_length=1, max_length=1000)
    reported_by: str | None = None


class GovernedMemoryHoldRequest(BaseModel):
    """Contract for applying or releasing a legal/regulatory hold."""

    hold_active: bool = Field(description="True to place on LEGAL_HOLD, False to return to STANDARD")
    justification: str = Field(min_length=1, max_length=1000)

    @field_validator("justification")
    @classmethod
    def validate_justification_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Legal hold justification cannot be empty or pure whitespace")
        return v.strip()


class GovernedMemorySearchRequest(BaseModel):
    """Purpose-bound, authenticated search request across governed memory."""

    query: str | None = Field(default=None, description="Optional text search keyword or phrase")
    purpose: MemoryPurpose = Field(default=MemoryPurpose.GENERAL, description="Required authorized purpose")
    category: MemoryCategory | None = None
    scope: MemoryScope | None = None
    min_trust_level: TrustLevel | None = None
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    include_superseded: bool = Field(default=False)
    limit: int = Field(default=20, ge=1, le=100)


class MemorySearchResultItem(BaseModel):
    """Evaluated memory item with relevance, trust, and inclusion explanation."""

    id: str
    content: str
    memory_category: MemoryCategory
    purpose: MemoryPurpose
    trust_level: TrustLevel
    lifecycle_state: MemoryLifecycleState
    confidence: float
    relevance_score: float = Field(ge=0.0, le=1.0)
    effective_trust_score: float = Field(ge=0.0, le=1.0)
    is_attested: bool
    taint: Taint
    provenance_uri: str | None
    inclusion_reason: str
    match_indicators: list[str] = Field(default_factory=list)


class GovernedMemorySearchResponse(BaseModel):
    """Governed memory search response with traceable filtering metrics."""

    tenant_id: str
    purpose: MemoryPurpose
    results: list[MemorySearchResultItem]
    total_evaluated: int
    excluded_count: int
    exclusion_reasons: dict[str, int] = Field(default_factory=dict)


class GovernedMemoryRecordResponse(BaseModel):
    """Comprehensive public representation of a Phase 7 Governed Memory record."""

    id: str
    tenant_id: str
    owner_id: str
    memory_type: str
    memory_category: MemoryCategory
    purpose: MemoryPurpose
    lifecycle_state: MemoryLifecycleState
    trust_level: TrustLevel
    scope: MemoryScope
    content: str
    content_hash: str
    version: int
    superseded_by_id: str | None = None
    attestation_status: AttestationStatus
    attested_by: str | None
    taint: Taint
    confidence: float
    retention_policy: RetentionPolicy
    retention_exception_reason: str | None = None
    ttl_seconds: int | None
    expires_at: datetime | None
    source_type: str
    source_uri: str | None = None
    source_transaction_id: str | None = None
    source_action_id: str | None = None
    derivation_chain: list[dict[str, Any]] = Field(default_factory=list)
    propagation_status: PropagationStatus
    propagation_details: dict[str, Any] = Field(default_factory=dict)
    dispute_reason: str | None = None
    idempotency_key: str | None = None
    metadata_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MemoryMaintenanceSweepResponse(BaseModel):
    """Outcome of automated TTL expiration and retention cleanup sweep."""

    tenant_id: str
    expired_count: int
    unexpired_active_count: int
    legal_holds_protected: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DeletionPropagationResult(BaseModel):
    """Multi-store logical sanitization and eviction propagation status report."""

    memory_id: str
    tenant_id: str
    postgres_shredded: bool = Field(
        default=True,
        description="True if primary PostgreSQL payload was logically sanitized and tombstoned",
    )
    qdrant_purged: bool | None = Field(
        default=None,
        description="True if purged, False if failed, None if unconfigured",
    )
    redis_invalidated: bool | None = Field(
        default=None,
        description="True if cache invalidated, False if failed, None if unconfigured",
    )
    mongo_purged: bool | None = Field(default=None)
    overall_status: PropagationStatus
    error_details: dict[str, str] = Field(default_factory=dict)
    message: str = Field(
        default="Memory logically sanitized and tombstoned",
        description="Truthful summary of primary sanitization and secondary eviction status",
    )
