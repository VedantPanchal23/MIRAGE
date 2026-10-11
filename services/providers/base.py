"""Base abstraction for LLM Provider Adapters in MIRAGE 3.0."""

import math
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProviderErrorType(StrEnum):
    """Standardized classification of provider errors."""

    AUTHENTICATION = "AUTHENTICATION"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    CONTEXT_LENGTH_EXCEEDED = "CONTEXT_LENGTH_EXCEEDED"
    TIMEOUT = "TIMEOUT"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    INVALID_REQUEST = "INVALID_REQUEST"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


class ProviderError(Exception):
    """Normalized exception raised by any concrete provider adapter."""

    def __init__(
        self,
        message: str,
        error_type: ProviderErrorType,
        status_code: int | None = None,
        retryable: bool = False,
        details: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.status_code = status_code
        self.retryable = retryable
        self.details = details

    def __str__(self) -> str:
        return f"[{self.error_type.value}] {self.message} (status: {self.status_code}, retryable: {self.retryable})"


class UsageInfo(BaseModel):
    """Normalized token consumption reported by a provider."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cached_tokens: int = Field(default=0, ge=0)


class ProviderResponse(BaseModel):
    """Normalized response envelope returned by provider adapters."""

    content: str = Field(..., description="Generated text content")
    usage: UsageInfo = Field(default_factory=UsageInfo)
    latency_ms: float = Field(default=0.0, ge=0.0)
    model_id: str = Field(...)
    provider: str = Field(...)
    finish_reason: str = Field(default="stop")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    raw_response: dict[str, Any] | None = Field(default=None)


class BaseProviderAdapter(ABC):
    """Abstract generic provider interface for model execution."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider, e.g. 'openai', 'anthropic', 'google', 'ollama', 'mock'."""
        pass

    @abstractmethod
    async def generate(
        self,
        prompt: str | list[dict[str, Any]],
        model_id: str,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> ProviderResponse:
        """Execute text or chat generation against the provider endpoint."""
        pass

    def calculate_cost(
        self,
        usage: UsageInfo,
        input_cost_per_million_micros: int,
        output_cost_per_million_micros: int,
        cached_input_cost_per_million_micros: int = 0,
    ) -> int:
        """Calculate durable cost in integer micros ($1 = 1,000,000 micros)."""
        uncached_prompt = max(0, usage.prompt_tokens - usage.cached_tokens)
        cost_float = (
            (uncached_prompt * input_cost_per_million_micros)
            + (usage.cached_tokens * cached_input_cost_per_million_micros)
            + (usage.completion_tokens * output_cost_per_million_micros)
        ) / 1_000_000.0
        return int(math.ceil(cost_float))
