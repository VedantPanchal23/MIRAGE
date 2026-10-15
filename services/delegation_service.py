"""Phase 8 Cross-Agent Delegation Governance Service.

Implements core multi-agent delegation contracts, authority attenuation enforcement,
ancestor chain validation, concurrency-safe activation/revocation, idempotency,
and non-repudiable audit logging.

Governing Principles:
- Delegation must never increase authority.
- The child authority is strictly derived from the intersection of parent agent authority,
  parent transaction capabilities, every active ancestor delegation grant, and requested scope.
- A pending grant cannot authorize execution.
- Activation binds the grant to a specific child transaction atomically.
- An ancestor revocation or expiration immediately invalidates all descendant authorizations.
- Normal revocation and expiration never delete audit lineage.
- Idempotency is enforced per tenant using semantic request verification.
"""

import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import session as db_session
from db.models import (
    Agent,
    AgentDelegation,
    AgentHandoff,
    AITransaction,
    AuditLogRecord,
    Capability,
)
from shared.logging import get_logger
from shared.schemas.agent import AgentStatus
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import (
    Decision,
    PolicyDecision,
    Taint,
    TransactionState,
    is_dangerous_triad_active,
)
from shared.schemas.delegation import (
    AttenuatedCapabilitySpec,
    DelegationGrantRequest,
    DelegationGrantResponse,
    DelegationStatus,
)
from shared.schemas.handoff import HandoffStatus

logger = get_logger("delegation_service")

# Server-controlled bounds and constants
MAX_DELEGATION_DEPTH: Final[int] = 4
DEFAULT_PAGE_LIMIT: Final[int] = 50
MAX_PAGE_LIMIT: Final[int] = 100

_TERMINAL_TRANSACTION_STATES: Final[set[str]] = {
    TransactionState.COMPLETED.value,
    TransactionState.FAILED.value,
    TransactionState.BLOCKED.value,
    TransactionState.CANCELLED.value,
    TransactionState.TIMEOUT.value,
    TransactionState.PARTIAL.value,
}

_DISCRETE_ALLOWLIST_KEYS: Final[set[str]] = {
    "tables",
    "collections",
    "allowed_actions",
    "domains",
    "methods",
    "models",
}

_SCALAR_MATCH_KEYS: Final[set[str]] = {
    "collection",
    "table",
    "database",
    "env",
    "read_only",
    "external",
}

_NUMERIC_CEILING_KEYS: Final[set[str]] = {
    "max_amount",
    "max_file_size_bytes",
    "max_limit",
    "max_records",
    "max_rate",
}


class DelegationError(Exception):
    """Base exception for delegation domain failures."""

    pass


class DelegationAttenuationError(DelegationError):
    """Raised when a requested delegation widens authority beyond parent/ancestor bounds."""

    pass


class DelegationConflictError(DelegationError):
    """Raised on state or idempotency conflict."""

    pass


class DelegationNotFoundError(DelegationError):
    """Raised when a referenced delegation, agent, or transaction does not exist."""

    pass


# ---------------------------------------------------------------------------
# Scope & Constraint Attenuation Helpers
# ---------------------------------------------------------------------------


def is_scope_attenuated(parent_scope: dict[str, Any] | None, child_scope: dict[str, Any] | None) -> tuple[bool, str]:
    """Verify that child_scope is a strict attenuation (subset) of parent_scope.

    Rules:
    - If parent_scope is empty ({}), parent has unrestricted scope; child can have {} or any valid restricted scope.
    - If parent_scope is not empty, child_scope cannot be empty (widening).
    - 'allowed_prefixes': each child prefix must start with at least one parent prefix.
    - Discrete allowlists ('tables', 'collections', etc.): child list must be subset of parent list.
    - Scalar match keys: child value must equal parent value.
    - Unsupported keys are rejected fail-closed to prevent bypassing attenuation.
    """
    p_scope = parent_scope or {}
    c_scope = child_scope or {}

    if not p_scope:
        # Parent has unrestricted scope
        return True, "Parent has unrestricted scope"

    if not c_scope and p_scope:
        return False, "Child resource scope cannot be unrestricted when parent is restricted"

    for key, p_val in p_scope.items():
        if key == "allowed_prefixes":
            if not isinstance(p_val, list):
                return False, f"Parent scope '{key}' must be a list"
            c_val = c_scope.get(key)
            if c_val is None:
                return False, "Child scope missing required 'allowed_prefixes' restriction"
            if not isinstance(c_val, list):
                return False, "Child 'allowed_prefixes' must be a list"
            # Every child prefix must begin with at least one parent prefix
            for c_prefix in c_val:
                if not isinstance(c_prefix, str):
                    return False, "Prefix items must be strings"
                if not any(c_prefix.startswith(p_prefix) for p_prefix in p_val if isinstance(p_prefix, str)):
                    return False, f"Child prefix '{c_prefix}' is not subsumed by any parent prefix in {p_val}"

        elif key in _DISCRETE_ALLOWLIST_KEYS:
            if not isinstance(p_val, (list, set, tuple)):
                return False, f"Parent scope key '{key}' must be a list"
            c_val = c_scope.get(key)
            if c_val is None:
                return False, f"Child scope missing required '{key}' restriction"
            if not isinstance(c_val, (list, set, tuple)):
                return False, f"Child scope key '{key}' must be a list"
            p_set = set(p_val)
            c_set = set(c_val)
            if not c_set.issubset(p_set):
                disallowed = c_set - p_set
                return False, f"Child scope '{key}' contains unauthorized items: {disallowed}"

        elif key in _SCALAR_MATCH_KEYS:
            c_val = c_scope.get(key)
            if c_val != p_val:
                return False, f"Child scope '{key}' value ({c_val}) must match parent value ({p_val})"

        else:
            # Unknown key in parent: reject fail-closed
            return False, f"Unsupported parent resource_scope key '{key}' cannot be verified for attenuation"

    # Ensure child does not introduce extra unrecognized keys not present in parent
    unrecognized = set(c_scope.keys()) - set(p_scope.keys())
    if unrecognized:
        return False, f"Child scope introduces unauthorized scope dimensions: {unrecognized}"

    return True, "Scope is safely attenuated"


def is_constraints_attenuated(
    parent_constraints: dict[str, Any] | None, child_constraints: dict[str, Any] | None
) -> tuple[bool, str]:
    """Verify child execution constraints are a strict attenuation of parent constraints.

    Rules:
    - Numeric limits in parent (max_amount, max_file_size_bytes, etc.) must be present
      in child with a value <= parent value.
    - Boolean restrictions in parent (e.g. read_only) must not be weakened.
    """
    p_cons = parent_constraints or {}
    c_cons = child_constraints or {}

    for key, p_val in p_cons.items():
        if key in _NUMERIC_CEILING_KEYS:
            if isinstance(p_val, (int, float)):
                c_val = c_cons.get(key)
                if c_val is None:
                    return False, f"Child constraints missing required numeric limit '{key}'"
                if not isinstance(c_val, (int, float)):
                    return False, f"Child constraint '{key}' must be numeric"
                if c_val > p_val:
                    return False, f"Child constraint '{key}' ({c_val}) exceeds parent ceiling ({p_val})"
        elif isinstance(p_val, bool):
            c_val = c_cons.get(key)
            if p_val and not c_val:
                return False, f"Child constraint '{key}' must remain True"

    return True, "Constraints are safely attenuated"


def _consolidate_resource_scopes(
    capabilities: Iterable[AttenuatedCapabilitySpec],
) -> dict[str, Any]:
    """Consolidate resource scopes across all capabilities into a grant-level structure."""
    consolidated: dict[str, Any] = {}
    for cap in capabilities:
        if not cap.resource_scope:
            continue
        consolidated[cap.capability_type] = cap.resource_scope
    return consolidated


def _is_semantically_equivalent(existing: AgentDelegation, request: DelegationGrantRequest) -> bool:
    """Deterministic comparison verifying whether a duplicate idempotency key is semantically identical."""
    if existing.parent_transaction_id != request.parent_transaction_id:
        return False
    if existing.child_agent_id != request.delegatee_agent_id:
        return False
    if existing.max_turns != request.max_turns:
        return False
    if existing.purpose.strip() != request.purpose.strip():
        return False

    # Compare sorted capabilities
    req_caps = sorted(
        [
            (
                c.capability_type,
                c.max_autonomy_level,
                json.dumps(c.resource_scope, sort_keys=True),
                json.dumps(c.constraints, sort_keys=True),
            )
            for c in request.delegated_capabilities
        ],
        key=lambda x: x[0],
    )
    exist_caps = sorted(
        [
            (
                c.get("capability_type", ""),
                c.get("max_autonomy_level", 0),
                json.dumps(c.get("resource_scope", {}), sort_keys=True),
                json.dumps(c.get("constraints", {}), sort_keys=True),
            )
            for c in existing.delegated_capabilities
        ],
        key=lambda x: x[0],
    )
    return req_caps == exist_caps


def _delegation_response(record: AgentDelegation) -> DelegationGrantResponse:
    """Transform an ORM AgentDelegation into an authoritative DelegationGrantResponse schema."""
    caps = [
        AttenuatedCapabilitySpec(
            capability_type=c["capability_type"],
            resource_scope=c.get("resource_scope", {}),
            constraints=c.get("constraints", {}),
            max_autonomy_level=c.get("max_autonomy_level", 0),
        )
        for c in record.delegated_capabilities
    ]
    return DelegationGrantResponse(
        id=record.id,
        tenant_id=record.tenant_id,
        parent_agent_id=record.parent_agent_id,
        parent_transaction_id=record.parent_transaction_id,
        child_agent_id=record.child_agent_id,
        child_transaction_id=record.child_transaction_id,
        delegated_capabilities=caps,
        resource_scope=record.resource_scope or {},
        max_turns=record.max_turns,
        max_autonomy_level=record.max_autonomy_level,
        delegation_depth=record.delegation_depth,
        status=DelegationStatus(record.status),
        purpose=record.purpose,
        idempotency_key=record.idempotency_key,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
        created_at=record.created_at,
    )


async def _append_delegation_audit(
    session: AsyncSession,
    tenant_id: str,
    actor_identity_id: str,
    delegation_id: str,
    transaction_id: str,
    event_type: str,
    decision: str,
    reason: str,
    payload: dict[str, Any],
) -> None:
    """Append a delegation lifecycle or authorization decision to the tamper-evident tenant audit hash chain."""
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
    chain_hash = compute_sha256(f"{prev_hash}:{entry_id}:{decision}:{now.isoformat()}")

    # Redact sensitive parameters if present
    clean_payload = dict(payload)
    for sensitive_key in ("secret", "token", "password", "api_key", "credentials"):
        if sensitive_key in clean_payload:
            clean_payload[sensitive_key] = "[REDACTED]"

    session.add(
        AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=seq,
            session_id=delegation_id,
            trace_id="delegation-service",
            prompt_hash=compute_sha256(""),
            response_hash=compute_sha256(""),
            hrs_score=0.0,
            risk_tier="DELEGATION_GOVERNANCE",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type=event_type,
            actor_identity_id=actor_identity_id,
            transaction_id=transaction_id,
            decision=decision,
            policy_reference="phase8_delegation_governance",
            reason=reason,
            event_payload=clean_payload,
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
    )


# ---------------------------------------------------------------------------
# Core Delegation Service Class
# ---------------------------------------------------------------------------


class DelegationService:
    """Core delegation-governance service enforcing authority attenuation, lifecycle transitions,
    and non-repudiable audit trails across cross-agent delegation chains.
    """

    async def _get_ancestor_chain(
        self, session: AsyncSession, tenant_id: str, transaction_id: str
    ) -> list[AgentDelegation]:
        """Walk up the incoming delegation chain starting from a given transaction ID.

        Returns all ancestor AgentDelegation records ordered from immediate parent upwards.
        Detects cycles and enforces MAX_DELEGATION_DEPTH.
        """
        ancestors: list[AgentDelegation] = []
        curr_txn_id: str | None = transaction_id
        seen_grants: set[str] = set()

        while curr_txn_id and len(ancestors) <= MAX_DELEGATION_DEPTH + 1:
            stmt = select(AgentDelegation).where(
                AgentDelegation.tenant_id == tenant_id,
                AgentDelegation.child_transaction_id == curr_txn_id,
            )
            grant = (await session.execute(stmt)).scalar_one_or_none()
            if not grant:
                break

            if grant.id in seen_grants:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Delegation cycle detected at grant '{grant.id}'",
                )
            seen_grants.add(grant.id)
            ancestors.append(grant)
            curr_txn_id = grant.parent_transaction_id

        return ancestors

    async def create_delegation_grant(
        self,
        auth: AuthContext,
        request: DelegationGrantRequest,
        session: AsyncSession | None = None,
    ) -> DelegationGrantResponse:
        """Create a pending delegation grant after strict authority attenuation and confinement checks."""
        if not auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authoritative tenant is required")

        async def _execute_create(s: AsyncSession) -> DelegationGrantResponse:
            # 1. Check idempotency first within this tenant
            existing = (
                await s.execute(
                    select(AgentDelegation).where(
                        AgentDelegation.tenant_id == auth.tenant_id,
                        AgentDelegation.idempotency_key == request.idempotency_key.strip(),
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                if _is_semantically_equivalent(existing, request):
                    return _delegation_response(existing)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key conflict: identical key reused with mismatched request parameters",
                )

            # 2. Verify parent transaction
            parent_txn = await s.get(AITransaction, request.parent_transaction_id)
            if parent_txn is None or parent_txn.tenant_id != auth.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent transaction not found")

            if parent_txn.state in _TERMINAL_TRANSACTION_STATES:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Parent transaction is terminal ({parent_txn.state}); cannot delegate authority",
                )

            if not parent_txn.agent_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Parent transaction does not have an associated delegating agent",
                )
            parent_agent_id = parent_txn.agent_id

            if auth.role not in {
                Role.SUPER_ADMIN,
                Role.TENANT_ADMIN,
                Role.OPERATOR,
            }:
                if not auth.agent_id or auth.agent_id != parent_agent_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Caller '{auth.agent_id or auth.identity_id}' is not authorized to create delegation for "
                            f"parent agent '{parent_agent_id}'"
                        ),
                    )

            # 3. Verify parent and child agents
            parent_agent = await s.get(Agent, parent_agent_id)
            if parent_agent is None or parent_agent.tenant_id != auth.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Parent agent is inactive or not found"
                )
            if parent_agent.status == AgentStatus.SUSPENDED.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Parent agent '{parent_agent_id}' is suspended and cannot delegate authority",
                )
            if parent_agent.status == AgentStatus.REVOKED.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Parent agent '{parent_agent_id}' is revoked and cannot delegate authority",
                )
            if not parent_agent.active or parent_agent.status == AgentStatus.REGISTERED.value:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Parent agent is inactive or not found"
                )

            child_agent = await s.get(Agent, request.delegatee_agent_id)
            if child_agent is None or child_agent.tenant_id != auth.tenant_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Delegatee agent is inactive or not found"
                )
            if child_agent.status == AgentStatus.SUSPENDED.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Delegatee agent '{request.delegatee_agent_id}' is suspended and cannot receive delegation",
                )
            if child_agent.status == AgentStatus.REVOKED.value:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Delegatee agent '{request.delegatee_agent_id}' is revoked and cannot receive delegation",
                )
            if not child_agent.active or child_agent.status == AgentStatus.REGISTERED.value:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Delegatee agent is inactive or not found"
                )

            # 4. Prohibit self-delegation
            if parent_agent_id == request.delegatee_agent_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Self-delegation is prohibited: parent agent and delegatee agent cannot be identical",
                )

            # 5. Inspect complete ancestor chain
            now = datetime.now(UTC)
            ancestors = await self._get_ancestor_chain(s, auth.tenant_id, parent_txn.id)

            # Check for delegation cycles with delegatee
            for anc in ancestors:
                if anc.parent_agent_id == request.delegatee_agent_id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Delegation cycle detected: delegatee '{request.delegatee_agent_id}' is an ancestor agent"
                        ),
                    )
                if anc.status == DelegationStatus.REVOKED.value or anc.revoked_at is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot delegate: ancestor delegation grant '{anc.id}' is revoked",
                    )
                if anc.status == DelegationStatus.EXPIRED.value or anc.expires_at <= now:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot delegate: ancestor delegation grant '{anc.id}' has expired",
                    )
                if anc.status != DelegationStatus.ACTIVE.value:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Cannot delegate: ancestor delegation grant '{anc.id}' "
                            f"is in non-active status '{anc.status}'"
                        ),
                    )

            # Server-controlled delegation depth
            depth = (ancestors[0].delegation_depth + 1) if ancestors else 1
            if depth > MAX_DELEGATION_DEPTH:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Delegation depth {depth} exceeds server ceiling limit of {MAX_DELEGATION_DEPTH}",
                )

            # 6. Turn budget validation
            parent_remaining_turns = parent_txn.max_turns - parent_txn.turn_count
            if parent_remaining_turns <= 0:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Parent transaction turn budget exhausted"
                )
            if request.max_turns > parent_remaining_turns:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Requested turn budget {request.max_turns} exceeds parent remaining turns "
                        f"({parent_remaining_turns})"
                    ),
                )
            for anc in ancestors:
                if request.max_turns > anc.max_turns:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Requested turn budget {request.max_turns} exceeds ancestor grant '{anc.id}' "
                            f"turn budget ({anc.max_turns})"
                        ),
                    )

            # 7. Expiry boundary validation
            requested_expires_at = now + timedelta(seconds=request.duration_seconds)
            if ancestors:
                earliest_ancestor_expiry = min(a.expires_at for a in ancestors)
                if requested_expires_at > earliest_ancestor_expiry:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Requested grant expiry ({requested_expires_at.isoformat()}) exceeds earliest "
                            f"ancestor expiry ({earliest_ancestor_expiry.isoformat()})"
                        ),
                    )

            # 8. Authority Attenuation Verification
            # Parent capabilities in Capability table
            cap_stmt = select(Capability).where(
                Capability.tenant_id == auth.tenant_id,
                Capability.revoked_at.is_(None),
                (Capability.expires_at.is_(None) | (Capability.expires_at > now)),
                (Capability.agent_id == parent_agent_id) | (Capability.identity_id == parent_txn.actor_identity_id),
            )
            parent_caps = (await s.execute(cap_stmt)).scalars().all()
            parent_caps_by_type: dict[str, list[Capability]] = {}
            for pc in parent_caps:
                parent_caps_by_type.setdefault(pc.capability_type, []).append(pc)

            # Ancestor delegation capabilities map
            ancestor_caps_by_type: dict[str, list[dict[str, Any]]] = {}
            if ancestors:
                # Immediate ancestor defines direct ceiling
                imm_anc = ancestors[0]
                for dc in imm_anc.delegated_capabilities:
                    ancestor_caps_by_type.setdefault(dc.get("capability_type", ""), []).append(dc)

            for req_cap in request.delegated_capabilities:
                # Must be possessed by parent
                if req_cap.capability_type not in parent_caps_by_type:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Parent agent lacks active capability '{req_cap.capability_type}'",
                    )

                available_parent_caps = parent_caps_by_type[req_cap.capability_type]

                # Check autonomy against parent agent and parent capability
                max_parent_cap_autonomy = max(pc.max_autonomy_level for pc in available_parent_caps)
                parent_autonomy_ceiling = min(parent_agent.max_autonomy_level, max_parent_cap_autonomy)
                if req_cap.max_autonomy_level > parent_autonomy_ceiling:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Requested autonomy level {req_cap.max_autonomy_level} for capability "
                            f"'{req_cap.capability_type}' exceeds parent ceiling {parent_autonomy_ceiling}"
                        ),
                    )

                # Check autonomy against ancestor grants
                if ancestor_caps_by_type:
                    if req_cap.capability_type not in ancestor_caps_by_type:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail=(
                                f"Capability '{req_cap.capability_type}' is not permitted by ancestor delegation grant"
                            ),
                        )
                    anc_cap = ancestor_caps_by_type[req_cap.capability_type][0]
                    if req_cap.max_autonomy_level > anc_cap.get("max_autonomy_level", 0):
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail=(
                                f"Requested autonomy level {req_cap.max_autonomy_level} exceeds ancestor "
                                f"delegation ceiling {anc_cap.get('max_autonomy_level', 0)}"
                            ),
                        )
                    # Check scope attenuation relative to ancestor
                    is_att, att_reason = is_scope_attenuated(anc_cap.get("resource_scope", {}), req_cap.resource_scope)
                    if not is_att:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail=(
                                f"Capability '{req_cap.capability_type}' scope widening rejected against ancestor: "
                                f"{att_reason}"
                            ),
                        )

                # Check scope attenuation against at least one parent capability
                scope_attenuated = False
                scope_fail_reasons: list[str] = []
                for pc in available_parent_caps:
                    is_att, att_reason = is_scope_attenuated(pc.resource_scope, req_cap.resource_scope)
                    if is_att:
                        is_cons_att, cons_reason = is_constraints_attenuated(pc.constraints, req_cap.constraints)
                        if is_cons_att:
                            scope_attenuated = True
                            break
                        else:
                            scope_fail_reasons.append(cons_reason)
                    else:
                        scope_fail_reasons.append(att_reason)

                if not scope_attenuated:
                    reason_msg = "; ".join(scope_fail_reasons)
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=(
                            f"Capability '{req_cap.capability_type}' scope/constraint widening rejected: {reason_msg}"
                        ),
                    )

            # 9. Dynamic Information Flow Control (DIFC) Interlock
            active_taints = parent_txn.taint_flags or []
            if is_dangerous_triad_active(active_taints) or Taint.CONCURRENT_RESTRICTION.value in active_taints:
                # Concurrent untrusted and confidential data restrict external communication
                for req_cap in request.delegated_capabilities:
                    if req_cap.capability_type.startswith("external:") or req_cap.capability_type in {
                        "tools:web_search",
                        "tools:http_request",
                        "tools:webhook",
                        "tools:email_send",
                        "network:egress",
                    }:
                        if req_cap.max_autonomy_level < 4:
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail=(
                                    "DIFC Dangerous Triad Interlock: external capabilities in confidential/untrusted "
                                    "context require mandatory human review (autonomy level 4)"
                                ),
                            )

            # 10. Persist Grant Record atomically with Idempotency Protection
            grant_id = f"del_{uuid.uuid4().hex}"
            caps_data = [c.model_dump() for c in request.delegated_capabilities]
            consolidated_scope = _consolidate_resource_scopes(request.delegated_capabilities)
            max_autonomy = max(c.max_autonomy_level for c in request.delegated_capabilities)

            grant_record = AgentDelegation(
                id=grant_id,
                tenant_id=auth.tenant_id,
                parent_agent_id=parent_agent_id,
                parent_transaction_id=request.parent_transaction_id,
                child_agent_id=request.delegatee_agent_id,
                child_transaction_id=None,  # PENDING lifecycle state
                delegated_capabilities=caps_data,
                resource_scope=consolidated_scope,
                max_autonomy_level=max_autonomy,
                delegation_depth=depth,
                max_turns=request.max_turns,
                status=DelegationStatus.PENDING.value,
                purpose=request.purpose.strip(),
                idempotency_key=request.idempotency_key.strip(),
                expires_at=requested_expires_at,
                revoked_at=None,
                created_at=now,
                updated_at=now,
            )

            try:
                async with s.begin_nested():
                    s.add(grant_record)
                    await s.flush()
            except IntegrityError:
                # Handle concurrent race on (tenant_id, idempotency_key)
                existing_race = (
                    await s.execute(
                        select(AgentDelegation).where(
                            AgentDelegation.tenant_id == auth.tenant_id,
                            AgentDelegation.idempotency_key == request.idempotency_key.strip(),
                        )
                    )
                ).scalar_one_or_none()
                if existing_race is not None and _is_semantically_equivalent(existing_race, request):
                    return _delegation_response(existing_race)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key conflict: identical key reused with mismatched request parameters",
                ) from None

            # 11. Append Audit Entry
            await _append_delegation_audit(
                session=s,
                tenant_id=auth.tenant_id,
                actor_identity_id=auth.identity_id or parent_txn.actor_identity_id,
                delegation_id=grant_record.id,
                transaction_id=request.parent_transaction_id,
                event_type="DELEGATION_GRANT_CREATED",
                decision="CREATE",
                reason=request.purpose.strip(),
                payload={
                    "parent_agent_id": parent_agent_id,
                    "child_agent_id": request.delegatee_agent_id,
                    "delegation_depth": depth,
                    "max_turns": request.max_turns,
                    "max_autonomy_level": max_autonomy,
                    "capabilities_count": len(request.delegated_capabilities),
                    "idempotency_key": request.idempotency_key.strip(),
                },
            )
            await s.flush()
            return _delegation_response(grant_record)

        if session is not None:
            return await _execute_create(session)
        async with db_session.get_tenant_session(auth.tenant_id) as managed_session:
            return await _execute_create(managed_session)

    async def activate_delegation_grant(
        self,
        auth: AuthContext,
        delegation_id: str,
        child_transaction_id: str,
        session: AsyncSession | None = None,
    ) -> DelegationGrantResponse:
        """Atomically bind a pending delegation grant to a child transaction and transition to ACTIVE."""
        if not auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authoritative tenant is required")

        async def _execute_activate(s: AsyncSession) -> DelegationGrantResponse:
            grant = await s.get(AgentDelegation, delegation_id, with_for_update=True)
            if grant is None or grant.tenant_id != auth.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delegation grant not found")

            now = datetime.now(UTC)

            # Terminal / invalid status checks
            if grant.status == DelegationStatus.REVOKED.value or grant.revoked_at is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Delegation grant is revoked")

            if grant.status == DelegationStatus.EXPIRED.value or grant.expires_at <= now:
                if grant.status != DelegationStatus.EXPIRED.value:
                    grant.status = DelegationStatus.EXPIRED.value
                    grant.updated_at = now
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Delegation grant has expired")

            if grant.status == DelegationStatus.ACTIVE.value:
                if grant.child_transaction_id == child_transaction_id:
                    # Idempotent reactivation
                    return _delegation_response(grant)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Delegation grant is already active and bound to a different child transaction",
                )

            if grant.status != DelegationStatus.PENDING.value:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Cannot activate delegation grant in state '{grant.status}'",
                )

            # Validate child transaction
            child_txn = await s.get(AITransaction, child_transaction_id, with_for_update=True)
            if child_txn is None or child_txn.tenant_id != auth.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Child transaction not found")

            if child_txn.agent_id != grant.child_agent_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Child transaction agent '{child_txn.agent_id}' does not match delegation "
                        f"child agent '{grant.child_agent_id}'"
                    ),
                )

            if child_txn.parent_transaction_id != grant.parent_transaction_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Child transaction parent transaction does not match delegation parent transaction",
                )

            if child_txn.state in _TERMINAL_TRANSACTION_STATES:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Child transaction is terminal ({child_txn.state}); cannot activate delegation",
                )

            # Check that child transaction is not already bound to another active delegation grant
            existing_active_binding = (
                await s.execute(
                    select(AgentDelegation).where(
                        AgentDelegation.tenant_id == auth.tenant_id,
                        AgentDelegation.child_transaction_id == child_transaction_id,
                        AgentDelegation.id != grant.id,
                        AgentDelegation.status == DelegationStatus.ACTIVE.value,
                    )
                )
            ).scalar_one_or_none()

            if existing_active_binding is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Child transaction '{child_transaction_id}' is already bound to active "
                        f"delegation grant '{existing_active_binding.id}'"
                    ),
                )

            # Verify ancestor chain is still active at activation time
            ancestors = await self._get_ancestor_chain(s, auth.tenant_id, grant.parent_transaction_id)
            for anc in ancestors:
                if anc.status == DelegationStatus.REVOKED.value or anc.revoked_at is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot activate: ancestor delegation grant '{anc.id}' is revoked",
                    )
                if anc.status == DelegationStatus.EXPIRED.value or anc.expires_at <= now:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Cannot activate: ancestor delegation grant '{anc.id}' has expired",
                    )

            # Atomic transition
            grant.child_transaction_id = child_transaction_id
            grant.status = DelegationStatus.ACTIVE.value
            grant.updated_at = now

            await _append_delegation_audit(
                session=s,
                tenant_id=auth.tenant_id,
                actor_identity_id=auth.identity_id or child_txn.actor_identity_id,
                delegation_id=grant.id,
                transaction_id=child_transaction_id,
                event_type="DELEGATION_GRANT_ACTIVATED",
                decision="ACTIVATE",
                reason="Delegation grant activated and bound to child transaction",
                payload={
                    "child_transaction_id": child_transaction_id,
                    "parent_transaction_id": grant.parent_transaction_id,
                    "child_agent_id": grant.child_agent_id,
                },
            )
            await s.flush()
            return _delegation_response(grant)

        if session is not None:
            return await _execute_activate(session)
        async with db_session.get_tenant_session(auth.tenant_id) as managed_session:
            return await _execute_activate(managed_session)

    async def get_delegation_grant(
        self,
        auth: AuthContext,
        delegation_id: str,
        session: AsyncSession | None = None,
    ) -> DelegationGrantResponse:
        """Retrieve an authoritative delegation grant within authenticated tenant context."""
        if not auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authoritative tenant is required")

        async def _execute_get(s: AsyncSession) -> DelegationGrantResponse:
            grant = await s.get(AgentDelegation, delegation_id)
            if grant is None or grant.tenant_id != auth.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delegation grant not found")

            # Lazy expiration check on read
            now = datetime.now(UTC)
            if (
                grant.status in (DelegationStatus.PENDING.value, DelegationStatus.ACTIVE.value)
                and grant.expires_at <= now
            ):
                grant.status = DelegationStatus.EXPIRED.value
                grant.updated_at = now
                await _append_delegation_audit(
                    session=s,
                    tenant_id=auth.tenant_id,
                    actor_identity_id=auth.identity_id or "system",
                    delegation_id=grant.id,
                    transaction_id=grant.child_transaction_id or grant.parent_transaction_id,
                    event_type="DELEGATION_GRANT_EXPIRED",
                    decision="EXPIRE",
                    reason="Grant expired during read evaluation",
                    payload={"expired_at": grant.expires_at.isoformat()},
                )
                await s.flush()

            return _delegation_response(grant)

        if session is not None:
            return await _execute_get(session)
        async with db_session.get_tenant_session(auth.tenant_id) as managed_session:
            return await _execute_get(managed_session)

    async def validate_delegation_for_operation(
        self,
        auth: AuthContext,
        delegation_id: str,
        capability_type: str,
        resource: dict[str, Any] | None = None,
        requested_autonomy_level: int = 0,
        session: AsyncSession | None = None,
    ) -> PolicyDecision:
        """Validate an active delegation grant immediately before tool/action execution."""
        if not auth.tenant_id:
            return PolicyDecision(decision=Decision.DENY, reason="Authoritative tenant is required")

        async def _execute_validate(s: AsyncSession) -> PolicyDecision:
            now = datetime.now(UTC)
            grant = await s.get(AgentDelegation, delegation_id)
            if grant is None or grant.tenant_id != auth.tenant_id:
                return PolicyDecision(decision=Decision.DENY, reason="Delegation grant not found")

            target_txn = grant.child_transaction_id or grant.parent_transaction_id

            # 1. Status Check: Pending cannot authorize execution
            if grant.status == DelegationStatus.PENDING.value:
                await _append_delegation_audit(
                    s,
                    auth.tenant_id,
                    auth.identity_id or "system",
                    grant.id,
                    target_txn,
                    "DELEGATION_AUTHORIZATION_DENIED",
                    Decision.DENY.value,
                    "Delegation grant is pending activation",
                    {"capability_type": capability_type},
                )
                return PolicyDecision(
                    decision=Decision.DENY,
                    reason="Delegation grant is pending activation; child transaction not bound",
                )

            # 2. Revocation Check
            if grant.status == DelegationStatus.REVOKED.value or grant.revoked_at is not None:
                await _append_delegation_audit(
                    s,
                    auth.tenant_id,
                    auth.identity_id or "system",
                    grant.id,
                    target_txn,
                    "DELEGATION_AUTHORIZATION_DENIED",
                    Decision.DENY.value,
                    "Delegation grant is revoked",
                    {"capability_type": capability_type},
                )
                return PolicyDecision(decision=Decision.DENY, reason="Delegation grant is revoked")

            # 3. Expiration Check
            if grant.status == DelegationStatus.EXPIRED.value or grant.expires_at <= now:
                if grant.status != DelegationStatus.EXPIRED.value:
                    grant.status = DelegationStatus.EXPIRED.value
                    grant.updated_at = now
                await _append_delegation_audit(
                    s,
                    auth.tenant_id,
                    auth.identity_id or "system",
                    grant.id,
                    target_txn,
                    "DELEGATION_AUTHORIZATION_DENIED",
                    Decision.DENY.value,
                    "Delegation grant has expired",
                    {"capability_type": capability_type},
                )
                return PolicyDecision(decision=Decision.DENY, reason="Delegation grant has expired")

            if grant.status != DelegationStatus.ACTIVE.value:
                await _append_delegation_audit(
                    s,
                    auth.tenant_id,
                    auth.identity_id or "system",
                    grant.id,
                    target_txn,
                    "DELEGATION_AUTHORIZATION_DENIED",
                    Decision.DENY.value,
                    f"Delegation grant in non-active status '{grant.status}'",
                    {"capability_type": capability_type},
                )
                return PolicyDecision(
                    decision=Decision.DENY,
                    reason=f"Delegation grant in non-active status '{grant.status}'",
                )

            # 4. Check Child and Parent Agent Lifecycle Status
            child_agent = await s.get(Agent, grant.child_agent_id)
            if child_agent is not None:
                if child_agent.status == AgentStatus.SUSPENDED.value:
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        f"Delegated child agent '{grant.child_agent_id}' is suspended",
                        {"child_agent_id": grant.child_agent_id},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=f"Delegated child agent '{grant.child_agent_id}' is suspended",
                    )
                if child_agent.status == AgentStatus.REVOKED.value or not child_agent.active:
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        f"Delegated child agent '{grant.child_agent_id}' is revoked or inactive",
                        {"child_agent_id": grant.child_agent_id},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=f"Delegated child agent '{grant.child_agent_id}' is revoked or inactive",
                    )

            parent_agent = await s.get(Agent, grant.parent_agent_id)
            if parent_agent is not None:
                if parent_agent.status == AgentStatus.SUSPENDED.value:
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        f"Delegating parent agent '{grant.parent_agent_id}' is suspended",
                        {"parent_agent_id": grant.parent_agent_id},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=f"Delegating parent agent '{grant.parent_agent_id}' is suspended",
                    )
                if parent_agent.status == AgentStatus.REVOKED.value or not parent_agent.active:
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        f"Delegating parent agent '{grant.parent_agent_id}' is revoked or inactive",
                        {"parent_agent_id": grant.parent_agent_id},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=f"Delegating parent agent '{grant.parent_agent_id}' is revoked or inactive",
                    )

            # 5. Complete Ancestor Chain Verification
            ancestors = await self._get_ancestor_chain(s, auth.tenant_id, grant.parent_transaction_id)
            for anc in ancestors:
                if anc.status == DelegationStatus.REVOKED.value or anc.revoked_at is not None:
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        f"Ancestor delegation grant '{anc.id}' is revoked",
                        {"ancestor_id": anc.id},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=f"Ancestor delegation grant '{anc.id}' is revoked",
                    )
                if anc.status == DelegationStatus.EXPIRED.value or anc.expires_at <= now:
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        f"Ancestor delegation grant '{anc.id}' has expired",
                        {"ancestor_id": anc.id},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=f"Ancestor delegation grant '{anc.id}' has expired",
                    )

                anc_parent = await s.get(Agent, anc.parent_agent_id)
                if anc_parent is not None and (
                    anc_parent.status in (AgentStatus.SUSPENDED.value, AgentStatus.REVOKED.value)
                    or not anc_parent.active
                ):
                    chain_break_msg = (
                        f"Ancestor agent '{anc.parent_agent_id}' is {anc_parent.status}; delegation chain broken"
                    )
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        chain_break_msg,
                        {"ancestor_agent_id": anc.parent_agent_id, "status": anc_parent.status},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=chain_break_msg,
                    )

                anc_child = await s.get(Agent, anc.child_agent_id)
                if anc_child is not None and (
                    anc_child.status in (AgentStatus.SUSPENDED.value, AgentStatus.REVOKED.value) or not anc_child.active
                ):
                    child_break_msg = (
                        f"Ancestor agent '{anc.child_agent_id}' is {anc_child.status}; delegation chain broken"
                    )
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        child_break_msg,
                        {"ancestor_agent_id": anc.child_agent_id, "status": anc_child.status},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=child_break_msg,
                    )

            # 5. Bound Child Transaction Checks
            if grant.child_transaction_id:
                child_txn = await s.get(AITransaction, grant.child_transaction_id)
                if child_txn is not None:
                    if child_txn.state in _TERMINAL_TRANSACTION_STATES:
                        await _append_delegation_audit(
                            s,
                            auth.tenant_id,
                            auth.identity_id or "system",
                            grant.id,
                            target_txn,
                            "DELEGATION_AUTHORIZATION_DENIED",
                            Decision.DENY.value,
                            f"Child transaction is terminal ({child_txn.state})",
                            {"child_transaction_id": child_txn.id},
                        )
                        return PolicyDecision(
                            decision=Decision.DENY,
                            reason=f"Child transaction is terminal ({child_txn.state})",
                        )
                    if child_txn.turn_count >= child_txn.max_turns or child_txn.turn_count >= grant.max_turns:
                        await _append_delegation_audit(
                            s,
                            auth.tenant_id,
                            auth.identity_id or "system",
                            grant.id,
                            target_txn,
                            "DELEGATION_AUTHORIZATION_DENIED",
                            Decision.DENY.value,
                            "Delegation turn budget exhausted",
                            {"turn_count": child_txn.turn_count, "max_turns": grant.max_turns},
                        )
                        return PolicyDecision(
                            decision=Decision.DENY,
                            reason="Delegation turn budget exhausted",
                        )

            # 6. Capability Matching
            matching_cap = next(
                (c for c in grant.delegated_capabilities if c.get("capability_type") == capability_type),
                None,
            )
            if not matching_cap:
                await _append_delegation_audit(
                    s,
                    auth.tenant_id,
                    auth.identity_id or "system",
                    grant.id,
                    target_txn,
                    "DELEGATION_AUTHORIZATION_DENIED",
                    Decision.DENY.value,
                    f"Capability '{capability_type}' not granted by delegation",
                    {"capability_type": capability_type},
                )
                return PolicyDecision(
                    decision=Decision.DENY,
                    reason=f"Capability '{capability_type}' not granted by delegation",
                )

            # 7. Autonomy Level Ceiling Check
            cap_autonomy = matching_cap.get("max_autonomy_level", 0)
            effective_autonomy = min(grant.max_autonomy_level, cap_autonomy)
            if requested_autonomy_level > effective_autonomy:
                await _append_delegation_audit(
                    s,
                    auth.tenant_id,
                    auth.identity_id or "system",
                    grant.id,
                    target_txn,
                    "DELEGATION_AUTHORIZATION_DENIED",
                    Decision.REQUIRE_APPROVAL.value,
                    "Requested autonomy exceeds delegation ceiling",
                    {
                        "requested_autonomy": requested_autonomy_level,
                        "ceiling": effective_autonomy,
                    },
                )
                return PolicyDecision(
                    decision=Decision.REQUIRE_APPROVAL,
                    reason=(
                        f"Requested autonomy level {requested_autonomy_level} exceeds "
                        f"delegation ceiling {effective_autonomy}"
                    ),
                )

            # 8. Resource Scope Validation for Operation
            target_res_dict = resource or {}
            cap_scope = matching_cap.get("resource_scope", {})
            if "allowed_prefixes" in cap_scope:
                allowed_pfx = cap_scope["allowed_prefixes"]
                target_path = (
                    target_res_dict.get("target_resource")
                    or target_res_dict.get("path")
                    or target_res_dict.get("uri")
                    or ""
                )
                if not any(target_path.startswith(pfx) for pfx in allowed_pfx):
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        f"Target resource '{target_path}' not allowed by prefixes {allowed_pfx}",
                        {"target_path": target_path, "allowed_prefixes": allowed_pfx},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=f"Target resource '{target_path}' not permitted by delegated scope {allowed_pfx}",
                    )

            for scope_k, scope_v in cap_scope.items():
                if scope_k == "allowed_prefixes":
                    continue
                if isinstance(scope_v, list):
                    actual_v = target_res_dict.get(scope_k)
                    if actual_v is not None and actual_v not in scope_v:
                        await _append_delegation_audit(
                            s,
                            auth.tenant_id,
                            auth.identity_id or "system",
                            grant.id,
                            target_txn,
                            "DELEGATION_AUTHORIZATION_DENIED",
                            Decision.DENY.value,
                            f"Parameter '{scope_k}={actual_v}' not permitted by scope {scope_v}",
                            {"parameter": scope_k, "value": actual_v},
                        )
                        return PolicyDecision(
                            decision=Decision.DENY,
                            reason=(
                                f"Resource parameter '{scope_k}' value '{actual_v}' is outside delegated list {scope_v}"
                            ),
                        )
                elif target_res_dict.get(scope_k) != scope_v:
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        f"Resource parameter '{scope_k}' mismatch",
                        {"parameter": scope_k, "expected": scope_v},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=f"Resource parameter '{scope_k}' does not match required delegated value '{scope_v}'",
                    )

            # 9. Constraints Validation for Operation
            cap_constraints = matching_cap.get("constraints", {})
            if "max_amount" in cap_constraints:
                req_amt = target_res_dict.get("amount")
                if isinstance(req_amt, (int, float)) and req_amt > cap_constraints["max_amount"]:
                    await _append_delegation_audit(
                        s,
                        auth.tenant_id,
                        auth.identity_id or "system",
                        grant.id,
                        target_txn,
                        "DELEGATION_AUTHORIZATION_DENIED",
                        Decision.DENY.value,
                        f"Parameter 'amount' ({req_amt}) exceeds delegated limit {cap_constraints['max_amount']}",
                        {"amount": req_amt, "max_amount": cap_constraints["max_amount"]},
                    )
                    return PolicyDecision(
                        decision=Decision.DENY,
                        reason=(
                            f"Parameter 'amount' ({req_amt}) exceeds delegated limit {cap_constraints['max_amount']}"
                        ),
                    )

            # 10. Audit Allowed Operation
            await _append_delegation_audit(
                s,
                auth.tenant_id,
                auth.identity_id or "system",
                grant.id,
                target_txn,
                "DELEGATION_AUTHORIZATION_ALLOWED",
                Decision.ALLOW.value,
                "Delegation grant authorizes operation",
                {"capability_type": capability_type},
            )
            return PolicyDecision(decision=Decision.ALLOW, reason="Delegation grant authorizes operation")

        if session is not None:
            return await _execute_validate(session)
        async with db_session.get_tenant_session(auth.tenant_id) as managed_session:
            return await _execute_validate(managed_session)

    async def revoke_delegation_grant(
        self,
        auth: AuthContext,
        delegation_id: str,
        reason: str,
        session: AsyncSession | None = None,
    ) -> DelegationGrantResponse:
        """Revoke a delegation grant immediately at the authorization boundary."""
        if not auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authoritative tenant is required")

        async def _execute_revoke(s: AsyncSession) -> DelegationGrantResponse:
            grant = await s.get(AgentDelegation, delegation_id, with_for_update=True)
            if grant is None or grant.tenant_id != auth.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delegation grant not found")

            # Idempotent if already revoked
            if grant.status == DelegationStatus.REVOKED.value:
                return _delegation_response(grant)

            now = datetime.now(UTC)
            grant.status = DelegationStatus.REVOKED.value
            grant.revoked_at = now
            grant.updated_at = now

            # Cascade revocation to associated pending or accepted handoffs
            hnd_stmt = (
                select(AgentHandoff)
                .where(
                    AgentHandoff.tenant_id == auth.tenant_id,
                    AgentHandoff.delegation_id == grant.id,
                    AgentHandoff.status.in_([HandoffStatus.PENDING.value, HandoffStatus.ACCEPTED.value]),
                )
                .with_for_update()
            )
            hnd_res = await s.execute(hnd_stmt)
            active_handoffs = hnd_res.scalars().all()
            for h in active_handoffs:
                h.status = HandoffStatus.REVOKED.value
                h.cancelled_at = now
                h.cancellation_reason = f"Bound delegation grant '{grant.id}' was revoked: {reason.strip()}"
                h.updated_at = now
                if h.child_transaction_id:
                    c_txn = await s.get(AITransaction, h.child_transaction_id, with_for_update=True)
                    if c_txn and hasattr(c_txn, "state") and c_txn.state not in _TERMINAL_TRANSACTION_STATES:
                        c_txn.state = TransactionState.CANCELLED.value
                        c_txn.final_disposition = TransactionState.CANCELLED.value
                        c_txn.version += 1
                        c_txn.updated_at = now

            # If child transaction was directly bound to delegation grant, cancel if active
            if grant.child_transaction_id:
                direct_child = await s.get(AITransaction, grant.child_transaction_id, with_for_update=True)
                if (
                    direct_child
                    and hasattr(direct_child, "state")
                    and direct_child.state not in _TERMINAL_TRANSACTION_STATES
                ):
                    direct_child.state = TransactionState.CANCELLED.value
                    direct_child.final_disposition = TransactionState.CANCELLED.value
                    direct_child.version += 1
                    direct_child.updated_at = now

            await _append_delegation_audit(
                session=s,
                tenant_id=auth.tenant_id,
                actor_identity_id=auth.identity_id or "system",
                delegation_id=grant.id,
                transaction_id=grant.child_transaction_id or grant.parent_transaction_id,
                event_type="DELEGATION_GRANT_REVOKED",
                decision="REVOKE",
                reason=reason.strip(),
                payload={
                    "revoked_at": now.isoformat(),
                    "reason": reason.strip(),
                    "child_agent_id": grant.child_agent_id,
                    "parent_agent_id": grant.parent_agent_id,
                    "cascaded_handoffs_count": len(active_handoffs),
                },
            )
            await s.flush()
            return _delegation_response(grant)

        if session is not None:
            return await _execute_revoke(session)
        async with db_session.get_tenant_session(auth.tenant_id) as managed_session:
            return await _execute_revoke(managed_session)

    async def expire_delegation_grant(
        self,
        auth: AuthContext,
        delegation_id: str,
        session: AsyncSession | None = None,
    ) -> DelegationGrantResponse:
        """Explicitly transition a grant to EXPIRED status."""
        if not auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authoritative tenant is required")

        async def _execute_expire(s: AsyncSession) -> DelegationGrantResponse:
            grant = await s.get(AgentDelegation, delegation_id, with_for_update=True)
            if grant is None or grant.tenant_id != auth.tenant_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delegation grant not found")

            now = datetime.now(UTC)
            if grant.status == DelegationStatus.EXPIRED.value:
                return _delegation_response(grant)

            grant.status = DelegationStatus.EXPIRED.value
            grant.updated_at = now

            await _append_delegation_audit(
                session=s,
                tenant_id=auth.tenant_id,
                actor_identity_id=auth.identity_id or "system",
                delegation_id=grant.id,
                transaction_id=grant.child_transaction_id or grant.parent_transaction_id,
                event_type="DELEGATION_GRANT_EXPIRED",
                decision="EXPIRE",
                reason="Delegation grant expired",
                payload={"expired_at": now.isoformat()},
            )
            await s.flush()
            return _delegation_response(grant)

        if session is not None:
            return await _execute_expire(session)
        async with db_session.get_tenant_session(auth.tenant_id) as managed_session:
            return await _execute_expire(managed_session)

    async def list_delegation_grants(
        self,
        auth: AuthContext,
        parent_transaction_id: str | None = None,
        parent_agent_id: str | None = None,
        child_agent_id: str | None = None,
        status: DelegationStatus | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> list[DelegationGrantResponse]:
        """List delegation grants for an authenticated tenant with filtering and pagination."""
        if not auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Authoritative tenant is required")

        async def _execute_list(s: AsyncSession) -> list[DelegationGrantResponse]:
            stmt = select(AgentDelegation).where(AgentDelegation.tenant_id == auth.tenant_id)

            if parent_transaction_id:
                stmt = stmt.where(AgentDelegation.parent_transaction_id == parent_transaction_id)
            if parent_agent_id:
                stmt = stmt.where(AgentDelegation.parent_agent_id == parent_agent_id)
            if child_agent_id:
                stmt = stmt.where(AgentDelegation.child_agent_id == child_agent_id)
            if status:
                stmt = stmt.where(AgentDelegation.status == status.value)

            stmt = stmt.order_by(AgentDelegation.created_at.desc(), AgentDelegation.id.desc())
            clamped_limit = min(max(1, limit), MAX_PAGE_LIMIT)
            clamped_offset = max(0, offset)
            stmt = stmt.limit(clamped_limit).offset(clamped_offset)

            rows = (await s.execute(stmt)).scalars().all()
            return [_delegation_response(r) for r in rows]

        if session is not None:
            return await _execute_list(session)
        async with db_session.get_tenant_session(auth.tenant_id) as managed_session:
            return await _execute_list(managed_session)


# Global singleton instance and public module-level function interfaces
delegation_service = DelegationService()

create_delegation_grant = delegation_service.create_delegation_grant
activate_delegation_grant = delegation_service.activate_delegation_grant
get_delegation_grant = delegation_service.get_delegation_grant
validate_delegation_for_operation = delegation_service.validate_delegation_for_operation
revoke_delegation_grant = delegation_service.revoke_delegation_grant
expire_delegation_grant = delegation_service.expire_delegation_grant
list_delegation_grants = delegation_service.list_delegation_grants
