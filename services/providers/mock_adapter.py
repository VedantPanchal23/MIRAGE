"""Deterministic mock provider adapter for zero-cost offline testing and security verification."""

import math
import time
from typing import Any

from services.providers.base import (
    BaseProviderAdapter,
    ProviderError,
    ProviderErrorType,
    ProviderResponse,
    UsageInfo,
)


class MockProviderAdapter(BaseProviderAdapter):
    """Offline deterministic mock provider for testing without external API credentials."""

    def __init__(
        self,
        *,
        fixed_latency_ms: float = 15.0,
        fail_with_rate_limit: bool = False,
        fail_with_timeout: bool = False,
        fail_with_upstream_500: bool = False,
    ) -> None:
        self.fixed_latency_ms = fixed_latency_ms
        self.fail_with_rate_limit = fail_with_rate_limit
        self.fail_with_timeout = fail_with_timeout
        self.fail_with_upstream_500 = fail_with_upstream_500

    @property
    def provider_name(self) -> str:
        return "mock"

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
        _ = (temperature, max_tokens, system_prompt)
        start_time = time.perf_counter()

        # Check simulated failure flags
        if self.fail_with_rate_limit or "rate_limit_fail" in model_id:
            raise ProviderError(
                message=f"Rate limit exceeded on mock provider for model {model_id}",
                error_type=ProviderErrorType.RATE_LIMIT_EXCEEDED,
                status_code=429,
                retryable=True,
                details="Rate limit simulation triggered",
            )
        if self.fail_with_timeout or "timeout_fail" in model_id:
            raise ProviderError(
                message=f"Upstream request timed out after {timeout_seconds}s for model {model_id}",
                error_type=ProviderErrorType.TIMEOUT,
                status_code=504,
                retryable=True,
                details="Timeout simulation triggered",
            )
        if self.fail_with_upstream_500 or "upstream_fail" in model_id:
            raise ProviderError(
                message=f"Upstream provider 500 error for model {model_id}",
                error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                status_code=500,
                retryable=True,
                details="500 Internal Server Error",
            )

        # Extract prompt text for length calculation
        if isinstance(prompt, list):
            prompt_str = " ".join(str(m.get("content", "")) for m in prompt)
        else:
            prompt_str = str(prompt)

        # Deterministic token approximation (4 characters per token heuristic)
        prompt_tokens = max(1, math.ceil(len(prompt_str) / 4))
        content = f"[MOCK_RESPONSE: {model_id}] Verified execution for: {prompt_str[:80]}"
        completion_tokens = max(1, math.ceil(len(content) / 4))

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0 + self.fixed_latency_ms

        tool_calls: list[dict[str, Any]] = []
        if tools and "request_tool" in prompt_str.lower():
            tool_calls.append(
                {
                    "id": "mock_call_001",
                    "type": "function",
                    "function": {"name": tools[0].get("function", {}).get("name", "example_tool"), "arguments": "{}"},
                }
            )

        return ProviderResponse(
            content=content,
            usage=UsageInfo(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cached_tokens=0,
            ),
            latency_ms=round(elapsed_ms, 2),
            model_id=model_id,
            provider="mock",
            finish_reason="tool_calls" if tool_calls else "stop",
            tool_calls=tool_calls,
            raw_response={"mock": True, "prompt_preview": prompt_str[:40]},
        )
