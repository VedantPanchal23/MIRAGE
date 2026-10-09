"""OpenAI-compatible drop-in reverse proxy (POST /v1/chat/completions) with live factual verification."""

import time
import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from pybreaker import CircuitBreakerError

from gateway.middleware.auth import get_current_tenant
from gateway.middleware.circuit_breaker import llm_circuit
from gateway.middleware.rate_limiter import rate_limiter
from services.output_assurance import output_assurance_service
from shared.config import get_settings
from shared.config.settings import EnvironmentType
from shared.logging import get_logger
from shared.schemas import VerificationRequest
from workers.orchestrator import VerificationOrchestrator

router = APIRouter(prefix="/v1", tags=["OpenAI Proxy"])
logger = get_logger("proxy_route")
settings = get_settings()
orchestrator = VerificationOrchestrator()


@router.post("/chat/completions")
async def chat_completions_proxy(
    request: Request,
    response: Response,
    payload: dict[str, Any],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> dict[str, Any]:
    """Proxy OpenAI chat completion requests, verifying factual consistency before return."""
    rl_res = await rate_limiter.check_rate_limit(tenant_id)
    response.headers["X-RateLimit-Limit"] = str(rl_res.limit)
    response.headers["X-RateLimit-Remaining"] = str(rl_res.remaining)
    response.headers["X-RateLimit-Reset"] = str(rl_res.reset_time)
    trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex)

    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload must contain a non-empty 'messages' list.",
        )

    last_user_msg = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    model_name = payload.get("model", settings.default_primary_model)

    # 1. Forward to LLM under circuit breaker protection
    start_time = time.time()
    completion_text = ""
    usage_info = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

    if settings.groq_api_key and settings.groq_api_key != "your_groq_api_key_here":
        try:

            async def _call_groq() -> dict[str, Any]:
                req_payload = dict(payload)
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        json=req_payload,
                    )
                    # If requested model is invalid/not found on provider, fall back to default primary model
                    if resp.status_code in (400, 404) and req_payload.get("model") != settings.default_primary_model:
                        logger.warning(
                            "Model not found on Groq, falling back to default primary model",
                            requested_model=req_payload.get("model"),
                            fallback_model=settings.default_primary_model,
                        )
                        req_payload["model"] = settings.default_primary_model
                        resp = await client.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                            json=req_payload,
                        )
                    resp.raise_for_status()
                    data = resp.json()
                    assert isinstance(data, dict)
                    return data

            groq_resp = await llm_circuit.call(_call_groq)
            completion_text = groq_resp["choices"][0]["message"]["content"]
            usage_info = groq_resp.get("usage", usage_info)
        except Exception as exc:
            logger.error("LLM upstream error", error=str(exc))
            if isinstance(exc, CircuitBreakerError):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Downstream LLM provider error: {exc}",
                ) from exc
            if settings.environment in {EnvironmentType.TEST, EnvironmentType.DEVELOPMENT}:
                completion_text = f"Verified response generated for prompt: '{last_user_msg}'."
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Downstream LLM provider error: {exc}",
                ) from exc
    else:
        # Development / mock response when no API key is provided
        completion_text = f"Verified response generated for prompt: '{last_user_msg}'."

    # 2. Run multi-signal verification through orchestrator
    v_req = VerificationRequest(
        prompt=last_user_msg,
        response=completion_text,
        tenant_id=tenant_id,
        model_id=model_name,
    )
    v_res = await orchestrator.verify_request(v_req)

    actual_hrs = v_res.hrs_result.hrs
    tier_str = v_res.hrs_result.tier.value
    final_text = v_res.verified_response

    # 3. Gate 4 Tier 1 DLP & Safety Inspection
    safety_res = output_assurance_service.run_dlp_and_safety(final_text)
    if safety_res.redacted_content is not None:
        final_text = safety_res.redacted_content
    if safety_res.prompt_injection_leakage:
        final_text = (
            "[RESPONSE BLOCKED BY MIRAGE GATE 4: "
            "Prompt injection/jailbreak control tokens detected in generated response]"
        )

    # Honest verification status calculation (never claim verified when contradicted, ungrounded, or unsafe)
    is_verified = (
        actual_hrs < 0.20
        and v_res.hrs_result.contradicted_claims_count == 0
        and safety_res.safe
        and v_res.hrs_result.claims_count > 0
        and v_res.hrs_result.conformal_interval.upper < 0.85
    )
    verification_status = (
        "VERIFIED" if is_verified
        else "CONTRADICTED" if v_res.hrs_result.contradicted_claims_count > 0
        else "BLOCKED" if not safety_res.safe
        else "PARTIALLY_VERIFIED" if (actual_hrs < 0.50 and safety_res.safe)
        else "UNVERIFIED"
    )

    # Attach verification metadata headers
    response.headers["X-Mirage-HRS"] = str(actual_hrs)
    response.headers["X-Mirage-Tier"] = tier_str
    response.headers["X-Mirage-Verified"] = "true" if is_verified else "false"
    response.headers["X-Mirage-Verification-Status"] = verification_status
    response.headers["X-Mirage-Safety-Safe"] = "true" if safety_res.safe else "false"
    response.headers["X-Trace-ID"] = trace_id

    elapsed_ms = round((time.time() - start_time) * 1000, 2)
    logger.info(
        "Proxy request completed",
        latency_ms=elapsed_ms,
        hrs=actual_hrs,
        tier=tier_str,
        verified=is_verified,
        safe=safety_res.safe,
    )

    # 4. Format strictly compliant OpenAI Chat Completion response
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": final_text,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": usage_info,
        "mirage": {
            "hrs": actual_hrs,
            "tier": tier_str,
            "trace_id": trace_id,
            "verified": is_verified,
            "safety_safe": safety_res.safe,
            "secrets_detected": safety_res.secrets_detected,
            "pii_detected": safety_res.pii_detected,
            "prompt_injection_leakage": safety_res.prompt_injection_leakage,
            "safety": safety_res.model_dump(),
            "claims_count": v_res.hrs_result.claims_count,
            "contradicted_count": v_res.hrs_result.contradicted_claims_count,
            "correction_applied": v_res.metadata.correction_applied,
            "conformal_interval": {
                "lower": v_res.hrs_result.conformal_interval.lower,
                "upper": v_res.hrs_result.conformal_interval.upper,
            },
        },
    }
