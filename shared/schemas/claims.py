"""Pydantic schemas for atomic claim decomposition and verification results."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ClaimType(StrEnum):
    FACTUAL = "factual"
    NUMERICAL = "numerical"
    TEMPORAL = "temporal"
    RELATIONAL = "relational"
    IMAGE_GROUNDED = "image_grounded"
    OPINION = "opinion"


class ClaimCriticality(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


CRITICALITY_WEIGHTS: dict[ClaimCriticality, float] = {
    ClaimCriticality.HIGH: 1.0,
    ClaimCriticality.MEDIUM: 0.6,
    ClaimCriticality.LOW: 0.3,
}


class VerificationStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Claim(BaseModel):
    """Atomic claim extracted by the FLAN-T5 decomposer."""

    model_config = ConfigDict(frozen=True)

    claim_id: str = Field(description="Unique claim identifier, e.g. 'c_01'")
    text: str = Field(description="Normalized atomic proposition string")
    claim_type: ClaimType = Field(default=ClaimType.FACTUAL, description="Taxonomy classification")
    criticality: ClaimCriticality = Field(
        default=ClaimCriticality.MEDIUM,
        description="Domain impact importance category",
    )
    criticality_weight: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Numeric weight multiplier used during HRS aggregation",
    )
    span_start: int | None = Field(default=None, description="Character start offset in source response")
    span_end: int | None = Field(default=None, description="Character end offset in source response")


class EvidenceChunk(BaseModel):
    """Supporting or refuting evidence retrieved from Qdrant knowledge base."""

    chunk_id: str
    document_id: str
    content: str
    similarity_score: float = Field(ge=0.0, le=1.0)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimVerificationResult(BaseModel):
    """Detailed verification signals and risk assessment for a single claim."""

    claim: Claim
    status: VerificationStatus
    risk_score: float = Field(ge=0.0, le=1.0, description="Calibrated claim hallucination probability")
    rav_score: float | None = Field(
        default=None, ge=0.0, le=1.0, description="Retrieval Support Score (0=supported, 1=unsupported)"
    )
    scs_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Semantic Entropy variance score")
    nli_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Multi-evidence NLI contradiction score")
    ics_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Intra-response contradiction score")
    vgs_score: float | None = Field(default=None, ge=0.0, le=1.0, description="Visual Grounding inconsistency score")
    signal_attribution: dict[str, float] = Field(
        default_factory=dict,
        description="TreeSHAP attribution percentage weights for this claim",
    )
    evidence_chunks: list[EvidenceChunk] = Field(default_factory=list)
    explanation: str | None = Field(default=None, description="Human-readable explanation of risk assessment")
