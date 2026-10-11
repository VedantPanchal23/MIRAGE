"""Groq LLM Provider Adapter for MIRAGE 3.0."""

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
from shared.config import get_settings


class GroqProviderAdapter(BaseProviderAdapter):
    """Adapter for Groq Cloud high-speed inference endpoints."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.groq.com/openai/v1",
    ) -> None:
        if not api_key:
            raise ValueError("GroqProviderAdapter requires a non-empty API key")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.settings = get_settings()

    @property
    def provider_name(self) -> str:
        return "groq"

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
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt})
        elif isinstance(prompt, list):
            messages.extend(prompt)

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                if resp.status_code == 401:
                    raise ProviderError(
                        message="Groq authentication failed: invalid API key",
                        error_type=ProviderErrorType.AUTHENTICATION,
                        status_code=401,
                        retryable=False,
                    )
                if resp.status_code == 429:
                    raise ProviderError(
                        message="Groq rate limit exceeded",
                        error_type=ProviderErrorType.RATE_LIMIT_EXCEEDED,
                        status_code=429,
                        retryable=True,
                    )
                if resp.status_code == 404:
                    # Model not found on Groq
                    raise ProviderError(
                        message=f"Model '{model_id}' not found on Groq endpoint",
                        error_type=ProviderErrorType.INVALID_REQUEST,
                        status_code=404,
                        retryable=False,
                    )
                if resp.status_code >= 500:
                    raise ProviderError(
                        message=f"Groq server error (HTTP {resp.status_code}): {resp.text[:200]}",
                        error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                        status_code=resp.status_code,
                        retryable=True,
                    )

                resp.raise_for_status()
                data = resp.json()

                choice = data["choices"][0]
                message = choice["message"]
                content = message.get("content") or ""
                finish_reason = choice.get("finish_reason", "stop")
                tool_calls = message.get("tool_calls", [])

                raw_usage = data.get("usage", {})
                prompt_toks = raw_usage.get("prompt_tokens", 0)
                comp_toks = raw_usage.get("completion_tokens", 0)
                tot_toks = raw_usage.get("total_tokens", prompt_toks + comp_toks)

                return ProviderResponse(
                    content=content,
                    usage=UsageInfo(
                        prompt_tokens=prompt_toks,
                        completion_tokens=comp_toks,
                        total_tokens=tot_toks,
                        cached_tokens=0,
                    ),
                    latency_ms=round(elapsed_ms, 2),
                    model_id=model_id,
                    provider="groq",
                    finish_reason=finish_reason,
                    tool_calls=tool_calls,
                    raw_response=data,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                message=f"Groq request timed out after {timeout_seconds}s",
                error_type=ProviderErrorType.TIMEOUT,
                status_code=504,
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                message=f"Groq network transport error: {exc}",
                error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                status_code=503,
                retryable=True,
            ) from exc
