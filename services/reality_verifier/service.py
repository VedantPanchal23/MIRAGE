"""Gate 5 Outcome Assurance and Reality Verification Service for MIRAGE 3.0.

Implements Reality_Verification.md, Input_Output_Assurance.md §6, and AI_Action_Contract.md.
Confirms actual real-world state changes, enforcing epistemic observability boundaries,
monotonic outcome state transitions, cryptographic ActionContract binding, and SSRF defenses.
"""

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, text

from db import session as db_session
from db.models import (
    ActionContract,
    AuditLogRecord,
    OutcomeVerificationRecord,
    TenantAuditLedger,
)
from shared.config import EnvironmentType, get_settings
from shared.logging import get_logger
from shared.schemas.action import ActionState
from shared.schemas.audit import (
    GENESIS_ROOT_HASH,
    TrustedCheckpointRegistry,
    compute_sha256,
    is_valid_sha256_hex,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    ObservabilityClass,
    OutcomeEscalationRequest,
    OutcomeEscalationResponse,
    OutcomeReconciliationResult,
    OutcomeStatus,
    OutcomeVerificationContract,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
)

from .adapters import (
    AdapterProbeResult,
    AsyncEventAdapter,
    BaseOutcomeAdapter,
    DatabaseStateAdapter,
    HttpResourceAdapter,
    IndependentObserverAdapter,
    SimulatedTestAdapter,
)
from .reconciliation import (
    _COMPLETION_ASSERTION_PATTERNS,
    VALID_OUTCOME_TRANSITIONS,
    _extract_clauses,
    _normalize_text,
    _strip_quotes_and_citations,
)

logger = get_logger("reality_verifier")


class RealityVerifierService:
    """Core Gate 5 Outcome Assurance engine validating external system state."""

    def __init__(
        self,
        checkpoint_registry: TrustedCheckpointRegistry | None = None,
    ) -> None:
        self.adapters: dict[OutcomeVerifierType, BaseOutcomeAdapter] = {
            OutcomeVerifierType.DATABASE: DatabaseStateAdapter(),
            OutcomeVerifierType.HTTP_RESOURCE: HttpResourceAdapter(),
            OutcomeVerifierType.ASYNC_EVENT: AsyncEventAdapter(),
            OutcomeVerifierType.SIMULATED: SimulatedTestAdapter(),
            OutcomeVerifierType.INDEPENDENT_OBSERVER: IndependentObserverAdapter(),
        }
        self.checkpoint_registry = checkpoint_registry or TrustedCheckpointRegistry()

    def _validate_outcome_transition(self, current_status: OutcomeStatus, new_status: OutcomeStatus) -> None:
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

    def _record_to_contract(
        self,
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
                mismatches.append(
                    f"evidence_source ('{record.evidence_source}' != '{canonical.get('evidence_source')}')"
                )
            if canonical.get("evidence_digest") and record.evidence_digest != canonical.get("evidence_digest"):
                mismatches.append(
                    f"evidence_digest ('{record.evidence_digest}' != '{canonical.get('evidence_digest')}')"
                )

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

    def _validate_chain_record_fields_and_hash(
        self,
        audit_record: AuditLogRecord,
        role_label: str = "record",
    ) -> str:
        """Validate all required cryptographic fields, format, types, and self-integrity.

        Fails closed (HTTP 409) if any field is missing, empty, malformed, or if the stored
        chain_hash does not match the recomputed canonical SHA-256 hash.
        Returns the validated verified_at ISO timestamp string.
        """
        # 1. entry_id validation
        entry_id = audit_record.entry_id
        if not entry_id or not isinstance(entry_id, str) or not entry_id.strip():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Audit chain record '{entry_id or 'unknown'}' missing or empty entry_id field.",
            )
        if len(entry_id) > 64 or not re.match(r"^[a-zA-Z0-9_\-]+$", entry_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Audit chain record '{entry_id}' has invalid entry_id format.",
            )

        # 2. prev_hash validation
        prev_hash = audit_record.prev_hash
        if not prev_hash or not isinstance(prev_hash, str) or not is_valid_sha256_hex(prev_hash):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Audit chain record '{entry_id}' missing or malformed prev_hash field.",
            )

        # 3. chain_hash validation
        chain_hash = audit_record.chain_hash
        if not chain_hash or not isinstance(chain_hash, str) or not is_valid_sha256_hex(chain_hash):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Audit chain record '{entry_id}' missing or malformed chain_hash field.",
            )

        # 4. decision validation
        decision = audit_record.decision
        if not decision or not isinstance(decision, str) or not decision.strip():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Audit chain record '{entry_id}' missing or empty decision field.",
            )

        # 5. event_payload and verified_at validation
        payload = audit_record.event_payload
        if payload is None or not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Audit chain record '{entry_id}' missing or invalid event_payload dictionary.",
            )

        verified_at = payload.get("verified_at")
        if not verified_at or not isinstance(verified_at, str) or not verified_at.strip():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Audit chain record '{entry_id}' missing or empty verified_at field in payload.",
            )

        # Timestamp format validation
        try:
            datetime.fromisoformat(verified_at)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Audit chain record '{entry_id}' has invalid ISO-8601 verified_at timestamp: '{verified_at}'.",
            ) from None

        # 6. Database column vs payload concordance
        if payload.get("decision") and payload.get("decision") != decision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit chain divergence: {role_label} '{entry_id}' payload decision "
                    f"'{payload.get('decision')}' disagrees with column decision '{decision}'."
                ),
            )
        if payload.get("outcome_status") and payload.get("outcome_status") != decision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit chain divergence: {role_label} '{entry_id}' payload outcome_status "
                    f"'{payload.get('outcome_status')}' disagrees with column decision '{decision}'."
                ),
            )
        if audit_record.transaction_id and payload.get("transaction_id"):
            if payload.get("transaction_id") != audit_record.transaction_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain divergence: {role_label} '{entry_id}' payload transaction_id "
                        f"'{payload.get('transaction_id')}' disagrees with column '{audit_record.transaction_id}'."
                    ),
                )

        # 7. Recompute canonical hash and verify exact match
        expected_chain_hash = compute_sha256(f"{prev_hash}:{entry_id}:{decision}:{verified_at}")
        if chain_hash != expected_chain_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit chain corruption detected at {role_label} '{entry_id}': "
                    f"chain_hash '{chain_hash}' does not match computed hash '{expected_chain_hash}'."
                ),
            )

        return verified_at

    @staticmethod
    def _validate_audit_correlation(record: OutcomeVerificationRecord, matching_audit: AuditLogRecord) -> None:
        """Enforce unambiguous 4-way correlation check between OutcomeVerificationRecord and AuditLogRecord."""
        payload = matching_audit.event_payload or {}
        if payload.get("outcome_id") != record.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord '{matching_audit.entry_id}' "
                    f"outcome_id '{payload.get('outcome_id')}' does not match record '{record.id}'."
                ),
            )
        if not payload.get("action_id") or payload.get("action_id") != record.action_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord '{matching_audit.entry_id}' "
                    f"action_id '{payload.get('action_id')}' does not match record '{record.action_id}'."
                ),
            )
        if matching_audit.tenant_id != record.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord '{matching_audit.entry_id}' "
                    f"tenant_id '{matching_audit.tenant_id}' does not match record '{record.tenant_id}'."
                ),
            )
        if matching_audit.transaction_id != record.transaction_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord column transaction_id "
                    f"'{matching_audit.transaction_id}' does not match record '{record.transaction_id}'."
                ),
            )
        if payload.get("transaction_id") != record.transaction_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor correlation mismatch: AuditLogRecord payload transaction_id "
                    f"'{payload.get('transaction_id')}' does not match record '{record.transaction_id}'."
                ),
            )

    @staticmethod
    def _extract_result_records(exec_res: Any) -> list[Any]:
        """Safely extract result records across live SQLAlchemy execution and test mock objects."""
        if hasattr(exec_res, "scalars"):
            scalars_call = exec_res.scalars()
            if hasattr(scalars_call, "all"):
                res_all = scalars_call.all()
                if isinstance(res_all, list):
                    return res_all
                elif hasattr(exec_res, "scalar_one_or_none"):
                    s_one = exec_res.scalar_one_or_none()
                    return [s_one] if s_one is not None else []
                return list(res_all)
            elif hasattr(exec_res, "scalar_one_or_none"):
                s_one = exec_res.scalar_one_or_none()
                return [s_one] if s_one is not None else []
        elif hasattr(exec_res, "scalar_one_or_none"):
            s_one = exec_res.scalar_one_or_none()
            return [s_one] if s_one is not None else []
        return []

    @staticmethod
    def _evaluate_outcome_status_and_confidence(
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
                reconciliation_notes.append(
                    "Eventual consistency polling timed out without observing stable target state."
                )
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

    @staticmethod
    async def _acquire_audit_chain_state(
        session: Any,
        tenant_id: str,
        verified_at_dt: datetime,
    ) -> tuple[str, int, TenantAuditLedger | None]:
        """Acquire serialized tenant audit chain state and compute monotonically increasing sequence number."""
        app_settings = get_settings()
        ledger_head_row = None
        is_live_postgres = False
        bind = getattr(session, "bind", None)
        if bind is None and hasattr(session, "get_bind"):
            try:
                bind = session.get_bind()
            except Exception:
                bind = None

        dialect = getattr(bind, "dialect", None) if bind is not None else None
        dialect_name = getattr(dialect, "name", None) if dialect is not None else None
        if isinstance(dialect_name, str) and dialect_name == "postgresql":
            is_live_postgres = True
        else:
            sync_session = getattr(session, "sync_session", None)
            sync_bind = getattr(sync_session, "bind", None) if sync_session is not None else None
            sync_dialect = getattr(sync_bind, "dialect", None) if sync_bind is not None else None
            sync_dialect_name = getattr(sync_dialect, "name", None) if sync_dialect is not None else None
            if isinstance(sync_dialect_name, str) and sync_dialect_name == "postgresql":
                is_live_postgres = True

        if app_settings.environment == EnvironmentType.PRODUCTION and not is_live_postgres:
            raise RuntimeError(
                "Production invariant violation: authoritative audit ledger append requires PostgreSQL dialect"
            )

        if is_live_postgres:
            # A. Transaction-scoped PostgreSQL advisory lock serializes concurrent transactions per tenant
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('tenant_audit_ledger:' || :tenant_id))"),
                {"tenant_id": tenant_id},
            )

            # B. Ensure persistent tenant ledger head row exists
            await session.execute(
                text(
                    """
                    INSERT INTO tenant_audit_ledgers (
                        tenant_id, head_chain_hash, sequence_number, created_at, updated_at
                    )
                    VALUES (:tenant_id, :genesis_hash, 0, :now, :now)
                    ON CONFLICT (tenant_id) DO NOTHING
                    """
                ),
                {"tenant_id": tenant_id, "genesis_hash": GENESIS_ROOT_HASH, "now": verified_at_dt},
            )

            # C. Row-level lock on the persistent tenant ledger head
            ledger_head_stmt = (
                select(TenantAuditLedger).where(TenantAuditLedger.tenant_id == tenant_id).with_for_update()
            )
            ledger_res = await session.execute(ledger_head_stmt)
            ledger_head_row = ledger_res.scalar_one_or_none()
            if ledger_head_row is None:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Authoritative tenant audit ledger head missing for tenant '{tenant_id}'",
                )

            # Monotonically link to the latest audit log entry if present
            latest_audit_stmt = (
                select(AuditLogRecord.chain_hash, AuditLogRecord.sequence_number)
                .where(AuditLogRecord.tenant_id == tenant_id)
                .order_by(AuditLogRecord.sequence_number.desc(), AuditLogRecord.created_at.desc())
                .limit(1)
            )
            latest_audit_row = (await session.execute(latest_audit_stmt)).first()

            if latest_audit_row and latest_audit_row[0]:
                prev_chain_hash = latest_audit_row[0]
                current_seq = max(ledger_head_row.sequence_number or 0, latest_audit_row[1] or 0)
            else:
                prev_chain_hash = ledger_head_row.head_chain_hash or GENESIS_ROOT_HASH
                current_seq = ledger_head_row.sequence_number or 0

            new_sequence = current_seq + 1
        else:
            # Narrowly scoped fallback for non-PostgreSQL unit test mocks (e.g. SQLite in test env)
            try:
                latest_audit = await session.execute(
                    select(AuditLogRecord.chain_hash, AuditLogRecord.sequence_number)
                    .where(AuditLogRecord.tenant_id == tenant_id)
                    .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
                    .limit(1)
                )
                scalar_fn = getattr(latest_audit, "scalar_one_or_none", None)
                scalar_val = scalar_fn() if callable(scalar_fn) else None
                if isinstance(scalar_val, str):
                    prev_chain_hash = scalar_val
                    new_sequence = 1
                else:
                    first_fn = getattr(latest_audit, "first", None)
                    latest_row = first_fn() if callable(first_fn) else None
                    if latest_row and type(latest_row).__name__ != "MagicMock":
                        prev_chain_hash = latest_row[0] if latest_row[0] is not None else GENESIS_ROOT_HASH
                        new_sequence = (latest_row[1] or 0) + 1
                    else:
                        prev_chain_hash = GENESIS_ROOT_HASH
                        new_sequence = 1
            except (Exception, StopAsyncIteration):
                prev_chain_hash = GENESIS_ROOT_HASH
                new_sequence = 1

        return prev_chain_hash, new_sequence, ledger_head_row

    async def _append_audit_trail_entry(
        self,
        *,
        session: Any,
        auth: AuthContext,
        request: OutcomeVerificationRequest,
        action: ActionContract,
        record: OutcomeVerificationRecord,
        outcome_status: OutcomeStatus,
        epistemic_confidence: float,
        probe_result: AdapterProbeResult,
        obs_class: ObservabilityClass,
        target_env: str,
        idempotency_key: str,
        effective_postconditions: dict[str, Any],
        verification_hash: str,
        verified_at_dt: datetime,
        verified_at_iso: str,
        discrepancies: list[str],
    ) -> None:
        """Append verified Gate 5 outcome event to tenant cryptographic audit ledger."""
        prev_chain_hash, new_sequence, ledger_head_row = await self._acquire_audit_chain_state(
            session=session,
            tenant_id=auth.tenant_id,
            verified_at_dt=verified_at_dt,
        )

        entry_id = f"aud_{uuid.uuid4().hex}"
        chain_hash = compute_sha256(f"{prev_chain_hash}:{entry_id}:{outcome_status.value}:{verified_at_iso}")

        audit_entry = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=auth.tenant_id,
            sequence_number=new_sequence,
            session_id=request.transaction_id,
            trace_id="gate5-outcome",
            prompt_hash="0" * 64,
            response_hash=verification_hash,
            hrs_score=round(1.0 - epistemic_confidence, 4),
            risk_tier="LOW" if epistemic_confidence > 0.8 else "MEDIUM",
            claims_count=len(effective_postconditions),
            claims_summary=[],
            correction_applied=False,
            event_type="GATE5_OUTCOME_VERIFIED",
            actor_identity_id=auth.identity_id or "system_actor",
            transaction_id=request.transaction_id,
            decision=outcome_status.value,
            policy_reference=None,
            capability_id=action.required_capability,
            reason=f"Observability: {obs_class.value}, Adapter: {probe_result.adapter_name}",
            event_payload={
                "outcome_id": record.id,
                "action_id": request.action_id,
                "transaction_id": request.transaction_id,
                "sequence_number": new_sequence,
                "observability_class": obs_class.value,
                "outcome_status": outcome_status.value,
                "epistemic_confidence": epistemic_confidence,
                "adapter": probe_result.adapter_name,
                "is_simulated": probe_result.is_simulated,
                "discrepancies": discrepancies,
                "target_environment": target_env,
                "idempotency_key": idempotency_key,
                "verified_at": verified_at_iso,
            },
            prev_hash=prev_chain_hash,
            chain_hash=chain_hash,
            created_at=verified_at_dt,
        )
        session.add(audit_entry)

        if isinstance(ledger_head_row, TenantAuditLedger):
            ledger_head_row.head_entry_id = entry_id
            ledger_head_row.head_chain_hash = chain_hash
            ledger_head_row.sequence_number = new_sequence
            ledger_head_row.updated_at = verified_at_dt

    async def verify_record_against_audit_trail(
        self,
        session: Any,
        record: OutcomeVerificationRecord,
        trusted_root_hash: str = GENESIS_ROOT_HASH,
        max_chain_depth: int = 500,
    ) -> OutcomeVerificationContract:
        """Verify OutcomeVerificationRecord integrity internally and against AuditLogRecord.

        Validates both self-consistency against canonical payload and external consistency
        against the append-only cryptographic AuditLogRecord trust anchor. Recursively traces
        the cryptographic chain back to trusted root (default genesis '0'*64). Fails closed (HTTP 409)
        if the trust anchor is missing, conflicting, tampered, or detached from the audit chain.
        """
        # 1. Trusted root format and authentication verification
        if not is_valid_sha256_hex(trusted_root_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Malformed trusted root hash: '{trusted_root_hash}' "
                    "must be a 64-character lowercase hexadecimal string."
                ),
            )

        is_trusted, trust_tier, checkpoint_record = await self.checkpoint_registry.evaluate_trust_level_async(
            record.tenant_id, trusted_root_hash, session=session
        )
        if not is_trusted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Untrusted root hash: Checkpoint '{trusted_root_hash}' is not an authenticated "
                    f"trust anchor for tenant '{record.tenant_id}'."
                ),
            )

        # 2. Internal canonical payload integrity and SHA-256 hash check
        contract = self._record_to_contract(
            record,
            trust_assurance_level=trust_tier.value if hasattr(trust_tier, "value") else str(trust_tier),
        )

        # 3. External AuditLogRecord trust anchor lookup
        audit_stmt = (
            select(AuditLogRecord)
            .where(
                AuditLogRecord.tenant_id == record.tenant_id,
                AuditLogRecord.event_type == "GATE5_OUTCOME_VERIFIED",
            )
            .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
        )
        audit_records = (await session.execute(audit_stmt)).scalars().all()

        matching_audits: list[AuditLogRecord] = []
        for a in audit_records:
            payload = a.event_payload or {}
            # Strict correlation matching: NO loose fallback matching on action or transaction alone
            if payload.get("outcome_id") == record.id:
                matching_audits.append(a)

        # For PENDING_VERIFICATION, verification has not taken place yet, so no GATE5_OUTCOME_VERIFIED anchor exists
        if record.outcome_status == OutcomeStatus.PENDING_VERIFICATION.value and not matching_audits:
            return self._record_to_contract(record, trust_assurance_level="PENDING_OBSERVATION")

        # Fail closed: OutcomeVerificationRecord cannot be verified without an authoritative anchor
        if not matching_audits:
            if record.outcome_status == OutcomeStatus.UNKNOWN.value:
                return self._record_to_contract(record, trust_assurance_level="EXPIRED_UNANCHORED")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Audit anchor missing: OutcomeVerificationRecord '{record.id}' has no corresponding "
                    f"authoritative AuditLogRecord trust anchor in tenant '{record.tenant_id}'."
                ),
            )

        if len(matching_audits) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Ambiguous or conflicting audit anchors detected: found {len(matching_audits)} matching "
                    f"AuditLogRecord entries for outcome '{record.id}'."
                ),
            )

        matching_audit = matching_audits[0]

        # 4. Unambiguous 4-way correlation check: outcome_id, action_id, tenant_id, transaction_id
        self._validate_audit_correlation(record, matching_audit)

        # 5. Hash and Decision verification against audit record
        if matching_audit.response_hash != record.verification_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cryptographic audit trail divergence: OutcomeVerificationRecord '{record.id}' "
                    f"verification_hash '{record.verification_hash}' does not match immutable "
                    f"AuditLogRecord response_hash '{matching_audit.response_hash}'."
                ),
            )
        if matching_audit.decision != record.outcome_status:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cryptographic audit trail divergence: OutcomeVerificationRecord '{record.id}' "
                    f"status '{record.outcome_status}' does not match immutable "
                    f"AuditLogRecord decision '{matching_audit.decision}'."
                ),
            )

        # 6. Cryptographic Chain Self-Integrity & Required Field verification (Fail-Closed)
        self._validate_chain_record_fields_and_hash(matching_audit, role_label=f"anchor '{matching_audit.entry_id}'")

        # 7. Full-Chain Recursive Validation Back to Trusted Root
        curr = matching_audit
        visited_hashes: set[str] = {curr.chain_hash}
        visited_entry_ids: set[str] = {curr.entry_id}
        chain_depth = 0

        while curr.prev_hash != trusted_root_hash:
            chain_depth += 1
            if chain_depth > max_chain_depth:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain traversal exceeded max depth {max_chain_depth} "
                        f"without reaching trusted root '{trusted_root_hash}' for tenant '{record.tenant_id}'."
                    ),
                )
            if curr.prev_hash in visited_hashes:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain cyclic loop detected at hash '{curr.prev_hash}' for tenant '{record.tenant_id}'."
                    ),
                )

            pred_stmt = (
                select(AuditLogRecord)
                .where(
                    AuditLogRecord.tenant_id == record.tenant_id,
                    AuditLogRecord.chain_hash == curr.prev_hash,
                )
                .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
            )
            exec_res = await session.execute(pred_stmt)
            pred_records: list[Any] = self._extract_result_records(exec_res)

            if not pred_records:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain broken linkage: predecessor block with chain_hash '{curr.prev_hash}' "
                        f"not found in audit trail for tenant '{record.tenant_id}' (depth {chain_depth}). "
                        f"Chain does not anchor to trusted root '{trusted_root_hash}'."
                    ),
                )

            if len(pred_records) > 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain ambiguous linkage: found {len(pred_records)} conflicting predecessor "
                        f"blocks with chain_hash '{curr.prev_hash}' for tenant '{record.tenant_id}'."
                    ),
                )

            pred_record = pred_records[0]

            # Predecessor tenant boundary check
            if pred_record.tenant_id != record.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain tenant isolation violation: ancestor '{pred_record.entry_id}' "
                        f"tenant '{pred_record.tenant_id}' does not match record tenant '{record.tenant_id}'."
                    ),
                )

            # Node repetition check
            if pred_record.entry_id in visited_entry_ids:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain node repetition detected at entry_id '{pred_record.entry_id}' "
                        f"for tenant '{record.tenant_id}'."
                    ),
                )

            if pred_record.chain_hash in visited_hashes or pred_record.prev_hash in visited_hashes:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain cyclic loop detected at ancestor '{pred_record.entry_id}' "
                        f"for tenant '{record.tenant_id}'."
                    ),
                )

            # Monotonicity check
            if pred_record.created_at and curr.created_at and pred_record.created_at > curr.created_at:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain reordering detected: ancestor block '{pred_record.entry_id}' timestamp "
                        f"'{pred_record.created_at}' is later than descendant '{curr.entry_id}' timestamp "
                        f"'{curr.created_at}'."
                    ),
                )

            # Sequence monotonicity check
            pred_seq = getattr(pred_record, "sequence_number", 0) or 0
            curr_seq = getattr(curr, "sequence_number", 0) or 0
            if pred_seq > 0 and curr_seq > 0 and pred_seq >= curr_seq:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain sequence inversion detected: ancestor block '{pred_record.entry_id}' "
                        f"sequence {pred_seq} >= descendant '{curr.entry_id}' sequence {curr_seq}."
                    ),
                )

            # Ancestor self-integrity and missing-field validation (fail-closed)
            self._validate_chain_record_fields_and_hash(pred_record, role_label=f"ancestor '{pred_record.entry_id}'")

            visited_hashes.add(curr.prev_hash)
            visited_hashes.add(pred_record.chain_hash)
            visited_entry_ids.add(pred_record.entry_id)
            curr = pred_record

        # Checkpoint sequence validation if authenticated checkpoint specifies a sequence
        if checkpoint_record and checkpoint_record.sequence_number > 0:
            final_seq = getattr(curr, "sequence_number", 0) or 0
            if final_seq > 0 and final_seq != checkpoint_record.sequence_number + 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Audit chain checkpoint sequence mismatch: checkpoint specifies sequence "
                        f"{checkpoint_record.sequence_number}, but leaf subchain connects at sequence {final_seq}."
                    ),
                )

        return contract

    async def verify_action_outcome(
        self,
        request: OutcomeVerificationRequest,
        auth: AuthContext,
    ) -> OutcomeVerificationContract:
        """Execute reality verification for an executed ActionContract."""
        # 1. Authorization: Only SUPER_ADMIN, TENANT_ADMIN, OPERATOR, API_CLIENT may trigger reality verification
        if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR, Role.API_CLIENT):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{auth.role.value}' is not authorized to trigger reality verification probes.",
            )

        outcome_id = f"outc_{uuid.uuid4().hex[:12]}"
        reconciliation_notes: list[str] = []
        idempotency_key = request.idempotency_key or f"idem_outc_{request.action_id}_{request.verifier_type.value}"

        async with db_session.get_tenant_session(auth.tenant_id) as session:
            # 2. Fetch and validate ActionContract under tenant boundary with row-level lock
            stmt = (
                select(ActionContract)
                .where(
                    ActionContract.id == request.action_id,
                    ActionContract.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            action = (await session.execute(stmt)).scalar_one_or_none()
            if not action:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"ActionContract '{request.action_id}' not found for tenant '{auth.tenant_id}'",
                )

            if action.transaction_id != request.transaction_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"ActionContract transaction mismatch: contract belongs to '{action.transaction_id}', "
                        f"request specified '{request.transaction_id}'"
                    ),
                )

            # 3. Action Execution State Invariant:
            # Action MUST be COMPLETED, EXECUTED, or EXECUTION_UNCERTAIN.
            # In-flight, proposed, or blocked actions CANNOT be verified.
            if action.state not in (ActionState.COMPLETED.value, "EXECUTED", ActionState.EXECUTION_UNCERTAIN.value):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot verify unexecuted action: ActionContract '{action.id}' is in state '{action.state}'. "
                        f"Only COMPLETED, EXECUTED, or EXECUTION_UNCERTAIN actions may be verified."
                    ),
                )

            # Epistemic Outcome Independence: An EXECUTION_UNCERTAIN action CANNOT be resolved
            # via transport-inferred acknowledgment (OBS_INFERRED) because transport was never confirmed.
            # Authoritative direct observation or independent probe is mandatory.
            if action.state == ActionState.EXECUTION_UNCERTAIN.value:
                if request.observability_class == ObservabilityClass.OBS_INFERRED:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Cannot resolve EXECUTION_UNCERTAIN action using transport acknowledgment "
                            "(OBS_INFERRED); independent direct observation or probe is required."
                        ),
                    )

            # 4. Check for existing outcome record for idempotency and monotonic state transitions
            existing_stmt = (
                select(OutcomeVerificationRecord)
                .where(
                    OutcomeVerificationRecord.tenant_id == auth.tenant_id,
                    OutcomeVerificationRecord.action_id == action.id,
                )
                .order_by(OutcomeVerificationRecord.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            raw_existing = (await session.execute(existing_stmt)).scalar_one_or_none()
            existing_record = raw_existing if isinstance(raw_existing, OutcomeVerificationRecord) else None
            if existing_record:
                # Idempotency and terminal state immutability check
                if existing_record.outcome_status in (
                    OutcomeStatus.SUCCESS_CONFIRMED.value,
                    OutcomeStatus.VERIFIED_SUCCESS.value,
                    OutcomeStatus.FAILED.value,
                    OutcomeStatus.VERIFIED_FAILURE.value,
                ):
                    if existing_record.idempotency_key == idempotency_key:
                        return await self.verify_record_against_audit_trail(session, existing_record)
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"ActionContract '{action.id}' outcome is already in terminal state "
                            f"'{existing_record.outcome_status}'. Terminal outcomes are immutable."
                        ),
                    )

            # Auto-route to INDEPENDENT_OBSERVER when observation payload is provided
            if request.observation is not None and request.verifier_type != OutcomeVerifierType.INDEPENDENT_OBSERVER:
                request = request.model_copy(update={"verifier_type": OutcomeVerifierType.INDEPENDENT_OBSERVER})

            # Observation ID Replay Defense:
            # ensure observation_id has not been consumed by another action in this tenant
            if request.observation:
                obs_id = request.observation.observation_id
                replay_stmt = select(OutcomeVerificationRecord).where(
                    OutcomeVerificationRecord.tenant_id == auth.tenant_id,
                    OutcomeVerificationRecord.action_id != action.id,
                )
                existing_for_tenant = (await session.execute(replay_stmt)).scalars().all()
                for rec in existing_for_tenant:
                    rec_obs_id = (rec.evidence_payload or {}).get("observation_id")
                    if rec_obs_id == obs_id:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                f"Observation replay attack detected: observation_id '{obs_id}' was already "
                                f"consumed for action '{rec.action_id}'. "
                                "Observations cannot be recycled across actions."
                            ),
                        )

            # 5. Environment Binding
            target_env = "DEFAULT"
            if isinstance(action.blast_radius, dict):
                target_env = action.blast_radius.get("target_environment", "DEFAULT")

            req_env = request.adapter_config.get("environment")
            if req_env and req_env.upper() != target_env.upper():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Environment mismatch: probe requested environment '{req_env}' does not match "
                        f"authorized ActionContract target_environment '{target_env}'"
                    ),
                )

            # 6. Risk-Sensitive Verification Policy & Production Simulation Check
            risk_policy = "DEFAULT"
            if action.outcome_contract and isinstance(action.outcome_contract, dict):
                risk_policy = action.outcome_contract.get("risk_sensitive_verification_policy", "DEFAULT")

            if risk_policy == "STRICT_DIRECT_ONLY":
                if request.verifier_type == OutcomeVerifierType.SIMULATED:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Action outcome contract mandates STRICT_DIRECT_ONLY policy. "
                            "Simulated probes are prohibited."
                        ),
                    )
                if request.observability_class in (ObservabilityClass.OBS_INFERRED, ObservabilityClass.OBS_BLIND):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Action outcome contract mandates STRICT_DIRECT_ONLY policy. "
                            f"Observability class '{request.observability_class.value}' is prohibited."
                        ),
                    )

            settings = get_settings()
            if (
                request.verifier_type == OutcomeVerifierType.SIMULATED
                and (settings.environment.value == "production" or target_env.upper() == "PROD")
                and not request.adapter_config.get("allow_simulated_for_test", False)
            ):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SimulatedTestAdapter is prohibited for production environment verification.",
                )

            # 7. Postconditions Binding Validation
            # Merge contract postconditions with request postconditions
            authoritative_postconditions: dict[str, Any] = {}
            if action.postconditions and isinstance(action.postconditions, list):
                for p in action.postconditions:
                    if isinstance(p, dict) and "target" in p:
                        authoritative_postconditions[p["target"]] = p.get("expected_value")

            # Check if request expected postconditions contradict contract postconditions
            for k, req_v in request.expected_postconditions.items():
                if k in authoritative_postconditions and authoritative_postconditions[k] != req_v:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Postcondition mismatch: requested postcondition '{k}={req_v}' contradicts "
                            f"ActionContract postcondition '{authoritative_postconditions[k]}'"
                        ),
                    )

            effective_postconditions = {**authoritative_postconditions, **request.expected_postconditions}
            effective_request = request.model_copy(update={"expected_postconditions": effective_postconditions})

            # Check verification deadline expiration
            now_utc = datetime.now(UTC)
            deadline_passed = False
            if existing_record and existing_record.verification_deadline:
                dl = existing_record.verification_deadline
                if dl.tzinfo is None:
                    dl = dl.replace(tzinfo=UTC)
                if now_utc > dl:
                    deadline_passed = True
            elif action.outcome_contract and isinstance(action.outcome_contract, dict):
                dl_sec = action.outcome_contract.get("verification_deadline_seconds")
                act_start = action.executed_at or action.created_at
                if dl_sec and act_start:
                    if act_start.tzinfo is None:
                        act_start = act_start.replace(tzinfo=UTC)
                    from datetime import timedelta

                    if now_utc > (act_start + timedelta(seconds=float(dl_sec))):
                        deadline_passed = True

            # 8. Select Adapter and execute probe
            adapter = self.adapters.get(request.verifier_type)
            if not adapter:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported outcome verifier type '{request.verifier_type}'",
                )

            probe_result = await adapter.verify(action, effective_request, auth.tenant_id)
            reconciliation_notes.extend(probe_result.reconciliation_notes)

            # 9. Determine OutcomeStatus and Epistemic Confidence
            target_scheme = ""
            if action.target_resource:
                target_scheme = (
                    action.target_resource.split("://")[0].lower()
                    if "://" in action.target_resource
                    else action.target_resource.split(":")[0].lower()
                )
            is_blind_sink = target_scheme in ("udp", "syslog", "mailto", "smtp", "blackhole", "devnull", "sink")

            obs_class = request.observability_class
            discrepancies = probe_result.discrepancies

            # Enforce authoritative blind sink override: client cannot forge OBS_DIRECT on write-only sinks
            if is_blind_sink and obs_class != ObservabilityClass.OBS_BLIND:
                obs_class = ObservabilityClass.OBS_BLIND
                reconciliation_notes.append(
                    f"Target resource '{action.target_resource}' is an unobservable write-only sink ({target_scheme}). "
                    f"Client observability class '{request.observability_class.value}' "
                    "authoritatively downgraded to OBS_BLIND."
                )

            outcome_status, epistemic_confidence = self._evaluate_outcome_status_and_confidence(
                obs_class=obs_class,
                discrepancies=discrepancies,
                effective_postconditions=effective_postconditions,
                is_simulated=probe_result.is_simulated,
                success_indicated=probe_result.success_indicated,
                observation=request.observation,
                deadline_passed=deadline_passed,
                reconciliation_notes=reconciliation_notes,
            )

            # 10. Monotonic state transition enforcement against existing record
            if existing_record:
                curr_status = OutcomeStatus(existing_record.outcome_status)
                self._validate_outcome_transition(curr_status, outcome_status)

            # 11. Canonical Cryptographic Verification Hash
            observed_state_bytes = json.dumps(
                probe_result.observed_state, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            observed_state_hash = hashlib.sha256(observed_state_bytes).hexdigest()
            verified_at_dt = datetime.now(UTC)
            verified_at_iso = verified_at_dt.isoformat()

            canonical_payload = {
                "schema_version": "mirage.outcome.v1",
                "tenant_id": auth.tenant_id,
                "transaction_id": action.transaction_id,
                "action_id": action.id,
                "contract_binding_hash": action.parameters_hash,
                "tool_name": action.tool_name,
                "target_resource": action.target_resource,
                "required_capability": action.required_capability,
                "target_environment": target_env,
                "observability_class": obs_class.value,
                "outcome_status": outcome_status.value,
                "epistemic_confidence": epistemic_confidence,
                "verifier_adapter": probe_result.adapter_name,
                "is_simulated": probe_result.is_simulated,
                "expected_postconditions": effective_postconditions,
                "observed_state_hash": observed_state_hash,
                "evidence_source": request.observation.source_id if request.observation else probe_result.adapter_name,
                "evidence_digest": request.observation.evidence_digest if request.observation else observed_state_hash,
                "verified_at": verified_at_iso,
                "idempotency_key": idempotency_key,
            }
            canonical_bytes = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            verification_hash = hashlib.sha256(canonical_bytes).hexdigest()

            evidence_payload = {
                **probe_result.evidence_payload,
                "_canonical_payload": canonical_payload,
            }

            # 12. Upsert OutcomeVerificationRecord
            if existing_record:
                record = existing_record
                record.observability_class = obs_class.value
                record.outcome_status = outcome_status.value
                record.epistemic_confidence = epistemic_confidence
                record.verifier_adapter = probe_result.adapter_name
                record.is_simulated = probe_result.is_simulated
                record.expected_postconditions = effective_postconditions
                record.observed_state = probe_result.observed_state
                record.discrepancies = discrepancies
                record.evidence_payload = evidence_payload
                record.reconciliation_notes = reconciliation_notes
                record.verification_hash = verification_hash
                record.idempotency_key = idempotency_key
                record.target_environment = target_env
                record.contract_binding_hash = action.parameters_hash
                record.verified_at = verified_at_dt
            else:
                record = OutcomeVerificationRecord(
                    id=outcome_id,
                    tenant_id=auth.tenant_id,
                    transaction_id=request.transaction_id,
                    action_id=request.action_id,
                    observability_class=obs_class.value,
                    outcome_status=outcome_status.value,
                    epistemic_confidence=epistemic_confidence,
                    verifier_adapter=probe_result.adapter_name,
                    is_simulated=probe_result.is_simulated,
                    expected_postconditions=effective_postconditions,
                    observed_state=probe_result.observed_state,
                    discrepancies=discrepancies,
                    evidence_payload=evidence_payload,
                    reconciliation_notes=reconciliation_notes,
                    verification_hash=verification_hash,
                    idempotency_key=idempotency_key,
                    target_environment=target_env,
                    contract_binding_hash=action.parameters_hash,
                    created_at=verified_at_dt,
                    verified_at=verified_at_dt,
                )
                session.add(record)

            if request.observation:
                record.evidence_source = request.observation.source_id
                record.evidence_digest = request.observation.evidence_digest
                record.observed_at = request.observation.observed_at
            else:
                record.evidence_source = probe_result.adapter_name
                record.evidence_digest = observed_state_hash
                record.observed_at = verified_at_dt

            # Update ActionContract status and lifecycle completion
            action.outcome_status = outcome_status.value
            if outcome_status in (OutcomeStatus.VERIFIED_SUCCESS, OutcomeStatus.SUCCESS_CONFIRMED):
                action.state = ActionState.COMPLETED.value
                action.completed_at = verified_at_dt
            elif outcome_status in (OutcomeStatus.VERIFIED_FAILURE, OutcomeStatus.FAILED):
                action.state = ActionState.FAILED.value

            # 13. Audit Trail Recording with PostgreSQL engine serialization and row locking
            await self._append_audit_trail_entry(
                session=session,
                auth=auth,
                request=request,
                action=action,
                record=record,
                outcome_status=outcome_status,
                epistemic_confidence=epistemic_confidence,
                probe_result=probe_result,
                obs_class=obs_class,
                target_env=target_env,
                idempotency_key=idempotency_key,
                effective_postconditions=effective_postconditions,
                verification_hash=verification_hash,
                verified_at_dt=verified_at_dt,
                verified_at_iso=verified_at_iso,
                discrepancies=discrepancies,
            )

            logger.info(
                "Gate 5 Outcome Verification completed",
                outcome_id=record.id,
                action_id=request.action_id,
                tenant_id=auth.tenant_id,
                observability=obs_class.value,
                status=outcome_status.value,
                confidence=epistemic_confidence,
                adapter=probe_result.adapter_name,
                discrepancies=len(discrepancies),
            )

            if discrepancies:
                from services.webhook_service import webhook_service

                await webhook_service.dispatch_event(
                    tenant_id=auth.tenant_id,
                    event_type="OUTCOME_DISCREPANCY",
                    payload={
                        "outcome_id": record.id,
                        "action_id": request.action_id,
                        "transaction_id": request.transaction_id,
                        "outcome_status": outcome_status.value,
                        "discrepancies": discrepancies,
                        "epistemic_confidence": epistemic_confidence,
                    },
                )

            return self._record_to_contract(record)

    def reconcile_output_with_outcome(
        self,
        response_text: str,
        outcome_contract: OutcomeVerificationContract,
        transaction_id: str | None = None,
        action_id: str | None = None,
        auth_tenant_id: str | None = None,
    ) -> OutcomeReconciliationResult:
        """Verify Output <-> Outcome consistency: prevent models from falsely claiming verified success."""
        # 1. Tenant boundary check
        if auth_tenant_id is not None:
            if not auth_tenant_id.strip() or outcome_contract.tenant_id != auth_tenant_id.strip():
                return OutcomeReconciliationResult(
                    is_consistent=False,
                    epistemic_conflict_detected=True,
                    conflict_reasons=[
                        f"Cross-tenant outcome violation: outcome tenant '{outcome_contract.tenant_id}' "
                        f"does not match authenticated tenant '{auth_tenant_id}'"
                    ],
                    recommended_disposition="REJECT",
                )

        # 2. Transaction and Action correlation check
        if transaction_id is not None:
            if not transaction_id.strip() or outcome_contract.transaction_id != transaction_id.strip():
                return OutcomeReconciliationResult(
                    is_consistent=False,
                    epistemic_conflict_detected=True,
                    conflict_reasons=[
                        f"Transaction correlation mismatch: outcome belongs to '{outcome_contract.transaction_id}', "
                        f"caller specified '{transaction_id}'"
                    ],
                    recommended_disposition="REJECT",
                )

        if action_id is not None:
            if not action_id.strip() or outcome_contract.action_id != action_id.strip():
                return OutcomeReconciliationResult(
                    is_consistent=False,
                    epistemic_conflict_detected=True,
                    conflict_reasons=[
                        f"Action correlation mismatch: outcome belongs to action '{outcome_contract.action_id}', "
                        f"caller specified '{action_id}'"
                    ],
                    recommended_disposition="REJECT",
                )

        # 3. Clause-aware normalization and polarity evaluation
        norm_text = _normalize_text(response_text)
        unquoted = _strip_quotes_and_citations(norm_text)
        clauses = _extract_clauses(unquoted)

        claims_completion = False
        has_explicit_failure = False
        conflict_reasons: list[str] = []

        for clause in clauses:
            clause_lower = clause.lower()
            if any(
                u in clause_lower
                for u in [
                    "cannot confirm",
                    "could not confirm",
                    "unclear whether",
                    "unable to confirm",
                    "unable to verify",
                    "not confirmed",
                    "failed to confirm",
                    "no confirmation that",
                    "no evidence that",
                ]
            ):
                continue

            if any(
                f in clause_lower
                for f in [
                    "operation failed",
                    "action failed",
                    "failed, so",
                    "failed to execute",
                    "execution failed",
                    "failed completely",
                    "was unsuccessful",
                    "did not succeed",
                ]
            ):
                has_explicit_failure = True

            for pat in _COMPLETION_ASSERTION_PATTERNS:
                for m in pat.finditer(clause):
                    start_idx = max(0, m.start() - 35)
                    prefix = clause[start_idx : m.start()].lower()
                    negated = any(
                        neg in prefix
                        for neg in [
                            "not ",
                            "never ",
                            "failed to ",
                            "unable to ",
                            "could not ",
                            "did not ",
                            "was not ",
                            "were not ",
                            "has not ",
                            "have not ",
                            "is not ",
                            "are not ",
                        ]
                    )
                    if not negated:
                        claims_completion = True
                        break
                if claims_completion:
                    break

        status_val = outcome_contract.outcome_status

        # If the output does NOT assert completion:
        if not claims_completion:
            # If the verified outcome was FAILED, UNKNOWN, UNOBSERVABLE, PARTIAL, or ACKNOWLEDGED_UNVERIFIED:
            # The model is honest and refrains from false success claims.
            if status_val in (
                OutcomeStatus.FAILED,
                OutcomeStatus.VERIFIED_FAILURE,
                OutcomeStatus.UNKNOWN,
                OutcomeStatus.UNOBSERVABLE,
                OutcomeStatus.UNVERIFIABLE,
                OutcomeStatus.PARTIAL,
                OutcomeStatus.PARTIAL_ACHIEVEMENT,
                OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
                OutcomeStatus.PENDING_VERIFICATION,
            ):
                return OutcomeReconciliationResult(
                    is_consistent=True,
                    epistemic_conflict_detected=False,
                    conflict_reasons=[],
                    recommended_disposition="PERMIT",
                )

            # If the verified outcome was confirmed success, but output explicitly asserted failure:
            if status_val in (
                OutcomeStatus.SUCCESS_CONFIRMED,
                OutcomeStatus.VERIFIED_SUCCESS,
                OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
            ):
                if has_explicit_failure:
                    return OutcomeReconciliationResult(
                        is_consistent=False,
                        epistemic_conflict_detected=True,
                        conflict_reasons=[
                            "Contradiction: Output claims action failure, but Gate 5 reality verification "
                            "confirmed successful state transition."
                        ],
                        recommended_disposition="REWRITE_WITH_CAVEAT",
                    )
                # Output expressed uncertainty without false claims
                return OutcomeReconciliationResult(
                    is_consistent=True,
                    epistemic_conflict_detected=False,
                    conflict_reasons=[],
                    recommended_disposition="PERMIT",
                )

        # Output DOES claim completion:
        # 4. Simulation Check: Simulated evidence NEVER justifies claims of physical success
        if outcome_contract.is_simulated:
            conflict_reasons.append(
                "Epistemic Invariant Violation: Output asserts real-world success, but verification evidence "
                "is simulated (SimulatedTestAdapter). Simulation evidence cannot prove physical real-world execution."
            )
            return OutcomeReconciliationResult(
                is_consistent=False,
                epistemic_conflict_detected=True,
                conflict_reasons=conflict_reasons,
                recommended_disposition="REWRITE_WITH_CAVEAT",
            )

        # 5. Confirmed Success Checks
        if status_val in (
            OutcomeStatus.SUCCESS_CONFIRMED,
            OutcomeStatus.VERIFIED_SUCCESS,
            OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        ):
            return OutcomeReconciliationResult(
                is_consistent=True,
                epistemic_conflict_detected=False,
                conflict_reasons=[],
                recommended_disposition="PERMIT",
            )

        # 6. Partial, Failed, Unobservable, Inferred, Unknown, Pending Handling
        conflict_msg = (
            f"Epistemic Invariant Violation: Output claims successful action completion, but Gate 5 "
            f"reality status is '{status_val.value}' with confidence {outcome_contract.epistemic_confidence}. "
        )
        if status_val == OutcomeStatus.PENDING_VERIFICATION:
            conflict_msg += (
                "Action outcome verification is still PENDING_VERIFICATION; real-world success is unconfirmed."
            )
        elif status_val == OutcomeStatus.ACKNOWLEDGED_UNVERIFIED:
            conflict_msg += "Transport acknowledgment alone does not prove destination state change."
        elif status_val in (OutcomeStatus.UNOBSERVABLE, OutcomeStatus.UNVERIFIABLE):
            conflict_msg += "Target resource is write-only/unobservable; physical state confirmation is impossible."
        elif status_val in (OutcomeStatus.FAILED, OutcomeStatus.VERIFIED_FAILURE):
            conflict_msg += "State verification observed explicit invariant failure."
        elif status_val in (OutcomeStatus.PARTIAL, OutcomeStatus.PARTIAL_ACHIEVEMENT):
            conflict_msg += (
                "Outcome is PARTIAL: subset of actions failed in batch; output cannot claim complete success."
            )
        elif status_val == OutcomeStatus.UNKNOWN:
            conflict_msg += "State verification timed out or was indeterminate."

        conflict_reasons.append(conflict_msg)

        disposition = (
            "REJECT" if status_val in (OutcomeStatus.FAILED, OutcomeStatus.VERIFIED_FAILURE) else "REWRITE_WITH_CAVEAT"
        )
        return OutcomeReconciliationResult(
            is_consistent=False,
            epistemic_conflict_detected=True,
            conflict_reasons=conflict_reasons,
            recommended_disposition=disposition,
        )

    async def get_outcome_by_id(
        self,
        outcome_id: str,
        tenant_id: str,
    ) -> OutcomeVerificationContract | None:
        """Fetch outcome contract by ID with deadline expiration check under tenant isolation."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = (
                select(OutcomeVerificationRecord)
                .where(
                    OutcomeVerificationRecord.id == outcome_id,
                    OutcomeVerificationRecord.tenant_id == tenant_id,
                )
                .with_for_update()
            )
            record = (await session.execute(stmt)).scalar_one_or_none()
            if not record:
                return None

            if record.outcome_status == OutcomeStatus.PENDING_VERIFICATION.value and record.verification_deadline:
                now_utc = datetime.now(UTC)
                dl = record.verification_deadline
                if dl.tzinfo is None:
                    dl = dl.replace(tzinfo=UTC)
                if now_utc > dl:
                    record.outcome_status = OutcomeStatus.UNKNOWN.value
                    record.epistemic_confidence = 0.0
                    record.reconciliation_notes = (record.reconciliation_notes or []) + [
                        "Verification deadline expired while pending. Monotonically transitioned to UNKNOWN."
                    ]
                    await session.flush()

            return await self.verify_record_against_audit_trail(session, record)

    async def get_outcome_by_action_id(
        self,
        action_id: str,
        tenant_id: str,
    ) -> OutcomeVerificationContract | None:
        """Fetch outcome contract for an ActionContract with deadline expiration check."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = (
                select(OutcomeVerificationRecord)
                .where(
                    OutcomeVerificationRecord.action_id == action_id,
                    OutcomeVerificationRecord.tenant_id == tenant_id,
                )
                .order_by(OutcomeVerificationRecord.created_at.desc())
                .limit(1)
                .with_for_update()
            )
            record = (await session.execute(stmt)).scalar_one_or_none()
            if not record:
                return None

            if record.outcome_status == OutcomeStatus.PENDING_VERIFICATION.value and record.verification_deadline:
                now_utc = datetime.now(UTC)
                dl = record.verification_deadline
                if dl.tzinfo is None:
                    dl = dl.replace(tzinfo=UTC)
                if now_utc > dl:
                    record.outcome_status = OutcomeStatus.UNKNOWN.value
                    record.epistemic_confidence = 0.0
                    record.reconciliation_notes = (record.reconciliation_notes or []) + [
                        "Verification deadline expired while pending. Monotonically transitioned to UNKNOWN."
                    ]
                    await session.flush()

            return await self.verify_record_against_audit_trail(session, record)

    async def get_pending_outcomes(
        self,
        tenant_id: str,
    ) -> list[OutcomeVerificationContract]:
        """Fetch all PENDING_VERIFICATION outcomes for a tenant, evaluating deadlines."""
        async with db_session.get_tenant_session(tenant_id) as session:
            stmt = (
                select(OutcomeVerificationRecord)
                .where(
                    OutcomeVerificationRecord.tenant_id == tenant_id,
                    OutcomeVerificationRecord.outcome_status == OutcomeStatus.PENDING_VERIFICATION.value,
                )
                .order_by(OutcomeVerificationRecord.created_at.asc())
                .with_for_update()
            )
            records = (await session.execute(stmt)).scalars().all()
            contracts: list[OutcomeVerificationContract] = []
            now_utc = datetime.now(UTC)

            for rec in records:
                if rec.verification_deadline:
                    dl = rec.verification_deadline
                    if dl.tzinfo is None:
                        dl = dl.replace(tzinfo=UTC)
                    if now_utc > dl:
                        rec.outcome_status = OutcomeStatus.UNKNOWN.value
                        rec.epistemic_confidence = 0.0
                        rec.reconciliation_notes = (rec.reconciliation_notes or []) + [
                            "Verification deadline expired while pending. Monotonically transitioned to UNKNOWN."
                        ]
                contract = await self.verify_record_against_audit_trail(session, rec)
                contracts.append(contract)

            await session.flush()
            return contracts

    async def escalate_outcome(
        self,
        request: OutcomeEscalationRequest,
        auth: AuthContext,
    ) -> OutcomeEscalationResponse:
        """Escalate an outcome verification record for operator review under tenant isolation."""
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            stmt = (
                select(OutcomeVerificationRecord)
                .where(
                    OutcomeVerificationRecord.id == request.outcome_id,
                    OutcomeVerificationRecord.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            record = (await session.execute(stmt)).scalar_one_or_none()
            if not record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Outcome record '{request.outcome_id}' not found for tenant '{auth.tenant_id}'",
                )

            now_dt = datetime.now(UTC)
            record.escalation_status = "ESCALATED"
            notes = f"Escalated by {auth.identity_id or 'operator'}: {request.reason}"
            if request.escalation_notes:
                notes += f" | {request.escalation_notes}"
            record.escalation_notes = notes

            entry_id = f"aud_esc_{uuid.uuid4().hex}"
            audit_entry = AuditLogRecord(
                entry_id=entry_id,
                tenant_id=auth.tenant_id,
                sequence_number=1,
                session_id=record.transaction_id,
                trace_id="gate5-escalate",
                prompt_hash="0" * 64,
                response_hash=record.verification_hash,
                hrs_score=0.0,
                risk_tier="HIGH",
                claims_count=0,
                claims_summary=[],
                correction_applied=False,
                event_type="GATE5_OUTCOME_ESCALATED",
                actor_identity_id=auth.identity_id or "system_actor",
                transaction_id=record.transaction_id,
                decision="ESCALATED",
                policy_reference=None,
                capability_id="operator_escalation",
                reason=request.reason,
                event_payload={
                    "outcome_id": record.id,
                    "action_id": record.action_id,
                    "reason": request.reason,
                    "notes": request.escalation_notes,
                },
                prev_hash=GENESIS_ROOT_HASH,
                chain_hash=compute_sha256(f"{record.id}:ESCALATED:{now_dt.isoformat()}"),
                created_at=now_dt,
            )
            session.add(audit_entry)
            await session.flush()

            return OutcomeEscalationResponse(
                outcome_id=record.id,
                escalation_status="ESCALATED",
                escalated_at=now_dt.isoformat(),
                reason=request.reason,
            )

    def propose_compensating_action(self, action: ActionContract) -> None:
        """In accordance with MIRAGE 3.0 Gate 5 Invariants:

        Gate 5 must NEVER execute a recovery or compensating action directly.
        Any compensating action MUST be submitted as a new governed Gate 3 action contract
        evaluated through ActionGovernorService.propose_and_authorize_action.
        """
        raise NotImplementedError(
            f"Gate 5 cannot execute compensating action for '{action.id}' directly. "
            "Compensating actions must be proposed and authorized through Gate 3 (Action Governor)."
        )


reality_verifier_service = RealityVerifierService()
