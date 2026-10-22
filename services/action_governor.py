"""Phase 3 Gate 3 Action Assurance, Tool Proxy, and Action Contract Governor Service."""

import ast
import json
import logging
import operator
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import (
    ActionApproval,
    ActionContract,
    AgentDelegation,
    AITransaction,
    AuditLogRecord,
    Capability,
    MCPServer,
    OutcomeVerificationRecord,
    ResourceLease,
    ToolDefinition,
)
from services.agent_governance import agent_governance_service
from services.concurrency_service import canonicalize_resource_uri, concurrency_service
from services.delegation_service import delegation_service
from services.mcp_client import GovernedMCPClient, MCPExecutionUncertainError
from shared.schemas.action import (
    ActionAuthorizationDecision,
    ActionBatchProposal,
    ActionExecutionRequest,
    ActionExecutionResult,
    ActionProposal,
    ActionReconciliationRequest,
    ActionReconciliationResolution,
    ActionState,
    ActionType,
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

logger = logging.getLogger(__name__)

# Constants for Salami-Slicing Defense & Cumulative Blast Radius
MAX_WINDOW_HOURS = 1
MAX_WINDOW_CUMULATIVE_COST = 1000.0  # Max aggregate dollars spent in 1-hour window
MAX_WINDOW_CUMULATIVE_RISK = 250  # Max aggregate risk score points in 1-hour window
MAX_WINDOW_ACTION_COUNT = 50  # Max actions in 1-hour window


class ToolProxyBypassError(Exception):
    """Raised when an unverified or direct tool call attempts to bypass Gate 3 Action Governance."""

    pass


_SAFE_ARITHMETIC_OPS: dict[type[ast.AST], Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval_math(expr: str) -> float | int:
    """Safe abstract syntax tree mathematical evaluator eliminating eval()."""

    def _eval_node(node: ast.AST) -> float | int:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.BinOp):
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            op = _SAFE_ARITHMETIC_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported math operator: {type(node.op).__name__}")
            res: float | int = float(op(left, right))
            return res
        elif isinstance(node, ast.UnaryOp):
            operand = _eval_node(node.operand)
            op = _SAFE_ARITHMETIC_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported math operator: {type(node.op).__name__}")
            res_u: float | int = float(op(operand))
            return res_u
        raise ValueError(f"Disallowed AST element in arithmetic expression: {type(node).__name__}")

    tree = ast.parse(expr.strip(), mode="eval")
    return _eval_node(tree.body)


class GovernedToolProxy:
    """Authoritative sandboxed Tool Proxy executing actions strictly for authorized ActionContracts."""

    def __init__(self, mcp_client: Any | None = None) -> None:
        self.invocation_counts: dict[str, int] = {}
        self.mcp_client = mcp_client

    def get_invocation_count(self, tool_name: str) -> int:
        return self.invocation_counts.get(tool_name, 0)

    def reset_invocation_counts(self) -> None:
        self.invocation_counts.clear()

    async def dispatch(
        self,
        *,
        contract: ActionContract,
        auth: AuthContext,
    ) -> tuple[dict[str, Any], str | None]:
        """Dispatch tool execution strictly verifying contract state."""
        _ = auth
        if contract.state != ActionState.EXECUTING.value:
            raise ToolProxyBypassError(
                f"Direct tool execution prohibited: contract '{contract.id}' is not in EXECUTING state "
                f"(current: {contract.state}). All tool dispatches must be authorized by Gate 3."
            )

        tool_name = contract.tool_name
        params = contract.normalized_parameters or {}
        target_resource = contract.target_resource

        # Increment verifiable invocation count for testing and live demonstration observation
        self.invocation_counts[tool_name] = self.invocation_counts.get(tool_name, 0) + 1

        fencing_token = contract.fencing_token

        try:
            # Check if this action is an external MCP tool
            if ":" in tool_name or (contract.tool_id and contract.tool_id.startswith("tool_")):
                async with db_session.get_tenant_session(auth.tenant_id) as s:
                    tool_stmt = select(ToolDefinition).where(
                        ToolDefinition.tenant_id == auth.tenant_id,
                        ToolDefinition.id == contract.tool_id,
                    )
                    tool_def = (await s.execute(tool_stmt)).scalar_one_or_none()
                    if tool_def and tool_def.tool_type == "MCP" and tool_def.mcp_server_id:
                        server_stmt = select(MCPServer).where(
                            MCPServer.tenant_id == auth.tenant_id,
                            MCPServer.id == tool_def.mcp_server_id,
                        )
                        server = (await s.execute(server_stmt)).scalar_one_or_none()
                        if not server:
                            raise ToolProxyBypassError(
                                f"Bound MCP server '{tool_def.mcp_server_id}' not found for tool '{tool_name}'"
                            )
                        if server.trust_status != "TRUSTED":
                            raise ToolProxyBypassError(
                                f"Bound MCP server '{server.id}' trust status is '{server.trust_status}', "
                                f"must be 'TRUSTED' (fail-closed)"
                            )

                        client = self.mcp_client or GovernedMCPClient()
                        raw_name = (tool_def.config or {}).get("raw_tool_name") or tool_name.split(":", 1)[-1]
                        mcp_res = await client.call_tool(
                            server=server,
                            raw_tool_name=raw_name,
                            arguments=params,
                        )
                        mcp_res["fencing_token"] = fencing_token
                        return mcp_res, None

            if tool_name == "calculator":
                expr = str(params.get("expression", "0"))
                val = _safe_eval_math(expr)
                return {"status": "ok", "result": val, "expression": expr, "fencing_token": fencing_token}, None

            elif tool_name in ("db_query", "internal_sql_query"):
                expected_token = params.get("expected_fencing_token")
                if expected_token is not None and expected_token != fencing_token:
                    raise ValueError(
                        f"Target-side fencing check failed: expected token {expected_token} "
                        f"!= active token {fencing_token}"
                    )
                return {
                    "status": "ok",
                    "rows_affected": 1,
                    "target": target_resource,
                    "fencing_token": fencing_token,
                    "rows": [{"id": 1, "name": "Corporate Records", "balance": 15000}],
                }, None

            elif tool_name in ("email_sender", "external_email"):
                recipient = params.get("recipient", "user@example.com")
                subject = params.get("subject", "Notification")
                return {
                    "status": "ok",
                    "delivered": True,
                    "recipient": recipient,
                    "subject": subject,
                    "message_id": f"msg_{uuid.uuid4().hex[:12]}",
                    "fencing_token": fencing_token,
                }, None

            elif tool_name == "customer_lookup":
                cust_id = params.get("customer_id", "CUST_001")
                return {
                    "status": "ok",
                    "customer_id": cust_id,
                    "tier": "enterprise",
                    "status_code": "ACTIVE",
                    "fencing_token": fencing_token,
                }, None

            elif tool_name == "controlled_test_probe":
                # Controlled probe tool for Section 22 verifiable execution proofs
                return {
                    "status": "ok",
                    "probe_executed": True,
                    "invocations": self.invocation_counts[tool_name],
                    "target": target_resource,
                    "params": params,
                    "fencing_token": fencing_token,
                }, None

            else:
                return {
                    "status": "ok",
                    "executed": True,
                    "tool": tool_name,
                    "target_resource": target_resource,
                    "params": params,
                    "fencing_token": fencing_token,
                }, None
        except MCPExecutionUncertainError:
            raise
        except Exception as exc:
            return {"status": "error", "error": str(exc), "fencing_token": fencing_token}, str(exc)


async def _record_action_audit_event(
    session: Any,
    tenant_id: str,
    event_type: str,
    actor_identity_id: str | None = None,
    transaction_id: str | None = None,
    decision: str | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    latest = await session.execute(
        select(AuditLogRecord.chain_hash, AuditLogRecord.sequence_number)
        .where(AuditLogRecord.tenant_id == tenant_id)
        .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
        .limit(1)
    )
    latest_row = latest.first()
    prev_hash = latest_row[0] if latest_row and latest_row[0] is not None else ("0" * 64)
    prev_seq = latest_row[1] if latest_row and len(latest_row) > 1 and latest_row[1] is not None else 0
    seq = prev_seq + 1
    now = datetime.now(UTC)
    entry_id = f"aud_{uuid.uuid4().hex}"
    chain_payload = f"{prev_hash}:{entry_id}:{event_type}:{decision or ''}:{now.isoformat()}"
    chain_hash = compute_sha256(chain_payload)

    session.add(
        AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=seq,
            session_id=transaction_id or "action-governance",
            trace_id="action-governor",
            prompt_hash=compute_sha256(""),
            response_hash=compute_sha256(""),
            hrs_score=0.0,
            risk_tier="ACTION_ASSURANCE",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type=event_type,
            actor_identity_id=actor_identity_id or "system_actor",
            transaction_id=transaction_id,
            decision=decision,
            reason=reason,
            event_payload=payload or {},
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
    )


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
        base_risk = {
            ActionType.READ.value: 10,
            ActionType.WRITE.value: 35,
            ActionType.EXECUTE.value: 40,
            ActionType.EGRESS.value: 50,
            ActionType.DELETE.value: 65,
        }.get(req.action_type.value, 40)

        trust_mod = {
            ToolTrustLevel.INTERNAL.value: 0,
            ToolTrustLevel.VERIFIED.value: 10,
            ToolTrustLevel.UNTRUSTED.value: 25,
        }.get(tool.trust_level, 10)

        env_mod = {
            "DEV": 0,
            "STAGING": 15,
            "PROD": 30,
        }.get(req.blast_radius.target_environment.upper(), 10)

        param_cost = 0.0
        for cost_key in ("amount", "amount_usd", "estimated_cost", "dollar_cost", "spend"):
            cval = normalized_params.get(cost_key)
            if isinstance(cval, (int, float)):
                param_cost = max(param_cost, float(cval))

        effective_cost = max(float(req.blast_radius.estimated_dollar_cost), param_cost)
        cost_mod = min(25, int(effective_cost / 100.0))
        single_action_risk = min(100, base_risk + trust_mod + env_mod + cost_mod)
        autonomy_level = min(4, single_action_risk // 20)

        # Salami-Slicing Defense & Cumulative Blast Radius Accounting
        window_start = now - timedelta(hours=MAX_WINDOW_HOURS)
        blast_stmt = select(
            func.count(ActionContract.id).label("count"),
            func.coalesce(func.sum(ActionContract.risk_score), 0).label("cumulative_risk"),
        ).where(
            ActionContract.tenant_id == tenant_id,
            ActionContract.created_at >= window_start,
            ActionContract.state.in_(
                [
                    ActionState.AUTHORIZED.value,
                    ActionState.EXECUTING.value,
                    ActionState.COMPLETED.value,
                ]
            ),
        )
        blast_res = await session.execute(blast_stmt)
        blast_row = blast_res.one()
        window_count = int(blast_row[0] or 0)
        window_risk = int(blast_row[1] or 0)

        # Sum cumulative dollar cost
        cost_contracts_stmt = select(ActionContract.blast_radius).where(
            ActionContract.tenant_id == tenant_id,
            ActionContract.created_at >= window_start,
            ActionContract.state.in_(
                [
                    ActionState.AUTHORIZED.value,
                    ActionState.EXECUTING.value,
                    ActionState.COMPLETED.value,
                ]
            ),
        )
        cost_contracts_res = await session.execute(cost_contracts_stmt)
        all_radii = cost_contracts_res.scalars().all()
        window_cost = sum(float(r.get("estimated_dollar_cost", 0.0) or 0.0) for r in all_radii if isinstance(r, dict))

        is_salami_violation = bool(
            (window_risk + single_action_risk > MAX_WINDOW_CUMULATIVE_RISK)
            or (window_cost + effective_cost > MAX_WINDOW_CUMULATIVE_COST)
            or (window_count >= MAX_WINDOW_ACTION_COUNT)
        )

        return single_action_risk, autonomy_level, effective_cost, window_risk, window_cost, is_salami_violation

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
        requires_outcome_assurance = bool(
            (req.outcome_contract and req.outcome_contract.requires_outcome_assurance)
            or req.action_type in (ActionType.WRITE, ActionType.DELETE, ActionType.EXECUTE, ActionType.EGRESS)
            or single_action_risk >= 40
            or autonomy_level >= 2
            or effective_cost > 0.0
        )

        if not requires_outcome_assurance:
            return False, None, None

        merged_postconditions = list(req.postconditions)
        if req.outcome_contract and req.outcome_contract.expected_postconditions:
            for ep in req.outcome_contract.expected_postconditions:
                if isinstance(ep, dict) and "target" in ep:
                    assertion = ep.get("assertion", "EQUALS")
                    merged_postconditions.append(
                        PostconditionRule(
                            assertion=assertion,
                            target=ep["target"],
                            expected_value=ep.get("expected_value"),
                        )
                    )

        # Criterion 1: Must define expected postconditions for autonomous authorization
        if not requires_human_approval and len(merged_postconditions) == 0:
            return (
                True,
                None,
                (
                    "Outcome Assurance contract violation: "
                    "action requires outcome assurance but defines zero expected postconditions."
                ),
            )

        # Criterion 2: Acceptable evidence sources
        acceptable_sources: list[str] = []
        if req.outcome_contract and req.outcome_contract.acceptable_evidence_sources:
            acceptable_sources = req.outcome_contract.acceptable_evidence_sources
        elif tool.tool_type == ToolType.HTTP:
            scheme = req.target_resource.split("://")[0] if "://" in req.target_resource else "http"
            acceptable_sources = [f"http:{scheme}", "HTTP_RESOURCE"]
        else:
            acceptable_sources = ["DATABASE", "HTTP_RESOURCE", "ASYNC_EVENT", "INDEPENDENT_OBSERVER"]

        if req.outcome_contract and len(req.outcome_contract.acceptable_evidence_sources) == 0:
            return (
                True,
                None,
                (
                    "Outcome Assurance contract violation: "
                    "acceptable_evidence_sources cannot be empty when outcome contract is specified."
                ),
            )

        # Criterion 3: Verification deadline
        deadline_sec = 30.0
        if req.outcome_contract:
            if req.outcome_contract.verification_deadline_seconds <= 0:
                return (
                    True,
                    None,
                    "Outcome Assurance contract violation: verification_deadline_seconds must be positive.",
                )
            deadline_sec = req.outcome_contract.verification_deadline_seconds

        outcome_contract_dict = {
            "requires_outcome_assurance": True,
            "expected_postconditions": [p.model_dump() for p in merged_postconditions],
            "acceptable_evidence_sources": acceptable_sources,
            "verification_deadline_seconds": deadline_sec,
            "risk_sensitive_verification_policy": (
                req.outcome_contract.risk_sensitive_verification_policy.value
                if req.outcome_contract
                else "STRICT_DIRECT_ONLY"
                if single_action_risk >= 60
                else "DEFAULT"
            ),
            "on_partial": req.outcome_contract.on_partial.value if req.outcome_contract else "HOLD_FOR_REVIEW",
            "on_uncertain": req.outcome_contract.on_uncertain.value if req.outcome_contract else "ESCALATE",
        }

        return True, outcome_contract_dict, None

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
                detail=("Approval replay attack detected: Approval token does not belong to this action/transaction."),
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
                return ActionAuthorizationDecision(
                    action_id=f"act_err_{uuid.uuid4().hex[:8]}",
                    decision=Decision.BLOCK,
                    state=ActionState.BLOCKED,
                    reason=f"Parent transaction '{req.transaction_id}' does not exist or access denied",
                    risk_score=100,
                    autonomy_level=4,
                    normalized_parameters={},
                    parameters_hash="",
                )
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
            elif not granted_capabilities:
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
        # Non-negotiable security invariant: Caller must be human Super Admin or Operator
        if auth.role not in (Role.SUPER_ADMIN, Role.OPERATOR):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Agents cannot self-grant approvals. L4 approvals require human administrator/operator credentials."
                ),
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
                    detail=(
                        "Agent/Requester cannot approve their own action proposal. Distinct human sign-off required."
                    ),
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

    async def deny_approval(self, auth: AuthContext, approval_id: str, reason: str) -> ApprovalResponse:
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

    async def list_pending_approvals(self, auth: AuthContext) -> list[ApprovalResponse]:
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
        if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Caller is not authorized to list stranded actions "
                    "(requires SUPER_ADMIN, TENANT_ADMIN, or OPERATOR)"
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
        self,
        auth: AuthContext,
        req: ActionReconciliationRequest,
    ) -> ActionExecutionResult:
        """Idempotently reconcile a stranded EXECUTING or EXECUTION_UNCERTAIN action with an immutable audit trail."""
        if auth.role not in (Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Caller is not authorized to reconcile actions (requires SUPER_ADMIN, TENANT_ADMIN, or OPERATOR)"
                ),
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
                # If requested resolution matches current terminal state, return idempotently
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

    # -------------------------------------------------------------------------
    # Helper Evaluators
    # -------------------------------------------------------------------------

    def _evaluate_precondition(self, precond: PreconditionRule, params: dict[str, Any], target_resource: str) -> bool:
        """Deterministic evaluation of pre-execution state checks."""
        check = precond.check_type.upper()
        if check == "RESOURCE_EXISTS":
            return bool(target_resource and len(target_resource) > 0)
        elif check == "PARAM_EXISTS":
            return precond.target in params and params[precond.target] is not None
        elif check == "NUMERIC_LTE":
            val = params.get(precond.target)
            if isinstance(val, (int, float)) and isinstance(precond.expected_value, (int, float)):
                return val <= precond.expected_value
            return False
        elif check == "ALLOWLIST":
            val = params.get(precond.target)
            if isinstance(precond.expected_value, list):
                return val in precond.expected_value
            return False
        elif check == "EQUALS":
            return bool(params.get(precond.target) == precond.expected_value)
        return True

    def _evaluate_postcondition(self, post: PostconditionRule, observed: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Evaluate postconditions against observed tool outputs."""
        assertion = post.assertion.upper()
        evidence: dict[str, Any] = {
            "assertion": assertion,
            "target": post.target,
            "expected_value": post.expected_value,
            "observed_value": observed.get(post.target),
        }

        if assertion == "KEY_EXISTS":
            satisfied = post.target in observed
        elif assertion == "STATUS_EQUALS":
            satisfied = observed.get("status") == post.expected_value
        elif assertion == "EQUALS":
            satisfied = observed.get(post.target) == post.expected_value
        else:
            satisfied = post.target in observed

        evidence["satisfied"] = satisfied
        return satisfied, evidence
