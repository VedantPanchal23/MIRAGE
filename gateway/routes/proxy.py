"""OpenAI-compatible drop-in reverse proxy (POST /v1/chat/completions) with multi-gate assurance."""

import re
import time
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pybreaker import CircuitBreakerError

from gateway.middleware.auth import get_current_tenant
from gateway.middleware.circuit_breaker import llm_circuit
from gateway.middleware.rate_limiter import rate_limiter
from services.budget_manager import budget_manager_service
from services.circuit_breaker import circuit_breaker_service
from services.model_router import model_router_service
from services.output_assurance import output_assurance_service
from services.pricing_service import pricing_service
from services.providers.base import ProviderError
from services.providers.factory import ProviderConfigurationError, get_provider_adapter
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas import (
    BudgetReservationRequest,
    BudgetSettlementRequest,
    RoutingRequest,
    VerificationRequest,
)
from workers.orchestrator import VerificationOrchestrator

router = APIRouter(prefix="/v1", tags=["OpenAI Proxy"])
logger = get_logger("proxy_route")
settings = get_settings()
orchestrator = VerificationOrchestrator()

_PII_OR_SECRET_PATTERN = re.compile(
    r"\b(?:\d{3}-\d{2}-\d{4}|\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}|api[_-]?key|password|secret)\b",
    re.IGNORECASE,
)


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

    # 1. Gate 1 Taint Detection: Headers, Payload, and Automatic Content Inspection
    header_taints = [t.strip().lower() for t in request.headers.get("X-Mirage-Taints", "").split(",") if t.strip()]
    payload_taints = [t.strip().lower() for t in (payload.get("taints") or []) if isinstance(t, str) and t.strip()]
    auto_taints = []
    if _PII_OR_SECRET_PATTERN.search(str(last_user_msg)):
        auto_taints.append("pii")

    combined_taints = sorted(set(header_taints + payload_taints + auto_taints))

    routing_req = RoutingRequest(
        tenant_id=tenant_id,
        transaction_id=trace_id,
        task_type="chat",
        estimated_input_tokens=max(1, len(str(last_user_msg)) // 4),
        estimated_output_tokens=max(1, payload.get("max_tokens") or 100),
        preferred_model=model_name,
        taints=combined_taints,
        risk_level=payload.get("risk_level", 0),
        allow_fallbacks=True,
    )

    # 2. Strict Fail-Closed Model Routing
    try:
        routing_decision = await model_router_service.route(routing_req)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Model routing infrastructure failure", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Model routing infrastructure failure: {exc}",
        ) from exc

    routed_model = routing_decision.selected_model_id
    routed_provider = routing_decision.provider
    decision_hash = routing_decision.decision_hash
    estimated_micros = routing_decision.estimated_cost_micros
    pricing_profile_id = routing_decision.pricing_profile_id

    # 3. Mandatory Preflight Budget Reservation
    reservation_amount = estimated_micros
    if reservation_amount <= 0 and routing_decision.fallback_ladder:
        for fb_id in routing_decision.fallback_ladder:
            try:
                fb_pricing = await pricing_service.get_active_pricing_profile(fb_id)
                fb_cost = pricing_service.calculate_cost_micros(
                    fb_pricing,
                    prompt_tokens=routing_req.estimated_input_tokens,
                    completion_tokens=routing_req.estimated_output_tokens,
                )
                if fb_cost > 0:
                    reservation_amount = fb_cost
                    break
            except Exception:
                continue

    try:
        res_req = BudgetReservationRequest(
            tenant_id=tenant_id,
            transaction_id=trace_id,
            estimated_cost_micros=max(1, reservation_amount),
            reservation_key=f"res_{trace_id}",
            attempt_number=1,
            selected_provider=routed_provider,
            selected_model=routed_model,
            timeout_seconds=300,
        )
        reservation = await budget_manager_service.reserve_budget(res_req)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Preflight budget reservation failed; denying provider execution", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Preflight budget reservation failed: {exc}",
        ) from exc

    # 4. Authoritative Provider Execution with Independently Governed Fallback Ladder
    start_time = time.time()
    completion_text = ""
    usage_info = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cached_tokens": 0}
    actual_cost_micros = 0

    candidates_to_try = [(routed_model, routed_provider, pricing_profile_id, 1)]
    for idx, fb_model in enumerate(routing_decision.fallback_ladder, start=2):
        candidates_to_try.append((fb_model, None, None, idx))

    execution_successful = False
    last_exec_error: Exception | None = None
    executed_model = routed_model
    executed_provider = routed_provider
    executed_pricing_id = pricing_profile_id
    executed_attempt = 1

    for cand_model, cand_prov, cand_price_id, attempt_num in candidates_to_try:
        if attempt_num > 1:
            # Check tenant budget available headroom for potential expansion
            tenant_budget = await budget_manager_service.get_tenant_budget(tenant_id)
            effective_headroom = tenant_budget.available_micros + reservation.amount_micros
            if routing_req.max_cost_micros is not None:
                effective_headroom = min(effective_headroom, routing_req.max_cost_micros)

            # Independently revalidate fallback candidate against all assurance constraints and budget
            is_valid, reason, profile, est_fb_cost, fb_price_id = (
                await model_router_service.revalidate_fallback_candidate(
                    candidate_model_id=cand_model,
                    request=routing_req,
                    remaining_budget_micros=effective_headroom,
                )
            )
            if not is_valid or profile is None:
                logger.warning("Fallback candidate disqualified", model=cand_model, reason=reason)
                continue

            # If fallback costs more than initially reserved, expand reservation under lock
            if est_fb_cost > reservation.amount_micros:
                delta = est_fb_cost - reservation.amount_micros
                try:
                    reservation = await budget_manager_service.expand_reservation(
                        tenant_id=tenant_id,
                        reservation_id=reservation.id,
                        additional_micros=delta,
                        new_provider=profile.provider,
                        new_model=profile.model_id,
                        attempt_number=attempt_num,
                    )
                except HTTPException:
                    logger.warning(
                        "Budget limit prevented expanding reservation for fallback",
                        model=cand_model,
                        delta=delta,
                    )
                    continue

            cand_prov = profile.provider
            cand_price_id = fb_price_id

        assert cand_prov is not None
        assert cand_price_id is not None

        try:
            adapter = get_provider_adapter(cand_prov)
            async def _execute_provider(
                _adapter: Any = adapter,
                _model: str = cand_model,
            ) -> Any:
                return await _adapter.generate(
                    prompt=messages,
                    model_id=_model,
                    temperature=payload.get("temperature", 0.7),
                    max_tokens=payload.get("max_tokens"),
                )

            prov_resp = await llm_circuit.call(_execute_provider)
            completion_text = prov_resp.content
            usage_info = {
                "prompt_tokens": prov_resp.usage.prompt_tokens,
                "completion_tokens": prov_resp.usage.completion_tokens,
                "total_tokens": prov_resp.usage.total_tokens,
                "cached_tokens": prov_resp.usage.cached_tokens,
            }
            executed_model = cand_model
            executed_provider = cand_prov
            executed_pricing_id = cand_price_id
            executed_attempt = attempt_num
            execution_successful = True
            await circuit_breaker_service.record_success(cand_prov, cand_model)
            break
        except (ProviderError, ProviderConfigurationError, CircuitBreakerError, Exception) as p_exc:
            await circuit_breaker_service.record_failure(cand_prov, cand_model)
            last_exec_error = p_exc
            logger.warning(
                "Execution attempt failed, checking fallback ladder",
                attempt=attempt_num,
                model=cand_model,
                provider=cand_prov,
                error=str(p_exc),
            )

    if not execution_successful:
        # Release reservation and fail closed: NEVER manufacture synthetic responses on execution failure
        await budget_manager_service.release_reservation(tenant_id, reservation.id)
        if isinstance(last_exec_error, CircuitBreakerError):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Downstream LLM circuit tripped: {last_exec_error}",
            )
        if isinstance(last_exec_error, ProviderConfigurationError):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Provider configuration error: {last_exec_error}",
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Downstream LLM provider execution failed: {last_exec_error}",
        )

    # 5. Authoritative Post-Inference Settlement
    prompt_toks = usage_info["prompt_tokens"]
    comp_toks = usage_info["completion_tokens"]
    cached_toks = usage_info.get("cached_tokens", 0)

    actual_cost_micros = await budget_manager_service.calculate_cost_for_model(
        model_id=executed_model,
        prompt_tokens=prompt_toks,
        completion_tokens=comp_toks,
        cached_tokens=cached_toks,
    )

    try:
        await budget_manager_service.settle_budget(
            tenant_id=tenant_id,
            request=BudgetSettlementRequest(
                reservation_id=reservation.id,
                actual_cost_micros=actual_cost_micros,
                model_id=executed_model,
                provider=executed_provider,
                prompt_tokens=prompt_toks,
                completion_tokens=comp_toks,
                cached_tokens=cached_toks,
                attempt_number=executed_attempt,
                pricing_profile_id=executed_pricing_id,
            ),
        )
    except HTTPException:
        raise
    except Exception as s_exc:
        logger.critical("Post-inference financial settlement failure", error=str(s_exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Financial settlement failure: {s_exc}",
        ) from s_exc

    # 6. Gate 4 Multi-Signal Output Assurance
    v_req = VerificationRequest(
        prompt=last_user_msg,
        response=completion_text,
        tenant_id=tenant_id,
        model_id=executed_model,
    )
    v_res = await orchestrator.verify_request(v_req)

    actual_hrs = v_res.hrs_result.hrs
    tier_str = v_res.hrs_result.tier.value
    final_text = v_res.verified_response

    # Gate 4 Tier 1 DLP & Safety Inspection
    safety_res = output_assurance_service.run_dlp_and_safety(final_text)
    if safety_res.redacted_content is not None:
        final_text = safety_res.redacted_content
    if safety_res.prompt_injection_leakage:
        final_text = (
            "[RESPONSE BLOCKED BY MIRAGE GATE 4: "
            "Prompt injection/jailbreak control tokens detected in generated response]"
        )

    # Honest verification status calculation
    is_verified = (
        actual_hrs < 0.20
        and v_res.hrs_result.contradicted_claims_count == 0
        and safety_res.safe
        and v_res.hrs_result.claims_count > 0
        and v_res.hrs_result.conformal_interval.upper < 0.85
    )
    verification_status = (
        "VERIFIED"
        if is_verified
        else "CONTRADICTED"
        if v_res.hrs_result.contradicted_claims_count > 0
        else "BLOCKED"
        if not safety_res.safe
        else "PARTIALLY_VERIFIED"
        if (actual_hrs < 0.50 and safety_res.safe)
        else "UNVERIFIED"
    )

    # Attach verification metadata headers
    response.headers["X-Mirage-HRS"] = str(actual_hrs)
    response.headers["X-Mirage-Tier"] = tier_str
    response.headers["X-Mirage-Verified"] = "true" if is_verified else "false"
    response.headers["X-Mirage-Verification-Status"] = verification_status
    response.headers["X-Mirage-Safety-Safe"] = "true" if safety_res.safe else "false"
    response.headers["X-Mirage-Model-Routed"] = executed_model
    response.headers["X-Mirage-Cost-Micros"] = str(actual_cost_micros)
    response.headers["X-Mirage-Decision-Hash"] = decision_hash
    response.headers["X-Trace-ID"] = trace_id

    elapsed_ms = round((time.time() - start_time) * 1000, 2)
    logger.info(
        "Proxy request completed",
        latency_ms=elapsed_ms,
        hrs=actual_hrs,
        tier=tier_str,
        verified=is_verified,
        safe=safety_res.safe,
        cost_micros=actual_cost_micros,
        model=executed_model,
        attempts=executed_attempt,
    )

    # 7. Format strictly compliant OpenAI Chat Completion response
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": executed_model,
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
            "model_routed": executed_model,
            "cost_micros": actual_cost_micros,
            "decision_hash": decision_hash,
            "conformal_interval": {
                "lower": v_res.hrs_result.conformal_interval.lower,
                "upper": v_res.hrs_result.conformal_interval.upper,
            },
        },
    }
