"""Gate 5 Outcome Assurance and Reality Verification Service for MIRAGE 3.0.

Implements Reality_Verification.md, Input_Output_Assurance.md §6, and AI_Action_Contract.md.
Confirms actual real-world state changes, enforcing epistemic observability boundaries,
monotonic outcome state transitions, cryptographic ActionContract binding, and SSRF defenses.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from db import session as db_session
from db.models import (
    ActionContract,
    AuditLogRecord,
    OutcomeVerificationRecord,
    TenantAuditLedger,
)
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas.action import ActionState
from shared.schemas.audit import (
    GENESIS_ROOT_HASH,
    TrustedCheckpointRegistry,
    compute_sha256,
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
from .audit_verifier import (
    acquire_audit_chain_state,
    append_audit_trail_entry,
    extract_result_records,
    validate_audit_correlation,
    validate_chain_record_fields_and_hash,
    verify_record_against_audit_trail,
)
from .evaluator import (
    evaluate_outcome_status_and_confidence,
    record_to_contract,
    validate_outcome_transition,
)
from .reconciliation import (
    reconcile_output_with_outcome,
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
        validate_outcome_transition(current_status, new_status)

    def _record_to_contract(
        self,
        record: OutcomeVerificationRecord,
        trust_assurance_level: str = "GENESIS_SENTINEL",
    ) -> OutcomeVerificationContract:
        """Convert an authoritative database record to an immutable OutcomeVerificationContract."""
        return record_to_contract(record, trust_assurance_level=trust_assurance_level)

    def _validate_chain_record_fields_and_hash(
        self,
        audit_record: AuditLogRecord,
        role_label: str = "record",
    ) -> str:
        """Validate all required cryptographic fields, format, types, and self-integrity."""
        return validate_chain_record_fields_and_hash(audit_record, role_label=role_label)

    @staticmethod
    def _validate_audit_correlation(record: OutcomeVerificationRecord, matching_audit: AuditLogRecord) -> None:
        """Enforce unambiguous 4-way correlation check between OutcomeVerificationRecord and AuditLogRecord."""
        validate_audit_correlation(record, matching_audit)

    @staticmethod
    def _extract_result_records(exec_res: Any) -> list[Any]:
        """Safely extract result records across live SQLAlchemy execution and test mock objects."""
        return extract_result_records(exec_res)

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
        """Compute authoritative Gate 5 OutcomeStatus and epistemic confidence."""
        return evaluate_outcome_status_and_confidence(
            obs_class=obs_class,
            discrepancies=discrepancies,
            effective_postconditions=effective_postconditions,
            is_simulated=is_simulated,
            success_indicated=success_indicated,
            observation=observation,
            deadline_passed=deadline_passed,
            reconciliation_notes=reconciliation_notes,
        )

    @staticmethod
    async def _acquire_audit_chain_state(
        session: Any,
        tenant_id: str,
        verified_at_dt: datetime,
    ) -> tuple[str, int, TenantAuditLedger | None]:
        """Acquire serialized tenant audit chain state and compute monotonically increasing sequence number."""
        return await acquire_audit_chain_state(session, tenant_id, verified_at_dt)

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
        await append_audit_trail_entry(
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

    async def verify_record_against_audit_trail(
        self,
        session: Any,
        record: OutcomeVerificationRecord,
        trusted_root_hash: str = GENESIS_ROOT_HASH,
        max_chain_depth: int = 500,
    ) -> OutcomeVerificationContract:
        """Verify OutcomeVerificationRecord integrity internally and against AuditLogRecord."""
        return await verify_record_against_audit_trail(
            session=session,
            record=record,
            checkpoint_registry=self.checkpoint_registry,
            trusted_root_hash=trusted_root_hash,
            max_chain_depth=max_chain_depth,
        )

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
        return reconcile_output_with_outcome(
            response_text=response_text,
            outcome_contract=outcome_contract,
            transaction_id=transaction_id,
            action_id=action_id,
            auth_tenant_id=auth_tenant_id,
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
