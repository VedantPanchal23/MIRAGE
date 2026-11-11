"""Independent observer adapter for verifying outcomes using authoritative independent observations.

Authoritative Specs: Reality_Verification.md §3.5.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status

from db.models import ActionContract
from shared.schemas.audit import is_valid_sha256_hex
from shared.schemas.outcome import (
    OutcomeVerificationRequest,
    compute_bound_evidence_digest,
    compute_evidence_digest,
)

from .base import AdapterProbeResult, BaseOutcomeAdapter, _redact_sensitive_payload


class IndependentObserverAdapter(BaseOutcomeAdapter):
    """Adapter for verifying outcomes using authoritative independent observations."""

    async def verify(
        self,
        action: ActionContract,
        request: OutcomeVerificationRequest,
        _tenant_id: str,
    ) -> AdapterProbeResult:
        if not request.observation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OutcomeVerifierType.INDEPENDENT_OBSERVER requires 'observation' in request payload.",
            )
        obs = request.observation

        # 1. Target resource validation
        if obs.target_resource.strip() != action.target_resource.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Target resource mismatch: observation target '{obs.target_resource}' "
                    f"does not match ActionContract target '{action.target_resource}'."
                ),
            )

        # 2. Anti-staleness & Timestamp Validation
        now_utc = datetime.now(UTC)
        obs_dt = obs.observed_at
        if obs_dt.tzinfo is None:
            obs_dt = obs_dt.replace(tzinfo=UTC)

        # Reject future timestamps (allowing 60s max clock skew)
        if obs_dt > now_utc + timedelta(seconds=60):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Future observation timestamp: observed_at ({obs_dt.isoformat()}) "
                    f"is in the future (current time: {now_utc.isoformat()})."
                ),
            )

        action_ts = action.executed_at or action.created_at
        if action_ts:
            act_dt = action_ts
            if act_dt.tzinfo is None:
                act_dt = act_dt.replace(tzinfo=UTC)
            if obs_dt < act_dt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Stale observation: observed_at ({obs_dt.isoformat()}) is earlier than "
                        f"action execution time ({act_dt.isoformat()})."
                    ),
                )

            if action.outcome_contract and isinstance(action.outcome_contract, dict):
                dl_sec = action.outcome_contract.get("verification_deadline_seconds")
                if dl_sec is not None:
                    deadline_dt = act_dt + timedelta(seconds=float(dl_sec))
                    if obs_dt > deadline_dt:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=(
                                f"Expired observation: observed_at ({obs_dt.isoformat()}) exceeds "
                                f"verification deadline ({deadline_dt.isoformat()}, {dl_sec}s from action)."
                            ),
                        )

        # 3. Acceptable evidence sources allowlist check
        if action.outcome_contract and isinstance(action.outcome_contract, dict):
            acceptable_sources = action.outcome_contract.get("acceptable_evidence_sources")
            if acceptable_sources and isinstance(acceptable_sources, list) and len(acceptable_sources) > 0:
                if obs.source_id not in acceptable_sources:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Untrusted evidence source: observer source '{obs.source_id}' is not in "
                            f"authorized acceptable_evidence_sources: {acceptable_sources}."
                        ),
                    )

        # 4. Canonical Digest Validation & Cryptographic Recomputation
        if not is_valid_sha256_hex(obs.evidence_digest):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid evidence digest '{obs.evidence_digest}': must be 64-char lowercase SHA-256 hex string."
                ),
            )

        computed_state_digest = compute_evidence_digest(obs.observed_state)
        computed_bound_digest = compute_bound_evidence_digest(obs.target_resource, obs.observed_state)
        if obs.evidence_digest != computed_state_digest and obs.evidence_digest != computed_bound_digest:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Evidence digest mismatch: submitted digest '{obs.evidence_digest}' does not match "
                    f"canonical recomputed digest '{computed_state_digest}' over observed state. "
                    "Evidence payload may have been tampered with or corrupted."
                ),
            )

        # 5. Evaluate discrepancies against expected postconditions
        expected = request.expected_postconditions
        discrepancies: list[str] = []
        for key, exp_val in expected.items():
            obs_val = obs.observed_state.get(key)
            if obs_val != exp_val:
                discrepancies.append(f"Postcondition violation on '{key}': expected '{exp_val}', observed '{obs_val}'.")

        safe_observed_state = _redact_sensitive_payload(obs.observed_state)
        safe_evidence = _redact_sensitive_payload(
            {
                "observation_id": obs.observation_id,
                "source_id": obs.source_id,
                "target_resource": obs.target_resource,
                "observed_at": obs.observed_at.isoformat(),
                "evidence_digest": obs.evidence_digest,
                "signature": obs.signature,
                "epistemic_confidence": obs.epistemic_confidence,
                "observed_state": safe_observed_state,
            }
        )

        return AdapterProbeResult(
            observed_state=safe_observed_state,
            evidence_payload=safe_evidence,
            discrepancies=discrepancies,
            is_simulated=False,
            adapter_name=f"IndependentObserverAdapter[{obs.source_id}]",
            success_indicated=(len(discrepancies) == 0),
            reconciliation_notes=[
                f"Verified via independent observer '{obs.source_id}' (digest: {obs.evidence_digest[:16]}...)"
            ],
        )
