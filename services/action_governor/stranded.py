"""Subsystem: Gate 3 Action Assurance.
Module: Stranded Action Detection and Operator Reconciliation.
Authoritative Specs: Technical_Architecture.md §6, AI_Action_Contract.md §7.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select

from db import session as db_session
from db.models import ActionContract
from shared.schemas.action import (
    ActionExecutionResult,
    ActionReconciliationRequest,
    ActionReconciliationResolution,
    ActionState,
    StrandedActionInfo,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import Taint
from shared.schemas.outcome import OutcomeStatus

from .audit import _record_action_audit_event


async def list_stranded_actions(
    auth: AuthContext,
    older_than_seconds: int = 60,
) -> list[StrandedActionInfo]:
    """Find actions stranded in EXECUTING or EXECUTION_UNCERTAIN state after worker crash/restart."""
    if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Caller is not authorized to list stranded actions (requires SUPER_ADMIN, TENANT_ADMIN, or OPERATOR)"
            ),
        )
    cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = (
            select(ActionContract)
            .where(
                ActionContract.tenant_id == auth.tenant_id,
                (
                    (ActionContract.state == ActionState.EXECUTION_UNCERTAIN.value)
                    | (
                        (ActionContract.state == ActionState.EXECUTING.value)
                        & (ActionContract.executed_at.is_(None) | (ActionContract.executed_at <= cutoff))
                    )
                ),
            )
            .order_by(ActionContract.created_at.desc())
        )
        res = await session.execute(stmt)
        contracts = res.scalars().all()
        return [
            StrandedActionInfo(
                action_id=c.id,
                transaction_id=c.transaction_id,
                agent_id=c.agent_id,
                tool_name=c.tool_name,
                target_resource=c.target_resource,
                state=ActionState(c.state),
                executed_at=c.executed_at.isoformat() if c.executed_at else None,
                error_message=c.error_message,
                requires_outcome_assurance=c.requires_outcome_assurance,
                fencing_token=c.fencing_token,
            )
            for c in contracts
        ]


async def reconcile_stranded_action(
    auth: AuthContext,
    req: ActionReconciliationRequest,
) -> ActionExecutionResult:
    """Idempotently reconcile a stranded EXECUTING or EXECUTION_UNCERTAIN action with an immutable audit trail."""
    if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Caller is not authorized to reconcile actions (requires SUPER_ADMIN, TENANT_ADMIN, or OPERATOR)",
        )

    now = datetime.now(UTC)
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = (
            select(ActionContract)
            .where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.id == req.action_id,
            )
            .with_for_update()
        )
        res = await session.execute(stmt)
        contract = res.scalar_one_or_none()
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Action contract '{req.action_id}' not found in tenant '{auth.tenant_id}'",
            )

        # Idempotency check: if contract is already in a terminal state
        if contract.state in (ActionState.COMPLETED.value, ActionState.FAILED.value, ActionState.EXECUTED.value):
            if (
                req.resolution == ActionReconciliationResolution.MARK_FAILED
                and contract.state == ActionState.FAILED.value
            ) or (
                req.resolution == ActionReconciliationResolution.MARK_COMPLETED
                and contract.state in (ActionState.COMPLETED.value, ActionState.EXECUTED.value)
            ):
                return ActionExecutionResult(
                    action_id=contract.id,
                    transaction_id=contract.transaction_id,
                    state=ActionState(contract.state),
                    observed_output=contract.observed_result or {},
                    taints={Taint.UNTRUSTED},
                    postconditions_satisfied=(contract.state == ActionState.COMPLETED.value),
                    postcondition_evidence=[],
                    error_message=contract.error_message,
                    outcome_status=OutcomeStatus(contract.outcome_status) if contract.outcome_status else None,
                    outcome_id=None,
                    requires_outcome_assurance=contract.requires_outcome_assurance,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Action contract '{req.action_id}' is already in terminal state '{contract.state}' "
                    f"and cannot be re-reconciled to '{req.resolution}'"
                ),
            )

        if contract.state not in (ActionState.EXECUTING.value, ActionState.EXECUTION_UNCERTAIN.value):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Action contract '{req.action_id}' is in state '{contract.state}'. "
                    "Only EXECUTING or EXECUTION_UNCERTAIN actions can be reconciled."
                ),
            )

        prev_state = contract.state
        outcome_id: str | None = None

        if req.resolution == ActionReconciliationResolution.MARK_FAILED:
            contract.state = ActionState.FAILED.value
            contract.error_message = f"Reconciled as FAILED by operator: {req.notes}"
            contract.outcome_status = OutcomeStatus.VERIFIED_FAILURE.value
            contract.completed_at = now
            final_state = ActionState.FAILED
            postconditions_ok = False

        elif req.resolution == ActionReconciliationResolution.MARK_UNCERTAIN:
            contract.state = ActionState.EXECUTION_UNCERTAIN.value
            contract.error_message = f"Confirmed EXECUTION_UNCERTAIN by operator: {req.notes}"
            contract.completed_at = None
            final_state = ActionState.EXECUTION_UNCERTAIN
            postconditions_ok = False

        elif req.resolution == ActionReconciliationResolution.MARK_COMPLETED:
            if contract.requires_outcome_assurance:
                final_state = ActionState.EXECUTED
                contract.state = ActionState.EXECUTED.value
                contract.outcome_status = OutcomeStatus.PENDING_VERIFICATION.value
                postconditions_ok = False
            else:
                final_state = ActionState.COMPLETED
                contract.state = ActionState.COMPLETED.value
                contract.outcome_status = None
                postconditions_ok = True

            contract.observed_result = req.observed_evidence or {
                "reconciled_by": auth.identity_id,
                "notes": req.notes,
            }
            contract.completed_at = now
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported reconciliation resolution: '{req.resolution}'",
            )

        # Record immutable audit event
        await _record_action_audit_event(
            session=session,
            tenant_id=auth.tenant_id,
            event_type="ACTION_RECONCILED",
            actor_identity_id=auth.identity_id,
            transaction_id=contract.transaction_id,
            decision=contract.state,
            reason=f"Action reconciled by operator: {req.notes}",
            payload={
                "action_id": contract.id,
                "previous_state": prev_state,
                "new_state": contract.state,
                "resolution": req.resolution.value,
                "notes": req.notes,
                "has_evidence": bool(req.observed_evidence),
            },
        )
        await session.flush()

        return ActionExecutionResult(
            action_id=contract.id,
            transaction_id=contract.transaction_id,
            state=final_state,
            observed_output=contract.observed_result or {},
            taints={Taint.UNTRUSTED},
            postconditions_satisfied=postconditions_ok,
            postcondition_evidence=[],
            error_message=contract.error_message,
            outcome_status=OutcomeStatus(contract.outcome_status) if contract.outcome_status else None,
            outcome_id=outcome_id,
            requires_outcome_assurance=contract.requires_outcome_assurance,
        )
