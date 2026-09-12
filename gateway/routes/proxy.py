"""OpenAI-compatible drop-in reverse proxy (POST /v1/chat/completions) with live factual verification."""

import time
import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from gateway.middleware.auth import get_current_tenant
from gateway.middleware.circuit_breaker import llm_circuit
from gateway.middleware.rate_limiter import rate_limiter
from shared.config import get_settings
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
    rate_limiter.check_rate_limit(tenant_id)
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

    # Attach verification metadata headers
    response.headers["X-Mirage-HRS"] = str(actual_hrs)
    response.headers["X-Mirage-Tier"] = tier_str
    response.headers["X-Trace-ID"] = trace_id

    elapsed_ms = round((time.time() - start_time) * 1000, 2)
    logger.info("Proxy request completed", latency_ms=elapsed_ms, hrs=actual_hrs, tier=tier_str)

    # 3. Format strictly compliant OpenAI Chat Completion response
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
            "verified": True,
            "claims_count": v_res.hrs_result.claims_count,
            "contradicted_count": v_res.hrs_result.contradicted_claims_count,
            "correction_applied": v_res.metadata.correction_applied,
            "conformal_interval": {
                "lower": v_res.hrs_result.conformal_interval.lower,
                "upper": v_res.hrs_result.conformal_interval.upper,
            },
        },
    }
