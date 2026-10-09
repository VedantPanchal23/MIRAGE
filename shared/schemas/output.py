"""Canonical Gate 4 Output Assurance contracts and schemas for MIRAGE 3.0.

Implements Input_Output_Assurance.md §5, Cost_Optimization.md §3, and Technical_Architecture.md §4.
"""

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.schemas.claims import ClaimVerificationResult
from shared.schemas.hrs import ConformalInterval, RiskTier, SignalAttribution


class OutputVerificationStatus(StrEnum):
    """Canonical verification status of AI generated output."""

    VERIFIED = "VERIFIED"
    PARTIALLY_VERIFIED = "PARTIALLY_VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONTRADICTED = "CONTRADICTED"
    BLOCKED = "BLOCKED"
    DEGRADED = "DEGRADED"


class Gate4Decision(StrEnum):
    """Authoritative decision space for Gate 4 Output Assurance policy gate."""

    ALLOW = "ALLOW"
    ALLOW_WITH_UNCERTAINTY = "ALLOW_WITH_UNCERTAINTY"
    REQUIRE_VERIFICATION = "REQUIRE_VERIFICATION"
    REDACT_TRANSFORM = "REDACT_TRANSFORM"
    REQUIRE_HUMAN_REVIEW = "REQUIRE_HUMAN_REVIEW"
    BLOCK = "BLOCK"


class VerificationTier(StrEnum):
    """Adaptive verification ladder tiers defined in Cost_Optimization.md §3."""

    TIER_1_DETERMINISTIC = "TIER_1_DETERMINISTIC"
    TIER_2_SMALL_MODEL = "TIER_2_SMALL_MODEL"
    TIER_3_RETRIEVAL_NLI = "TIER_3_RETRIEVAL_NLI"
    TIER_4_FRONTIER_JUDGE = "TIER_4_FRONTIER_JUDGE"
    TIER_5_HUMAN_REVIEW = "TIER_5_HUMAN_REVIEW"


class VerificationBudget(BaseModel):
    """Budget limits allocated to Gate 4 verification for an AI Transaction."""

    model_config = ConfigDict(frozen=True)

    max_cost_dollars: float = Field(default=0.10, ge=0.0, description="Maximum allowed spend on verification")
    max_tokens: int = Field(default=4000, ge=0, description="Maximum verification tokens")
    max_latency_ms: float = Field(default=5000.0, ge=0.0, description="Wall-clock verification latency budget")
    max_model_calls: int = Field(default=10, ge=0, description="Maximum verification model invocations")


class BudgetConsumption(BaseModel):
    """Telemetry tracking verification resources consumed during Gate 4 processing."""

    cost_dollars: float = Field(default=0.0, ge=0.0)
    tokens_used: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    model_calls: int = Field(default=0, ge=0)
    escalation_count: int = Field(default=0, ge=0)


class CalibrationMetadata(BaseModel):
    """Provenance and scientific calibration metadata."""

    dataset_id: str = Field(default="mirage_calib_v1")
    sample_count: int = Field(default=500, ge=0)
    method: str = Field(default="isotonic")
    ece: float = Field(default=0.021, ge=0.0, le=1.0)
    brier_score: float = Field(default=0.045, ge=0.0, le=1.0)
    is_certified: bool = Field(
        default=False,
        description="Whether calibration is verified on empirical held-out benchmark splits (e.g. HaluEval/FActScore)",
    )
    certification_status: str = Field(
        default="NOT_SCIENTIFICALLY_CERTIFIED",
        description="Certification status: EMPIRICALLY_CERTIFIED or NOT_SCIENTIFICALLY_CERTIFIED",
    )
    empirical_dataset_checksum: str | None = Field(
        default=None,
        description="SHA-256 checksum of authoritative held-out evaluation dataset when certified",
    )
    finite_sample_guarantee: str = Field(
        default=(
            "Analytical conformal interval derived under exchangeability assumption (Vovk et al. 2005); "
            "requires empirical benchmark certification for statistical production SLA."
        ),
        description="Explicit disclosure demarcating analytical formula bounds from certified empirical coverage.",
    )
    calibrated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    @model_validator(mode="after")
    def validate_scientific_certification(self) -> "CalibrationMetadata":
        """Strictly prevent asserting empirical certification without verified sample size and dataset checksum."""
        if self.is_certified or self.certification_status == "EMPIRICALLY_CERTIFIED":
            if not self.empirical_dataset_checksum or len(self.empirical_dataset_checksum) != 64:
                raise ValueError(
                    "Certified calibration requires a valid 64-character SHA-256 empirical_dataset_checksum"
                )
            if not re.fullmatch(r"[0-9a-fA-F]{64}", self.empirical_dataset_checksum):
                raise ValueError("empirical_dataset_checksum must be a valid hexadecimal SHA-256 string")
            if self.sample_count < 1000:
                raise ValueError("Empirically certified calibration requires sample_count >= 1000")
        return self


class OutputSafetyResult(BaseModel):
    """Result of DLP and safety inspection on the output payload."""

    safe: bool = True
    pii_detected: bool = False
    secrets_detected: bool = False
    prompt_injection_leakage: bool = False
    redacted_content: str | None = None
    violation_reasons: list[str] = Field(default_factory=list)


class OutputFactualResult(BaseModel):
    """Result of factual grounding and NLI consistency checks."""

    factual_consistency_score: float = Field(default=1.0, ge=0.0, le=1.0)
    claims_count: int = Field(default=0, ge=0)
    supported_claims_count: int = Field(default=0, ge=0)
    contradicted_claims_count: int = Field(default=0, ge=0)
    unsupported_claims_count: int = Field(default=0, ge=0)
    evidence_sufficiency: float = Field(default=1.0, ge=0.0, le=1.0)


class OutputAssuranceContract(BaseModel):
    """Canonical Gate 4 Output Assurance contract encapsulating verified state."""

    output_id: str = Field(description="Unique output identifier")
    transaction_id: str = Field(description="Parent AI Transaction identifier")
    tenant_id: str = Field(description="Authoritative tenant identifier")
    model_id: str = Field(description="Generator model identifier")
    model_version: str = Field(default="1.0.0")
    original_output: str = Field(description="Original unverified model response")
    final_output: str = Field(description="Final output (original, redacted, or corrected)")
    output_hash: str = Field(description="SHA-256 fingerprint of final output")

    verification_status: OutputVerificationStatus
    final_decision: Gate4Decision
    risk_classification: RiskTier
    risk_score: float = Field(ge=0.0, le=1.0, description="Calibrated HRS probability")

    conformal_interval: ConformalInterval
    signal_attribution: SignalAttribution

    safety_result: OutputSafetyResult
    factual_result: OutputFactualResult
    claims: list[ClaimVerificationResult] = Field(default_factory=list)

    verification_tier_path: list[VerificationTier] = Field(default_factory=list)
    escalation_reasons: list[str] = Field(default_factory=list)
    budget_consumed: BudgetConsumption = Field(default_factory=BudgetConsumption)
    calibration_metadata: CalibrationMetadata = Field(default_factory=CalibrationMetadata)
    verifier_provenance: list[str] = Field(default_factory=list)

    was_corrected: bool = False
    correction_attempts: int = Field(default=0, ge=0)
    correction_history: list[dict[str, Any]] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    verified_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    audit_record_hash: str = Field(default="", description="Cryptographic SHA-256 hash linking to audit chain")


class OutputAssuranceRequest(BaseModel):
    """Request payload submitted to Gate 4 for output assurance."""

    transaction_id: str = Field(description="Parent AI Transaction ID")
    model_id: str = Field(default="allam-2-7b")
    model_version: str = Field(default="1.0.0")
    response_text: str = Field(min_length=1, description="Generated completion to assure")
    prompt: str = Field(default="", description="Original user prompt")
    context_chunks: list[dict[str, Any] | str] = Field(
        default_factory=list, description="Optional Gate 2 evidence context chunks"
    )
    evidence_chunks: list[dict[str, Any] | str] = Field(
        default_factory=list, description="Alternative alias for evidence context chunks"
    )
    knowledge_base_id: str | None = Field(default=None, description="Qdrant collection for RAV grounding")
    image_urls: list[str] = Field(default_factory=list, description="Multimodal image references")
    auto_correct: bool = Field(default=True, description="Enable autonomous LangGraph correction loop")
    require_factual_verification: bool = Field(
        default=True, description="Whether to invoke Tier 3 verification ladder"
    )
    budget: VerificationBudget = Field(default_factory=VerificationBudget)
