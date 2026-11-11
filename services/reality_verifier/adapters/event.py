"""Bounded exponential backoff polling adapter for eventual consistency (OBS_EVENTUAL).

Authoritative Specs: Reality_Verification.md §3.3.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from db.models import ActionContract
from shared.schemas.outcome import OutcomeVerificationRequest

from .base import AdapterProbeResult, BaseOutcomeAdapter


class AsyncEventAdapter(BaseOutcomeAdapter):
    """Bounded exponential backoff polling adapter for eventual consistency (OBS_EVENTUAL)."""

    async def verify(
        self,
        action: ActionContract,
        request: OutcomeVerificationRequest,
        tenant_id: str,
    ) -> AdapterProbeResult:
        expected = request.expected_postconditions
        config = request.adapter_config
        attempts = 0
        max_attempts = min(request.max_poll_attempts, 30)
        interval = max(request.poll_interval_seconds, 0.05)
        start_time = time.time()
        timeout = min(request.timeout_seconds, 60.0)

        observed_state: dict[str, Any] = {}
        discrepancies: list[str] = []
        evidence: dict[str, Any] = {
            "adapter": "AsyncEventAdapter",
            "action_id": action.id,
            "tenant_id": tenant_id,
            "poll_attempts": 0,
        }

        probe_fn = config.get("probe_callable")
        simulated_values = config.get("simulated_progression")
        is_sim = bool(simulated_values)

        matched = False

        while attempts < max_attempts and (time.time() - start_time) < timeout:
            attempts += 1
            evidence["poll_attempts"] = attempts

            if callable(probe_fn):
                try:
                    observed_state = await probe_fn(action, tenant_id)
                except Exception as exc:
                    observed_state = {"error": str(exc)}
            elif simulated_values and isinstance(simulated_values, list):
                idx = min(attempts - 1, len(simulated_values) - 1)
                observed_state = simulated_values[idx]
            else:
                observed_state = action.observed_result or {}

            current_discrepancies: list[str] = []
            for key, expected_val in expected.items():
                if observed_state.get(key) != expected_val:
                    current_discrepancies.append(
                        f"Field '{key}' expected '{expected_val}', currently '{observed_state.get(key)}'"
                    )

            if not current_discrepancies:
                matched = True
                discrepancies = []
                break
            else:
                discrepancies = current_discrepancies

            await asyncio.sleep(interval)
            interval = min(interval * 1.5, 5.0)

        if not matched:
            discrepancies.append(
                f"Eventual consistency verification timed out after {attempts} attempts "
                f"({round(time.time() - start_time, 2)}s)"
            )

        return AdapterProbeResult(
            observed_state=observed_state,
            evidence_payload=evidence,
            discrepancies=discrepancies,
            is_simulated=is_sim,
            adapter_name="AsyncEventAdapter",
            success_indicated=matched,
            reconciliation_notes=[f"Polled {attempts} times before completion"],
        )
