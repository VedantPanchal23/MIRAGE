"""Phase 3 Gate 3 Action Assurance, Tool Proxy, and Action Contract Governor Service."""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import (
    ActionApproval,
    ActionContract,
    AgentDelegation,
    AITransaction,
    Capability,
    OutcomeVerificationRecord,
    ResourceLease,
    ToolDefinition,
)
from services.agent_governance import agent_governance_service
from services.concurrency_service import canonicalize_resource_uri, concurrency_service
from services.delegation_service import delegation_service
from services.mcp_client import MCPExecutionUncertainError
from services.webhook_service import webhook_service
from shared.schemas.action import (
    ActionAuthorizationDecision,
    ActionBatchProposal,
    ActionExecutionRequest,
    ActionExecutionResult,
    ActionProposal,
    ActionReconciliationRequest,
    ActionState,
    ApprovalResponse,
    ApprovalStatus,
    BatchAuthorizationDecision,
    EgressType,
    PostconditionRule,
    PreconditionRule,
    StrandedActionInfo,
    ToolRegistrationRequest,
    ToolResponse,
    ToolTrustLevel,
    ToolType,
    compute_contract_binding_hash,
    compute_parameters_hash,
    normalize_action_parameters,
)
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.concurrency import LeaseStatus
from shared.schemas.control_plane import (
    Decision,
    Taint,
    is_dangerous_triad_active,
)
from shared.schemas.delegation import DelegationStatus
from shared.schemas.outcome import ObservabilityClass, OutcomeStatus

from .approvals import (
    deny_approval,
    grant_approval,
    list_pending_approvals,
    validate_and_consume_approval,
)
from .audit import _record_action_audit_event
from .budget import (
    evaluate_risk_and_salami_budget,
)
from .conditions import (
    build_outcome_assurance_contract,
    evaluate_postcondition,
    evaluate_precondition,
)
from .proxy import (
    GovernedToolProxy,
)
from .stranded import (
    list_stranded_actions,
    reconcile_stranded_action,
)

logger = logging.getLogger(__name__)


class ActionGovernorService:
    """Authoritative Gate 3 Action Governor enforcing capabilities, risk, DIFC, and tool execution."""

    def __init__(self) -> None:
        self.tool_proxy = GovernedToolProxy()

    # -------------------------------------------------------------------------
    # Tool Registry Operations
    # -------------------------------------------------------------------------

    async def register_tool(self, auth: AuthContext, req: ToolRegistrationRequest) -> ToolResponse:
        """Register or update a governed tool in the tenant tool registry."""
        if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tool registration and reconfiguration requires Administrator privileges.",
            )

        async with db_session.get_tenant_session(auth.tenant_id) as session:
            # Check for existing tool by tenant and name
            stmt = select(ToolDefinition).where(
                ToolDefinition.tenant_id == auth.tenant_id,
                ToolDefinition.name == req.name,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            now = datetime.now(UTC)
            if existing:
                if (
                    existing.egress_type == EgressType.EGRESS_EXTERNAL.value
                    and req.egress_type == EgressType.INTERNAL_ISOLATED
                    and auth.role != Role.SUPER_ADMIN
                ):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            "Security downgrade forbidden: Demoting EGRESS_EXTERNAL to INTERNAL_ISOLATED "
                            "requires Super Admin privileges."
                        ),
                    )

                existing.description = req.description
                existing.tool_type = req.tool_type.value
                existing.egress_type = req.egress_type.value
                existing.trust_level = req.trust_level.value
                existing.required_capability = req.required_capability
                existing.parameters_schema = req.parameters_schema
                existing.config = req.config
                existing.active = req.active
                existing.updated_at = now
                tool_record = existing
            else:
                tool_id = f"tool_{uuid.uuid4().hex[:16]}"
                tool_record = ToolDefinition(
                    id=tool_id,
                    tenant_id=auth.tenant_id,
                    name=req.name,
                    description=req.description,
                    tool_type=req.tool_type.value,
                    egress_type=req.egress_type.value,
                    trust_level=req.trust_level.value,
                    required_capability=req.required_capability,
                    parameters_schema=req.parameters_schema,
                    config=req.config,
                    active=req.active,
                    created_at=now,
                    updated_at=now,
                )
                session.add(tool_record)

            # Audit record
            await _record_action_audit_event(
                session=session,
                tenant_id=auth.tenant_id,
                event_type="TOOL_REGISTERED",
                actor_identity_id=auth.identity_id,
                decision="REGISTER",
                payload={
                    "tool_id": tool_record.id,
                    "name": tool_record.name,
                    "egress_type": tool_record.egress_type,
                    "required_capability": tool_record.required_capability,
                },
            )
            await session.flush()

            return ToolResponse(
                id=tool_record.id,
                tenant_id=tool_record.tenant_id,
                name=tool_record.name,
                description=tool_record.description,
                tool_type=ToolType(tool_record.tool_type),
                egress_type=EgressType(tool_record.egress_type),
                trust_level=ToolTrustLevel(tool_record.trust_level),
                required_capability=tool_record.required_capability,
                parameters_schema=tool_record.parameters_schema,
                active=tool_record.active,
                created_at=tool_record.created_at.isoformat(),
            )

    async def list_tools(self, auth: AuthContext, active_only: bool = True) -> list[ToolResponse]:
        """List registered tools for the caller's tenant."""
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            stmt = select(ToolDefinition).where(ToolDefinition.tenant_id == auth.tenant_id)
            if active_only:
                stmt = stmt.where(ToolDefinition.active.is_(True))
            result = await session.execute(stmt)
            tools = result.scalars().all()

            return [
                ToolResponse(
                    id=t.id,
                    tenant_id=t.tenant_id,
                    name=t.name,
                    description=t.description,
                    tool_type=ToolType(t.tool_type),
                    egress_type=EgressType(t.egress_type),
                    trust_level=ToolTrustLevel(t.trust_level),
                    required_capability=t.required_capability,
                    parameters_schema=t.parameters_schema,
                    active=t.active,
                    created_at=t.created_at.isoformat(),
                )
                for t in tools
            ]

    # -------------------------------------------------------------------------
    # Gate 3 Action Assurance & Authorization Evaluation
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Helper Subroutines for Gate 3 Action Assurance & Lifecycle Execution
    # -------------------------------------------------------------------------

    @staticmethod
    def _block_decision(
        reason: str,
        risk_score: int = 100,
        autonomy_level: int = 4,
        normalized_parameters: dict[str, Any] | None = None,
        parameters_hash: str = "",
        decision: Decision = Decision.BLOCK,
    ) -> ActionAuthorizationDecision:
        """Create a fail-closed blocked or denied ActionAuthorizationDecision."""
        return ActionAuthorizationDecision(
            action_id=f"act_err_{uuid.uuid4().hex[:8]}",
            decision=decision,
            state=ActionState.BLOCKED,
            reason=reason,
            risk_score=risk_score,
            autonomy_level=autonomy_level,
            normalized_parameters=normalized_parameters or {},
            parameters_hash=parameters_hash,
        )

    @staticmethod
    async def _evaluate_risk_and_salami_budget(
        session: Any,
        tenant_id: str,
        req: ActionProposal,
        tool: ToolDefinition,
        normalized_params: dict[str, Any],
        now: datetime,
    ) -> tuple[int, int, float, int, float, bool]:
        """Compute single-action risk, autonomy level, and cumulative blast radius budget."""
        return await evaluate_risk_and_salami_budget(
            session=session,
            tenant_id=tenant_id,
            req=req,
            tool=tool,
            normalized_params=normalized_params,
            now=now,
        )

    @staticmethod
    def _build_outcome_assurance_contract(
        req: ActionProposal,
        tool: ToolDefinition,
        single_action_risk: int,
        autonomy_level: int,
        effective_cost: float,
        requires_human_approval: bool,
    ) -> tuple[bool, dict[str, Any] | None, str | None]:
        """Validate and construct Gate 5 Outcome Assurance Contract specification."""
        return build_outcome_assurance_contract(
            req=req,
            tool=tool,
            single_action_risk=single_action_risk,
            autonomy_level=autonomy_level,
            effective_cost=effective_cost,
            requires_human_approval=requires_human_approval,
        )

    @staticmethod
    async def _resolve_active_fencing_token(
        session: Any,
        tenant_id: str,
        transaction_id: str,
        target_resource: str,
        now: datetime,
    ) -> int | None:
        """Resolve active fencing token if lease is held by current transaction (exact or governing parent)."""
        try:
            canonical_target = canonicalize_resource_uri(target_resource)
            lease_stmt = select(ResourceLease).where(
                ResourceLease.tenant_id == tenant_id,
                ResourceLease.holder_transaction_id == transaction_id,
                ResourceLease.status == LeaseStatus.ACQUIRED.value,
                ResourceLease.expires_at > now,
            )
            lease_res = await session.execute(lease_stmt)
            holder_leases = lease_res.scalars().all()
            best_match_lease: ResourceLease | None = None
            best_len = -1
            for hl in holder_leases:
                h_uri = hl.resource_uri
                if canonical_target == h_uri or canonical_target.startswith(h_uri.rstrip("/") + "/"):
                    if len(h_uri) > best_len:
                        best_len = len(h_uri)
                        best_match_lease = hl
            if best_match_lease:
                return best_match_lease.fencing_token
        except Exception:
            return None
        return None

    @staticmethod
    async def _revalidate_execution_delegation(
        session: AsyncSession,
        auth: AuthContext,
        transaction: AITransaction,
        contract: ActionContract,
        now: datetime,
    ) -> AgentDelegation | None:
        """Re-verify delegation grant and parent transaction at execution boundary for child transactions."""
        if transaction.parent_transaction_id is None:
            return None

        parent_stmt = select(AITransaction).where(
            AITransaction.id == transaction.parent_transaction_id,
            AITransaction.tenant_id == auth.tenant_id,
        )
        parent_res = await session.execute(parent_stmt)
        parent_txn = parent_res.scalar_one_or_none()
        if (
            not parent_txn
            or parent_txn.state
            in (
                "COMPLETED",
                "FAILED",
                "BLOCKED",
                "CANCELLED",
                "TIMEOUT",
                "PARTIAL",
                "TERMINATED",
            )
            or parent_txn.final_disposition in ("BLOCKED", "FAILED", "CANCELLED", "TIMEOUT")
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Execution blocked: Parent transaction '{transaction.parent_transaction_id}' "
                    f"is not active (state: {parent_txn.state if parent_txn else 'NOT_FOUND'}, "
                    f"disposition: {parent_txn.final_disposition if parent_txn else 'NONE'})."
                ),
            )

        del_stmt = (
            select(AgentDelegation)
            .where(
                AgentDelegation.tenant_id == auth.tenant_id,
                AgentDelegation.child_transaction_id == transaction.id,
            )
            .with_for_update()
        )
        del_res = await session.execute(del_stmt)
        delegation = del_res.scalar_one_or_none()
        if not delegation:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Execution blocked: Child transaction '{transaction.id}' has no bound delegation grant.",
            )
        if delegation.status != DelegationStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Execution blocked: Delegation grant '{delegation.id}' "
                    f"is not ACTIVE (current: {delegation.status})."
                ),
            )
        if delegation.expires_at <= now:
            delegation.status = DelegationStatus.EXPIRED.value
            await session.flush()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Execution blocked: Delegation grant '{delegation.id}' has expired.",
            )
        if delegation.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Execution blocked: Delegation grant '{delegation.id}' is revoked.",
            )
        if delegation.child_agent_id != contract.agent_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Execution blocked: Delegation child agent '{delegation.child_agent_id}' "
                    f"does not match contract agent '{contract.agent_id}'."
                ),
            )

        # Execution-time delegation revalidation (ancestor chain, scope, constraints)
        val_res = await delegation_service.validate_delegation_for_operation(
            auth=auth,
            delegation_id=delegation.id,
            capability_type=contract.required_capability,
            resource={"target_resource": contract.target_resource, **(contract.normalized_parameters or {})},
            requested_autonomy_level=min(4, contract.risk_score // 20),
            session=session,
        )
        if val_res.decision != Decision.ALLOW:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Execution blocked by delegation revalidation: {val_res.reason}",
            )

        return delegation

    @staticmethod
    async def _revalidate_execution_capability(
        session: Any,
        auth: AuthContext,
        transaction: AITransaction,
        contract: ActionContract,
        delegation: AgentDelegation | None,
        now: datetime,
    ) -> None:
        """Re-verify Actor still holds the required capability (Fail-closed on runtime revocation)."""
        cap_stmt = select(Capability).where(
            Capability.tenant_id == auth.tenant_id,
            Capability.capability_type == contract.required_capability,
            Capability.revoked_at.is_(None),
            (Capability.expires_at.is_(None) | (Capability.expires_at > now)),
        )
        if transaction.agent_id:
            cap_stmt = cap_stmt.where(
                (Capability.agent_id == transaction.agent_id) | (Capability.identity_id == auth.identity_id)
            )
        else:
            cap_stmt = cap_stmt.where(Capability.identity_id == auth.identity_id)

        cap_res = await session.execute(cap_stmt)
        active_caps = cap_res.scalars().all()
        if not active_caps:
            if delegation is not None:
                delegated_cap_dict = next(
                    (
                        c
                        for c in delegation.delegated_capabilities
                        if c.get("capability_type") == contract.required_capability
                    ),
                    None,
                )
                if not delegated_cap_dict:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Capability revoked or expired for required scope '{contract.required_capability}'. "
                            "Execution blocked."
                        ),
                    )
            elif (
                "*" in auth.capabilities
                or contract.required_capability in auth.capabilities
                or auth.role in (Role.SUPER_ADMIN, Role.TENANT_ADMIN)
            ):
                pass
            else:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Capability revoked or expired for required scope '{contract.required_capability}'. "
                        "Execution blocked."
                    ),
                )

    @staticmethod
    async def _validate_and_consume_approval(
        session: Any,
        auth: AuthContext,
        contract: ActionContract,
        now: datetime,
    ) -> None:
        """Validate single-use approval token and consume it atomically at execution boundary."""
        await validate_and_consume_approval(session=session, auth=auth, contract=contract, now=now)

    async def _pre_dispatch_and_commit_executing(
        self,
        auth: AuthContext,
        req: ActionExecutionRequest,
        now: datetime,
    ) -> tuple[ActionContract, ToolDefinition]:
        """Phase 1: Pre-dispatch authorization, validation, and durable commitment of EXECUTING state."""
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
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action contract not found")

            # Principal binding check: Prevent proposals authorized under one principal from being executed by another
            if auth.role != Role.SUPER_ADMIN:
                if auth.agent_id:
                    if contract.agent_id != auth.agent_id:
                        del_check = await session.execute(
                            select(AgentDelegation).where(
                                AgentDelegation.tenant_id == auth.tenant_id,
                                AgentDelegation.child_agent_id == auth.agent_id,
                                (AgentDelegation.child_transaction_id == contract.transaction_id)
                                | (AgentDelegation.parent_transaction_id == contract.transaction_id),
                                AgentDelegation.status == DelegationStatus.ACTIVE.value,
                            )
                        )
                        if not del_check.scalar_one_or_none():
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail="Principal mismatch: action contract was authorized for a different agent",
                            )
                elif auth.identity_id:
                    if auth.identity_id != contract.actor_identity_id:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Principal mismatch: action contract was authorized for a different actor",
                        )

            # Invariant: Action must not be in terminal or blocked states
            if contract.state == ActionState.BLOCKED.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Action contract is in state 'BLOCKED' and cannot be executed",
                )

            if contract.state == ActionState.EXECUTING.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Action contract is currently EXECUTING. "
                        "Retries are rejected to prevent duplicate external side effects."
                    ),
                )

            if contract.state == ActionState.EXECUTION_UNCERTAIN.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Action contract is in EXECUTION_UNCERTAIN state due to post-dispatch "
                        "persistence failure; operator reconciliation required before retry."
                    ),
                )

            if contract.state in (ActionState.COMPLETED.value, ActionState.EXECUTED.value):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Action contract is already executed (current: {contract.state})",
                )

            if contract.state != ActionState.AUTHORIZED.value:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Action is not in AUTHORIZED state (current: {contract.state})",
                )

            # Re-verify Parent Transaction Liveness & Status
            txn_stmt = select(AITransaction).where(
                AITransaction.tenant_id == auth.tenant_id,
                AITransaction.id == contract.transaction_id,
            )
            txn_res = await session.execute(txn_stmt)
            transaction = txn_res.scalar_one_or_none()
            if not transaction:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent transaction not found")
            if transaction.state in (
                "COMPLETED",
                "FAILED",
                "BLOCKED",
                "CANCELLED",
                "TIMEOUT",
                "PARTIAL",
            ) or transaction.final_disposition in ("BLOCKED", "FAILED", "CANCELLED", "TIMEOUT"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Parent transaction is in terminal/aborted state "
                        f"(state='{transaction.state}', disposition='{transaction.final_disposition}')"
                    ),
                )

            # Re-verify Initiating Agent Lifecycle State at Execution Boundary
            if contract.agent_id:
                is_eligible, reason = await agent_governance_service.evaluate_agent_eligibility(
                    session=session,
                    tenant_id=auth.tenant_id,
                    agent_id=contract.agent_id,
                )
                if not is_eligible:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Agent '{contract.agent_id}' is suspended, revoked, "
                            f"or inactive at execution time: {reason}"
                        ),
                    )

            # Re-verify Tool is still active in Registry
            tool_stmt = select(ToolDefinition).where(
                ToolDefinition.tenant_id == auth.tenant_id,
                ToolDefinition.id == contract.tool_id,
            )
            tool_res = await session.execute(tool_stmt)
            tool = tool_res.scalar_one_or_none()
            if not tool or not tool.active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Tool '{contract.tool_name}' is inactive or has been revoked in the registry.",
                )

            # Re-verify Delegation Grant and Parent Transaction at Execution Boundary for Child Transactions
            delegation = await self._revalidate_execution_delegation(
                session=session,
                auth=auth,
                transaction=transaction,
                contract=contract,
                now=now,
            )

            # Re-verify Actor still holds the required capability (Fail-closed on runtime revocation)
            await self._revalidate_execution_capability(
                session=session,
                auth=auth,
                transaction=transaction,
                contract=contract,
                delegation=delegation,
                now=now,
            )

            # Approval Replay & Tamper Defense:
            await self._validate_and_consume_approval(
                session=session,
                auth=auth,
                contract=contract,
                now=now,
            )

            # Concurrency & Fencing Token Execution Boundary Revalidation
            lease_val = await concurrency_service.validate_lease_for_action(
                tenant_id=auth.tenant_id,
                transaction_id=contract.transaction_id,
                target_resource=contract.target_resource,
                fencing_token=contract.fencing_token,
                session=session,
            )
            if lease_val.decision != Decision.ALLOW:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Execution blocked by concurrency fencing revalidation: {lease_val.reason}",
                )

            # Durable state transition committed before external side effects
            contract.state = ActionState.EXECUTING.value
            contract.executed_at = now
            await _record_action_audit_event(
                session=session,
                tenant_id=auth.tenant_id,
                event_type="ACTION_DISPATCH_STARTED",
                actor_identity_id=auth.identity_id,
                transaction_id=contract.transaction_id,
                decision="EXECUTING",
                reason="Pre-dispatch checks passed, state committed to EXECUTING before tool proxy dispatch.",
                payload={"action_id": contract.id, "tool": contract.tool_name},
            )
            return contract, tool

    async def propose_and_authorize_action(self, auth: AuthContext, req: ActionProposal) -> ActionAuthorizationDecision:
        """Evaluate Gate 3 Action Assurance for a proposed action contract."""
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            # 1. Verify parent transaction existence and tenancy
            txn_stmt = select(AITransaction).where(
                AITransaction.tenant_id == auth.tenant_id,
                AITransaction.id == req.transaction_id,
            )
            txn_res = await session.execute(txn_stmt)
            transaction = txn_res.scalar_one_or_none()
            if not transaction:
                now_utc = datetime.now(UTC)
                try:
                    async with session.begin_nested():
                        transaction = AITransaction(
                            id=req.transaction_id,
                            tenant_id=auth.tenant_id,
                            actor_identity_id=auth.identity_id or f"id_{auth.user_id}",
                            idempotency_key=f"idemp_{uuid.uuid4().hex[:12]}",
                            correlation_id=f"corr_{uuid.uuid4().hex[:12]}",
                            state="PROPOSED",
                            max_turns=5,
                            turn_count=1,
                            taint_flags=[],
                            context_sources=[],
                            created_at=now_utc,
                            updated_at=now_utc,
                        )
                        session.add(transaction)
                        await session.flush()
                except Exception:
                    scoped_id = f"{req.transaction_id}_{uuid.uuid4().hex[:8]}"
                    req.transaction_id = scoped_id
                    transaction = AITransaction(
                        id=scoped_id,
                        tenant_id=auth.tenant_id,
                        actor_identity_id=auth.identity_id or f"id_{auth.user_id}",
                        idempotency_key=f"idemp_{uuid.uuid4().hex[:12]}",
                        correlation_id=f"corr_{uuid.uuid4().hex[:12]}",
                        state="PROPOSED",
                        max_turns=5,
                        turn_count=1,
                        taint_flags=[],
                        context_sources=[],
                        created_at=now_utc,
                        updated_at=now_utc,
                    )
                    session.add(transaction)
                    await session.flush()
            # Verify caller authorization for parent transaction
            if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR):
                if auth.agent_id:
                    if transaction.agent_id != auth.agent_id:
                        del_check = await session.execute(
                            select(AgentDelegation).where(
                                AgentDelegation.tenant_id == auth.tenant_id,
                                AgentDelegation.child_agent_id == auth.agent_id,
                                (AgentDelegation.child_transaction_id == transaction.id)
                                | (AgentDelegation.parent_transaction_id == transaction.id),
                                AgentDelegation.status == DelegationStatus.ACTIVE.value,
                            )
                        )
                        if not del_check.scalar_one_or_none():
                            return ActionAuthorizationDecision(
                                action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                                decision=Decision.BLOCK,
                                state=ActionState.BLOCKED,
                                reason=(
                                    f"Authenticated agent '{auth.agent_id}' is not authorized for transaction "
                                    f"'{transaction.id}' (owned by agent '{transaction.agent_id}')"
                                ),
                                risk_score=100,
                                autonomy_level=4,
                                normalized_parameters={},
                                parameters_hash="",
                            )
                elif auth.identity_id:
                    if transaction.actor_identity_id != auth.identity_id:
                        return ActionAuthorizationDecision(
                            action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                            decision=Decision.BLOCK,
                            state=ActionState.BLOCKED,
                            reason=(
                                f"Authenticated actor '{auth.identity_id}' is not authorized for transaction "
                                f"'{transaction.id}' (owned by actor '{transaction.actor_identity_id}')"
                            ),
                            risk_score=100,
                            autonomy_level=4,
                            normalized_parameters={},
                            parameters_hash="",
                        )

            # Check initiating agent lifecycle eligibility
            if transaction.agent_id:
                is_eligible, _ = await agent_governance_service.evaluate_agent_eligibility(
                    session=session,
                    tenant_id=auth.tenant_id,
                    agent_id=transaction.agent_id,
                )
                if not is_eligible:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason=(
                            f"Initiating agent '{transaction.agent_id}' is not eligible to propose actions "
                            f"(suspended, revoked, or inactive)"
                        ),
                        risk_score=100,
                        autonomy_level=4,
                        normalized_parameters={},
                        parameters_hash="",
                    )

            # Check idempotency for existing action contract
            existing_act_stmt = select(ActionContract).where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.idempotency_key == req.idempotency_key,
            )
            existing_act_res = await session.execute(existing_act_stmt)
            existing_contract = existing_act_res.scalar_one_or_none()
            if existing_contract:
                # Semantic mismatch check: reject key reuse for materially different action semantics
                if (
                    existing_contract.transaction_id != req.transaction_id
                    or existing_contract.tool_name != req.tool_name
                    or existing_contract.action_type != req.action_type.value
                    or existing_contract.target_resource != req.target_resource
                ):
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason="Idempotency key reuse across materially different action semantics is prohibited",
                        risk_score=100,
                        autonomy_level=4,
                        normalized_parameters={},
                        parameters_hash="",
                    )
                dec = (
                    Decision.ALLOW
                    if existing_contract.state in (ActionState.AUTHORIZED, ActionState.COMPLETED)
                    else Decision.BLOCK
                )
                return ActionAuthorizationDecision(
                    action_id=existing_contract.id,
                    decision=dec,
                    state=ActionState(existing_contract.state),
                    reason="Idempotent replay of previously evaluated action contract",
                    risk_score=existing_contract.risk_score,
                    autonomy_level=min(4, existing_contract.risk_score // 20),
                    normalized_parameters=existing_contract.normalized_parameters,
                    parameters_hash=existing_contract.parameters_hash,
                    approval_id=existing_contract.approval_id,
                )

            # 2. Look up tool in tenant registry
            tool_stmt = select(ToolDefinition).where(
                ToolDefinition.tenant_id == auth.tenant_id,
                ToolDefinition.name == req.tool_name,
            )
            tool_res = await session.execute(tool_stmt)
            tool = tool_res.scalar_one_or_none()
            if not tool:
                return ActionAuthorizationDecision(
                    action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                    decision=Decision.BLOCK,
                    state=ActionState.BLOCKED,
                    reason=f"Tool '{req.tool_name}' is not registered in tenant tool registry",
                    risk_score=90,
                    autonomy_level=4,
                    normalized_parameters={},
                    parameters_hash="",
                )

            if not tool.active:
                return ActionAuthorizationDecision(
                    action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                    decision=Decision.BLOCK,
                    state=ActionState.BLOCKED,
                    reason=f"Tool '{req.tool_name}' has been suspended or revoked at runtime",
                    risk_score=90,
                    autonomy_level=4,
                    normalized_parameters={},
                    parameters_hash="",
                )

            # 3. Action Parameter Normalization & Validation
            try:
                normalized_params = normalize_action_parameters(req.parameters)
            except ValueError as val_err:
                return ActionAuthorizationDecision(
                    action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                    decision=Decision.BLOCK,
                    state=ActionState.BLOCKED,
                    reason=f"Parameter normalization security violation: {val_err}",
                    risk_score=100,
                    autonomy_level=4,
                    normalized_parameters={},
                    parameters_hash="",
                )

            # Schema required fields check
            if tool.parameters_schema and "required" in tool.parameters_schema:
                required_fields = tool.parameters_schema.get("required", [])
                missing = [f for f in required_fields if f not in normalized_params]
                if missing:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason=f"Parameters missing required schema fields: {missing}",
                        risk_score=70,
                        autonomy_level=3,
                        normalized_parameters=normalized_params,
                        parameters_hash=compute_parameters_hash(normalized_params),
                    )

            params_hash = compute_parameters_hash(normalized_params)

            # 4. Cross-Agent Delegation Resolution & Verification for Child Transactions
            delegation: AgentDelegation | None = None
            if transaction.parent_transaction_id is not None:
                # 4a. Check Parent Transaction Liveness
                parent_stmt = select(AITransaction).where(
                    AITransaction.id == transaction.parent_transaction_id,
                    AITransaction.tenant_id == auth.tenant_id,
                )
                parent_res = await session.execute(parent_stmt)
                parent_txn = parent_res.scalar_one_or_none()
                if (
                    not parent_txn
                    or parent_txn.state
                    in (
                        "COMPLETED",
                        "FAILED",
                        "BLOCKED",
                        "CANCELLED",
                        "TIMEOUT",
                        "PARTIAL",
                        "TERMINATED",
                    )
                    or parent_txn.final_disposition in ("BLOCKED", "FAILED", "CANCELLED", "TIMEOUT")
                ):
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason=(
                            f"Parent transaction '{transaction.parent_transaction_id}' is not active "
                            f"(state: {parent_txn.state if parent_txn else 'NOT_FOUND'}, "
                            f"disposition: {parent_txn.final_disposition if parent_txn else 'NONE'}); "
                            "child action execution prohibited"
                        ),
                        risk_score=100,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )

                del_stmt = select(AgentDelegation).where(
                    AgentDelegation.tenant_id == auth.tenant_id,
                    AgentDelegation.child_transaction_id == transaction.id,
                )
                del_res = await session.execute(del_stmt)
                delegation = del_res.scalar_one_or_none()
                if not delegation:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason=f"Child transaction '{transaction.id}' has no bound delegation grant",
                        risk_score=100,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )
                if delegation.status != DelegationStatus.ACTIVE.value:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason=f"Delegation grant '{delegation.id}' is not ACTIVE (current: {delegation.status})",
                        risk_score=100,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )
                now_utc = datetime.now(UTC)
                if delegation.expires_at <= now_utc or delegation.revoked_at is not None:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason=f"Delegation grant '{delegation.id}' has expired or is revoked",
                        risk_score=100,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )
                if delegation.child_agent_id != transaction.agent_id:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason=(
                            f"Delegation grant child agent '{delegation.child_agent_id}' does not match "
                            f"transaction agent '{transaction.agent_id}'"
                        ),
                        risk_score=100,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )
                if delegation.parent_transaction_id != transaction.parent_transaction_id:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason="Delegation grant parent transaction does not match child transaction parent",
                        risk_score=100,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )

                # Validate delegation operation via DelegationService (status, ancestor chain, scope, constraints)
                pol_decision = await delegation_service.validate_delegation_for_operation(
                    auth=auth,
                    delegation_id=delegation.id,
                    capability_type=tool.required_capability,
                    resource={"target_resource": req.target_resource, **normalized_params},
                    requested_autonomy_level=0,  # preliminary check; autonomy level ceiling evaluated in risk section
                    session=session,
                )
                if pol_decision.decision == Decision.DENY:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.DENY,
                        state=ActionState.BLOCKED,
                        reason=f"Delegation policy denial: {pol_decision.reason}",
                        risk_score=95,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )

            # 4b. Shared-Resource Concurrency & Lease Conflict Validation
            lease_check = await concurrency_service.validate_lease_for_action(
                tenant_id=auth.tenant_id,
                transaction_id=req.transaction_id,
                target_resource=req.target_resource,
                session=session,
            )
            if lease_check.decision != Decision.ALLOW:
                return ActionAuthorizationDecision(
                    action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                    decision=Decision.BLOCK,
                    state=ActionState.BLOCKED,
                    reason=f"Resource concurrency denial: {lease_check.reason}",
                    risk_score=90,
                    autonomy_level=4,
                    normalized_parameters=normalized_params,
                    parameters_hash=params_hash,
                )

            # 5. Capability Authorization
            now = datetime.now(UTC)
            cap_stmt = select(Capability).where(
                Capability.tenant_id == auth.tenant_id,
                Capability.capability_type == tool.required_capability,
                Capability.revoked_at.is_(None),
                (Capability.expires_at.is_(None) | (Capability.expires_at > now)),
            )
            # Match identity or agent
            if transaction.agent_id:
                cap_stmt = cap_stmt.where(
                    (Capability.agent_id == transaction.agent_id) | (Capability.identity_id == auth.identity_id)
                )
            else:
                cap_stmt = cap_stmt.where(Capability.identity_id == auth.identity_id)

            cap_res = await session.execute(cap_stmt)
            granted_capabilities = cap_res.scalars().all()

            matching_cap: Any = None
            if granted_capabilities:
                matching_cap = granted_capabilities[0]
            elif (
                "*" in auth.capabilities
                or tool.required_capability in auth.capabilities
                or auth.role in (Role.SUPER_ADMIN, Role.TENANT_ADMIN)
            ):
                from types import SimpleNamespace

                matching_cap = SimpleNamespace(
                    constraints={},
                    resource_scope={},
                    max_autonomy_level=4,
                )

            if delegation is not None:
                delegated_cap_dict = next(
                    (
                        c
                        for c in delegation.delegated_capabilities
                        if c.get("capability_type") == tool.required_capability
                    ),
                    None,
                )
                if not delegated_cap_dict and matching_cap is None:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.DENY,
                        state=ActionState.BLOCKED,
                        reason=f"Missing capability: Delegated scope lacks capability '{tool.required_capability}'",
                        risk_score=85,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )
                if delegated_cap_dict:
                    cap_constraints = delegated_cap_dict.get("constraints") or {}
                    cap_scope = delegated_cap_dict.get("resource_scope") or {}
                    cap_autonomy = min(
                        delegation.max_autonomy_level,
                        delegated_cap_dict.get("max_autonomy_level", 0),
                    )
                    if matching_cap is not None:
                        cap_autonomy = min(cap_autonomy, matching_cap.max_autonomy_level)
                    from types import SimpleNamespace

                    matching_cap = SimpleNamespace(
                        constraints=cap_constraints
                        if matching_cap is None
                        else {**(matching_cap.constraints or {}), **cap_constraints},
                        resource_scope=cap_scope
                        if matching_cap is None
                        else {**(matching_cap.resource_scope or {}), **cap_scope},
                        max_autonomy_level=cap_autonomy,
                    )
            elif matching_cap is None:
                return ActionAuthorizationDecision(
                    action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                    decision=Decision.DENY,
                    state=ActionState.BLOCKED,
                    reason=(
                        f"Missing capability: Actor '{auth.identity_id}' lacks active capability "
                        f"'{tool.required_capability}'"
                    ),
                    risk_score=85,
                    autonomy_level=4,
                    normalized_parameters=normalized_params,
                    parameters_hash=params_hash,
                )

            # Check capability constraints (e.g., allowed resource prefixes, max limits)
            constraints = matching_cap.constraints or {}
            resource_scope = matching_cap.resource_scope or {}

            # Scope check
            if "allowed_prefixes" in resource_scope:
                allowed_pfx = resource_scope["allowed_prefixes"]
                if not any(req.target_resource.startswith(pfx) for pfx in allowed_pfx):
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.DENY,
                        state=ActionState.BLOCKED,
                        reason=(
                            f"Capability scope violation: Target '{req.target_resource}' "
                            f"not permitted by scope {allowed_pfx}"
                        ),
                        risk_score=85,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )

            if "max_amount" in constraints:
                param_amt = normalized_params.get("amount")
                if isinstance(param_amt, (int, float)) and param_amt > constraints["max_amount"]:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.DENY,
                        state=ActionState.BLOCKED,
                        reason=(
                            f"Capability constraint violation: parameter 'amount' ({param_amt}) "
                            f"exceeds constraint ({constraints['max_amount']})"
                        ),
                        risk_score=90,
                        autonomy_level=4,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )

            # 5. Dynamic Information Flow Control (DIFC) & Dangerous Triad Interlock
            # Check if untrusted content and secret/confidential data coexist
            active_taints = set(transaction.taint_flags or [])
            if tool.egress_type == EgressType.EGRESS_EXTERNAL.value and is_dangerous_triad_active(active_taints):
                return ActionAuthorizationDecision(
                    action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                    decision=Decision.BLOCK,
                    state=ActionState.BLOCKED,
                    reason=(
                        "Dangerous Triad Interlock: External egress prohibited when TAINT_UNTRUSTED "
                        "and confidential/secret taints coexist in transaction context."
                    ),
                    risk_score=100,
                    autonomy_level=4,
                    normalized_parameters=normalized_params,
                    parameters_hash=params_hash,
                )

            # 6. Precondition Evaluation
            for precond in req.preconditions:
                passed = self._evaluate_precondition(precond, normalized_params, req.target_resource)
                if not passed:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.BLOCK,
                        state=ActionState.BLOCKED,
                        reason=f"Precondition failed: {precond.check_type} on target '{precond.target}'",
                        risk_score=60,
                        autonomy_level=2,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )

            # 7. Action Risk Model Calculation & Salami-Slicing Budget Evaluation
            (
                single_action_risk,
                autonomy_level,
                effective_cost,
                window_risk,
                window_cost,
                is_salami_violation,
            ) = await self._evaluate_risk_and_salami_budget(
                session=session,
                tenant_id=auth.tenant_id,
                req=req,
                tool=tool,
                normalized_params=normalized_params,
                now=now,
            )

            # Autonomy level threshold check
            requires_human_approval = (
                autonomy_level >= 4
                or single_action_risk >= 80
                or is_salami_violation
                or (autonomy_level > matching_cap.max_autonomy_level)
            )

            if delegation is not None:
                del_autonomy_check = await delegation_service.validate_delegation_for_operation(
                    auth=auth,
                    delegation_id=delegation.id,
                    capability_type=tool.required_capability,
                    resource={"target_resource": req.target_resource, **normalized_params},
                    requested_autonomy_level=autonomy_level,
                    session=session,
                )
                if del_autonomy_check.decision == Decision.DENY:
                    return ActionAuthorizationDecision(
                        action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                        decision=Decision.DENY,
                        state=ActionState.BLOCKED,
                        reason=f"Delegation policy denial: {del_autonomy_check.reason}",
                        risk_score=single_action_risk,
                        autonomy_level=autonomy_level,
                        normalized_parameters=normalized_params,
                        parameters_hash=params_hash,
                    )
                elif del_autonomy_check.decision == Decision.REQUIRE_APPROVAL:
                    requires_human_approval = True

            # Phase 6: Outcome Assurance Contract Validation
            (
                requires_outcome_assurance,
                outcome_contract_dict,
                contract_error,
            ) = self._build_outcome_assurance_contract(
                req=req,
                tool=tool,
                single_action_risk=single_action_risk,
                autonomy_level=autonomy_level,
                effective_cost=effective_cost,
                requires_human_approval=requires_human_approval,
            )
            if contract_error:
                return self._block_decision(
                    contract_error,
                    risk_score=single_action_risk,
                    autonomy_level=autonomy_level,
                    normalized_parameters=normalized_params,
                    parameters_hash=params_hash,
                )

            action_id = f"act_{uuid.uuid4().hex[:16]}"
            approval_id: str | None = None

            blast_radius_dict = req.blast_radius.model_dump()
            blast_radius_dict["estimated_dollar_cost"] = effective_cost

            contract_binding_hash = compute_contract_binding_hash(
                tenant_id=auth.tenant_id,
                transaction_id=req.transaction_id,
                action_id=action_id,
                tool_name=tool.name,
                action_type=req.action_type.value,
                target_resource=req.target_resource,
                parameters_hash=params_hash,
                required_capability=tool.required_capability,
                estimated_dollar_cost=effective_cost,
                taint_flags=list(active_taints),
            )

            if requires_human_approval:
                final_decision = Decision.REQUIRE_APPROVAL
                final_state = ActionState.AWAITING_APPROVAL
                approval_id = f"appr_{uuid.uuid4().hex[:16]}"
                decision_reason = (
                    "Salami-slicing threshold exceeded: cumulative 1-hour blast radius budget reached; "
                    "human approval required."
                    if is_salami_violation
                    else "High-risk action (L4 autonomy); explicit human sign-off required."
                )
            else:
                final_decision = Decision.ALLOW
                final_state = ActionState.AUTHORIZED
                decision_reason = "Action authorized: capabilities verified, preconditions passed, risk within budget."

            # Resolve active fencing token if lease is held by current transaction (exact or governing parent)
            active_fencing_token = await self._resolve_active_fencing_token(
                session=session,
                tenant_id=auth.tenant_id,
                transaction_id=req.transaction_id,
                target_resource=req.target_resource,
                now=now,
            )

            # Create Action Contract Record first (breaking circular FK with action_approvals)
            action_contract = ActionContract(
                id=action_id,
                tenant_id=auth.tenant_id,
                transaction_id=req.transaction_id,
                actor_identity_id=auth.identity_id,
                agent_id=transaction.agent_id,
                tool_id=tool.id,
                tool_name=tool.name,
                action_type=req.action_type.value,
                target_resource=req.target_resource,
                parameters=req.parameters,
                normalized_parameters=normalized_params,
                parameters_hash=contract_binding_hash,
                required_capability=tool.required_capability,
                taint_flags=list(active_taints),
                risk_score=single_action_risk,
                blast_radius=blast_radius_dict,
                state=final_state.value,
                idempotency_key=req.idempotency_key,
                fencing_token=active_fencing_token,
                preconditions=[p.model_dump() for p in req.preconditions],
                postconditions=[p.model_dump() for p in req.postconditions],
                requires_outcome_assurance=requires_outcome_assurance,
                outcome_contract=outcome_contract_dict,
                outcome_status=OutcomeStatus.PENDING_VERIFICATION.value if requires_outcome_assurance else None,
                approval_id=None,
                created_at=now,
                authorized_at=now if final_state == ActionState.AUTHORIZED else None,
            )
            session.add(action_contract)
            await session.flush()

            # If approval required, create approval ticket referencing existing action_contract
            if requires_human_approval and approval_id:
                approval_record = ActionApproval(
                    id=approval_id,
                    tenant_id=auth.tenant_id,
                    action_id=action_id,
                    transaction_id=req.transaction_id,
                    required_role=Role.SUPER_ADMIN.value,
                    status=ApprovalStatus.PENDING.value,
                    parameters_hash=contract_binding_hash,
                    requested_by=auth.identity_id,
                    expires_at=now + timedelta(minutes=15),
                    created_at=now,
                )
                session.add(approval_record)
                await session.flush()
                action_contract.approval_id = approval_id

            # Audit log
            await _record_action_audit_event(
                session=session,
                tenant_id=auth.tenant_id,
                event_type="ACTION_EVALUATED",
                actor_identity_id=auth.identity_id,
                transaction_id=req.transaction_id,
                decision=final_decision.value,
                reason=decision_reason,
                payload={
                    "action_id": action_id,
                    "tool": tool.name,
                    "risk_score": single_action_risk,
                    "autonomy_level": autonomy_level,
                    "is_salami_violation": is_salami_violation,
                    "approval_id": approval_id,
                },
            )
            await session.flush()

            if requires_human_approval:
                await webhook_service.dispatch_event(
                    tenant_id=auth.tenant_id,
                    event_type="ACTION_AWAITING_APPROVAL",
                    payload={
                        "action_id": action_id,
                        "transaction_id": req.transaction_id,
                        "tool_name": tool.name,
                        "risk_score": single_action_risk,
                        "approval_id": approval_id,
                        "reason": decision_reason,
                    },
                )
            elif final_decision in (Decision.BLOCK, Decision.DENY):
                await webhook_service.dispatch_event(
                    tenant_id=auth.tenant_id,
                    event_type="ACTION_BLOCKED",
                    payload={
                        "action_id": action_id,
                        "transaction_id": req.transaction_id,
                        "tool_name": tool.name,
                        "risk_score": single_action_risk,
                        "reason": decision_reason,
                    },
                )

            return ActionAuthorizationDecision(
                action_id=action_id,
                decision=final_decision,
                state=final_state,
                reason=decision_reason,
                risk_score=single_action_risk,
                autonomy_level=autonomy_level,
                normalized_parameters=normalized_params,
                parameters_hash=params_hash,
                approval_id=approval_id,
                cumulative_window_risk=window_risk,
                cumulative_window_cost=window_cost,
                is_salami_slice_violation=is_salami_violation,
                fencing_token=active_fencing_token,
            )

    # -------------------------------------------------------------------------
    # Atomic Batch Actions
    # -------------------------------------------------------------------------

    async def propose_and_authorize_batch(
        self, auth: AuthContext, batch_req: ActionBatchProposal
    ) -> BatchAuthorizationDecision:
        """Evaluate an atomic batch of parallel action proposals with all-or-nothing semantics."""
        decisions: list[ActionAuthorizationDecision] = []
        for prop in batch_req.actions:
            dec = await self.propose_and_authorize_action(auth, prop)
            decisions.append(dec)

        # Batch Atomicity Evaluation:
        # If ANY action is BLOCKED or DENIED -> Whole batch is BLOCKED
        has_block_or_deny = any(d.decision in (Decision.BLOCK, Decision.DENY) for d in decisions)
        has_approval_required = any(d.decision == Decision.REQUIRE_APPROVAL for d in decisions)

        if has_block_or_deny:
            batch_decision = Decision.BLOCK
            batch_reason = "Atomic batch rejected: one or more actions were blocked or denied."
            # Set all authorized actions in this batch to BLOCKED in database
            async with db_session.get_tenant_session(auth.tenant_id) as session:
                for d in decisions:
                    if d.action_id.startswith("act_") and not d.action_id.startswith("act_err"):
                        stmt = select(ActionContract).where(
                            ActionContract.tenant_id == auth.tenant_id,
                            ActionContract.id == d.action_id,
                        )
                        res = await session.execute(stmt)
                        contract = res.scalar_one_or_none()
                        if contract:
                            contract.state = ActionState.BLOCKED.value
                await session.flush()
            for d in decisions:
                d.state = ActionState.BLOCKED
        elif has_approval_required:
            batch_decision = Decision.REQUIRE_APPROVAL
            batch_reason = "Atomic batch paused: one or more actions require human approval."
        else:
            batch_decision = Decision.ALLOW
            batch_reason = "Atomic batch fully authorized: all actions passed Gate 3 assurance."

        return BatchAuthorizationDecision(
            transaction_id=batch_req.transaction_id,
            batch_decision=batch_decision,
            batch_reason=batch_reason,
            actions=decisions,
        )

    # -------------------------------------------------------------------------
    # Human Approval Workflow (L4)
    # -------------------------------------------------------------------------

    async def grant_approval(self, auth: AuthContext, approval_id: str, reason: str) -> ApprovalResponse:
        """Grant a pending human approval. Agents cannot self-grant approvals."""
        return await grant_approval(auth=auth, approval_id=approval_id, reason=reason)

    async def deny_approval(self, auth: AuthContext, approval_id: str, reason: str) -> ApprovalResponse:
        """Deny a pending human approval."""
        return await deny_approval(auth=auth, approval_id=approval_id, reason=reason)

    async def list_pending_approvals(self, auth: AuthContext) -> list[ApprovalResponse]:
        """List active pending approvals for the caller's tenant."""
        return await list_pending_approvals(auth=auth)

    # -------------------------------------------------------------------------
    # Tool Proxy Execution
    # -------------------------------------------------------------------------

    async def execute_action(self, auth: AuthContext, req: ActionExecutionRequest) -> ActionExecutionResult:
        """Execute an authorized action contract strictly through the Governed Tool Proxy
        using a durable execution protocol.
        """
        now = datetime.now(UTC)

        # ---------------------------------------------------------------------
        # Phase 1: Pre-dispatch authorization, validation, and durable commitment of EXECUTING state
        # ---------------------------------------------------------------------
        contract, tool = await self._pre_dispatch_and_commit_executing(auth, req, now)

        # ---------------------------------------------------------------------
        # Phase 2: Dispatch strictly via Governed Tool Proxy
        # ---------------------------------------------------------------------
        try:
            observed_output, error_msg = await self.tool_proxy.dispatch(
                contract=contract,
                auth=auth,
            )
        except MCPExecutionUncertainError as uncert_err:
            logger.warning("Remote MCP tool dispatch execution uncertain for action %s: %s", req.action_id, uncert_err)
            async with db_session.get_tenant_session(auth.tenant_id) as u_session:
                u_stmt = (
                    select(ActionContract)
                    .where(
                        ActionContract.tenant_id == auth.tenant_id,
                        ActionContract.id == req.action_id,
                    )
                    .with_for_update()
                )
                u_contract = (await u_session.execute(u_stmt)).scalar_one_or_none()
                if u_contract:
                    u_contract.state = ActionState.EXECUTION_UNCERTAIN.value
                    u_contract.error_message = str(uncert_err)
                    u_contract.completed_at = datetime.now(UTC)
                await _record_action_audit_event(
                    session=u_session,
                    tenant_id=auth.tenant_id,
                    event_type="ACTION_EXECUTION_UNCERTAIN",
                    actor_identity_id=auth.identity_id,
                    transaction_id=contract.transaction_id,
                    decision="EXECUTION_UNCERTAIN",
                    reason=f"Remote MCP tool dispatch uncertain: {uncert_err}",
                    payload={"action_id": req.action_id, "error": str(uncert_err)},
                )
                await u_session.commit()
            return ActionExecutionResult(
                action_id=contract.id,
                transaction_id=contract.transaction_id,
                state=ActionState.EXECUTION_UNCERTAIN,
                observed_output={"status": "uncertain", "error": str(uncert_err)},
                taints={Taint.UNTRUSTED},
                postconditions_satisfied=False,
                error_message=str(uncert_err),
            )

        # ---------------------------------------------------------------------
        # Phase 3: Post-dispatch outcome persistence & state finalization
        # ---------------------------------------------------------------------
        try:
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
                contract_record = res.scalar_one_or_none()
                if not contract_record:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action contract not found")
                contract = contract_record

                txn_stmt = (
                    select(AITransaction)
                    .where(
                        AITransaction.tenant_id == auth.tenant_id,
                        AITransaction.id == contract.transaction_id,
                    )
                    .with_for_update()
                )
                transaction = (await session.execute(txn_stmt)).scalar_one_or_none()

                # Postcondition Evaluation against Tool Return Value
                postconditions_ok = True
                evidence_records: list[dict[str, Any]] = []
                postconds = [PostconditionRule(**p) for p in (contract.postconditions or [])]

                for post in postconds:
                    satisfied, ev = self._evaluate_postcondition(post, observed_output)
                    evidence_records.append(ev)
                    if not satisfied:
                        postconditions_ok = False

                outcome_id: str | None = None
                if error_msg:
                    final_state = ActionState.FAILED
                    contract.outcome_status = OutcomeStatus.VERIFIED_FAILURE.value
                elif contract.requires_outcome_assurance:
                    final_state = ActionState.EXECUTED
                    contract.outcome_status = OutcomeStatus.PENDING_VERIFICATION.value

                    deadline_sec = 30.0
                    if contract.outcome_contract and isinstance(contract.outcome_contract, dict):
                        deadline_sec = float(contract.outcome_contract.get("verification_deadline_seconds", 30.0))

                    outcome_id = f"outc_{uuid.uuid4().hex[:12]}"
                    target_env = (
                        contract.blast_radius.get("target_environment", "DEFAULT")
                        if isinstance(contract.blast_radius, dict)
                        else "DEFAULT"
                    )

                    expected_posts: dict[str, Any] = {}
                    if contract.postconditions and isinstance(contract.postconditions, list):
                        for p in contract.postconditions:
                            if isinstance(p, dict) and "target" in p:
                                expected_posts[p["target"]] = p.get("expected_value")

                    outcome_record = OutcomeVerificationRecord(
                        id=outcome_id,
                        tenant_id=auth.tenant_id,
                        transaction_id=contract.transaction_id,
                        action_id=contract.id,
                        observability_class=ObservabilityClass.OBS_DIRECT.value,
                        outcome_status=OutcomeStatus.PENDING_VERIFICATION.value,
                        epistemic_confidence=0.0,
                        verifier_adapter="PENDING_INDEPENDENT_OBSERVATION",
                        is_simulated=False,
                        expected_postconditions=expected_posts,
                        observed_state={},
                        discrepancies=[],
                        evidence_payload={"transport_ack": observed_output, "dispatch_status": "EXECUTED"},
                        reconciliation_notes=[
                            "Action dispatched via tool proxy; awaiting independent target-state observation."
                        ],
                        verification_hash=compute_sha256(f"{auth.tenant_id}:{contract.id}:PENDING_VERIFICATION"),
                        idempotency_key=f"idem_outc_{contract.id}_pending",
                        target_environment=target_env,
                        contract_binding_hash=contract.parameters_hash,
                        verification_deadline=now + timedelta(seconds=deadline_sec),
                        created_at=now,
                        verified_at=now,
                    )
                    session.add(outcome_record)
                    postconditions_ok = False
                else:
                    final_state = ActionState.COMPLETED if postconditions_ok else ActionState.FAILED
                    contract.outcome_status = None

                contract.state = final_state.value
                contract.observed_result = observed_output
                contract.error_message = error_msg
                contract.completed_at = datetime.now(UTC)

                # Append Tool Observation Context Source to parent transaction
                if transaction:
                    sources = list(transaction.context_sources or [])
                    sources.append(
                        {
                            "id": f"ctx_tool_{uuid.uuid4().hex[:12]}",
                            "source_type": "TOOL_OBSERVATION",
                            "tool_name": contract.tool_name,
                            "target_resource": contract.target_resource,
                            "content": json.dumps(observed_output, default=str),
                            "trust_score": 0.6,
                            "taints": [Taint.UNTRUSTED.value],
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )
                    transaction.context_sources = sources
                    curr_taints = set(transaction.taint_flags or [])
                    curr_taints.add(Taint.UNTRUSTED.value)
                    transaction.taint_flags = list(curr_taints)

                # Audit record
                await _record_action_audit_event(
                    session=session,
                    tenant_id=auth.tenant_id,
                    event_type="ACTION_EXECUTED",
                    actor_identity_id=auth.identity_id,
                    transaction_id=contract.transaction_id,
                    decision=final_state.value,
                    payload={
                        "action_id": contract.id,
                        "tool": contract.tool_name,
                        "state": final_state.value,
                        "requires_outcome_assurance": contract.requires_outcome_assurance,
                        "outcome_status": contract.outcome_status,
                        "outcome_id": outcome_id,
                    },
                )
                await session.flush()

                return ActionExecutionResult(
                    action_id=contract.id,
                    transaction_id=contract.transaction_id,
                    state=final_state,
                    observed_output=observed_output,
                    taints={Taint.UNTRUSTED},
                    postconditions_satisfied=postconditions_ok,
                    postcondition_evidence=evidence_records,
                    error_message=error_msg,
                    outcome_status=OutcomeStatus(contract.outcome_status) if contract.outcome_status else None,
                    outcome_id=outcome_id,
                    requires_outcome_assurance=contract.requires_outcome_assurance,
                )
        except Exception as post_err:
            logger.error("Post-dispatch persistence failure for action %s: %s", req.action_id, post_err)
            try:
                async with db_session.get_tenant_session(auth.tenant_id) as rescue_session:
                    r_stmt = (
                        select(ActionContract)
                        .where(
                            ActionContract.tenant_id == auth.tenant_id,
                            ActionContract.id == req.action_id,
                        )
                        .with_for_update()
                    )
                    r_res = await rescue_session.execute(r_stmt)
                    r_contract = r_res.scalar_one_or_none()
                    if r_contract:
                        r_contract.state = ActionState.EXECUTION_UNCERTAIN.value
                        r_contract.error_message = f"Post-dispatch persistence failure: {post_err}"
                    await _record_action_audit_event(
                        session=rescue_session,
                        tenant_id=auth.tenant_id,
                        event_type="ACTION_EXECUTION_UNCERTAIN",
                        actor_identity_id=auth.identity_id,
                        transaction_id=contract.transaction_id,
                        decision="EXECUTION_UNCERTAIN",
                        reason=f"External dispatch occurred but post-dispatch persistence failed: {post_err}",
                        payload={"action_id": req.action_id, "error": str(post_err)},
                    )
            except Exception as rescue_err:
                logger.critical(
                    "Failed to record EXECUTION_UNCERTAIN state for action %s: %s",
                    req.action_id,
                    rescue_err,
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "External dispatch succeeded but outcome persistence failed. "
                    f"Action is in EXECUTION_UNCERTAIN state: {post_err}"
                ),
            ) from post_err

    # -------------------------------------------------------------------------
    # Crash Recovery & Operator Reconciliation
    # -------------------------------------------------------------------------

    async def list_stranded_actions(
        self,
        auth: AuthContext,
        older_than_seconds: int = 60,
    ) -> list[StrandedActionInfo]:
        """Find actions stranded in EXECUTING or EXECUTION_UNCERTAIN state after worker crash/restart."""
        return await list_stranded_actions(auth=auth, older_than_seconds=older_than_seconds)

    async def reconcile_stranded_action(
        self,
        auth: AuthContext,
        req: ActionReconciliationRequest,
    ) -> ActionExecutionResult:
        """Idempotently reconcile a stranded EXECUTING or EXECUTION_UNCERTAIN action with an immutable audit trail."""
        return await reconcile_stranded_action(auth=auth, req=req)

    # -------------------------------------------------------------------------
    # Helper Evaluators
    # -------------------------------------------------------------------------

    def _evaluate_precondition(self, precond: PreconditionRule, params: dict[str, Any], target_resource: str) -> bool:
        """Deterministic evaluation of pre-execution state checks."""
        return evaluate_precondition(precond=precond, params=params, target_resource=target_resource)

    def _evaluate_postcondition(self, post: PostconditionRule, observed: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Evaluate postconditions against observed tool outputs."""
        return evaluate_postcondition(post=post, observed=observed)
