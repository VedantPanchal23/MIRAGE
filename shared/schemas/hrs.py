"""Pydantic schemas for the Hallucination Risk Score (HRS) engine."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class RiskTier(StrEnum):
    LOW = "LOW"  # HRS < 0.20 (Deliver directly)
    MEDIUM = "MEDIUM"  # 0.20 <= HRS < 0.60 (Log and monitor)
    HIGH = "HIGH"  # 0.60 <= HRS < 0.85 (Trigger agentic correction loop)
    CRITICAL = "CRITICAL"  # HRS >= 0.85 (Block / escalate immediately)


def determine_risk_tier(hrs: float) -> RiskTier:
    """Classify a calibrated HRS probability into its operational risk tier."""
    if hrs < 0.20:
        return RiskTier.LOW
    if hrs < 0.60:
        return RiskTier.MEDIUM
    if hrs < 0.85:
        return RiskTier.HIGH
    return RiskTier.CRITICAL


class ConformalInterval(BaseModel):
    """Mondrian (Group-Conditional) Conformal Prediction confidence interval."""

    lower: float = Field(ge=0.0, le=1.0, description="Lower bound of confidence interval")
    upper: float = Field(ge=0.0, le=1.0, description="Upper bound of confidence interval")
    confidence_level: float = Field(default=0.95, ge=0.5, le=0.999, description="Nominal coverage target (e.g., 0.95)")
    conditional_group: str = Field(
        default="overall", description="Mondrian slice group, e.g. 'tier:HIGH' or 'type:numerical'"
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> "ConformalInterval":
        if self.lower > self.upper:
            raise ValueError(f"Interval lower bound ({self.lower}) cannot exceed upper bound ({self.upper})")
        return self

    @property
    def width(self) -> float:
        """Width of prediction interval; measures predictive sharpness."""
        return round(self.upper - self.lower, 4)


class SignalAttribution(BaseModel):
    """TreeSHAP exact feature attributions decomposed across active signals."""

    rav: float = Field(default=0.0, ge=0.0, le=1.0)
    scs: float = Field(default=0.0, ge=0.0, le=1.0)
    nli: float = Field(default=0.0, ge=0.0, le=1.0)
    ics: float = Field(default=0.0, ge=0.0, le=1.0)
    vgs: float | None = Field(default=None, ge=0.0, le=1.0)


class HRSResult(BaseModel):
    """Aggregate response-level Hallucination Risk Score result."""

    hrs: float = Field(ge=0.0, le=1.0, description="Calibrated hallucination probability (Isotonic Regression)")
    raw_score: float = Field(ge=0.0, le=1.0, description="Uncalibrated raw output from LightGBM meta-learner")
    tier: RiskTier = Field(description="Operational classification tier")
    conformal_interval: ConformalInterval
    signal_attribution: SignalAttribution
    claims_count: int = Field(ge=0)
    contradicted_claims_count: int = Field(ge=0)
    computation_latency_ms: float = Field(ge=0.0)
