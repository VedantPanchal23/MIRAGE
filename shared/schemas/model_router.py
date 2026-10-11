"""Typed contracts for MIRAGE 3.0 Model Routing and Capability Profiles."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ModelTier(StrEnum):
    """Model tier classification reflecting reasoning capability, latency, and cost."""

    FRONTIER = "FRONTIER"
    CAPABLE = "CAPABLE"
    SPECIALIZED = "SPECIALIZED"


class ModelFamily(StrEnum):
    """Known model provider family identifiers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OLLAMA = "ollama"
    MOCK = "mock"


class ModelCapabilityProfile(BaseModel):
    """Authoritative capability profile for an LLM registered in MIRAGE."""

    model_id: str = Field(..., description="Unique model identifier, e.g. 'gpt-4o' or 'claude-3-5-sonnet'")
    provider: str = Field(..., description="Provider adapter key: openai, anthropic, google, ollama, mock")
    family: str = Field(default="general", description="Model family or organization")
    tier: ModelTier = Field(default=ModelTier.CAPABLE, description="Model tier: FRONTIER, CAPABLE, or SPECIALIZED")
    context_window: int = Field(default=128000, description="Max context tokens supported")
    supports_tools: bool = Field(default=True, description="Whether model supports function / tool calling")
    supports_vision: bool = Field(default=False, description="Whether model supports image / multimodal inputs")
    supports_structured_output: bool = Field(default=True, description="Whether model enforces JSON schema")
    supports_system_prompt: bool = Field(
        default=True, description="Whether model supports distinct system instructions"
    )
    is_zero_retention: bool = Field(
        default=False, description="Whether endpoint guarantees zero data retention (HIPAA/BAA)"
    )
    reliability_index: float = Field(
        default=0.85, ge=0.0, le=1.0, description="Historical accuracy and calibration score"
    )
    expected_latency_ms: float = Field(default=800.0, description="Median expected time-to-first-token in ms")
    input_cost_per_million_micros: int = Field(
        default=2500000, ge=0, description="Input cost per 1M tokens in micros ($2.50 = 2,500,000 micros)"
    )
    output_cost_per_million_micros: int = Field(
        default=10000000, ge=0, description="Output cost per 1M tokens in micros ($10.00 = 10,000,000 micros)"
    )
    cached_input_cost_per_million_micros: int = Field(
        default=1250000, ge=0, description="Cached prompt input cost per 1M tokens in micros"
    )
    active: bool = Field(default=True, description="Whether model is currently operational")


class PricingProfile(BaseModel):
    """Versioned pricing profile for a registered model."""

    id: str = Field(..., description="Pricing profile identifier")
    model_id: str = Field(..., description="Target model ID")
    effective_date: str = Field(default="2026-01-01", description="Effective ISO date")
    currency: str = Field(default="USD", description="Billing currency")
    input_cost_per_million_micros: int = Field(..., ge=0, description="Micros per 1,000,000 input tokens")
    output_cost_per_million_micros: int = Field(..., ge=0, description="Micros per 1,000,000 output tokens")
    cached_input_cost_per_million_micros: int = Field(
        default=0, ge=0, description="Micros per 1,000,000 cached input tokens"
    )
    is_active: bool = Field(default=True, description="Whether this pricing version is active")


class CandidateExclusion(BaseModel):
    """Explainable rejection reason for a model candidate during routing."""

    model_id: str = Field(..., description="Candidate model evaluated")
    rule: str = Field(..., description="Constraint rule that caused rejection")
    reason: str = Field(..., description="Human-readable explanation of rejection")


class RoutingRequest(BaseModel):
    """Incoming request to evaluate and select the optimal model under assurance constraints."""

    tenant_id: str = Field(..., description="Authoritative tenant ID")
    transaction_id: str | None = Field(default=None, description="Optional AI Transaction ID")
    task_type: str = Field(
        default="general",
        description="Task classification: chat, reasoning, extraction, coding, classification, general",
    )
    estimated_input_tokens: int = Field(default=100, ge=1, description="Estimated input prompt token length")
    estimated_output_tokens: int = Field(default=250, ge=1, description="Estimated completion token length")
    max_cost_micros: int | None = Field(default=None, description="Maximum allowed cost in micros for this call")
    max_latency_ms: float | None = Field(default=None, description="Maximum tolerated latency in milliseconds")
    required_capabilities: list[str] = Field(
        default_factory=list, description="Mandatory capabilities: tools, vision, structured_output"
    )
    taints: list[str] = Field(default_factory=list, description="Gate 1 data taints: pii, phi, confidential, secret")
    risk_level: int = Field(default=0, ge=0, le=5, description="Autonomy risk level (0=L0 read-only, 4=L4 high-impact)")
    preferred_model: str | None = Field(default=None, description="Caller's preferred model if allowed by policy")
    allow_fallbacks: bool = Field(default=True, description="Whether router should provide a fallback ladder")
    geofence: str | None = Field(default=None, description="Data residency constraint, e.g. 'EU', 'US'")


class RoutingDecision(BaseModel):
    """Authoritative, reproducible outcome of Model Router evaluation."""

    decision_id: str = Field(..., description="Unique routing decision ID")
    tenant_id: str = Field(..., description="Tenant identifier")
    selected_model_id: str = Field(..., description="Chosen model ID")
    provider: str = Field(..., description="Adapter provider name")
    tier: ModelTier = Field(..., description="Selected model tier")
    score: float = Field(..., description="Composite optimization score")
    estimated_cost_micros: int = Field(..., description="Estimated cost for prompt + expected completion")
    estimated_latency_ms: float = Field(..., description="Estimated median latency")
    fallback_ladder: list[str] = Field(default_factory=list, description="Ordered viable fallback models")
    exclusions: list[CandidateExclusion] = Field(
        default_factory=list, description="Explainable audit of rejected models"
    )
    decision_hash: str = Field(..., description="Cryptographic SHA-256 hash of routing decision inputs and output")
    reason: str = Field(..., description="Explanation of why this model was chosen")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
