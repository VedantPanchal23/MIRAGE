"""Google Gemini API provider adapter."""

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


class GeminiProviderAdapter(BaseProviderAdapter):
    """Adapter for Google Gemini generateContent REST API."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    @property
    def provider_name(self) -> str:
        return "google"

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
        _ = tools
        if not self.api_key:
            raise ProviderError(
                message="Google Gemini API key is missing or unconfigured",
                error_type=ProviderErrorType.CONFIGURATION_ERROR,
                status_code=401,
                retryable=False,
            )

        # Normalize contents
        contents: list[dict[str, Any]] = []
        if isinstance(prompt, str):
            contents.append({"role": "user", "parts": [{"text": prompt}]})
        elif isinstance(prompt, list):
            for m in prompt:
                role = "model" if m.get("role") in ("assistant", "model") else "user"
                if m.get("role") == "system" and not system_prompt:
                    system_prompt = m.get("content", "")
                    continue
                contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        clean_model_id = model_id if model_id.startswith("models/") else f"models/{model_id}"
        url = f"{self.base_url}/{clean_model_id}:generateContent?key={self.api_key}"

        start_time = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                resp = await client.post(url, json=payload)
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0

                if resp.status_code in (401, 403):
                    raise ProviderError(
                        message="Invalid Google Gemini API key or unauthorized",
                        error_type=ProviderErrorType.AUTHENTICATION,
                        status_code=resp.status_code,
                        retryable=False,
                    )
                if resp.status_code == 429:
                    raise ProviderError(
                        message="Google Gemini quota or rate limit exceeded",
                        error_type=ProviderErrorType.RATE_LIMIT_EXCEEDED,
                        status_code=429,
                        retryable=True,
                    )
                if resp.status_code == 400:
                    raise ProviderError(
                        message=f"Google Gemini bad request: {resp.text}",
                        error_type=ProviderErrorType.INVALID_REQUEST,
                        status_code=400,
                        retryable=False,
                    )
                if resp.status_code >= 500:
                    raise ProviderError(
                        message=f"Google Gemini upstream error (status {resp.status_code}): {resp.text}",
                        error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                        status_code=resp.status_code,
                        retryable=True,
                    )

                resp.raise_for_status()
                data = resp.json()

                candidates = data.get("candidates", [])
                content_text = ""
                finish_reason = "stop"
                if candidates:
                    first_candidate = candidates[0]
                    parts = first_candidate.get("content", {}).get("parts", [])
                    content_text = "".join(p.get("text", "") for p in parts)
                    finish_reason = first_candidate.get("finishReason", "STOP").lower()

                usage_meta = data.get("usageMetadata", {})
                prompt_toks = usage_meta.get("promptTokenCount", 0)
                comp_toks = usage_meta.get("candidatesTokenCount", 0)
                cached_toks = usage_meta.get("cachedContentTokenCount", 0)

                return ProviderResponse(
                    content=content_text,
                    usage=UsageInfo(
                        prompt_tokens=prompt_toks,
                        completion_tokens=comp_toks,
                        total_tokens=prompt_toks + comp_toks,
                        cached_tokens=cached_toks,
                    ),
                    latency_ms=round(elapsed_ms, 2),
                    model_id=model_id,
                    provider="google",
                    finish_reason=finish_reason,
                    tool_calls=[],
                    raw_response=data,
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                message=f"Google Gemini request timed out after {timeout_seconds}s",
                error_type=ProviderErrorType.TIMEOUT,
                status_code=504,
                retryable=True,
                details=str(exc),
            ) from exc
        except httpx.RequestError as exc:
            raise ProviderError(
                message=f"Network error communicating with Google Gemini: {exc}",
                error_type=ProviderErrorType.UPSTREAM_UNAVAILABLE,
                status_code=502,
                retryable=True,
                details=str(exc),
            ) from exc
