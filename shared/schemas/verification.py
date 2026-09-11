"""Pydantic schemas for the Verification API requests, responses, and execution metadata."""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from shared.schemas.claims import ClaimVerificationResult
from shared.schemas.hrs import HRSResult


class VerificationRequest(BaseModel):
    """Payload submitted to POST /v1/verify for factual consistency inspection."""

    prompt: str = Field(min_length=1, description="Original user prompt provided to the LLM")
    response: str = Field(min_length=1, description="Generated response to be verified")
    tenant_id: str = Field(default="default_tenant", description="Tenant identifier for multi-tenant isolation")
    knowledge_base_id: str | None = Field(
        default=None,
        description="Target Qdrant collection ID for retrieval-augmented verification",
    )
    image_urls: list[str] = Field(
        default_factory=list,
        description="Optional list of image URLs/paths referenced in multimodal claims",
    )
    model_id: str = Field(default="llama-3.1-70b-versatile", description="Generator model identifier")
    auto_correct: bool = Field(
        default=True,
        description="Whether to run the LangGraph agentic correction loop if HRS exceeds threshold",
    )


class VerificationMetadata(BaseModel):
    """Telemetry and execution metrics associated with a verification pass."""

    trace_id: str
    execution_time_ms: float = Field(ge=0.0)
    pipeline_signals_used: list[str]
    cached_scs_hit: bool = False
    correction_applied: bool = False
    correction_iterations: int = Field(default=0, ge=0)
    circuit_breakers_tripped: list[str] = Field(default_factory=list)


class VerificationResponse(BaseModel):
    """Comprehensive response returned by the verification pipeline."""

    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")
    verified_response: str = Field(description="Final output (rewritten if corrected, otherwise original)")
    original_response: str = Field(description="Original unverified text")
    hrs_result: HRSResult
    claims: list[ClaimVerificationResult] = Field(default_factory=list)
    metadata: VerificationMetadata


class VerificationStreamEvent(BaseModel):
    """Incremental verification event published over the WebSocket endpoint."""

    event_type: str = Field(description="'claim_extracted' | 'signal_completed' | 'hrs_computed' | 'correction_step'")
    payload: dict[str, Any]
    trace_id: str
