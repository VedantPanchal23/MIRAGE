"""Typed contracts for Gate 2 Context Assurance, Provenance, and Governed Memory."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from shared.schemas.control_plane import Taint, TaintLatticeLevel


class ContextSourceType(StrEnum):
    """Authoritative source category for context items."""

    SYSTEM_POLICY = "SYSTEM_POLICY"
    AGENT_INSTRUCTION = "AGENT_INSTRUCTION"
    USER_INPUT = "USER_INPUT"
    RETRIEVED_EVIDENCE = "RETRIEVED_EVIDENCE"
    MEMORY_ATTESTED = "MEMORY_ATTESTED"
    MEMORY_ADVISORY = "MEMORY_ADVISORY"
    TOOL_OBSERVATION = "TOOL_OBSERVATION"


class AttestationStatus(StrEnum):
    """Cryptographic or human attestation tier for memory and evidence."""

    NONE = "NONE"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"
    PIPELINE_SIGNED = "PIPELINE_SIGNED"


class ContextDisposition(StrEnum):
    """Evaluation outcome for an individual context candidate."""

    ACCEPTED = "ACCEPTED"
    QUARANTINED_AS_DATA = "QUARANTINED_AS_DATA"
    SANITIZED = "SANITIZED"
    REJECTED = "REJECTED"
    BUDGET_EXCLUDED = "BUDGET_EXCLUDED"


class MemoryScope(StrEnum):
    """Visibility boundary for governed memory."""

    ORGANIZATIONAL = "ORGANIZATIONAL"
    AGENT = "AGENT"
    USER = "USER"


class ContextProvenance(BaseModel):
    """Cryptographically auditable lineage of context origin."""

    source_uri: str = Field(description="URI, filename, tool identifier, or memory key")
    document_id: str | None = Field(default=None, description="Authoritative document ID if from KB")
    chunk_id: str | None = Field(default=None, description="Vector or text chunk ID")
    generation: int | None = Field(default=None, description="Document index generation / version")
    origin_id: str | None = Field(default=None, description="Source transaction, user, or author ID")
    attestation_status: AttestationStatus = AttestationStatus.NONE
    attested_by: str | None = None
    retrieval_score: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ContextItemCandidate(BaseModel):
    """Candidate context payload submitted for Gate 2 evaluation."""

    id: str | None = None
    source_type: ContextSourceType
    content: str = Field(min_length=1, max_length=100_000)
    provenance: ContextProvenance
    declared_taint: Taint = Taint.PUBLIC
    is_instruction: bool = False
    ttl_seconds: int | None = Field(default=None, ge=1)


class ContextItem(BaseModel):
    """Evaluated, verified context item with assigned trust and disposition."""

    id: str
    source_type: ContextSourceType
    content: str
    tenant_id: str
    is_instruction: bool
    taint: Taint
    provenance: ContextProvenance
    integrity_hash: str
    trust_score: float = Field(ge=0.0, le=1.0)
    expiration_ts: datetime | None = None
    disposition: ContextDisposition = ContextDisposition.ACCEPTED
    disposition_reason: str | None = None
    indicators: list[str] = Field(default_factory=list)


class GovernedContextRequest(BaseModel):
    """Request to assemble and assure context for an AI Transaction."""

    transaction_id: str
    items: list[ContextItemCandidate]
    max_context_bytes: int = Field(default=32_000, ge=500, le=500_000)
    min_trust_threshold: float = Field(default=0.20, ge=0.0, le=1.0)
    quarantine_injections: bool = Field(
        default=True,
        description="If True, encapsulates detected injection payloads strictly as data; if False, drops item.",
    )


class GovernedContextResponse(BaseModel):
    """Assembled governed prompt and context evaluation ledger."""

    transaction_id: str
    assembled_prompt: str
    context_items: list[ContextItem]
    accepted_count: int
    rejected_count: int
    quarantined_count: int
    effective_taints: set[Taint]
    high_water_lattice_level: TaintLatticeLevel
    budget_consumed_bytes: int
    budget_truncated: bool
    provenance_audit_hash: str


class MemoryCreateRequest(BaseModel):
    """Creation contract for Governed Memory."""

    content: str = Field(min_length=1, max_length=50_000)
    memory_type: str = Field(default="ADVISORY", description="'ATTESTED' or 'ADVISORY'")
    scope: MemoryScope = MemoryScope.ORGANIZATIONAL
    owner_id: str = Field(default="system")
    attestation_status: AttestationStatus = AttestationStatus.NONE
    attested_by: str | None = None
    declared_taint: Taint = Taint.INTERNAL
    ttl_seconds: int | None = Field(default=None, ge=1)
    metadata_payload: dict[str, Any] = Field(default_factory=dict)


class MemoryResponse(BaseModel):
    """Public representation of a Governed Memory record."""

    id: str
    tenant_id: str
    owner_id: str
    memory_type: str
    scope: MemoryScope
    content: str
    content_hash: str
    attestation_status: AttestationStatus
    attested_by: str | None
    taint: Taint
    confidence: float
    ttl_seconds: int | None
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
