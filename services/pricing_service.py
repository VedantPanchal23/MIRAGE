"""Authoritative Pricing Service for MIRAGE 3.0 Execution Plane.

Enforces unified pricing profile resolution, effective-date selection, non-negative rates,
and deterministic cost calculation without floating-point drift or hard-coded fallbacks.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import ModelPricingProfileRecord
from shared.logging import get_logger

logger = get_logger("pricing_service")


class PricingProfileNotFoundError(Exception):
    """Raised when an active pricing profile cannot be resolved for a model."""

    pass


class PricingValidationError(Exception):
    """Raised when pricing profile fields or usage counters violate invariants."""

    pass


class PricingService:
    """Authoritative service for resolving pricing profiles and calculating costs."""

    # Provider model aliases mapped to canonical model IDs registered in MIRAGE
    MODEL_ALIASES: dict[str, str] = {
        "gpt-4o-2024-05-13": "gpt-4o",
        "gpt-4o-2024-08-06": "gpt-4o",
        "gpt-4o-mini-2024-07-18": "gpt-4o-mini",
        "claude-3-5-sonnet-latest": "claude-3-5-sonnet-20241022",
        "claude-3-haiku": "claude-3-haiku-20240307",
        "gemini-1.5-pro-latest": "gemini-1.5-pro",
        "gemini-1.5-flash-latest": "gemini-1.5-flash",
    }

    def canonicalize_model_id(self, raw_model_id: str) -> str:
        """Resolve upstream provider aliases to the canonical MIRAGE model ID."""
        cleaned = raw_model_id.strip()
        return self.MODEL_ALIASES.get(cleaned, cleaned)

    async def get_active_pricing_profile(
        self,
        model_id: str,
        session: AsyncSession | None = None,
        as_of: datetime | None = None,
    ) -> ModelPricingProfileRecord:
        """Look up the single authoritative active pricing profile by effective date.

        Selects the profile with is_active=True and effective_date <= as_of_date,
        ordered by effective_date DESC, created_at DESC, limit 1.
        Strictly fails closed if no active pricing profile exists.
        """
        canonical_id = self.canonicalize_model_id(model_id)
        current_dt = as_of or datetime.now(UTC)
        current_date_str = current_dt.strftime("%Y-%m-%d")

        if session is not None:
            return await self._query_pricing_profile(session, canonical_id, current_date_str)

        async with db_session.get_system_session() as sys_session:
            return await self._query_pricing_profile(sys_session, canonical_id, current_date_str)

    async def _query_pricing_profile(
        self,
        session: AsyncSession,
        canonical_id: str,
        current_date_str: str,
    ) -> ModelPricingProfileRecord:
        stmt = (
            select(ModelPricingProfileRecord)
            .where(
                ModelPricingProfileRecord.model_id == canonical_id,
                ModelPricingProfileRecord.is_active.is_(True),
                ModelPricingProfileRecord.effective_date <= current_date_str,
            )
            .order_by(
                ModelPricingProfileRecord.effective_date.desc(),
                ModelPricingProfileRecord.created_at.desc(),
            )
            .limit(1)
        )
        record = (await session.execute(stmt)).scalar_one_or_none()
        if record is None:
            raise PricingProfileNotFoundError(
                f"No active pricing profile found for model '{canonical_id}' effective on or before {current_date_str}"
            )

        # Enforce non-negative integer rate invariants
        for field_name in (
            "input_cost_per_million_micros",
            "output_cost_per_million_micros",
            "cached_input_cost_per_million_micros",
        ):
            val = getattr(record, field_name)
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise PricingValidationError(
                    f"Corrupt pricing profile '{record.id}': invalid {field_name}={val!r}"
                )

        if not record.currency or not isinstance(record.currency, str):
            raise PricingValidationError(
                f"Corrupt pricing profile '{record.id}': invalid currency={record.currency!r}"
            )

        return record

    def calculate_cost_micros(
        self,
        pricing: ModelPricingProfileRecord,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int = 0,
    ) -> int:
        """Calculate total billable execution cost in integer micro-units.

        Formula:
            uncached_prompt = max(0, prompt_tokens - cached_tokens)
            raw = (uncached_prompt * in_rate) + (cached_tokens * cache_rate) + (completion_tokens * out_rate)
            cost_micros = ceil(raw / 1,000,000)

        Uses exact integer arithmetic (ceil via integer division: (raw + 999_999) // 1_000_000)
        to prevent binary floating-point drift or precision loss.
        """
        for rate_name in (
            "input_cost_per_million_micros",
            "output_cost_per_million_micros",
            "cached_input_cost_per_million_micros",
        ):
            r_val = getattr(pricing, rate_name, 0)
            if isinstance(r_val, bool) or not isinstance(r_val, int) or r_val < 0:
                raise PricingValidationError(
                    f"Pricing rate '{rate_name}' must be a non-negative integer, got {r_val!r}"
                )

        for name, val in [
            ("prompt_tokens", prompt_tokens),
            ("completion_tokens", completion_tokens),
            ("cached_tokens", cached_tokens),
        ]:
            if isinstance(val, bool) or not isinstance(val, int) or val < 0:
                raise PricingValidationError(
                    f"Token count '{name}' must be a non-negative integer, got {val!r}"
                )

        if cached_tokens > prompt_tokens:
            raise PricingValidationError(
                f"Invalid usage: cached_tokens ({cached_tokens}) cannot exceed prompt_tokens ({prompt_tokens})"
            )

        uncached_prompt = prompt_tokens - cached_tokens
        raw_units = (
            (uncached_prompt * pricing.input_cost_per_million_micros)
            + (cached_tokens * pricing.cached_input_cost_per_million_micros)
            + (completion_tokens * pricing.output_cost_per_million_micros)
        )

        if raw_units == 0:
            return 0

        # Exact integer ceiling division
        return (raw_units + 999_999) // 1_000_000

    def parse_usage_dict(self, usage: dict[str, Any] | None) -> tuple[int, int, int]:
        """Safely extract prompt_tokens, completion_tokens, and cached_tokens from provider usage payloads.

        Treats missing, negative, or malformed counters conservatively without fabricating data.
        """
        if not usage or not isinstance(usage, dict):
            raise PricingValidationError("Missing or non-dictionary provider usage object")

        if "prompt_tokens" not in usage:
            raise PricingValidationError("Missing required 'prompt_tokens' in provider usage payload")
        if "completion_tokens" not in usage:
            raise PricingValidationError("Missing required 'completion_tokens' in provider usage payload")

        prompt_tokens = usage["prompt_tokens"]
        completion_tokens = usage["completion_tokens"]

        if isinstance(prompt_tokens, bool) or not isinstance(prompt_tokens, int) or prompt_tokens < 0:
            raise PricingValidationError(f"Invalid prompt_tokens: {prompt_tokens!r}")
        if isinstance(completion_tokens, bool) or not isinstance(completion_tokens, int) or completion_tokens < 0:
            raise PricingValidationError(f"Invalid completion_tokens: {completion_tokens!r}")

        # Handle provider-specific cached token field variants
        cached_tokens = 0
        if "cached_tokens" in usage:
            cached_tokens = usage["cached_tokens"]
        elif "prompt_tokens_details" in usage and isinstance(usage["prompt_tokens_details"], dict):
            cached_tokens = usage["prompt_tokens_details"].get("cached_tokens", 0)

        if isinstance(cached_tokens, bool) or not isinstance(cached_tokens, int) or cached_tokens < 0:
            raise PricingValidationError(f"Invalid cached_tokens: {cached_tokens!r}")

        if cached_tokens > prompt_tokens:
            raise PricingValidationError(
                f"Invalid usage: cached_tokens ({cached_tokens}) cannot exceed prompt_tokens ({prompt_tokens})"
            )

        return prompt_tokens, completion_tokens, cached_tokens


pricing_service = PricingService()
