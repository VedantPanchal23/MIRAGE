"""Simulated test adapter for automated pipelines and testbeds.

Authoritative Specs: Reality_Verification.md §3.4.
"""

from __future__ import annotations

from db.models import ActionContract
from shared.schemas.outcome import OutcomeVerificationRequest

from .base import AdapterProbeResult, BaseOutcomeAdapter


class SimulatedTestAdapter(BaseOutcomeAdapter):
    """Explicitly simulated test adapter for automated pipelines and testbeds.

    Enforces mandatory simulation provenance marking.
    NEVER satisfies production SUCCESS_CONFIRMED.
    """

    async def verify(
        self,
        action: ActionContract,
        request: OutcomeVerificationRequest,
        tenant_id: str,
    ) -> AdapterProbeResult:
        config = request.adapter_config
        expected = request.expected_postconditions
        simulated_state = config.get("simulated_state", dict(expected))
        discrepancies: list[str] = []

        for key, expected_val in expected.items():
            if simulated_state.get(key) != expected_val:
                discrepancies.append(
                    f"Simulated mismatch on '{key}': expected '{expected_val}', observed '{simulated_state.get(key)}'"
                )

        return AdapterProbeResult(
            observed_state=simulated_state,
            evidence_payload={
                "simulated": True,
                "fixture": config.get("fixture_name", "default"),
                "action_id": action.id,
                "tenant_id": tenant_id,
                "disclaimer": "SIMULATED_TEST_VERIFIER_NOT_PRODUCTION",
            },
            discrepancies=discrepancies,
            is_simulated=True,
            adapter_name="SimulatedTestAdapter",
            success_indicated=(len(discrepancies) == 0),
            reconciliation_notes=[
                "Verified using SimulatedTestAdapter; "
                "simulation evidence CANNOT satisfy production physical verification."
            ],
        )
