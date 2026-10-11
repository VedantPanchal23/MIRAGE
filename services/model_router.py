"""Authoritative Intelligent Model Router service for MIRAGE 3.0 Execution Plane.

Enforces multi-gate assurance evaluation:
- Gate 1: Deployment-aware privacy, zero-data-retention, and VPC isolation constraints
- Gate 3: Autonomy and risk-tier validation (L3+ requiring FRONTIER tier and reliability >= 0.85)
- Distributed Circuit Breakers with single-canary probe recovery leases
- Authoritative Pricing Service integration (fail-closed on missing profiles, zero hardcoded fallback rates)
- Cryptographic SHA-256 Decision Provenance Hashing
- Independent Revalidation for Fallback Candidates
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select

from db import session as db_session
from db.models import ModelRegistryRecord
from services.circuit_breaker import circuit_breaker_service
from services.pricing_service import (
    PricingProfileNotFoundError,
    pricing_service,
)
from shared.config import get_settings
from shared.config.settings import EnvironmentType
from shared.logging import get_logger
from shared.schemas.model_router import (
    CandidateExclusion,
    ModelCapabilityProfile,
    ModelTier,
    RoutingDecision,
    RoutingRequest,
)

logger = get_logger("model_router")

SENSITIVE_TAINTS = {"phi", "pii", "confidential", "secret", "financial"}


class ModelRouterService:
    """Intelligent Model Router evaluating assurance, privacy, risk, cost, and latency constraints."""

    def record_failure(self, model_id: str, provider: str | None = None) -> None:
        """Record upstream error and trip circuit breaker."""
        prov = provider or ("mock" if "mock" in model_id else "openai")
        key = circuit_breaker_service._breaker_key(prov, model_id)
        with circuit_breaker_service._lock:
            count = circuit_breaker_service._local_failures.get(key, 0) + 1
            circuit_breaker_service._local_failures[key] = count
            if count >= circuit_breaker_service.failure_threshold:
                circuit_breaker_service._local_opened_at[key] = datetime.now(UTC).timestamp()

    def record_success(self, model_id: str, provider: str | None = None) -> None:
        """Record upstream success and reset circuit breaker."""
        prov = provider or ("mock" if "mock" in model_id else "openai")
        key = circuit_breaker_service._breaker_key(prov, model_id)
        with circuit_breaker_service._lock:
            circuit_breaker_service._local_failures.pop(key, None)
            circuit_breaker_service._local_opened_at.pop(key, None)
            circuit_breaker_service._local_probe_leased_until.pop(key, None)

    def is_circuit_open(self, model_id: str, provider: str | None = None) -> bool:
        """Check whether the circuit breaker for a model is currently tripped."""
        prov = provider or ("mock" if "mock" in model_id else "openai")
        key = circuit_breaker_service._breaker_key(prov, model_id)
        with circuit_breaker_service._lock:
            opened_at = circuit_breaker_service._local_opened_at.get(key)
            if opened_at is None:
                return False
            elapsed = datetime.now(UTC).timestamp() - opened_at
            if elapsed > circuit_breaker_service.recovery_timeout_seconds:
                return False
            return True

    async def list_models(self) -> list[ModelCapabilityProfile]:
        """List all active registered models with their deployment-aware capability profiles."""
        async with db_session.get_system_session() as session:
            stmt = select(ModelRegistryRecord).where(ModelRegistryRecord.active.is_(True))
            records = (await session.execute(stmt)).scalars().all()

            profiles = []
            for r in records:
                try:
                    price_rec = await pricing_service.get_active_pricing_profile(r.id, session=session)
                    in_cost = price_rec.input_cost_per_million_micros
                    out_cost = price_rec.output_cost_per_million_micros
                    cache_cost = price_rec.cached_input_cost_per_million_micros
                except PricingProfileNotFoundError:
                    in_cost = 0
                    out_cost = 0
                    cache_cost = 0

                profiles.append(
                    ModelCapabilityProfile(
                        model_id=r.id,
                        provider=r.provider,
                        family=r.family,
                        tier=ModelTier(r.tier),
                        context_window=r.context_window,
                        supports_tools=r.supports_tools,
                        supports_vision=r.supports_vision,
                        supports_structured_output=r.supports_structured_output,
                        supports_system_prompt=r.supports_system_prompt,
                        is_zero_retention=r.is_zero_retention,
                        deployment_type=r.deployment_type,
                        privacy_verified_at=r.privacy_verified_at,
                        privacy_policy_version=r.privacy_policy_version,
                        endpoint_url=r.endpoint_url,
                        reliability_index=r.reliability_index,
                        expected_latency_ms=r.expected_latency_ms,
                        input_cost_per_million_micros=in_cost,
                        output_cost_per_million_micros=out_cost,
                        cached_input_cost_per_million_micros=cache_cost,
                        active=r.active,
                    )
                )
            return profiles

    async def get_model_profile(self, model_id: str) -> ModelCapabilityProfile | None:
        """Fetch capability profile for a single model."""
        models = await self.list_models()
        return next((m for m in models if m.model_id == model_id), None)

    async def route(self, request: RoutingRequest) -> RoutingDecision:
        """Evaluate candidate models against multi-gate constraints and return the optimal model decision."""
        models = await self.list_models()
        if not models:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Model registry is empty or uninitialized",
            )

        settings = get_settings()
        exclusions: list[CandidateExclusion] = []
        valid_candidates: list[tuple[ModelCapabilityProfile, float, int, float, str]] = []

        total_req_tokens = request.estimated_input_tokens + request.estimated_output_tokens

        # Check for sensitive taints at Gate 1
        req_taints_lower = {t.lower().strip() for t in request.taints if t.strip()}
        has_sensitive_taints = bool(req_taints_lower & SENSITIVE_TAINTS)

        for m in models:
            # 1. Environment and test-only provider restriction
            if m.provider == "mock":
                if settings.environment == EnvironmentType.PRODUCTION:
                    exclusions.append(
                        CandidateExclusion(
                            model_id=m.model_id,
                            rule="TEST_PROVIDER_DISALLOWED_IN_PRODUCTION",
                            reason=f"Mock provider model '{m.model_id}' is strictly forbidden in production",
                        )
                    )
                    continue

            # 2. Distributed Circuit Breaker check
            is_available, cb_state = await circuit_breaker_service.is_available(m.provider, m.model_id)
            if not is_available:
                exclusions.append(
                    CandidateExclusion(
                        model_id=m.model_id,
                        rule="CIRCUIT_BREAKER_OPEN",
                        reason=(
                            f"Circuit breaker tripped ({cb_state}) due to consecutive upstream failures on model "
                            f"'{m.model_id}'"
                        ),
                    )
                )
                continue

            # 3. Gate 1 Privacy & Deployment Constraint
            if has_sensitive_taints:
                # Must have verified zero-retention attestation
                if not m.is_zero_retention:
                    exclusions.append(
                        CandidateExclusion(
                            model_id=m.model_id,
                            rule="GATE1_DATA_RESIDENCY_PRIVACY",
                            reason=(
                                f"Model '{m.model_id}' lacks zero-data-retention guarantee for sensitive taint(s): "
                                f"{sorted(req_taints_lower & SENSITIVE_TAINTS)}"
                            ),
                        )
                    )
                    continue

                if m.privacy_verified_at is None:
                    exclusions.append(
                        CandidateExclusion(
                            model_id=m.model_id,
                            rule="GATE1_PRIVACY_ATTESTATION_MISSING",
                            reason=f"Model '{m.model_id}' lacks verified privacy attestation timestamp",
                        )
                    )
                    continue

                # Must be deployed in private VPC, on-prem, or air-gapped
                if m.deployment_type not in ("cloud_dedicated_vpc", "on_prem_local", "air_gapped"):
                    exclusions.append(
                        CandidateExclusion(
                            model_id=m.model_id,
                            rule="GATE1_DEPLOYMENT_NOT_ISOLATED",
                            reason=(
                                f"Model '{m.model_id}' deployment type '{m.deployment_type}' does not provide "
                                f"required physical/VPC isolation for sensitive taints"
                            ),
                        )
                    )
                    continue

                # Local Ollama endpoint check
                if m.provider == "ollama":
                    endpoint = (m.endpoint_url or getattr(settings, "ollama_base_url", "")).lower()
                    if not (
                        "localhost" in endpoint or "127.0.0.1" in endpoint or endpoint.startswith("http://10.")
                    ):
                        exclusions.append(
                            CandidateExclusion(
                                model_id=m.model_id,
                                rule="GATE1_LOCAL_ENDPOINT_UNVERIFIED",
                                reason=f"Ollama local endpoint '{endpoint}' is unverified or external",
                            )
                        )
                        continue

            # 4. Gate 3 Risk Level Constraint
            if request.risk_level >= 3:
                # Consequential actions require FRONTIER tier and high reliability index
                if m.tier != ModelTier.FRONTIER:
                    exclusions.append(
                        CandidateExclusion(
                            model_id=m.model_id,
                            rule="GATE3_RISK_TIER_INSUFFICIENT",
                            reason=(
                                f"Risk level L{request.risk_level} requires FRONTIER tier models; "
                                f"model '{m.model_id}' is tier '{m.tier.value}'"
                            ),
                        )
                    )
                    continue
                if m.reliability_index < 0.85:
                    exclusions.append(
                        CandidateExclusion(
                            model_id=m.model_id,
                            rule="GATE3_RELIABILITY_INSUFFICIENT",
                            reason=(
                                f"Risk level L{request.risk_level} requires reliability >= 0.85; "
                                f"model '{m.model_id}' index is {m.reliability_index}"
                            ),
                        )
                    )
                    continue
            elif request.risk_level == 2:
                if m.reliability_index < 0.75:
                    exclusions.append(
                        CandidateExclusion(
                            model_id=m.model_id,
                            rule="GATE3_RELIABILITY_INSUFFICIENT",
                            reason=(
                                f"Risk level L2 requires reliability >= 0.75; model '{m.model_id}' "
                                f"index is {m.reliability_index}"
                            ),
                        )
                    )
                    continue

            # 5. Mandatory Capability Constraints
            if "tools" in request.required_capabilities and not m.supports_tools:
                exclusions.append(
                    CandidateExclusion(
                        model_id=m.model_id,
                        rule="CAPABILITY_TOOLS_UNSUPPORTED",
                        reason=f"Task requires tool calling, but model '{m.model_id}' does not support it",
                    )
                )
                continue
            if "vision" in request.required_capabilities and not m.supports_vision:
                exclusions.append(
                    CandidateExclusion(
                        model_id=m.model_id,
                        rule="CAPABILITY_VISION_UNSUPPORTED",
                        reason=f"Task requires vision/multimodal input, but model '{m.model_id}' does not support it",
                    )
                )
                continue
            if "structured_output" in request.required_capabilities and not m.supports_structured_output:
                exclusions.append(
                    CandidateExclusion(
                        model_id=m.model_id,
                        rule="CAPABILITY_STRUCTURED_OUTPUT_UNSUPPORTED",
                        reason=(
                            f"Task requires structured JSON schema output, but model '{m.model_id}' does not support it"
                        ),
                    )
                )
                continue

            # 6. Context Window Constraint
            if total_req_tokens > m.context_window:
                exclusions.append(
                    CandidateExclusion(
                        model_id=m.model_id,
                        rule="CONTEXT_WINDOW_EXCEEDED",
                        reason=(
                            f"Total requested tokens ({total_req_tokens}) exceeds context window ({m.context_window}) "
                            f"of model '{m.model_id}'"
                        ),
                    )
                )
                continue

            # 7. Authoritative Pricing Profile and Cost Calculation
            try:
                pricing_record = await pricing_service.get_active_pricing_profile(m.model_id)
                pricing_id = pricing_record.id
                est_cost_micros = pricing_service.calculate_cost_micros(
                    pricing_record,
                    prompt_tokens=request.estimated_input_tokens,
                    completion_tokens=request.estimated_output_tokens,
                )
            except PricingProfileNotFoundError:
                exclusions.append(
                    CandidateExclusion(
                        model_id=m.model_id,
                        rule="PRICING_PROFILE_UNAVAILABLE",
                        reason=f"No active pricing profile found for model '{m.model_id}'; fail closed",
                    )
                )
                continue

            if request.max_cost_micros is not None and est_cost_micros > request.max_cost_micros:
                exclusions.append(
                    CandidateExclusion(
                        model_id=m.model_id,
                        rule="MAX_COST_BUDGET_EXCEEDED",
                        reason=(
                            f"Estimated cost {est_cost_micros} micros exceeds max allowed budget "
                            f"{request.max_cost_micros} micros for model '{m.model_id}'"
                        ),
                    )
                )
                continue

            # 8. Latency Constraint
            if request.max_latency_ms is not None and m.expected_latency_ms > request.max_latency_ms:
                exclusions.append(
                    CandidateExclusion(
                        model_id=m.model_id,
                        rule="MAX_LATENCY_EXCEEDED",
                        reason=(
                            f"Expected latency {m.expected_latency_ms}ms exceeds max allowed latency "
                            f"{request.max_latency_ms}ms for model '{m.model_id}'"
                        ),
                    )
                )
                continue

            # 9. Compute Composite Scoring
            cost_norm = 1.0 / (1.0 + (est_cost_micros / 100_000.0))
            latency_norm = 1.0 / (1.0 + (m.expected_latency_ms / 500.0))
            rel_norm = m.reliability_index

            if request.risk_level >= 3:
                w_rel, w_cost, w_lat = 0.65, 0.20, 0.15
            elif request.task_type in ("reasoning", "coding"):
                w_rel, w_cost, w_lat = 0.50, 0.30, 0.20
            elif request.task_type in ("extraction", "classification"):
                w_cost, w_lat, w_rel = 0.50, 0.30, 0.20
            elif request.task_type == "chat":
                w_lat, w_cost, w_rel = 0.45, 0.40, 0.15
            else:
                w_cost, w_lat, w_rel = 0.40, 0.30, 0.30

            score = (w_cost * cost_norm) + (w_lat * latency_norm) + (w_rel * rel_norm)

            if request.preferred_model and request.preferred_model == m.model_id:
                score += 0.25

            valid_candidates.append(
                (m, round(score, 4), est_cost_micros, m.expected_latency_ms, pricing_id)
            )

        if not valid_candidates:
            exclusion_summary = [e.model_dump() for e in exclusions]
            logger.warning(
                "No feasible model satisfies routing constraints",
                tenant_id=request.tenant_id,
                exclusions_count=len(exclusions),
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "No feasible model satisfies assurance constraints",
                    "tenant_id": request.tenant_id,
                    "exclusions": exclusion_summary,
                },
            )

        # Sort valid candidates: if a preferred model was requested and is feasible, prioritize it at the top;
        # otherwise sort by composite score descending.
        if request.preferred_model:
            valid_candidates.sort(
                key=lambda x: (1 if x[0].model_id == request.preferred_model else 0, x[1]),
                reverse=True,
            )
        else:
            valid_candidates.sort(key=lambda x: x[1], reverse=True)
        chosen_profile, chosen_score, chosen_cost, chosen_latency, chosen_pricing_id = valid_candidates[0]

        fallback_ladder = [c[0].model_id for c in valid_candidates[1:]] if request.allow_fallbacks else []

        decision_id = f"dec_{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC)

        # Decision provenance payload
        hash_payload = {
            "decision_id": decision_id,
            "tenant_id": request.tenant_id,
            "selected_model": chosen_profile.model_id,
            "score": chosen_score,
            "estimated_cost_micros": chosen_cost,
            "pricing_profile_id": chosen_pricing_id,
            "taints": sorted(request.taints),
            "risk_level": request.risk_level,
            "required_capabilities": sorted(request.required_capabilities),
            "fallback_ladder": fallback_ladder,
            "timestamp": now.isoformat(),
        }
        raw_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True).encode()).hexdigest()

        reason = (
            f"Selected {chosen_profile.model_id} ({chosen_profile.tier.value}) with score {chosen_score:.4f} "
            f"satisfying Gate 1 privacy (taints={request.taints}), Gate 3 risk (L{request.risk_level}), "
            f"and budget bounds ({chosen_cost} micros, pricing={chosen_pricing_id})."
        )

        return RoutingDecision(
            decision_id=decision_id,
            tenant_id=request.tenant_id,
            selected_model_id=chosen_profile.model_id,
            provider=chosen_profile.provider,
            tier=chosen_profile.tier,
            score=chosen_score,
            estimated_cost_micros=chosen_cost,
            estimated_latency_ms=chosen_latency,
            fallback_ladder=fallback_ladder,
            exclusions=exclusions,
            decision_hash=raw_hash,
            pricing_profile_id=chosen_pricing_id,
            reason=reason,
            created_at=now,
        )

    async def revalidate_fallback_candidate(
        self,
        candidate_model_id: str,
        request: RoutingRequest,
        remaining_budget_micros: int,
    ) -> tuple[bool, str | None, ModelCapabilityProfile | None, int, str]:
        """Independently revalidate a fallback candidate before execution.

        Returns: (is_valid, exclusion_reason, profile, estimated_cost_micros, pricing_profile_id).
        """
        profile = await self.get_model_profile(candidate_model_id)
        if profile is None or not profile.active:
            return False, f"Model '{candidate_model_id}' is inactive or not found", None, 0, ""

        settings = get_settings()
        if profile.provider == "mock" and settings.environment == EnvironmentType.PRODUCTION:
            return False, f"Mock provider model '{candidate_model_id}' is forbidden in production", None, 0, ""

        # Circuit breaker
        is_avail, cb_state = await circuit_breaker_service.is_available(profile.provider, profile.model_id)
        if not is_avail:
            return False, f"Circuit breaker is {cb_state} for model '{candidate_model_id}'", None, 0, ""

        # Gate 1 Privacy
        req_taints_lower = {t.lower().strip() for t in request.taints if t.strip()}
        if bool(req_taints_lower & SENSITIVE_TAINTS):
            if (
                not profile.is_zero_retention
                or profile.privacy_verified_at is None
                or profile.deployment_type not in ("cloud_dedicated_vpc", "on_prem_local", "air_gapped")
            ):
                return False, f"Model '{candidate_model_id}' does not satisfy Gate 1 privacy constraints", None, 0, ""

        # Gate 3 Risk
        if request.risk_level >= 3:
            if profile.tier != ModelTier.FRONTIER or profile.reliability_index < 0.85:
                return False, f"Model '{candidate_model_id}' does not satisfy Gate 3 risk constraints", None, 0, ""

        # Capabilities
        for cap in request.required_capabilities:
            if cap == "tools" and not profile.supports_tools:
                return False, f"Model '{candidate_model_id}' lacks tool support", None, 0, ""
            if cap == "vision" and not profile.supports_vision:
                return False, f"Model '{candidate_model_id}' lacks vision support", None, 0, ""
            if cap == "structured_output" and not profile.supports_structured_output:
                return False, f"Model '{candidate_model_id}' lacks structured output support", None, 0, ""

        # Pricing and budget coverage
        try:
            pricing_record = await pricing_service.get_active_pricing_profile(candidate_model_id)
            est_cost = pricing_service.calculate_cost_micros(
                pricing_record,
                prompt_tokens=request.estimated_input_tokens,
                completion_tokens=request.estimated_output_tokens,
            )
            if est_cost > remaining_budget_micros:
                return (
                    False,
                    f"Estimated cost {est_cost} exceeds remaining budget {remaining_budget_micros}",
                    None,
                    0,
                    "",
                )
            return True, None, profile, est_cost, pricing_record.id
        except PricingProfileNotFoundError:
            return False, f"Pricing profile unavailable for model '{candidate_model_id}'", None, 0, ""


model_router_service = ModelRouterService()
