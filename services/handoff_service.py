"""Agent Handoff Service governing cross-agent execution lifecycle.

Adheres to MIRAGE Phase 8 architecture:
- Authoritative lineage verification connecting parent transactions, child agents, and delegations.
- Server-side derivation of sender identity, tenant boundaries, and inherited taints.
- Strict lifecycle state transitions with replay and semantic collision protection.
- Pre-acceptance revalidation of ancestor authority chain, delegation status, and agent eligibility.
- Child transaction spawning with turn budgeting and inherited DIFC taint tags.
- Gate 3 execution boundary remains mandatory: handoff acceptance is never permission for unverified tool execution.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentDelegation, AgentHandoff, AITransaction, AuditLogRecord
from db.session import get_tenant_session
from services.agent_governance import agent_governance_service
from services.delegation_service import delegation_service
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.handoff import (
    AgentHandoffAcceptRequest,
    AgentHandoffAcceptResponse,
    AgentHandoffCancelRequest,
    AgentHandoffCreateRequest,
    AgentHandoffResponse,
    HandoffStatus,
    is_terminal_handoff_status,
)

logger = get_logger("handoff_service")


class AgentHandoffService:
    """Authoritative management service for cross-agent governed handoffs."""

    async def create_handoff(
        self,
        auth: AuthContext,
        request: AgentHandoffCreateRequest,
        session: AsyncSession | None = None,
    ) -> AgentHandoffResponse:
        """Create a new pending handoff from an active parent execution to an authorized delegatee agent."""
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> AgentHandoffResponse:
            # 1. Idempotency check with semantic collision defense
            idem_stmt = select(AgentHandoff).where(
                AgentHandoff.tenant_id == auth.tenant_id,
                AgentHandoff.idempotency_key == request.idempotency_key,
            )
            idem_res = await s.execute(idem_stmt)
            existing = idem_res.scalar_one_or_none()
            if existing:
                if (
                    existing.parent_transaction_id != request.parent_transaction_id
                    or existing.child_agent_id != request.child_agent_id
                    or existing.delegation_id != request.delegation_id
                    or existing.purpose != request.purpose
                ):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=("Idempotency key reuse across materially divergent handoff semantics is prohibited"),
                    )
                return self._map_to_response(existing)

            # 2. Validate parent transaction
            parent_txn_stmt = select(AITransaction).where(
                AITransaction.id == request.parent_transaction_id,
                AITransaction.tenant_id == auth.tenant_id,
            )
            parent_txn_res = await s.execute(parent_txn_stmt)
            parent_txn = parent_txn_res.scalar_one_or_none()
            if not parent_txn:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=(
                        f"Parent transaction '{request.parent_transaction_id}' not found in tenant '{auth.tenant_id}'"
                    ),
                )
            if parent_txn.state != "ACTIVE" or parent_txn.final_disposition is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Parent transaction '{parent_txn.id}' is not in active state (state: {parent_txn.state})",
                )

            # Derive parent agent id
            parent_agent_id = parent_txn.agent_id or auth.agent_id
            if not parent_agent_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Parent transaction lacks an associated agent ID",
                )

            if parent_agent_id == request.child_agent_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Self-handoff is prohibited: parent agent cannot handoff to itself",
                )

            # 3. Validate delegation grant
            del_stmt = select(AgentDelegation).where(
                AgentDelegation.id == request.delegation_id,
                AgentDelegation.tenant_id == auth.tenant_id,
            )
            del_res = await s.execute(del_stmt)
            delegation = del_res.scalar_one_or_none()
            if not delegation:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Delegation grant '{request.delegation_id}' not found in tenant '{auth.tenant_id}'",
                )
            if delegation.status != "ACTIVE":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Delegation grant '{delegation.id}' is not ACTIVE (status: {delegation.status})",
                )
            if delegation.expires_at <= now:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Delegation grant '{delegation.id}' has expired",
                )
            if delegation.revoked_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Delegation grant '{delegation.id}' has been revoked",
                )

            # Lineage checks
            if delegation.parent_transaction_id != parent_txn.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Delegation grant '{delegation.id}' parent transaction "
                        f"('{delegation.parent_transaction_id}') does not match '{parent_txn.id}'"
                    ),
                )
            if delegation.child_agent_id != request.child_agent_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Delegation grant '{delegation.id}' child agent "
                        f"('{delegation.child_agent_id}') does not match requested child '{request.child_agent_id}'"
                    ),
                )

            # 4. Validate child agent lifecycle eligibility
            child_eligible, reason = await agent_governance_service.evaluate_agent_eligibility(
                session=s,
                tenant_id=auth.tenant_id,
                agent_id=request.child_agent_id,
            )
            if not child_eligible:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Child agent '{request.child_agent_id}' is not eligible: {reason}",
                )

            # 5. Attenuated permitted scope validation
            if request.permitted_scope:
                # Ensure permitted_scope does not widen delegation.resource_scope
                err = delegation_service._verify_attenuation(
                    parent_scope=delegation.resource_scope or {},
                    child_scope=request.permitted_scope,
                )
                if err:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Handoff permitted scope widening error: {err}",
                    )

            # 6. Server-side taint inheritance from parent transaction
            inherited_taints = list(parent_txn.taint_flags or [])

            handoff_id = f"hnd_{uuid.uuid4().hex[:16]}"
            expires_at = now + timedelta(seconds=request.duration_seconds)

            handoff = AgentHandoff(
                id=handoff_id,
                tenant_id=auth.tenant_id,
                parent_transaction_id=parent_txn.id,
                parent_agent_id=parent_agent_id,
                child_agent_id=request.child_agent_id,
                delegation_id=delegation.id,
                child_transaction_id=None,
                status=HandoffStatus.PENDING.value,
                purpose=request.purpose,
                permitted_scope=request.permitted_scope,
                inherited_taint_flags=inherited_taints,
                idempotency_key=request.idempotency_key,
                expires_at=expires_at,
                accepted_at=None,
                completed_at=None,
                cancelled_at=None,
                cancellation_reason=None,
                created_at=now,
                updated_at=now,
            )
            s.add(handoff)
            await s.flush()

            await self._emit_audit_event(
                session=s,
                tenant_id=auth.tenant_id,
                action="AGENT_HANDOFF_CREATED",
                details={
                    "handoff_id": handoff_id,
                    "parent_transaction_id": parent_txn.id,
                    "parent_agent_id": parent_agent_id,
                    "child_agent_id": request.child_agent_id,
                    "delegation_id": delegation.id,
                    "expires_at": expires_at.isoformat(),
                },
            )

            return self._map_to_response(handoff)

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def get_handoff(
        self,
        auth: AuthContext,
        handoff_id: str,
        session: AsyncSession | None = None,
    ) -> AgentHandoffResponse:
        """Retrieve an authoritative agent handoff record by ID within caller tenant."""

        async def _execute(s: AsyncSession) -> AgentHandoffResponse:
            stmt = select(AgentHandoff).where(
                AgentHandoff.id == handoff_id,
                AgentHandoff.tenant_id == auth.tenant_id,
            )
            res = await s.execute(stmt)
            handoff = res.scalar_one_or_none()
            if not handoff:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent handoff '{handoff_id}' not found in tenant '{auth.tenant_id}'",
                )
            return self._map_to_response(handoff)

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def list_handoffs(
        self,
        auth: AuthContext,
        status_filter: HandoffStatus | None = None,
        parent_transaction_id: str | None = None,
        child_agent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> list[AgentHandoffResponse]:
        """List tenant handoffs with filtering and bounded pagination."""

        async def _execute(s: AsyncSession) -> list[AgentHandoffResponse]:
            stmt = select(AgentHandoff).where(AgentHandoff.tenant_id == auth.tenant_id)
            if status_filter:
                stmt = stmt.where(AgentHandoff.status == status_filter.value)
            if parent_transaction_id:
                stmt = stmt.where(AgentHandoff.parent_transaction_id == parent_transaction_id)
            if child_agent_id:
                stmt = stmt.where(AgentHandoff.child_agent_id == child_agent_id)

            stmt = stmt.order_by(AgentHandoff.created_at.desc()).limit(limit).offset(offset)
            res = await s.execute(stmt)
            records = res.scalars().all()
            return [self._map_to_response(r) for r in records]

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def accept_handoff(
        self,
        auth: AuthContext,
        handoff_id: str,
        request: AgentHandoffAcceptRequest,
        session: AsyncSession | None = None,
    ) -> AgentHandoffAcceptResponse:
        """Accept a pending handoff, revalidate the ancestor chain, and spawn a child transaction."""
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> AgentHandoffAcceptResponse:
            # 1. Row-lock handoff
            hnd_stmt = (
                select(AgentHandoff)
                .where(
                    AgentHandoff.id == handoff_id,
                    AgentHandoff.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            hnd_res = await s.execute(hnd_stmt)
            handoff = hnd_res.scalar_one_or_none()
            if not handoff:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent handoff '{handoff_id}' not found in tenant '{auth.tenant_id}'",
                )

            # 2. Authorization check: caller must match child agent or be operator/admin
            if auth.agent_id != handoff.child_agent_id and auth.role not in {
                Role.SUPER_ADMIN,
                Role.TENANT_ADMIN,
                Role.OPERATOR,
            }:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Caller '{auth.identity_id}' is not authorized to accept handoff for "
                        f"child agent '{handoff.child_agent_id}'"
                    ),
                )

            # 3. State transition check
            if handoff.status != HandoffStatus.PENDING.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot accept handoff in non-PENDING status '{handoff.status}'",
                )

            # 4. Expiration check
            if handoff.expires_at <= now:
                handoff.status = HandoffStatus.EXPIRED.value
                handoff.updated_at = now
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot accept handoff: handoff offer has expired",
                )

            # 5. Revalidate delegation grant
            del_stmt = (
                select(AgentDelegation)
                .where(
                    AgentDelegation.id == handoff.delegation_id,
                    AgentDelegation.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            del_res = await s.execute(del_stmt)
            delegation = del_res.scalar_one_or_none()
            if (
                not delegation
                or delegation.status != "ACTIVE"
                or delegation.expires_at <= now
                or delegation.revoked_at is not None
            ):
                handoff.status = HandoffStatus.REVOKED.value
                handoff.updated_at = now
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot accept handoff: bound delegation grant has expired or been revoked",
                )

            # 6. Revalidate parent transaction
            parent_txn_stmt = (
                select(AITransaction)
                .where(
                    AITransaction.id == handoff.parent_transaction_id,
                    AITransaction.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            parent_txn_res = await s.execute(parent_txn_stmt)
            parent_txn = parent_txn_res.scalar_one_or_none()
            if not parent_txn or parent_txn.state != "ACTIVE" or parent_txn.final_disposition is not None:
                handoff.status = HandoffStatus.CANCELLED.value
                handoff.cancellation_reason = "Parent transaction terminated before handoff acceptance"
                handoff.cancelled_at = now
                handoff.updated_at = now
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot accept handoff: parent transaction is no longer active",
                )

            # 7. Revalidate child agent lifecycle status
            child_eligible, reason = await agent_governance_service.evaluate_agent_eligibility(
                session=s,
                tenant_id=auth.tenant_id,
                agent_id=handoff.child_agent_id,
            )
            if not child_eligible:
                handoff.status = HandoffStatus.REJECTED.value
                handoff.updated_at = now
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Child agent '{handoff.child_agent_id}' is not eligible: {reason}",
                )

            # 8. Spawn child transaction
            child_txn_id = f"txn_child_{uuid.uuid4().hex[:12]}"
            remaining_parent_turns = max(1, parent_txn.max_turns - parent_txn.turn_count)
            allocated_turns = min(delegation.max_turns, remaining_parent_turns)

            context_entry = {
                "source": "handoff",
                "handoff_id": handoff.id,
                "parent_transaction_id": parent_txn.id,
                "input_context": request.input_context,
            }

            child_txn = AITransaction(
                id=child_txn_id,
                tenant_id=auth.tenant_id,
                actor_identity_id=auth.identity_id,
                agent_id=handoff.child_agent_id,
                parent_transaction_id=parent_txn.id,
                idempotency_key=f"idem_child_{child_txn_id}",
                correlation_id=parent_txn.correlation_id,
                state="ACTIVE",
                max_turns=allocated_turns,
                turn_count=0,
                final_disposition=None,
                taint_flags=list(handoff.inherited_taint_flags or []),
                context_sources=[context_entry],
                created_at=now,
                updated_at=now,
            )
            s.add(child_txn)

            # 9. Update handoff and delegation records
            handoff.status = HandoffStatus.ACCEPTED.value
            handoff.child_transaction_id = child_txn_id
            handoff.accepted_at = now
            handoff.updated_at = now

            if delegation.child_transaction_id is None:
                delegation.child_transaction_id = child_txn_id
                delegation.updated_at = now

            await s.flush()

            await self._emit_audit_event(
                session=s,
                tenant_id=auth.tenant_id,
                action="AGENT_HANDOFF_ACCEPTED",
                details={
                    "handoff_id": handoff.id,
                    "child_transaction_id": child_txn_id,
                    "child_agent_id": handoff.child_agent_id,
                    "allocated_turns": allocated_turns,
                },
            )

            return AgentHandoffAcceptResponse(
                handoff=self._map_to_response(handoff),
                child_transaction_id=child_txn_id,
                inherited_taint_flags=list(handoff.inherited_taint_flags or []),
                allocated_turns=allocated_turns,
            )

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def cancel_handoff(
        self,
        auth: AuthContext,
        handoff_id: str,
        request: AgentHandoffCancelRequest,
        session: AsyncSession | None = None,
    ) -> AgentHandoffResponse:
        """Cancel a pending or active handoff with required reason and child transaction termination."""
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> AgentHandoffResponse:
            hnd_stmt = (
                select(AgentHandoff)
                .where(
                    AgentHandoff.id == handoff_id,
                    AgentHandoff.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            hnd_res = await s.execute(hnd_stmt)
            handoff = hnd_res.scalar_one_or_none()
            if not handoff:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent handoff '{handoff_id}' not found in tenant '{auth.tenant_id}'",
                )

            # Terminal states cannot be cancelled
            if is_terminal_handoff_status(handoff.status):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot cancel handoff in terminal status '{handoff.status}'",
                )

            # If child transaction was spawned, terminate it
            if handoff.child_transaction_id:
                child_stmt = (
                    select(AITransaction)
                    .where(
                        AITransaction.id == handoff.child_transaction_id,
                        AITransaction.tenant_id == auth.tenant_id,
                    )
                    .with_for_update()
                )
                child_res = await s.execute(child_stmt)
                child_txn = child_res.scalar_one_or_none()
                if child_txn and child_txn.state == "ACTIVE":
                    child_txn.state = "TERMINATED"
                    child_txn.final_disposition = "CANCELLED"
                    child_txn.updated_at = now

            handoff.status = HandoffStatus.CANCELLED.value
            handoff.cancelled_at = now
            handoff.cancellation_reason = request.reason
            handoff.updated_at = now
            await s.flush()

            await self._emit_audit_event(
                session=s,
                tenant_id=auth.tenant_id,
                action="AGENT_HANDOFF_CANCELLED",
                details={
                    "handoff_id": handoff.id,
                    "reason": request.reason,
                    "cancelled_by": auth.identity_id,
                },
            )

            return self._map_to_response(handoff)

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def complete_handoff(
        self,
        auth: AuthContext,
        handoff_id: str,
        session: AsyncSession | None = None,
    ) -> AgentHandoffResponse:
        """Mark an accepted handoff as completed following successful child execution & outcome assurance."""
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> AgentHandoffResponse:
            hnd_stmt = (
                select(AgentHandoff)
                .where(
                    AgentHandoff.id == handoff_id,
                    AgentHandoff.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            hnd_res = await s.execute(hnd_stmt)
            handoff = hnd_res.scalar_one_or_none()
            if not handoff:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent handoff '{handoff_id}' not found in tenant '{auth.tenant_id}'",
                )
            if handoff.status != HandoffStatus.ACCEPTED.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot complete handoff in non-ACCEPTED status '{handoff.status}'",
                )
            handoff.status = HandoffStatus.COMPLETED.value
            handoff.completed_at = now
            handoff.updated_at = now
            await s.flush()

            await self._emit_audit_event(
                session=s,
                tenant_id=auth.tenant_id,
                action="AGENT_HANDOFF_COMPLETED",
                details={
                    "handoff_id": handoff.id,
                    "child_transaction_id": handoff.child_transaction_id,
                    "completed_by": auth.identity_id,
                },
            )
            return self._map_to_response(handoff)

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def cancel_handoffs_for_parent_transaction(
        self,
        tenant_id: str,
        parent_transaction_id: str,
        reason: str,
        cancelled_by: str,
        session: AsyncSession,
    ) -> int:
        """Cancel all pending or accepted handoffs for a cancelled parent transaction."""
        now = datetime.now(UTC)
        stmt = (
            select(AgentHandoff)
            .where(
                AgentHandoff.tenant_id == tenant_id,
                AgentHandoff.parent_transaction_id == parent_transaction_id,
                AgentHandoff.status.in_([HandoffStatus.PENDING.value, HandoffStatus.ACCEPTED.value]),
            )
            .with_for_update()
        )
        res = await session.execute(stmt)
        handoffs = res.scalars().all()
        count = 0
        for hnd in handoffs:
            hnd.status = HandoffStatus.CANCELLED.value
            hnd.cancelled_at = now
            hnd.cancellation_reason = reason
            hnd.updated_at = now
            count += 1
            await self._emit_audit_event(
                session=session,
                tenant_id=tenant_id,
                action="AGENT_HANDOFF_CANCELLED",
                details={
                    "handoff_id": hnd.id,
                    "parent_transaction_id": parent_transaction_id,
                    "reason": reason,
                    "cancelled_by": cancelled_by,
                },
            )
        return count

    def _map_to_response(self, handoff: AgentHandoff) -> AgentHandoffResponse:
        return AgentHandoffResponse(
            id=handoff.id,
            tenant_id=handoff.tenant_id,
            parent_transaction_id=handoff.parent_transaction_id,
            parent_agent_id=handoff.parent_agent_id,
            child_agent_id=handoff.child_agent_id,
            delegation_id=handoff.delegation_id,
            child_transaction_id=handoff.child_transaction_id,
            status=HandoffStatus(handoff.status),
            purpose=handoff.purpose,
            permitted_scope=handoff.permitted_scope or {},
            inherited_taint_flags=list(handoff.inherited_taint_flags or []),
            idempotency_key=handoff.idempotency_key,
            expires_at=handoff.expires_at,
            accepted_at=handoff.accepted_at,
            completed_at=handoff.completed_at,
            cancelled_at=handoff.cancelled_at,
            cancellation_reason=handoff.cancellation_reason,
            created_at=handoff.created_at,
            updated_at=handoff.updated_at,
        )

    async def _emit_audit_event(
        self,
        session: AsyncSession,
        tenant_id: str,
        action: str,
        details: dict[str, Any],
    ) -> None:
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
        entry_id = f"aud_hnd_{uuid.uuid4().hex}"
        payload_str = f"{prev_hash}:{entry_id}:{action}:{now.isoformat()}:{tenant_id}"
        chain_hash = compute_sha256(payload_str)

        rec = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=seq,
            session_id=details.get("handoff_id", "handoff"),
            trace_id=f"handoff-{details.get('handoff_id', 'na')}",
            prompt_hash=compute_sha256(f"handoff:{action}"),
            response_hash=compute_sha256(action),
            hrs_score=0.0,
            risk_tier="GOVERNED_HANDOFF",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type=action,
            actor_identity_id=details.get("child_agent_id") or details.get("cancelled_by") or "system",
            transaction_id=details.get("parent_transaction_id"),
            decision="ALLOW",
            policy_reference="agent_handoff_governance",
            reason=details.get("reason", action),
            event_payload=details,
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
        session.add(rec)
        await session.flush()


handoff_service = AgentHandoffService()
