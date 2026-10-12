"""OpenAI chat completion provider adapter."""

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


class OpenAIProviderAdapter(BaseProviderAdapter):
    """Adapter for OpenAI and OpenAI-compatible inference endpoints."""

    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "openai"

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
                message="OpenAI API key is missing or unconfigured",
                error_type=ProviderErrorType.CONFIGURATION_ERROR,
                status_code=401,
                retryable=False,
            )

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
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                if resp.status_code == 401:
                    raise ProviderError(
                        message="Invalid OpenAI API key or unauthorized",
                        error_type=ProviderErrorType.AUTHENTICATION,
                        status_code=401,
                        retryable=False,
                    )
                if resp.status_code == 429:
                    raise ProviderError(
                        message="OpenAI rate limit or quota exceeded",
                        error_type=ProviderErrorType.RATE_LIMIT_EXCEEDED,
                        status_code=429,
                        retryable=True,
                    )
                if resp.status_code == 400:
                    err_msg = resp.text
                    err_type = (
                        ProviderErrorType.CONTEXT_LENGTH_EXCEEDED
                        if "maximum context length" in err_msg.lower()
                        else ProviderErrorType.INVALID_REQUEST
                    )
                    raise ProviderError(
                        message=f"OpenAI bad request: {err_msg}",
                        error_type=err_type,
                        status_code=400,
                        retryable=False,
                        details=err_msg,
                    )
                if resp.status_code >= 500:
                    raise ProviderError(
                        message=f"OpenAI upstream error (status {resp.status_code}): {resp.text}",
                        error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                        status_code=resp.status_code,
                        retryable=True,
                    )

                resp.raise_for_status()
                data = resp.json()

                choice = data["choices"][0]
                message = choice.get("message", {})
                content = message.get("content") or ""
                finish_reason = choice.get("finish_reason", "stop")
                tool_calls = message.get("tool_calls") or []

                raw_usage = data.get("usage", {})
                usage = UsageInfo(
                    prompt_tokens=raw_usage.get("prompt_tokens", 0),
                    completion_tokens=raw_usage.get("completion_tokens", 0),
                    total_tokens=raw_usage.get("total_tokens", 0),
                    cached_tokens=raw_usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
                )

                return ProviderResponse(
                    content=content,
                    usage=usage,
                    latency_ms=round(elapsed_ms, 2),
                    model_id=model_id,
                    provider="openai",
                    finish_reason=finish_reason,
                    tool_calls=tool_calls,
                    raw_response=data,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                message=f"OpenAI request timed out after {timeout_seconds}s",
                error_type=ProviderErrorType.TIMEOUT,
                status_code=504,
                retryable=True,
                details=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                message=f"Network error communicating with OpenAI: {exc}",
                error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                status_code=502,
                retryable=True,
                details=str(exc),
            ) from exc
