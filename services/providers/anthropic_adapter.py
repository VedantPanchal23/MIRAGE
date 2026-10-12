"""Anthropic Messages API provider adapter."""

import time
from typing import Any

import httpx

from services.providers.base import (
    BaseProviderAdapter,
    ProviderError,
    ProviderErrorType,
    ProviderResponse,
    UsageInfo,
)
from services.providers.ssrf_validator import SSRFValidationError, create_ssrf_safe_client


class AnthropicProviderAdapter(BaseProviderAdapter):
    """Adapter for Anthropic Claude messages API."""

    def __init__(self, api_key: str = "", base_url: str = "https://api.anthropic.com/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "anthropic"

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
        if not self.api_key:
            raise ProviderError(
                message="Anthropic API key is missing or unconfigured",
                error_type=ProviderErrorType.CONFIGURATION_ERROR,
                status_code=401,
                retryable=False,
            )

        messages: list[dict[str, Any]] = []
        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt})
        elif isinstance(prompt, list):
            for m in prompt:
                if m.get("role") != "system":
                    messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
                elif not system_prompt:
                    system_prompt = m.get("content", "")

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens or 1024,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if tools:
            # Map OpenAI tool schema to Anthropic tools schema if needed
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", t)
                anthropic_tools.append(
                    {
                        "name": fn.get("name", "tool"),
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {}),
                    }
                )
            payload["tools"] = anthropic_tools

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        start_time = time.perf_counter()
        try:
            async with create_ssrf_safe_client(allow_local=False, timeout=timeout_seconds) as client:
                resp = await client.post(
                    f"{self.base_url}/messages",
                    headers=headers,
                    json=payload,
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                if 300 <= resp.status_code < 400:
                    raise ProviderError(
                        message=(
                            f"Anthropic endpoint returned redirect status {resp.status_code}; redirects are prohibited"
                        ),
                        error_type=ProviderErrorType.INVALID_REQUEST,
                        status_code=resp.status_code,
                        retryable=False,
                    )
                if resp.status_code in (401, 403):
                    raise ProviderError(
                        message="Invalid Anthropic API key or unauthorized",
                        error_type=ProviderErrorType.AUTHENTICATION,
                        status_code=resp.status_code,
                        retryable=False,
                    )
                if resp.status_code == 429:
                    raise ProviderError(
                        message="Anthropic rate limit exceeded",
                        error_type=ProviderErrorType.RATE_LIMIT_EXCEEDED,
                        status_code=429,
                        retryable=True,
                    )
                if resp.status_code == 400:
                    raise ProviderError(
                        message=f"Anthropic bad request: {resp.text}",
                        error_type=ProviderErrorType.INVALID_REQUEST,
                        status_code=400,
                        retryable=False,
                    )
                if resp.status_code >= 500:
                    raise ProviderError(
                        message=f"Anthropic upstream error (status {resp.status_code}): {resp.text}",
                        error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                        status_code=resp.status_code,
                        retryable=True,
                    )

                resp.raise_for_status()
                data = resp.json()

                content_blocks = data.get("content", [])
                text_parts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
                content = "".join(text_parts)

                tool_calls: list[dict[str, Any]] = []
                for b in content_blocks:
                    if b.get("type") == "tool_use":
                        tool_calls.append(
                            {
                                "id": b.get("id"),
                                "type": "function",
                                "function": {
                                    "name": b.get("name"),
                                    "arguments": b.get("input", {}),
                                },
                            }
                        )

                raw_usage = data.get("usage", {})
                prompt_toks = raw_usage.get("input_tokens", 0)
                comp_toks = raw_usage.get("output_tokens", 0)
                cached_toks = raw_usage.get("cache_read_input_tokens", 0)

                return ProviderResponse(
                    content=content,
                    usage=UsageInfo(
                        prompt_tokens=prompt_toks,
                        completion_tokens=comp_toks,
                        total_tokens=prompt_toks + comp_toks,
                        cached_tokens=cached_toks,
                    ),
                    latency_ms=round(elapsed_ms, 2),
                    model_id=model_id,
                    provider="anthropic",
                    finish_reason=data.get("stop_reason", "end_turn"),
                    tool_calls=tool_calls,
                    raw_response=data,
                )
        except SSRFValidationError as exc:
            raise ProviderError(
                message=f"SSRF violation: outbound connection blocked: {exc}",
                error_type=ProviderErrorType.CONFIGURATION_ERROR,
                status_code=403,
                retryable=False,
                details=str(exc),
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                message=f"Anthropic request timed out after {timeout_seconds}s",
                error_type=ProviderErrorType.TIMEOUT,
                status_code=504,
                retryable=True,
                details=str(exc),
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                message=f"HTTP status error from Anthropic (status {exc.response.status_code}): {exc}",
                error_type=ProviderErrorType.INVALID_REQUEST,
                status_code=exc.response.status_code if exc.response is not None else 500,
                retryable=False,
                details=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                message=f"Network error communicating with Anthropic: {exc}",
                error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                status_code=502,
                retryable=True,
                details=str(exc),
            ) from exc
