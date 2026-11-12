"""Gate 5 Reality Verifier - Status, Confidence, and Contract Evaluator.

Handles state transitions, confidence scoring across observability classes,
and cryptographic read-time contract verification for OutcomeVerificationRecord.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import HTTPException, status

from db.models import OutcomeVerificationRecord
from shared.schemas.outcome import (
    ObservabilityClass,
    OutcomeStatus,
    OutcomeVerificationContract,
)

from .reconciliation import VALID_OUTCOME_TRANSITIONS


def validate_outcome_transition(current_status: OutcomeStatus, new_status: OutcomeStatus) -> None:
    """Enforce monotonic outcome state machine preventing status regression or illegal upgrades."""
    allowed = VALID_OUTCOME_TRANSITIONS.get(current_status, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Illegal outcome transition: cannot transition from '{current_status.value}' "
                f"to '{new_status.value}'. Transition not permitted by monotonic outcome state machine."
            ),
        )


def record_to_contract(
    record: OutcomeVerificationRecord,
    trust_assurance_level: str = "GENESIS_SENTINEL",
) -> OutcomeVerificationContract:
    """Convert an authoritative database record to an immutable OutcomeVerificationContract.

    Enforces read-time cryptographic integrity check against the canonical payload.
    """
    canonical = (record.evidence_payload or {}).get("_canonical_payload")
    if canonical and isinstance(canonical, dict):
        # 1. Verify column integrity against canonical payload
        mismatches: list[str] = []
        if record.outcome_status != canonical.get("outcome_status"):
            mismatches.append(f"outcome_status ('{record.outcome_status}' != '{canonical.get('outcome_status')}')")
        if record.tenant_id != canonical.get("tenant_id"):
            mismatches.append(f"tenant_id ('{record.tenant_id}' != '{canonical.get('tenant_id')}')")
        if record.action_id != canonical.get("action_id"):
            mismatches.append(f"action_id ('{record.action_id}' != '{canonical.get('action_id')}')")
        if record.transaction_id != canonical.get("transaction_id"):
            mismatches.append(f"transaction_id ('{record.transaction_id}' != '{canonical.get('transaction_id')}')")
        if record.observability_class != canonical.get("observability_class"):
            mismatches.append(
                f"observability_class ('{record.observability_class}' != '{canonical.get('observability_class')}')"
            )
        if abs(record.epistemic_confidence - float(canonical.get("epistemic_confidence", 0.0))) > 1e-5:
            stored_conf = record.epistemic_confidence
            expected_conf = canonical.get("epistemic_confidence")
            mismatches.append(f"epistemic_confidence ('{stored_conf}' != '{expected_conf}')")
        if canonical.get("evidence_source") and record.evidence_source != canonical.get("evidence_source"):
            mismatches.append(f"evidence_source ('{record.evidence_source}' != '{canonical.get('evidence_source')}')")
        if canonical.get("evidence_digest") and record.evidence_digest != canonical.get("evidence_digest"):
            mismatches.append(f"evidence_digest ('{record.evidence_digest}' != '{canonical.get('evidence_digest')}')")

        if mismatches:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cryptographic integrity violation: OutcomeVerificationRecord '{record.id}' "
                    f"tampered in storage. Divergences: {', '.join(mismatches)}"
                ),
            )

        # 2. Recompute SHA-256 over canonical payload
        recomputed_hash = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if recomputed_hash != record.verification_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cryptographic integrity violation: OutcomeVerificationRecord '{record.id}' "
                    f"verification_hash mismatch. Stored: '{record.verification_hash}', "
                    f"Recomputed: '{recomputed_hash}'"
                ),
            )

    verified_dt = (
        record.verified_at.isoformat() if hasattr(record.verified_at, "isoformat") else str(record.verified_at)
    )
    return OutcomeVerificationContract(
        outcome_id=record.id,
        transaction_id=record.transaction_id,
        action_id=record.action_id,
        tenant_id=record.tenant_id,
        observability_class=ObservabilityClass(record.observability_class),
        outcome_status=OutcomeStatus(record.outcome_status),
        epistemic_confidence=record.epistemic_confidence,
        verifier_adapter=record.verifier_adapter,
        is_simulated=record.is_simulated,
        expected_postconditions=record.expected_postconditions,
        observed_state=record.observed_state,
        discrepancies=record.discrepancies,
        evidence_payload=record.evidence_payload,
        reconciliation_notes=record.reconciliation_notes,
        verification_hash=record.verification_hash,
        idempotency_key=record.idempotency_key or "",
        target_environment=record.target_environment or "DEFAULT",
        contract_binding_hash=record.contract_binding_hash,
        evidence_source=record.evidence_source,
        evidence_digest=record.evidence_digest,
        observed_at=(
            record.observed_at.isoformat()
            if hasattr(record.observed_at, "isoformat") and record.observed_at
            else str(record.observed_at)
            if record.observed_at
            else None
        ),
        verification_deadline=(
            record.verification_deadline.isoformat()
            if hasattr(record.verification_deadline, "isoformat") and record.verification_deadline
            else str(record.verification_deadline)
            if record.verification_deadline
            else None
        ),
        escalation_status=record.escalation_status,
        escalation_notes=record.escalation_notes,
        schema_version="mirage.outcome.v1",
        verified_at=verified_dt,
        trust_assurance_level=trust_assurance_level,
    )


def evaluate_outcome_status_and_confidence(
    *,
    obs_class: ObservabilityClass,
    discrepancies: list[str],
    effective_postconditions: dict[str, Any],
    is_simulated: bool,
    success_indicated: bool,
    observation: Any | None,
    deadline_passed: bool,
    reconciliation_notes: list[str],
) -> tuple[OutcomeStatus, float]:
    """Compute authoritative Gate 5 OutcomeStatus and epistemic confidence.

    Preserves strict epistemic outcome independence:
    - OBS_BLIND yields strictly UNOBSERVABLE (confidence 0.0)
    - OBS_INFERRED yields ACKNOWLEDGED_UNVERIFIED (confidence 0.50)
    - Void postconditions cannot produce verified success
    - Simulated probes cannot satisfy production SUCCESS_CONFIRMED
    - Expired verification deadlines downgrade tentative success to UNKNOWN
    """
    if obs_class == ObservabilityClass.OBS_BLIND:
        reconciliation_notes.append(
            "Target resource is OBS_BLIND (write-only sink). No readback channel exists. "
            "Epistemic confidence is strictly 0.0."
        )
        outcome_status = OutcomeStatus.UNOBSERVABLE
        epistemic_confidence = 0.0

    elif obs_class == ObservabilityClass.OBS_INFERRED:
        reconciliation_notes.append(
            "Target resource is OBS_INFERRED (transport-acknowledged only). "
            "Actual postconditions at destination sink cannot be directly inspected by MIRAGE."
        )
        outcome_status = OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
        epistemic_confidence = 0.50

    elif obs_class == ObservabilityClass.OBS_DIRECT:
        if len(effective_postconditions) == 0:
            reconciliation_notes.append(
                "Void postcondition assertion: zero expected postconditions were specified. "
                "SUCCESS_CONFIRMED requires authoritative postcondition state verification. "
                "Status downgraded to ACKNOWLEDGED_UNVERIFIED."
            )
            outcome_status = OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
            epistemic_confidence = 0.50
        elif is_simulated:
            if discrepancies:
                outcome_status = OutcomeStatus.FAILED
                epistemic_confidence = 0.95
            else:
                reconciliation_notes.append(
                    "Probe executed using SimulatedTestAdapter; physical reality unverified. "
                    "Cannot be awarded SUCCESS_CONFIRMED."
                )
                outcome_status = OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
                epistemic_confidence = 0.50
        elif discrepancies:
            if len(discrepancies) < len(effective_postconditions) and len(effective_postconditions) > 1:
                outcome_status = OutcomeStatus.PARTIAL_ACHIEVEMENT if observation else OutcomeStatus.PARTIAL
                raw_conf = observation.epistemic_confidence if observation else 0.85
                epistemic_confidence = min(raw_conf, 0.70)
            else:
                outcome_status = OutcomeStatus.VERIFIED_FAILURE if observation else OutcomeStatus.FAILED
                epistemic_confidence = 0.95
        else:
            outcome_status = OutcomeStatus.VERIFIED_SUCCESS if observation else OutcomeStatus.SUCCESS_CONFIRMED
            epistemic_confidence = observation.epistemic_confidence if observation else 1.00

    elif obs_class == ObservabilityClass.OBS_EVENTUAL:
        if len(effective_postconditions) == 0:
            reconciliation_notes.append(
                "Void postcondition assertion: zero expected postconditions were specified. "
                "Cannot award SUCCESS_EVENTUALLY_OBSERVED without verified postconditions."
            )
            outcome_status = OutcomeStatus.ACKNOWLEDGED_UNVERIFIED
            epistemic_confidence = 0.50
        elif success_indicated and not discrepancies:
            outcome_status = OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED
            epistemic_confidence = 0.95
        elif "timed out" in " ".join(discrepancies).lower():
            reconciliation_notes.append("Eventual consistency polling timed out without observing stable target state.")
            outcome_status = OutcomeStatus.UNKNOWN
            epistemic_confidence = 0.0
        else:
            outcome_status = OutcomeStatus.FAILED
            epistemic_confidence = 0.90

    else:
        outcome_status = OutcomeStatus.UNKNOWN
        epistemic_confidence = 0.0

    if deadline_passed:
        if outcome_status in (
            OutcomeStatus.VERIFIED_SUCCESS,
            OutcomeStatus.SUCCESS_CONFIRMED,
            OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        ):
            outcome_status = OutcomeStatus.UNKNOWN
            epistemic_confidence = 0.0
            reconciliation_notes.append(
                "Verification deadline expired. "
                "Late observation cannot convert an expired action into verified success."
            )
        elif observation is None and not success_indicated:
            outcome_status = OutcomeStatus.UNKNOWN
            epistemic_confidence = 0.0
            reconciliation_notes.append(
                "Verification deadline expired without independent confirmation. Downgraded to UNKNOWN."
            )

    return outcome_status, epistemic_confidence
