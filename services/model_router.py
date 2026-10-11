"""Authoritative Intelligent Model Router service for MIRAGE 3.0 Execution Plane."""

import hashlib
import json
import math
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select

from db import session as db_session
from db.models import ModelPricingProfileRecord, ModelRegistryRecord
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

    def __init__(self) -> None:
        self._circuit_failures: dict[str, int] = {}
        self._circuit_opened_at: dict[str, datetime] = {}
        self._failure_threshold = 5
        self._recovery_timeout_seconds = 60.0

    def record_failure(self, model_id: str) -> None:
        """Record upstream error and trip circuit breaker if failure threshold is met."""
        count = self._circuit_failures.get(model_id, 0) + 1
        self._circuit_failures[model_id] = count
        if count >= self._failure_threshold and model_id not in self._circuit_opened_at:
            self._circuit_opened_at[model_id] = datetime.now(UTC)
            logger.warning("Circuit breaker opened for model", model_id=model_id, failure_count=count)

    def record_success(self, model_id: str) -> None:
        """Record upstream success and reset circuit breaker."""
        self._circuit_failures.pop(model_id, None)
        self._circuit_opened_at.pop(model_id, None)

    def is_circuit_open(self, model_id: str) -> bool:
        """Check whether the circuit breaker for a model is currently tripped."""
        opened_at = self._circuit_opened_at.get(model_id)
        if opened_at is None:
            return False
        elapsed = (datetime.now(UTC) - opened_at).total_seconds()
        if elapsed > self._recovery_timeout_seconds:
            # Half-open recovery test
            self._circuit_opened_at.pop(model_id, None)
            self._circuit_failures[model_id] = self._failure_threshold - 1
            return False
        return True

    async def list_models(self) -> list[ModelCapabilityProfile]:
        """List all active registered models with their capability profiles."""
        async with db_session.get_system_session() as session:
            stmt = select(ModelRegistryRecord).where(ModelRegistryRecord.active.is_(True))
            records = (await session.execute(stmt)).scalars().all()

            profiles = []
            for r in records:
                # Get latest pricing
                price_stmt = (
                    select(ModelPricingProfileRecord)
                    .where(
                        ModelPricingProfileRecord.model_id == r.id,
                        ModelPricingProfileRecord.is_active.is_(True),
                    )
                    .order_by(ModelPricingProfileRecord.created_at.desc())
                    .limit(1)
                )
                price_rec = (await session.execute(price_stmt)).scalar_one_or_none()
                in_cost = price_rec.input_cost_per_million_micros if price_rec else 2500000
                out_cost = price_rec.output_cost_per_million_micros if price_rec else 10000000
                cache_cost = price_rec.cached_input_cost_per_million_micros if price_rec else 1250000

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
                        reliability_index=r.reliability_index,
                        expected_latency_ms=r.expected_latency_ms,
                        input_cost_per_million_micros=in_cost,
                        output_cost_per_million_micros=out_cost,
                        cached_input_cost_per_million_micros=cache_cost,
                        active=r.active,
                    )
                )
            return profiles

    async def route(self, request: RoutingRequest) -> RoutingDecision:
        """Evaluate candidate models against multi-gate constraints and return the optimal model decision."""
        models = await self.list_models()
        if not models:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Model registry is empty or uninitialized",
            )

        exclusions: list[CandidateExclusion] = []
        valid_candidates: list[tuple[ModelCapabilityProfile, float, int, float]] = []

        total_req_tokens = request.estimated_input_tokens + request.estimated_output_tokens

        # Check for sensitive taints at Gate 1
        req_taints_lower = {t.lower() for t in request.taints}
        has_sensitive_taints = bool(req_taints_lower & SENSITIVE_TAINTS)

        for m in models:
            # 1. Circuit breaker check
            if self.is_circuit_open(m.model_id):
                exclusions.append(
                    CandidateExclusion(
                        model_id=m.model_id,
                        rule="CIRCUIT_BREAKER_OPEN",
                        reason=f"Circuit breaker tripped due to consecutive upstream failures on model '{m.model_id}'",
                    )
                )
                continue

            # 2. Gate 1 Privacy & Taint Constraint
            if has_sensitive_taints:
                is_private_or_zero_retention = m.is_zero_retention or m.provider in ("ollama", "mock")
                if not is_private_or_zero_retention:
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

            # 3. Gate 3 Risk Level Constraint
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

            # 4. Mandatory Capability Constraints
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

            # 5. Context Window Constraint
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

            # 6. Cost Calculation and Constraint
            est_cost_float = (
                (request.estimated_input_tokens * m.input_cost_per_million_micros)
                + (request.estimated_output_tokens * m.output_cost_per_million_micros)
            ) / 1_000_000.0
            est_cost_micros = int(math.ceil(est_cost_float))

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

            # 7. Latency Constraint
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

            # 8. Compute Composite Scoring
            cost_norm = 1.0 / (1.0 + (est_cost_micros / 100_000.0))
            latency_norm = 1.0 / (1.0 + (m.expected_latency_ms / 500.0))
            rel_norm = m.reliability_index

            # Weighting adaptation based on task and risk
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

            # Preferred model boost if safe
            if request.preferred_model and request.preferred_model == m.model_id:
                score += 0.25

            valid_candidates.append((m, round(score, 4), est_cost_micros, m.expected_latency_ms))

        # Check if any model survived
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

        # Sort valid candidates by score descending
        valid_candidates.sort(key=lambda x: x[1], reverse=True)
        chosen_profile, chosen_score, chosen_cost, chosen_latency = valid_candidates[0]

        fallback_ladder = [c[0].model_id for c in valid_candidates[1:]] if request.allow_fallbacks else []

        decision_id = f"dec_{uuid.uuid4().hex[:16]}"
        now = datetime.now(UTC)

        # Decision provenance hash
        hash_payload = {
            "decision_id": decision_id,
            "tenant_id": request.tenant_id,
            "selected_model": chosen_profile.model_id,
            "score": chosen_score,
            "estimated_cost_micros": chosen_cost,
            "taints": sorted(request.taints),
            "risk_level": request.risk_level,
            "timestamp": now.isoformat(),
        }
        raw_hash = hashlib.sha256(json.dumps(hash_payload, sort_keys=True).encode()).hexdigest()

        reason = (
            f"Selected {chosen_profile.model_id} ({chosen_profile.tier.value}) with composite score {chosen_score:.4f} "
            f"satisfying Gate 1 privacy (taints={request.taints}), Gate 3 risk (L{request.risk_level}), "
            f"and budget bounds ({chosen_cost} micros)."
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
            reason=reason,
            created_at=now,
        )


model_router_service = ModelRouterService()
