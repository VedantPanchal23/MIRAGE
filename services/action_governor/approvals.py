"""Subsystem: Gate 3 Action Assurance.
Module: Human-in-the-Loop Action Approval Governance.
Authoritative Specs: Technical_Architecture.md §6, Security.md §4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from db import session as db_session
from db.models import ActionApproval, ActionContract
from shared.schemas.action import (
    ActionState,
    ApprovalResponse,
    ApprovalStatus,
    compute_contract_binding_hash,
    compute_parameters_hash,
)
from shared.schemas.auth import AuthContext, Role

from .audit import _record_action_audit_event


async def validate_and_consume_approval(
    session: Any,
    auth: AuthContext,
    contract: ActionContract,
    now: datetime,
) -> None:
    """Validate single-use approval token and consume it atomically at execution boundary."""
    if not contract.approval_id:
        return

    appr_stmt = (
        select(ActionApproval)
        .where(
            ActionApproval.tenant_id == auth.tenant_id,
            ActionApproval.id == contract.approval_id,
        )
        .with_for_update()
    )
    appr_res = await session.execute(appr_stmt)
    approval = appr_res.scalar_one_or_none()
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Execution forbidden: Required L4 approval was not found",
        )
    if approval.status == ApprovalStatus.CONSUMED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approval replay attack detected: Approval token has already been consumed.",
        )
    if approval.status != ApprovalStatus.GRANTED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Execution forbidden: Approval is in status '{approval.status}'",
        )
    if approval.expires_at < now:
        approval.status = ApprovalStatus.EXPIRED.value
        await session.flush()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Execution forbidden: Approval token has expired.",
        )

    # Cross-transaction & cross-action replay defense:
    if approval.action_id != contract.id or approval.transaction_id != contract.transaction_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approval replay attack detected: Approval token does not belong to this action/transaction.",
        )

    # Recompute and verify contract binding hash
    cost_val = (
        float(contract.blast_radius.get("estimated_dollar_cost", 0.0))
        if isinstance(contract.blast_radius, dict)
        else 0.0
    )
    recomputed_hash = compute_contract_binding_hash(
        tenant_id=contract.tenant_id,
        transaction_id=contract.transaction_id,
        action_id=contract.id,
        tool_name=contract.tool_name,
        action_type=contract.action_type,
        target_resource=contract.target_resource,
        parameters_hash=compute_parameters_hash(contract.normalized_parameters),
        required_capability=contract.required_capability,
        estimated_dollar_cost=cost_val,
        taint_flags=contract.taint_flags,
    )
    if recomputed_hash != approval.parameters_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Parameter tampering detected: cryptographic binding fingerprint mismatch "
                "between contract and approval."
            ),
        )

    # Transition approval to CONSUMED (single-use defense)
    approval.status = ApprovalStatus.CONSUMED.value


async def grant_approval(auth: AuthContext, approval_id: str, reason: str) -> ApprovalResponse:
    """Grant a pending human approval. Agents cannot self-grant approvals."""
    if auth.role not in (Role.SUPER_ADMIN, Role.OPERATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agents cannot self-grant approvals. L4 approvals require human administrator/operator credentials.",
        )

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = (
            select(ActionApproval)
            .where(
                ActionApproval.tenant_id == auth.tenant_id,
                ActionApproval.id == approval_id,
            )
            .with_for_update()
        )
        res = await session.execute(stmt)
        approval = res.scalar_one_or_none()
        if not approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

        # Check self-approval: Requester cannot grant their own approval
        if approval.requested_by == auth.identity_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agent/Requester cannot approve their own action proposal. Distinct human sign-off required.",
            )

        if approval.status != ApprovalStatus.PENDING.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Approval request is already in state '{approval.status}'",
            )

        now = datetime.now(UTC)
        if approval.expires_at < now:
            approval.status = ApprovalStatus.EXPIRED.value
            await session.flush()
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Approval request has expired")

        # Transition action contract to AUTHORIZED with row lock
        act_stmt = (
            select(ActionContract)
            .where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.id == approval.action_id,
            )
            .with_for_update()
        )
        act_res = await session.execute(act_stmt)
        contract = act_res.scalar_one_or_none()
        if not contract:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Associated action contract not found",
            )

        # Verify contract binding hash
        cost_val = (
            float(contract.blast_radius.get("estimated_dollar_cost", 0.0))
            if isinstance(contract.blast_radius, dict)
            else 0.0
        )
        recomputed_hash = compute_contract_binding_hash(
            tenant_id=contract.tenant_id,
            transaction_id=contract.transaction_id,
            action_id=contract.id,
            tool_name=contract.tool_name,
            action_type=contract.action_type,
            target_resource=contract.target_resource,
            parameters_hash=compute_parameters_hash(contract.normalized_parameters),
            required_capability=contract.required_capability,
            estimated_dollar_cost=cost_val,
            taint_flags=contract.taint_flags,
        )
        if recomputed_hash != approval.parameters_hash:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Action contract tampering detected prior to approval: cryptographic binding hash mismatch.",
            )

        approval.status = ApprovalStatus.GRANTED.value
        approval.decided_by = auth.identity_id
        approval.decision_reason = reason
        approval.decided_at = now

        contract.state = ActionState.AUTHORIZED.value
        contract.authorized_at = now

        # Audit record
        await _record_action_audit_event(
            session=session,
            tenant_id=auth.tenant_id,
            event_type="APPROVAL_GRANTED",
            actor_identity_id=auth.identity_id,
            transaction_id=approval.transaction_id,
            decision="GRANTED",
            reason=reason,
            payload={"approval_id": approval_id, "action_id": approval.action_id},
        )
        await session.flush()

        return ApprovalResponse(
            id=approval.id,
            tenant_id=approval.tenant_id,
            action_id=approval.action_id,
            transaction_id=approval.transaction_id,
            required_role=approval.required_role,
            status=ApprovalStatus.GRANTED,
            parameters_hash=approval.parameters_hash,
            requested_by=approval.requested_by,
            decided_by=approval.decided_by,
            decision_reason=approval.decision_reason,
            expires_at=approval.expires_at.isoformat(),
            created_at=approval.created_at.isoformat(),
        )


async def deny_approval(auth: AuthContext, approval_id: str, reason: str) -> ApprovalResponse:
    """Deny a pending human approval."""
    if auth.role not in (Role.SUPER_ADMIN, Role.OPERATOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="L4 approvals require human administrator/operator credentials.",
        )

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = (
            select(ActionApproval)
            .where(
                ActionApproval.tenant_id == auth.tenant_id,
                ActionApproval.id == approval_id,
            )
            .with_for_update()
        )
        res = await session.execute(stmt)
        approval = res.scalar_one_or_none()
        if not approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

        now = datetime.now(UTC)
        approval.status = ApprovalStatus.DENIED.value
        approval.decided_by = auth.identity_id
        approval.decision_reason = reason
        approval.decided_at = now

        # Transition action contract to BLOCKED with row lock
        act_stmt = (
            select(ActionContract)
            .where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.id == approval.action_id,
            )
            .with_for_update()
        )
        act_res = await session.execute(act_stmt)
        contract = act_res.scalar_one_or_none()
        if contract:
            contract.state = ActionState.BLOCKED.value

        # Audit record
        await _record_action_audit_event(
            session=session,
            tenant_id=auth.tenant_id,
            event_type="APPROVAL_DENIED",
            actor_identity_id=auth.identity_id,
            transaction_id=approval.transaction_id,
            decision="DENIED",
            reason=reason,
            payload={"approval_id": approval_id, "action_id": approval.action_id},
        )
        await session.flush()

        return ApprovalResponse(
            id=approval.id,
            tenant_id=approval.tenant_id,
            action_id=approval.action_id,
            transaction_id=approval.transaction_id,
            required_role=approval.required_role,
            status=ApprovalStatus.DENIED,
            parameters_hash=approval.parameters_hash,
            requested_by=approval.requested_by,
            decided_by=approval.decided_by,
            decision_reason=approval.decision_reason,
            expires_at=approval.expires_at.isoformat(),
            created_at=approval.created_at.isoformat(),
        )


async def list_pending_approvals(auth: AuthContext) -> list[ApprovalResponse]:
    """List active pending approvals for the caller's tenant."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        now = datetime.now(UTC)
        stmt = select(ActionApproval).where(
            ActionApproval.tenant_id == auth.tenant_id,
            ActionApproval.status == ApprovalStatus.PENDING.value,
            ActionApproval.expires_at > now,
        )
        res = await session.execute(stmt)
        approvals = res.scalars().all()

        return [
            ApprovalResponse(
                id=a.id,
                tenant_id=a.tenant_id,
                action_id=a.action_id,
                transaction_id=a.transaction_id,
                required_role=a.required_role,
                status=ApprovalStatus(a.status),
                parameters_hash=a.parameters_hash,
                requested_by=a.requested_by,
                decided_by=a.decided_by,
                decision_reason=a.decision_reason,
                expires_at=a.expires_at.isoformat(),
                created_at=a.created_at.isoformat(),
            )
            for a in approvals
        ]
