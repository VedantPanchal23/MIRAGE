"""Phase 8 Hierarchical Outcome Assurance and Aggregation Service for MIRAGE.

Implements cross-agent hierarchical outcome assurance evaluating parent and child agent
executions, integrating Gate 5 Reality Verifier, agent handoffs, delegation governance,
and audit trails.

Enforces core MIRAGE principles:
- Child tool execution completion is distinct from independently verified outcome completion.
- A parent transaction cannot be finalized as successfully completed while required child
  work remains pending, executing, failed, cancelled, expired, or awaiting outcome verification.
- Late child observations cannot silently reverse committed terminal results.
- Epistemic observability boundaries are strictly preserved; unverified actions cannot
  claim successful completion.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    ActionContract,
    AgentHandoff,
    AITransaction,
    AuditLogRecord,
    OutcomeVerificationRecord,
)
from db.session import get_tenant_session
from shared.logging import get_logger
from shared.schemas.action import ActionState
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext
from shared.schemas.handoff import HandoffStatus
from shared.schemas.hierarchical_outcome import (
    ActionOutcomeSummary,
    ChildExecutionSummary,
    HandoffSummary,
    HierarchicalOutcomeResponse,
    HierarchicalOutcomeStatus,
    compute_hierarchical_evaluation_hash,
)
from shared.schemas.outcome import OutcomeStatus

logger = get_logger("hierarchical_outcome_service")

_TERMINAL_TRANSACTION_STATES = {
    "COMPLETED",
    "FAILED",
    "BLOCKED",
    "CANCELLED",
    "TIMEOUT",
    "PARTIAL",
    "TERMINATED",
}

_VERIFIED_SUCCESS_OUTCOMES = {
    OutcomeStatus.VERIFIED_SUCCESS.value,
    OutcomeStatus.SUCCESS_CONFIRMED.value,
    OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED.value,
}

_FAILED_OUTCOMES = {
    OutcomeStatus.VERIFIED_FAILURE.value,
    OutcomeStatus.FAILED.value,
}

_UNVERIFIABLE_OUTCOMES = {
    OutcomeStatus.UNVERIFIABLE.value,
    OutcomeStatus.UNOBSERVABLE.value,
}


class HierarchicalOutcomeService:
    """Authoritative management service for hierarchical parent-child outcome assurance."""

    async def aggregate_transaction_outcome(
        self,
        auth: AuthContext,
        transaction_id: str,
        session: AsyncSession | None = None,
    ) -> HierarchicalOutcomeResponse:
        """Aggregates and evaluates hierarchical outcome status across a transaction lineage."""

        async def _execute(s: AsyncSession) -> HierarchicalOutcomeResponse:
            # 1. Fetch parent transaction under tenant boundary
            parent_stmt = select(AITransaction).where(
                AITransaction.id == transaction_id,
                AITransaction.tenant_id == auth.tenant_id,
            )
            parent_res = await s.execute(parent_stmt)
            parent_txn = parent_res.scalar_one_or_none()
            if not parent_txn:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Transaction '{transaction_id}' not found in tenant '{auth.tenant_id}'",
                )

            # 2. Recursively gather all descendant child transactions
            all_child_txns: list[AITransaction] = []
            frontier = [parent_txn.id]
            visited = {parent_txn.id}

            while frontier:
                child_stmt = select(AITransaction).where(
                    AITransaction.parent_transaction_id.in_(frontier),
                    AITransaction.tenant_id == auth.tenant_id,
                )
                child_res = await s.execute(child_stmt)
                children = child_res.scalars().all()
                next_frontier: list[str] = []
                for child in children:
                    if child.id not in visited:
                        visited.add(child.id)
                        all_child_txns.append(child)
                        next_frontier.append(child.id)
                frontier = next_frontier

            all_txn_ids = [parent_txn.id] + [c.id for c in all_child_txns]

            # 3. Fetch all handoffs associated with the transaction hierarchy
            handoff_stmt = (
                select(AgentHandoff)
                .where(
                    AgentHandoff.parent_transaction_id.in_(all_txn_ids),
                    AgentHandoff.tenant_id == auth.tenant_id,
                )
                .order_by(AgentHandoff.created_at.asc())
            )
            handoff_res = await s.execute(handoff_stmt)
            all_handoffs = handoff_res.scalars().all()

            # 4. Fetch all action contracts for all transactions in lineage
            action_stmt = (
                select(ActionContract)
                .where(
                    ActionContract.transaction_id.in_(all_txn_ids),
                    ActionContract.tenant_id == auth.tenant_id,
                )
                .order_by(ActionContract.created_at.asc())
            )
            action_res = await s.execute(action_stmt)
            all_actions = action_res.scalars().all()

            # 5. Fetch all Gate 5 outcome records for these actions
            all_action_ids = [a.id for a in all_actions]
            outcomes_by_action_id: dict[str, OutcomeVerificationRecord] = {}
            if all_action_ids:
                outcome_stmt = select(OutcomeVerificationRecord).where(
                    OutcomeVerificationRecord.action_id.in_(all_action_ids),
                    OutcomeVerificationRecord.tenant_id == auth.tenant_id,
                )
                outcome_res = await s.execute(outcome_stmt)
                for rec in outcome_res.scalars().all():
                    outcomes_by_action_id[rec.action_id] = rec

            # 6. Map parent direct actions
            parent_action_summaries: list[ActionOutcomeSummary] = []
            for act in all_actions:
                if act.transaction_id == parent_txn.id:
                    summary = self._build_action_summary(act, outcomes_by_action_id.get(act.id))
                    parent_action_summaries.append(summary)

            # 7. Group and map child transaction summaries
            child_executions: list[ChildExecutionSummary] = []
            for child in all_child_txns:
                child_acts = [a for a in all_actions if a.transaction_id == child.id]
                child_summaries = [self._build_action_summary(a, outcomes_by_action_id.get(a.id)) for a in child_acts]

                # Determine execution completion vs outcome verification
                exec_completed = child.state in _TERMINAL_TRANSACTION_STATES or child.final_disposition is not None

                total_acts = len(child_summaries)
                verified_success_acts = sum(
                    1 for a in child_summaries if a.outcome_status in _VERIFIED_SUCCESS_OUTCOMES
                )
                pending_verif_acts = sum(
                    1
                    for a in child_summaries
                    if (
                        a.requires_outcome_assurance
                        and (a.outcome_status == OutcomeStatus.PENDING_VERIFICATION.value or a.outcome_status is None)
                        and a.action_state not in (ActionState.BLOCKED.value, ActionState.PROPOSED.value)
                    )
                )
                failed_acts = sum(
                    1
                    for a in child_summaries
                    if (a.outcome_status in _FAILED_OUTCOMES or a.action_state == ActionState.FAILED.value)
                )
                unverifiable_acts = sum(1 for a in child_summaries if a.outcome_status in _UNVERIFIABLE_OUTCOMES)

                # Outcomes are verified ONLY if all actions requiring outcome assurance are verified success
                req_assurance_count = sum(1 for a in child_summaries if a.requires_outcome_assurance)
                if req_assurance_count > 0:
                    outcomes_verified = verified_success_acts == req_assurance_count and failed_acts == 0
                else:
                    outcomes_verified = exec_completed and (
                        child.final_disposition == "COMPLETED" or child.state == "COMPLETED"
                    )

                child_executions.append(
                    ChildExecutionSummary(
                        child_transaction_id=child.id,
                        parent_transaction_id=child.parent_transaction_id or parent_txn.id,
                        agent_id=child.agent_id,
                        state=child.state,
                        final_disposition=child.final_disposition,
                        execution_completed=exec_completed,
                        outcomes_verified=outcomes_verified,
                        total_actions=total_acts,
                        verified_success_actions=verified_success_acts,
                        pending_verification_actions=pending_verif_acts,
                        failed_actions=failed_acts,
                        unverifiable_actions=unverifiable_acts,
                        action_summaries=child_summaries,
                    )
                )

            # 8. Map handoffs
            handoff_summaries = [
                HandoffSummary(
                    handoff_id=h.id,
                    parent_transaction_id=h.parent_transaction_id,
                    parent_agent_id=h.parent_agent_id,
                    child_agent_id=h.child_agent_id,
                    delegation_id=h.delegation_id,
                    child_transaction_id=h.child_transaction_id,
                    status=h.status,
                    purpose=h.purpose,
                    expires_at=h.expires_at,
                    accepted_at=h.accepted_at,
                    completed_at=h.completed_at,
                    cancelled_at=h.cancelled_at,
                )
                for h in all_handoffs
            ]

            # 9. Perform hierarchical state machine evaluation
            is_parent_terminal = (
                parent_txn.state in _TERMINAL_TRANSACTION_STATES or parent_txn.final_disposition is not None
            )

            discrepancies: list[str] = []
            reconciliation_notes: list[str] = []

            hierarchical_status, ep_confidence = self._evaluate_hierarchical_status(
                parent_txn=parent_txn,
                parent_actions=parent_action_summaries,
                child_executions=child_executions,
                handoffs=handoff_summaries,
                discrepancies=discrepancies,
                reconciliation_notes=reconciliation_notes,
            )

            # 10. Late-observation / Terminal Protection Defense
            if is_parent_terminal:
                # Check for late arrivals or divergent child outcomes
                if (
                    parent_txn.final_disposition == "COMPLETED"
                    and hierarchical_status != HierarchicalOutcomeStatus.VERIFIED_SUCCESS
                ):
                    discrepancies.append(
                        f"Terminal discrepancy: parent transaction committed with disposition 'COMPLETED', "
                        f"but hierarchical evaluation resolved to '{hierarchical_status.value}'."
                    )
                    reconciliation_notes.append(
                        "Parent transaction terminal status is immutable; late child observation discrepancy "
                        "recorded for audit without retroactive mutation."
                    )
                    await self._emit_audit_event(
                        session=s,
                        tenant_id=auth.tenant_id,
                        action="HIERARCHICAL_LATE_OBSERVATION_RECORDED",
                        details={
                            "parent_transaction_id": parent_txn.id,
                            "parent_disposition": parent_txn.final_disposition,
                            "evaluated_status": hierarchical_status.value,
                            "discrepancies": discrepancies,
                        },
                    )

            now = datetime.now(UTC)
            evaluation_hash = compute_hierarchical_evaluation_hash(
                parent_transaction_id=parent_txn.id,
                tenant_id=auth.tenant_id,
                hierarchical_status=hierarchical_status.value,
                epistemic_confidence=ep_confidence,
                child_count=len(child_executions),
                handoff_count=len(handoff_summaries),
                timestamp_iso=now.isoformat(),
            )

            # Record standard evaluation audit
            await self._emit_audit_event(
                session=s,
                tenant_id=auth.tenant_id,
                action="HIERARCHICAL_OUTCOME_EVALUATED",
                details={
                    "parent_transaction_id": parent_txn.id,
                    "hierarchical_status": hierarchical_status.value,
                    "epistemic_confidence": ep_confidence,
                    "total_child_transactions": len(child_executions),
                    "total_handoffs": len(handoff_summaries),
                    "evaluation_hash": evaluation_hash,
                },
            )

            return HierarchicalOutcomeResponse(
                parent_transaction_id=parent_txn.id,
                tenant_id=auth.tenant_id,
                parent_state=parent_txn.state,
                parent_disposition=parent_txn.final_disposition,
                is_parent_terminal=is_parent_terminal,
                hierarchical_status=hierarchical_status,
                epistemic_confidence=ep_confidence,
                evaluated_at=now,
                total_child_transactions=len(child_executions),
                active_child_transactions=sum(1 for c in child_executions if not c.execution_completed),
                total_handoffs=len(handoff_summaries),
                pending_handoffs=sum(1 for h in handoff_summaries if h.status == HandoffStatus.PENDING.value),
                parent_actions=parent_action_summaries,
                child_executions=child_executions,
                handoffs=handoff_summaries,
                discrepancies=discrepancies,
                reconciliation_notes=reconciliation_notes,
                evaluation_hash=evaluation_hash,
            )

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def verify_hierarchical_completion(
        self,
        auth: AuthContext,
        transaction_id: str,
        session: AsyncSession,
    ) -> None:
        """Enforces that a parent transaction cannot transition to COMPLETED if child work is pending or unverified.

        Raises:
            HTTPException(409): If pending child work, unverified child actions, or child failures exist.
        """
        outcome_resp = await self.aggregate_transaction_outcome(auth, transaction_id, session=session)

        # If the transaction has no handoffs and no child transactions, parent evaluation alone applies
        if outcome_resp.total_child_transactions == 0 and outcome_resp.total_handoffs == 0:
            return

        if outcome_resp.pending_handoffs > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot complete transaction '{transaction_id}': {outcome_resp.pending_handoffs} "
                    "delegated handoff(s) are still pending acceptance."
                ),
            )

        if outcome_resp.active_child_transactions > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot complete transaction '{transaction_id}': {outcome_resp.active_child_transactions} "
                    "child transaction(s) are still actively executing."
                ),
            )

        if outcome_resp.hierarchical_status == HierarchicalOutcomeStatus.AWAITING_OUTCOME_VERIFICATION:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot complete transaction '{transaction_id}': Child execution tool calls completed, "
                    "but independent Gate 5 reality verification remains pending."
                ),
            )

        if outcome_resp.hierarchical_status in (
            HierarchicalOutcomeStatus.HIERARCHICAL_FAILURE,
            HierarchicalOutcomeStatus.CANCELLED,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot complete transaction '{transaction_id}': Hierarchical child work resulted in "
                    f"status '{outcome_resp.hierarchical_status.value}'."
                ),
            )

        if outcome_resp.hierarchical_status != HierarchicalOutcomeStatus.VERIFIED_SUCCESS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot complete transaction '{transaction_id}': Hierarchical status is "
                    f"'{outcome_resp.hierarchical_status.value}'."
                ),
            )

    def _evaluate_hierarchical_status(
        self,
        parent_txn: AITransaction,
        parent_actions: list[ActionOutcomeSummary],
        child_executions: list[ChildExecutionSummary],
        handoffs: list[HandoffSummary],
        discrepancies: list[str],
        reconciliation_notes: list[str],
    ) -> tuple[HierarchicalOutcomeStatus, float]:
        """Deterministic evaluation policy for hierarchical status and epistemic confidence."""
        # 1. Parent explicit cancellation or failure
        if parent_txn.state == "CANCELLED" or parent_txn.final_disposition == "CANCELLED":
            reconciliation_notes.append("Parent transaction was cancelled.")
            return HierarchicalOutcomeStatus.CANCELLED, 0.0

        if parent_txn.state == "FAILED" or parent_txn.final_disposition == "FAILED":
            reconciliation_notes.append("Parent transaction has failed.")
            return HierarchicalOutcomeStatus.HIERARCHICAL_FAILURE, 0.0

        # 2. Check for pending handoffs
        pending_handoffs = [h for h in handoffs if h.status == HandoffStatus.PENDING.value]
        if pending_handoffs:
            reconciliation_notes.append(f"{len(pending_handoffs)} handoff offer(s) pending acceptance by child agents.")
            return HierarchicalOutcomeStatus.PENDING_CHILD_WORK, 0.0

        # 3. Check for active child transactions
        active_children = [c for c in child_executions if not c.execution_completed]
        if active_children:
            reconciliation_notes.append(f"{len(active_children)} child transaction(s) are actively executing.")
            return HierarchicalOutcomeStatus.PENDING_CHILD_WORK, 0.0

        # 4. Check for rejected, expired, or revoked handoffs without completed children
        aborted_handoffs = [
            h
            for h in handoffs
            if h.status in (HandoffStatus.EXPIRED.value, HandoffStatus.REJECTED.value, HandoffStatus.REVOKED.value)
        ]
        if aborted_handoffs:
            discrepancies.append(
                f"Delegated handoffs aborted before completion: {[h.handoff_id for h in aborted_handoffs]}"
            )
            reconciliation_notes.append("Delegated execution aborted prior to successful completion.")
            return HierarchicalOutcomeStatus.HIERARCHICAL_FAILURE, 0.0

        # Collect all actions across parent and children
        all_actions = parent_actions + [a for c in child_executions for a in c.action_summaries]

        # 5. Check for actions awaiting Gate 5 outcome verification
        pending_verification_actions = [
            a
            for a in all_actions
            if a.requires_outcome_assurance
            and (a.outcome_status == OutcomeStatus.PENDING_VERIFICATION.value or a.outcome_status is None)
            and a.action_state not in (ActionState.BLOCKED.value, ActionState.PROPOSED.value)
        ]
        if pending_verification_actions:
            reconciliation_notes.append(
                f"{len(pending_verification_actions)} action(s) executed but awaiting Gate 5 reality verification."
            )
            return HierarchicalOutcomeStatus.AWAITING_OUTCOME_VERIFICATION, 0.0

        # 6. Check for failed actions
        failed_actions = [
            a for a in all_actions if a.outcome_status in _FAILED_OUTCOMES or a.action_state == ActionState.FAILED.value
        ]
        if failed_actions:
            discrepancies.append(f"Failed actions detected: {[a.action_id for a in failed_actions]}")
            # If some actions succeeded, evaluate partial achievement
            successful_actions = [a for a in all_actions if a.outcome_status in _VERIFIED_SUCCESS_OUTCOMES]
            if successful_actions:
                reconciliation_notes.append("Subset of hierarchical actions failed while others verified successfully.")
                return HierarchicalOutcomeStatus.PARTIAL_ACHIEVEMENT, 0.0
            return HierarchicalOutcomeStatus.HIERARCHICAL_FAILURE, 0.0

        # 7. Check for unverifiable / blind sink actions
        unverifiable_actions = [a for a in all_actions if a.outcome_status in _UNVERIFIABLE_OUTCOMES]
        if unverifiable_actions:
            discrepancies.append(
                f"Unverifiable actions targeting blind sinks detected: {[a.action_id for a in unverifiable_actions]}"
            )
            reconciliation_notes.append(
                "Actions executed against write-only or blind sinks with epistemic confidence 0.0."
            )
            successful_actions = [a for a in all_actions if a.outcome_status in _VERIFIED_SUCCESS_OUTCOMES]
            if successful_actions:
                return HierarchicalOutcomeStatus.PARTIAL_ACHIEVEMENT, 0.0
            return HierarchicalOutcomeStatus.UNVERIFIABLE, 0.0

        # 8. All actions requiring outcome assurance verified success
        assurance_actions = [a for a in all_actions if a.requires_outcome_assurance]
        if assurance_actions:
            confidences = [a.epistemic_confidence for a in assurance_actions]
            # Weakest-link conservative epistemic confidence
            min_confidence = min(confidences) if confidences else 1.0
            reconciliation_notes.append(
                f"All {len(assurance_actions)} consequential actions independently verified by Gate 5 Reality Verifier."
            )
            return HierarchicalOutcomeStatus.VERIFIED_SUCCESS, min_confidence

        # If no actions required outcome assurance, check if transactions completed cleanly
        all_completed = (parent_txn.state == "COMPLETED" or parent_txn.final_disposition == "COMPLETED") and all(
            c.execution_completed for c in child_executions
        )
        if all_completed:
            reconciliation_notes.append(
                "All transactions completed cleanly with no external outcome assurance required."
            )
            return HierarchicalOutcomeStatus.VERIFIED_SUCCESS, 1.0

        return HierarchicalOutcomeStatus.UNKNOWN, 0.0

    def _build_action_summary(
        self,
        action: ActionContract,
        outcome_rec: OutcomeVerificationRecord | None,
    ) -> ActionOutcomeSummary:
        """Constructs an ActionOutcomeSummary from ActionContract and OutcomeVerificationRecord."""
        outcome_status = outcome_rec.outcome_status if outcome_rec else action.outcome_status
        epistemic_confidence = outcome_rec.epistemic_confidence if outcome_rec else 0.0
        observability_class = outcome_rec.observability_class if outcome_rec else None
        discrepancies = list(outcome_rec.discrepancies or []) if outcome_rec else []

        return ActionOutcomeSummary(
            action_id=action.id,
            transaction_id=action.transaction_id,
            tool_name=action.tool_name,
            target_resource=action.target_resource,
            requires_outcome_assurance=action.requires_outcome_assurance,
            action_state=action.state,
            outcome_status=outcome_status,
            epistemic_confidence=epistemic_confidence,
            observability_class=observability_class,
            discrepancies=discrepancies,
        )

    async def _emit_audit_event(
        self,
        session: AsyncSession,
        tenant_id: str,
        action: str,
        details: dict[str, Any],
    ) -> None:
        """Emits tamper-evident hash-chained audit log entry."""
        last_stmt = (
            select(AuditLogRecord.chain_hash, AuditLogRecord.sequence_number)
            .where(AuditLogRecord.tenant_id == tenant_id)
            .order_by(AuditLogRecord.sequence_number.desc())
            .limit(1)
        )
        last_res = await session.execute(last_stmt)
        last_row = last_res.first()
        prev_hash = last_row[0] if last_row and last_row[0] is not None else ("0" * 64)
        seq = (last_row[1] + 1) if last_row and len(last_row) > 1 and last_row[1] is not None else 1

        now = datetime.now(UTC)
        entry_id = f"aud_hier_{uuid.uuid4().hex}"
        payload_str = f"{prev_hash}:{entry_id}:{action}:{now.isoformat()}:{tenant_id}"
        chain_hash = compute_sha256(payload_str)

        rec = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=seq,
            session_id=details.get("parent_transaction_id", "hierarchy"),
            trace_id=f"hier-{details.get('parent_transaction_id', 'na')}",
            prompt_hash=compute_sha256(f"hierarchical:{action}"),
            response_hash=compute_sha256(action),
            hrs_score=0.0,
            risk_tier="HIERARCHICAL_ASSURANCE",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type=action,
            actor_identity_id="system",
            transaction_id=details.get("parent_transaction_id"),
            decision="ALLOW",
            policy_reference="hierarchical_outcome_governance",
            reason=details.get("reason", action),
            event_payload=details,
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
        session.add(rec)
        await session.flush()


hierarchical_outcome_service = HierarchicalOutcomeService()
