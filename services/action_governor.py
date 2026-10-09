"""Phase 3 Gate 3 Action Assurance, Tool Proxy, and Action Contract Governor Service."""

import ast
import json
import operator
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select

from db import session as db_session
from db.models import ActionApproval, ActionContract, AITransaction, AuditLogRecord, Capability, ToolDefinition
from shared.schemas.action import (
    ActionAuthorizationDecision,
    ActionBatchProposal,
    ActionExecutionRequest,
    ActionExecutionResult,
    ActionProposal,
    ActionState,
    ActionType,
    ApprovalResponse,
    ApprovalStatus,
    BatchAuthorizationDecision,
    EgressType,
    PostconditionRule,
    PreconditionRule,
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
from shared.schemas.control_plane import (
    Decision,
    Taint,
    is_dangerous_triad_active,
)

# Constants for Salami-Slicing Defense & Cumulative Blast Radius
MAX_WINDOW_HOURS = 1
MAX_WINDOW_CUMULATIVE_COST = 1000.0  # Max aggregate dollars spent in 1-hour window
MAX_WINDOW_CUMULATIVE_RISK = 250    # Max aggregate risk score points in 1-hour window
MAX_WINDOW_ACTION_COUNT = 50        # Max actions in 1-hour window


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

    def __init__(self) -> None:
        self.invocation_counts: dict[str, int] = {}

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

        try:
            if tool_name == "calculator":
                expr = str(params.get("expression", "0"))
                val = _safe_eval_math(expr)
                return {"status": "ok", "result": val, "expression": expr}, None

            elif tool_name in ("db_query", "internal_sql_query"):
                return {
                    "status": "ok",
                    "rows_affected": 1,
                    "target": target_resource,
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
                }, None

            elif tool_name == "customer_lookup":
                cust_id = params.get("customer_id", "CUST_001")
                return {
                    "status": "ok",
                    "customer_id": cust_id,
                    "tier": "enterprise",
                    "status_code": "ACTIVE",
                }, None

            elif tool_name == "controlled_test_probe":
                # Controlled probe tool for Section 22 verifiable execution proofs
                return {
                    "status": "ok",
                    "probe_executed": True,
                    "invocations": self.invocation_counts[tool_name],
                    "target": target_resource,
                    "params": params,
                }, None

            else:
                return {
                    "status": "ok",
                    "executed": True,
                    "tool": tool_name,
                    "target_resource": target_resource,
                    "params": params,
                }, None
        except Exception as exc:
            return {"status": "error", "error": str(exc)}, str(exc)


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
        select(AuditLogRecord.chain_hash)
        .where(AuditLogRecord.tenant_id == tenant_id)
        .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
        .limit(1)
    )
    prev_hash = latest.scalar_one_or_none() or "0" * 64
    now = datetime.now(UTC)
    entry_id = f"aud_{uuid.uuid4().hex}"
    chain_payload = f"{prev_hash}:{entry_id}:{event_type}:{decision or ''}:{now.isoformat()}"
    chain_hash = compute_sha256(chain_payload)

    session.add(
        AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
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

    async def propose_and_authorize_action(
        self, auth: AuthContext, req: ActionProposal
    ) -> ActionAuthorizationDecision:
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

            # Check idempotency for existing action contract
            existing_act_stmt = select(ActionContract).where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.idempotency_key == req.idempotency_key,
            )
            existing_act_res = await session.execute(existing_act_stmt)
            existing_contract = existing_act_res.scalar_one_or_none()
            if existing_contract:
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

            # 4. Capability Authorization
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
            if not granted_capabilities:
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
            matching_cap = granted_capabilities[0]
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

            # 7. Action Risk Model Calculation
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

            # 8. Salami-Slicing Defense & Cumulative Blast Radius Accounting
            window_start = now - timedelta(hours=MAX_WINDOW_HOURS)
            blast_stmt = select(
                func.count(ActionContract.id).label("count"),
                func.coalesce(func.sum(ActionContract.risk_score), 0).label("cumulative_risk"),
            ).where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.created_at >= window_start,
                ActionContract.state.in_([
                    ActionState.AUTHORIZED.value,
                    ActionState.EXECUTING.value,
                    ActionState.COMPLETED.value,
                ]),
            )
            blast_res = await session.execute(blast_stmt)
            blast_row = blast_res.one()
            window_count = int(blast_row[0] or 0)
            window_risk = int(blast_row[1] or 0)

            # Sum cumulative dollar cost
            cost_contracts_stmt = select(ActionContract.blast_radius).where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.created_at >= window_start,
                ActionContract.state.in_([
                    ActionState.AUTHORIZED.value,
                    ActionState.EXECUTING.value,
                    ActionState.COMPLETED.value,
                ]),
            )
            cost_contracts_res = await session.execute(cost_contracts_stmt)
            all_radii = cost_contracts_res.scalars().all()
            window_cost = sum(
                float(r.get("estimated_dollar_cost", 0.0) or 0.0) for r in all_radii if isinstance(r, dict)
            )

            # Detect salami slicing
            is_salami_violation = (
                (window_risk + single_action_risk > MAX_WINDOW_CUMULATIVE_RISK)
                or (window_cost + effective_cost > MAX_WINDOW_CUMULATIVE_COST)
                or (window_count >= MAX_WINDOW_ACTION_COUNT)
            )

            # Autonomy level threshold check
            requires_human_approval = (
                autonomy_level >= 4
                or single_action_risk >= 80
                or is_salami_violation
                or (autonomy_level > matching_cap.max_autonomy_level)
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
                preconditions=[p.model_dump() for p in req.preconditions],
                postconditions=[p.model_dump() for p in req.postconditions],
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
                    "Agents cannot self-grant approvals. L4 approvals require human "
                    "administrator/operator credentials."
                ),
            )

        async with db_session.get_tenant_session(auth.tenant_id) as session:
            stmt = select(ActionApproval).where(
                ActionApproval.tenant_id == auth.tenant_id,
                ActionApproval.id == approval_id,
            ).with_for_update()
            res = await session.execute(stmt)
            approval = res.scalar_one_or_none()
            if not approval:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval request not found")

            # Check self-approval: Requester cannot grant their own approval
            if approval.requested_by == auth.identity_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "Agent/Requester cannot approve their own action proposal. "
                        "Distinct human sign-off required."
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
            act_stmt = select(ActionContract).where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.id == approval.action_id,
            ).with_for_update()
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
            stmt = select(ActionApproval).where(
                ActionApproval.tenant_id == auth.tenant_id,
                ActionApproval.id == approval_id,
            ).with_for_update()
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
            act_stmt = select(ActionContract).where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.id == approval.action_id,
            ).with_for_update()
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
        """Execute an authorized action contract strictly through the Governed Tool Proxy."""
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            stmt = select(ActionContract).where(
                ActionContract.tenant_id == auth.tenant_id,
                ActionContract.id == req.action_id,
            ).with_for_update()
            res = await session.execute(stmt)
            contract = res.scalar_one_or_none()
            if not contract:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action contract not found")

            # Invariant: Action must not be in terminal or blocked states
            if contract.state == ActionState.BLOCKED.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Action contract is in state 'BLOCKED' and cannot be executed",
                )

            if contract.state in (ActionState.COMPLETED.value, ActionState.EXECUTING.value):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Action contract is already executed or executing (current: {contract.state})",
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
            if transaction.final_disposition in ("BLOCKED", "FAILED", "CANCELLED", "TIMEOUT"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Parent transaction is in terminal/aborted state '{transaction.final_disposition}'",
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

            now = datetime.now(UTC)

            # Re-verify Actor still holds the required capability (Fail-closed on runtime revocation)
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
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Capability revoked or expired for required scope '{contract.required_capability}'. "
                        "Execution blocked."
                    ),
                )

            # Approval Replay & Tamper Defense:
            if contract.approval_id:
                appr_stmt = select(ActionApproval).where(
                    ActionApproval.tenant_id == auth.tenant_id,
                    ActionApproval.id == contract.approval_id,
                ).with_for_update()
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
                        detail=(
                            "Approval replay attack detected: Approval token does not belong to this "
                            "action/transaction."
                        ),
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

            contract.state = ActionState.EXECUTING.value
            contract.executed_at = now
            await session.flush()

            # Dispatch strictly via Governed Tool Proxy
            observed_output, error_msg = await self.tool_proxy.dispatch(
                contract=contract,
                auth=auth,
            )

            # Postcondition Evaluation
            postconditions_ok = True
            evidence_records: list[dict[str, Any]] = []
            postconds = [PostconditionRule(**p) for p in (contract.postconditions or [])]

            for post in postconds:
                satisfied, ev = self._evaluate_postcondition(post, observed_output)
                evidence_records.append(ev)
                if not satisfied:
                    postconditions_ok = False

            final_state = ActionState.COMPLETED if (not error_msg and postconditions_ok) else ActionState.FAILED

            contract.state = final_state.value
            contract.observed_result = observed_output
            contract.error_message = error_msg
            contract.completed_at = datetime.now(UTC)

            # Append Tool Observation Context Source to parent transaction
            if transaction:
                sources = list(transaction.context_sources or [])
                sources.append({
                    "id": f"ctx_tool_{uuid.uuid4().hex[:12]}",
                    "source_type": "TOOL_OBSERVATION",
                    "tool_name": contract.tool_name,
                    "target_resource": contract.target_resource,
                    "content": json.dumps(observed_output, default=str),
                    "trust_score": 0.6,
                    "taints": [Taint.UNTRUSTED.value],
                    "timestamp": datetime.now(UTC).isoformat(),
                })
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
                    "postconditions_ok": postconditions_ok,
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
            )

    # -------------------------------------------------------------------------
    # Helper Evaluators
    # -------------------------------------------------------------------------

    def _evaluate_precondition(
        self, precond: PreconditionRule, params: dict[str, Any], target_resource: str
    ) -> bool:
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

    def _evaluate_postcondition(
        self, post: PostconditionRule, observed: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
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
