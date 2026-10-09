"""Phase 1 control-plane policy, capability, taint, and transaction services."""

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from db import session as db_session
from db.models import ActionContract, Agent, AITransaction, AuditLogRecord, Budget, Capability, OutputAssuranceRecord, Policy
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext
from shared.schemas.control_plane import (
    CapabilityValidationRequest,
    Decision,
    InputAssuranceRequest,
    InputAssuranceResult,
    PolicyDecision,
    Taint,
    TransactionCreateRequest,
    TransactionResponse,
    TransactionState,
    TransactionTransitionRequest,
    is_dangerous_triad_active,
    normalize_taints,
)

_INJECTION_PATTERNS = (
    re.compile(r"\b(ignore|disregard)\b.{0,40}\b(previous|prior|system|above|instructions)\b", re.IGNORECASE),
    re.compile(r"\b(system prompt|developer message|jailbreak|DAN mode|developer mode)\b", re.IGNORECASE),
    re.compile(r"\b(leak your prompt|leak instructions|repeat everything above)\b", re.IGNORECASE),
    re.compile(r"!\[.*?\]\(https?://[^\s\)]+\?[^\s\)]*\)", re.IGNORECASE),
)
_SECRET_PATTERNS = (
    re.compile(r"\b(?:api[_ -]?key|password|secret|private[_ -]?key)\b\s*[:=]", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
)
_PII_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
)

_TERMINAL = {
    TransactionState.COMPLETED,
    TransactionState.FAILED,
    TransactionState.BLOCKED,
    TransactionState.CANCELLED,
    TransactionState.TIMEOUT,
    TransactionState.PARTIAL,
}
_TRANSITIONS: dict[TransactionState, set[TransactionState]] = {
    TransactionState.PENDING: {TransactionState.ANALYZING, TransactionState.BLOCKED, TransactionState.CANCELLED},
    TransactionState.ANALYZING: {
        TransactionState.ASSEMBLING_CONTEXT,
        TransactionState.BLOCKED,
        TransactionState.FAILED,
        TransactionState.CANCELLED,
    },
    TransactionState.ASSEMBLING_CONTEXT: {
        TransactionState.TURN_REASONING,
        TransactionState.BLOCKED,
        TransactionState.FAILED,
        TransactionState.CANCELLED,
    },
    TransactionState.TURN_REASONING: {
        TransactionState.AUTHORIZING_ACTION,
        TransactionState.VERIFYING_OUTPUT,
        TransactionState.FAILED,
        TransactionState.CANCELLED,
    },
    TransactionState.AUTHORIZING_ACTION: {
        TransactionState.AWAITING_APPROVAL,
        TransactionState.EXECUTING_TOOL,
        TransactionState.BLOCKED,
        TransactionState.CANCELLED,
    },
    TransactionState.AWAITING_APPROVAL: {
        TransactionState.EXECUTING_TOOL,
        TransactionState.BLOCKED,
        TransactionState.CANCELLED,
        TransactionState.TIMEOUT,
    },
    TransactionState.EXECUTING_TOOL: {
        TransactionState.VERIFYING_OUTCOME,
        TransactionState.FAILED,
        TransactionState.PARTIAL,
        TransactionState.CANCELLED,
    },
    TransactionState.VERIFYING_OUTCOME: {
        TransactionState.UPDATING_CONTEXT,
        TransactionState.PARTIAL,
        TransactionState.FAILED,
        TransactionState.CANCELLED,
    },
    TransactionState.UPDATING_CONTEXT: {
        TransactionState.TURN_REASONING,
        TransactionState.VERIFYING_OUTPUT,
        TransactionState.FAILED,
        TransactionState.CANCELLED,
    },
    TransactionState.VERIFYING_OUTPUT: {
        TransactionState.COMPLETED,
        TransactionState.PARTIAL,
        TransactionState.FAILED,
        TransactionState.CANCELLED,
    },
}


def _transaction_response(record: AITransaction) -> TransactionResponse:
    return TransactionResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        actor_identity_id=record.actor_identity_id,
        state=TransactionState(record.state),
        turn_count=record.turn_count,
        max_turns=record.max_turns,
        taints={Taint(item) for item in record.taint_flags},
        version=record.version,
        final_disposition=record.final_disposition,
        policy_id=record.policy_id,
        correlation_id=record.correlation_id,
    )


async def evaluate_policy(tenant_id: str, policy_id: str | None, context: dict[str, Any]) -> PolicyDecision:
    """Evaluate a typed declarative policy schema deterministically."""
    if policy_id is None:
        return PolicyDecision(decision=Decision.BLOCK, reason="No active policy explicitly permits this transaction")
    async with db_session.get_tenant_session(tenant_id) as session:
        policy = await session.get(Policy, policy_id)
        if policy is None or policy.tenant_id != tenant_id or policy.status != "active":
            return PolicyDecision(decision=Decision.BLOCK, reason="Policy is absent or inactive", policy_id=policy_id)
        rules = policy.rules
        allowed_keys = {"effect", "max_risk", "require_approval", "deny_indicators", "disallowed_taints"}
        if not isinstance(rules, dict) or set(rules) - allowed_keys:
            return PolicyDecision(
                decision=Decision.BLOCK,
                reason="Policy schema is invalid",
                policy_id=policy.id,
                policy_version=policy.version,
            )
        effect = rules.get("effect")
        if effect not in {item.value for item in Decision}:
            return PolicyDecision(
                decision=Decision.BLOCK,
                reason="Policy effect is invalid",
                policy_id=policy.id,
                policy_version=policy.version,
            )
        if context.get("risk", 0) > rules.get("max_risk", 100):
            return PolicyDecision(
                decision=Decision.REQUIRE_APPROVAL,
                reason="Risk exceeds policy ceiling",
                policy_id=policy.id,
                policy_version=policy.version,
            )
        if any(item in rules.get("deny_indicators", []) for item in context.get("indicators", [])):
            return PolicyDecision(
                decision=Decision.BLOCK,
                reason="Policy denies detected input indicator",
                policy_id=policy.id,
                policy_version=policy.version,
            )
        if any(item in rules.get("disallowed_taints", []) for item in context.get("taints", [])):
            return PolicyDecision(
                decision=Decision.BLOCK,
                reason="Policy prohibits active context taint",
                policy_id=policy.id,
                policy_version=policy.version,
            )
        if rules.get("require_approval"):
            return PolicyDecision(
                decision=Decision.REQUIRE_APPROVAL,
                reason="Policy requires approval",
                policy_id=policy.id,
                policy_version=policy.version,
            )
        return PolicyDecision(
            decision=Decision(effect),
            reason="Policy evaluated deterministically",
            policy_id=policy.id,
            policy_version=policy.version,
        )


async def assure_input(auth: AuthContext, request: InputAssuranceRequest) -> InputAssuranceResult:
    """Run cheap deterministic Gate 1 checks before any model or tool work."""
    indicators: list[str] = []
    raw_taints: set[Taint] = {Taint.UNTRUSTED}
    if request.declared_confidential:
        raw_taints.add(Taint.CONFIDENTIAL)
        indicators.append("declared_confidential")
    if any(pat.search(request.content) for pat in _SECRET_PATTERNS):
        raw_taints.add(Taint.SECRET_CREDENTIAL)
        raw_taints.add(Taint.CONFIDENTIAL)
        indicators.append("secret_credential")
    if any(pat.search(request.content) for pat in _PII_PATTERNS):
        raw_taints.add(Taint.RESTRICTED_PII)
        raw_taints.add(Taint.CONFIDENTIAL)
        indicators.append("pii_detected")
    if any(pattern.search(request.content) for pattern in _INJECTION_PATTERNS):
        indicators.append("prompt_injection")

    risk = min(
        100,
        request.initial_risk
        + (50 if "prompt_injection" in indicators else 0)
        + (30 if "secret_credential" in indicators else 0)
        + (15 if "pii_detected" in indicators else 0)
        + (10 if "declared_confidential" in indicators else 0),
    )
    normalized = normalize_taints(raw_taints)
    if "prompt_injection" in indicators:
        return InputAssuranceResult(
            decision=PolicyDecision(decision=Decision.BLOCK, reason="Input contains a prompt-injection indicator"),
            taints=normalized,
            risk=risk,
            indicators=indicators,
        )
    if "secret_credential" in indicators:
        return InputAssuranceResult(
            decision=PolicyDecision(
                decision=Decision.BLOCK, reason="Input contains plaintext credentials in untrusted context"
            ),
            taints=normalized,
            risk=risk,
            indicators=indicators,
        )
    decision = await evaluate_policy(
        auth.tenant_id,
        request.policy_id,
        {"risk": risk, "indicators": indicators, "taints": [t.value for t in normalized]},
    )
    return InputAssuranceResult(decision=decision, taints=normalized, risk=risk, indicators=indicators)


async def _append_audit(
    session: Any,
    tenant_id: str,
    actor_id: str,
    transaction_id: str,
    decision: str,
    reason: str,
    policy_ref: str | None,
    payload: dict[str, Any],
) -> None:
    """Append control-plane decisions to the existing tenant hash chain."""
    latest = await session.execute(
        select(AuditLogRecord.chain_hash)
        .where(AuditLogRecord.tenant_id == tenant_id)
        .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
        .limit(1)
    )
    prev_hash = latest.scalar_one_or_none() or "0" * 64
    now = datetime.now(UTC)
    entry_id = f"aud_{uuid.uuid4().hex}"
    chain_hash = compute_sha256(f"{prev_hash}:{entry_id}:{decision}:{now.isoformat()}")
    session.add(
        AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            session_id=transaction_id,
            trace_id="control-plane",
            prompt_hash=compute_sha256(""),
            response_hash=compute_sha256(""),
            hrs_score=0.0,
            risk_tier="CONTROL_PLANE",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type="control_plane_decision",
            actor_identity_id=actor_id,
            transaction_id=transaction_id,
            decision=decision,
            policy_reference=policy_ref,
            reason=reason,
            event_payload=payload,
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
    )


async def create_transaction(auth: AuthContext, request: TransactionCreateRequest) -> TransactionResponse:
    """Create a tenant-bound transaction after Gate 1 and parent confinement checks."""
    if auth.identity_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A resolved identity is required")
    gate = await assure_input(auth, request)
    if gate.decision.decision in {Decision.BLOCK, Decision.DENY}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=gate.decision.reason)
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        existing = (
            await session.execute(
                select(AITransaction).where(
                    AITransaction.tenant_id == auth.tenant_id, AITransaction.idempotency_key == request.idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _transaction_response(existing)
        if request.agent_id and await session.get(Agent, request.agent_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent")
        parent: AITransaction | None = None
        if request.parent_transaction_id:
            parent = await session.get(AITransaction, request.parent_transaction_id)
            if parent is None or parent.tenant_id != auth.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent transaction not found")
            if parent.state in {item.value for item in _TERMINAL}:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Parent transaction is terminal; cannot spawn child transaction",
                )
            if request.max_turns > parent.max_turns - parent.turn_count:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Child transaction exceeds parent turn budget"
                )
            gate.taints.update(Taint(item) for item in parent.taint_flags)
        if request.budget_id and await session.get(Budget, request.budget_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown budget")
        final_taints = normalize_taints(gate.taints)
        record = AITransaction(
            id=f"txn_{uuid.uuid4().hex}",
            tenant_id=auth.tenant_id,
            actor_identity_id=auth.identity_id,
            agent_id=request.agent_id,
            parent_transaction_id=request.parent_transaction_id,
            idempotency_key=request.idempotency_key,
            correlation_id=request.correlation_id,
            state=TransactionState.PENDING,
            max_turns=request.max_turns,
            taint_flags=sorted(item.value for item in final_taints),
            policy_id=request.policy_id,
            budget_id=request.budget_id,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(record)
        await _append_audit(
            session,
            auth.tenant_id,
            auth.identity_id,
            record.id,
            gate.decision.decision.value,
            gate.decision.reason,
            request.policy_id,
            {"taints": record.taint_flags, "risk": gate.risk},
        )
        await session.flush()
        return _transaction_response(record)


async def transition_transaction(
    auth: AuthContext, transaction_id: str, request: TransactionTransitionRequest
) -> TransactionResponse:
    """Apply a validated optimistic-concurrency lifecycle transition."""
    if auth.identity_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A resolved identity is required")
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        record = await session.get(AITransaction, transaction_id, with_for_update=True)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
        source = TransactionState(record.state)
        if record.version != request.expected_version:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction version conflict")
        if source in _TERMINAL or request.target_state not in _TRANSITIONS.get(source, set()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Invalid transaction transition {source.value} to {request.target_state.value}",
            )
        if request.target_state == TransactionState.TURN_REASONING:
            if record.turn_count >= record.max_turns:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Transaction turn budget exhausted")
            record.turn_count += 1
        if request.target_state == TransactionState.COMPLETED:
            # Enforce Gate 4 completion binding invariant:
            # 1. OutputAssuranceRecord must exist and match tenant_id and transaction_id.
            # 2. If request specifies output_id or expected_output_hash, it must match.
            # 3. Cannot be BLOCK or REQUIRE_HUMAN_REVIEW.
            # 4. Turn & Action Freshness: No action contracts executed after output assurance was recorded.
            requires_gate4 = False
            if record.policy_id:
                policy = await session.get(Policy, record.policy_id)
                if policy and policy.rules.get("require_gate4"):
                    requires_gate4 = True

            out_query = select(OutputAssuranceRecord).where(
                OutputAssuranceRecord.transaction_id == transaction_id,
                OutputAssuranceRecord.tenant_id == auth.tenant_id,
            )
            if request.output_id:
                out_query = out_query.where(OutputAssuranceRecord.id == request.output_id)

            out_stmt = out_query.order_by(OutputAssuranceRecord.created_at.desc()).limit(1)
            out_rec = (await session.execute(out_stmt)).scalar_one_or_none()

            if requires_gate4 and out_rec is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Cannot complete transaction: Gate 4 Output Assurance record is required "
                        "by governing policy, but none exists."
                    ),
                )

            if out_rec is not None:
                if request.expected_output_hash and out_rec.output_hash != request.expected_output_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Cannot complete transaction: Output hash mismatch "
                            f"(expected {request.expected_output_hash}, got {out_rec.output_hash})."
                        ),
                    )

                if out_rec.final_decision == "BLOCK" or out_rec.verification_status == "BLOCKED":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot complete transaction: Latest Gate 4 decision is BLOCK ({out_rec.id}).",
                    )
                if out_rec.final_decision == "REQUIRE_HUMAN_REVIEW":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Cannot complete transaction: Output requires human review "
                            f"before release ({out_rec.id})."
                        ),
                    )

                # Check action freshness: ensure no actions were completed or updated after output was assured
                post_action_stmt = (
                    select(ActionContract)
                    .where(
                        ActionContract.transaction_id == transaction_id,
                        ActionContract.tenant_id == auth.tenant_id,
                        ActionContract.updated_at > out_rec.created_at,
                    )
                    .limit(1)
                )
                post_action = (await session.execute(post_action_stmt)).scalar_one_or_none()
                if post_action:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Cannot complete transaction: Output assurance is stale. Action '{post_action.id}' "
                            f"was modified after output was evaluated ({post_action.updated_at} > {out_rec.created_at})."
                        ),
                    )
        record.state = request.target_state.value
        all_taints = normalize_taints(set(record.taint_flags) | {item.value for item in request.add_taints})
        record.taint_flags = sorted(item.value for item in all_taints)
        record.version += 1
        record.updated_at = datetime.now(UTC)
        if request.target_state in _TERMINAL:
            record.final_disposition = request.target_state.value
        await _append_audit(
            session,
            auth.tenant_id,
            auth.identity_id,
            record.id,
            request.target_state.value,
            request.reason,
            record.policy_id,
            {"taints": record.taint_flags, "version": record.version},
        )
        await session.flush()
        return _transaction_response(record)


async def cancel_transaction(
    auth: AuthContext, transaction_id: str, reason: str = "Transaction cancelled by client"
) -> TransactionResponse:
    """Abort an in-flight transaction with audit recording."""
    if auth.identity_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A resolved identity is required")
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        record = await session.get(AITransaction, transaction_id, with_for_update=True)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found")
        source = TransactionState(record.state)
        if source in _TERMINAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transaction is already terminal ({source.value}) and cannot be cancelled",
            )
        record.state = TransactionState.CANCELLED.value
        record.final_disposition = TransactionState.CANCELLED.value
        record.version += 1
        record.updated_at = datetime.now(UTC)
        await _append_audit(
            session,
            auth.tenant_id,
            auth.identity_id,
            record.id,
            TransactionState.CANCELLED.value,
            reason,
            record.policy_id,
            {"taints": record.taint_flags, "version": record.version},
        )
        await session.flush()
        return _transaction_response(record)


async def validate_capability(auth: AuthContext, request: CapabilityValidationRequest) -> PolicyDecision:
    """Validate active, scoped capability ownership with DIFC dynamic interlocks."""
    if auth.identity_id is None:
        return PolicyDecision(decision=Decision.DENY, reason="No authoritative identity")
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        capability = await session.get(Capability, request.capability_id)
        now = datetime.now(UTC)
        if capability is None or capability.tenant_id != auth.tenant_id:
            return PolicyDecision(decision=Decision.DENY, reason="Capability not found")
        if capability.identity_id != auth.identity_id or capability.capability_type != request.capability_type:
            return PolicyDecision(decision=Decision.DENY, reason="Capability is not bound to this identity")
        if capability.revoked_at is not None or (capability.expires_at is not None and capability.expires_at <= now):
            return PolicyDecision(decision=Decision.DENY, reason="Capability is revoked or expired")
        if request.requested_autonomy_level > capability.max_autonomy_level:
            return PolicyDecision(
                decision=Decision.REQUIRE_APPROVAL, reason="Requested autonomy exceeds capability ceiling"
            )
        if any(request.resource.get(k) != v for k, v in capability.resource_scope.items()):
            return PolicyDecision(decision=Decision.DENY, reason="Requested resource is outside capability scope")

        # Dynamic Information Flow Control (DIFC) Interlocking (Dangerous Triad prevention)
        if request.transaction_id:
            txn = await session.get(AITransaction, request.transaction_id)
            if txn is not None and txn.tenant_id == auth.tenant_id:
                if is_dangerous_triad_active(txn.taint_flags) or Taint.CONCURRENT_RESTRICTION.value in txn.taint_flags:
                    is_egress = (
                        request.capability_type.startswith("external:")
                        or capability.capability_type.startswith("external:")
                        or capability.constraints.get("egress") == "external"
                        or request.resource.get("external") is True
                        or request.capability_type
                        in {
                            "tools:web_search",
                            "tools:http_request",
                            "tools:webhook",
                            "tools:email_send",
                            "network:egress",
                        }
                    )
                    if is_egress:
                        if request.requested_autonomy_level < 4:
                            return PolicyDecision(
                                decision=Decision.REQUIRE_APPROVAL,
                                reason=(
                                    "DIFC Dangerous Triad Interlock: concurrent untrusted and confidential "
                                    "taints demote external communication to mandatory human approval (L4)"
                                ),
                            )
                        if capability.max_autonomy_level < 4:
                            return PolicyDecision(
                                decision=Decision.DENY,
                                reason="Capability ceiling prohibits L4 approval under concurrent taint restriction",
                            )

        return PolicyDecision(decision=Decision.ALLOW, reason="Capability is active and scoped")
