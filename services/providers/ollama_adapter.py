"""Ollama local inference provider adapter."""

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


class OllamaProviderAdapter(BaseProviderAdapter):
    """Adapter for local Ollama server running air-gapped / on-premise models."""

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        self.base_url = base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "ollama"

    async def generate(
        self,
        prompt: str | list[dict[str, Any]],
        model_id: str,
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        system_prompt: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> ProviderResponse:
        _ = tools
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt})
        elif isinstance(prompt, list):
            messages.extend(prompt)

        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        payload: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "stream": False,
            "options": options,
        }

        start_time = time.perf_counter()
        try:
            async with create_ssrf_safe_client(allow_local=True, timeout=timeout_seconds) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                if 300 <= resp.status_code < 400:
                    raise ProviderError(
                        message=(
                            f"Ollama endpoint returned redirect status {resp.status_code}; redirects are prohibited"
                        ),
                        error_type=ProviderErrorType.INVALID_REQUEST,
                        status_code=resp.status_code,
                        retryable=False,
                    )
                if resp.status_code == 404:
                    raise ProviderError(
                        message=f"Model '{model_id}' not found on local Ollama server",
                        error_type=ProviderErrorType.INVALID_REQUEST,
                        status_code=404,
                        retryable=False,
                    )
                if resp.status_code >= 500:
                    raise ProviderError(
                        message=f"Ollama server error (status {resp.status_code}): {resp.text}",
                        error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                        status_code=resp.status_code,
                        retryable=True,
                    )

                resp.raise_for_status()
                data = resp.json()

                content = data.get("message", {}).get("content", "")
                prompt_toks = data.get("prompt_eval_count", 0)
                comp_toks = data.get("eval_count", 0)

                return ProviderResponse(
                    content=content,
                    usage=UsageInfo(
                        prompt_tokens=prompt_toks,
                        completion_tokens=comp_toks,
                        total_tokens=prompt_toks + comp_toks,
                        cached_tokens=0,
                    ),
                    latency_ms=round(elapsed_ms, 2),
                    model_id=model_id,
                    provider="ollama",
                    finish_reason="stop",
                    tool_calls=[],
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
                message=f"Ollama request timed out after {timeout_seconds}s",
                error_type=ProviderErrorType.TIMEOUT,
                status_code=504,
                retryable=True,
                details=str(exc),
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                message=f"HTTP status error from Ollama (status {exc.response.status_code}): {exc}",
                error_type=ProviderErrorType.INVALID_REQUEST,
                status_code=exc.response.status_code if exc.response is not None else 500,
                retryable=False,
                details=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                message=f"Cannot connect to local Ollama server at {self.base_url}: {exc}",
                error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                status_code=502,
                retryable=True,
                details=str(exc),
            ) from exc
