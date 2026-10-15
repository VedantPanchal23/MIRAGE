"""Shared-Resource Concurrency, Lease Management, and Fencing Token Service.

Adheres to MIRAGE Phase 8 architecture:
- Explicit canonical URI normalization and hierarchical prefix conflict detection
  (avoids substring false positives/negatives).
- ACID transactional row locking with monotonically increasing fencing tokens per resource.
- Stale-holder rejection: lease expiration alone never makes a stale holder safe to execute.
- Safe release and renewal ownership validation preventing accidental cross-execution release.
- Tenant isolation and cryptographic audit log emission.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentHandoff, AITransaction, AuditLogRecord, ResourceLease
from db.session import get_tenant_session
from services.agent_governance import agent_governance_service
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext
from shared.schemas.concurrency import (
    ConcurrencyMode,
    LeaseStatus,
    ResourceLeaseAcquireRequest,
    ResourceLeaseReleaseRequest,
    ResourceLeaseRenewRequest,
    ResourceLeaseResponse,
)
from shared.schemas.control_plane import Decision, PolicyDecision

logger = get_logger("concurrency_service")


def canonicalize_resource_uri(raw_uri: str) -> str:
    """Normalize a target resource string into a canonical, unambiguous URI.

    Handles scheme-less paths, duplicate slashes, query strings, and path casing.
    Example:
      'db://Finance/Ledger/' -> 'db://finance/ledger'
      'http://api.service.com:8080/v1/orders/' -> 'http://api.service.com:8080/v1/orders'
    """
    stripped = raw_uri.strip()
    if not stripped:
        raise ValueError("Resource URI cannot be empty or whitespace")

    if "://" not in stripped:
        stripped = f"resource://local/{stripped.lstrip('/')}"

    parsed = urlparse(stripped)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()

    # Normalize path segments (remove duplicate slashes and redundant trailing slashes, case-fold)
    path_segments = [seg.lower() for seg in parsed.path.split("/") if seg and seg != "."]
    normalized_path = "/" + "/".join(path_segments) if path_segments else ""

    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{normalized_path}{query}"


def are_resources_in_conflict(
    res_a: str,
    mode_a: ConcurrencyMode | str,
    res_b: str,
    mode_b: ConcurrencyMode | str,
) -> bool:
    """Determine whether two resource lease requests conflict.

    Semantics:
    1. SHARED vs SHARED never conflicts (concurrent reads allowed).
    2. If either mode is EXCLUSIVE, conflicts occur if:
       - The canonical URIs are identical.
       - Either resource is a hierarchical prefix parent of the other (e.g. 'db://fin/ledger'
         conflicts with 'db://fin/ledger/accounts').
    3. Unrelated or non-overlapping sibling subpaths do not conflict.
    """
    m_a = mode_a.value if isinstance(mode_a, ConcurrencyMode) else str(mode_a).upper()
    m_b = mode_b.value if isinstance(mode_b, ConcurrencyMode) else str(mode_b).upper()

    if m_a == ConcurrencyMode.SHARED.value and m_b == ConcurrencyMode.SHARED.value:
        return False

    can_a = canonicalize_resource_uri(res_a)
    can_b = canonicalize_resource_uri(res_b)

    if can_a == can_b:
        return True

    # Hierarchical prefix overlap checking
    # E.g. 'db://finance/ledger' and 'db://finance/ledger/tx123'
    if can_b.startswith(f"{can_a}/") or can_a.startswith(f"{can_b}/"):
        return True

    return False


class ResourceConcurrencyService:
    """Authoritative management service for shared-resource concurrency and fencing tokens."""

    async def acquire_lease(
        self,
        auth: AuthContext,
        request: ResourceLeaseAcquireRequest,
        session: AsyncSession | None = None,
    ) -> ResourceLeaseResponse:
        """Atomically acquire a shared or exclusive lease with a monotonically increasing fencing token."""
        canonical_uri = canonicalize_resource_uri(request.resource_uri)
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> ResourceLeaseResponse:
            # 1. Validate caller transaction
            txn_stmt = select(AITransaction).where(
                AITransaction.id == request.transaction_id,
                AITransaction.tenant_id == auth.tenant_id,
            )
            txn_res = await s.execute(txn_stmt)
            txn = txn_res.scalar_one_or_none()
            if not txn:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Transaction '{request.transaction_id}' not found in tenant '{auth.tenant_id}'",
                )
            if txn.state != "ACTIVE" or txn.final_disposition is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Transaction '{request.transaction_id}' is not active (state: {txn.state})",
                )

            # 2. Validate agent lifecycle eligibility
            eligible, reason = await agent_governance_service.evaluate_agent_eligibility(
                session=s,
                tenant_id=auth.tenant_id,
                agent_id=request.agent_id,
            )
            if not eligible:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Agent '{request.agent_id}' is not eligible: {reason}",
                )

            # 3. Validate handoff if specified
            if request.handoff_id:
                hnd_stmt = select(AgentHandoff).where(
                    AgentHandoff.id == request.handoff_id,
                    AgentHandoff.tenant_id == auth.tenant_id,
                )
                hnd_res = await s.execute(hnd_stmt)
                hnd = hnd_res.scalar_one_or_none()
                if not hnd:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Bound handoff '{request.handoff_id}' not found in tenant '{auth.tenant_id}'",
                    )
                if hnd.status not in {"PENDING", "ACCEPTED"}:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Bound handoff '{request.handoff_id}' is in non-active status '{hnd.status}'",
                    )

            # 4. Lock and check active leases in the tenant
            active_leases_stmt = (
                select(ResourceLease)
                .where(
                    ResourceLease.tenant_id == auth.tenant_id,
                    ResourceLease.status == LeaseStatus.ACQUIRED.value,
                )
                .with_for_update()
            )
            active_res = await s.execute(active_leases_stmt)
            active_leases = active_res.scalars().all()

            for lease in active_leases:
                if lease.expires_at <= now:
                    lease.status = LeaseStatus.EXPIRED.value
                    lease.updated_at = now
                    continue

                if are_resources_in_conflict(
                    canonical_uri,
                    request.concurrency_mode,
                    lease.resource_uri,
                    lease.concurrency_mode,
                ):
                    if lease.holder_transaction_id == request.transaction_id:
                        # Re-entrant renewal by the same transaction
                        lease.expires_at = max(lease.expires_at, now + timedelta(seconds=request.duration_seconds))
                        lease.updated_at = now
                        await self._emit_audit_event(
                            session=s,
                            tenant_id=auth.tenant_id,
                            action="RESOURCE_LEASE_REENTRY_EXTENDED",
                            details={"lease_id": lease.id, "resource_uri": canonical_uri},
                        )
                        return self._map_to_response(lease)

                    # Conflicting lease held by another transaction
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Resource conflict: resource '{canonical_uri}' is currently leased under "
                            f"{lease.concurrency_mode} mode by transaction '{lease.holder_transaction_id}' "
                            f"(lease ID: '{lease.id}') until {lease.expires_at.isoformat()}"
                        ),
                    )

            # 5. Calculate strictly monotonically increasing fencing token for this canonical URI
            token_stmt = select(func.coalesce(func.max(ResourceLease.fencing_token), 0)).where(
                ResourceLease.tenant_id == auth.tenant_id,
                ResourceLease.resource_uri == canonical_uri,
            )
            token_res = await s.execute(token_stmt)
            max_token = int(token_res.scalar_one())
            next_fencing_token = max_token + 1

            lease_id = f"lse_{uuid.uuid4().hex[:16]}"
            new_lease = ResourceLease(
                id=lease_id,
                tenant_id=auth.tenant_id,
                resource_uri=canonical_uri,
                holder_agent_id=request.agent_id,
                holder_transaction_id=request.transaction_id,
                holder_handoff_id=request.handoff_id,
                concurrency_mode=request.concurrency_mode.value,
                fencing_token=next_fencing_token,
                status=LeaseStatus.ACQUIRED.value,
                expires_at=now + timedelta(seconds=request.duration_seconds),
                released_at=None,
                created_at=now,
                updated_at=now,
            )
            s.add(new_lease)
            await s.flush()

            await self._emit_audit_event(
                session=s,
                tenant_id=auth.tenant_id,
                action="RESOURCE_LEASE_ACQUIRED",
                details={
                    "lease_id": lease_id,
                    "resource_uri": canonical_uri,
                    "holder_transaction_id": request.transaction_id,
                    "holder_agent_id": request.agent_id,
                    "concurrency_mode": request.concurrency_mode.value,
                    "fencing_token": next_fencing_token,
                    "expires_at": new_lease.expires_at.isoformat(),
                },
            )

            return self._map_to_response(new_lease)

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def release_lease(
        self,
        auth: AuthContext,
        lease_id: str,
        request: ResourceLeaseReleaseRequest,
        session: AsyncSession | None = None,
    ) -> ResourceLeaseResponse:
        """Safely release an acquired lease with strict holder ownership and fencing token verification."""
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> ResourceLeaseResponse:
            lease_stmt = (
                select(ResourceLease)
                .where(
                    ResourceLease.id == lease_id,
                    ResourceLease.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            lease_res = await s.execute(lease_stmt)
            lease = lease_res.scalar_one_or_none()
            if not lease:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Resource lease '{lease_id}' not found in tenant '{auth.tenant_id}'",
                )

            # Ownership and fencing token validation
            if lease.holder_transaction_id != request.transaction_id or lease.holder_agent_id != request.agent_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot release lease: caller is not the authoritative lease holder",
                )

            if lease.fencing_token != request.fencing_token:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot release lease: supplied fencing token {request.fencing_token} "
                        f"does not match lease fencing token {lease.fencing_token}"
                    ),
                )

            if lease.status in {LeaseStatus.RELEASED.value, LeaseStatus.EXPIRED.value}:
                return self._map_to_response(lease)

            lease.status = LeaseStatus.RELEASED.value
            lease.released_at = now
            lease.updated_at = now
            await s.flush()

            await self._emit_audit_event(
                session=s,
                tenant_id=auth.tenant_id,
                action="RESOURCE_LEASE_RELEASED",
                details={
                    "lease_id": lease.id,
                    "resource_uri": lease.resource_uri,
                    "holder_transaction_id": request.transaction_id,
                    "fencing_token": lease.fencing_token,
                },
            )

            return self._map_to_response(lease)

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def renew_lease(
        self,
        auth: AuthContext,
        lease_id: str,
        request: ResourceLeaseRenewRequest,
        session: AsyncSession | None = None,
    ) -> ResourceLeaseResponse:
        """Safely renew an active lease before expiration."""
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> ResourceLeaseResponse:
            lease_stmt = (
                select(ResourceLease)
                .where(
                    ResourceLease.id == lease_id,
                    ResourceLease.tenant_id == auth.tenant_id,
                )
                .with_for_update()
            )
            lease_res = await s.execute(lease_stmt)
            lease = lease_res.scalar_one_or_none()
            if not lease:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Resource lease '{lease_id}' not found in tenant '{auth.tenant_id}'",
                )

            if lease.holder_transaction_id != request.transaction_id or lease.holder_agent_id != request.agent_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Cannot renew lease: caller is not the authoritative lease holder",
                )

            if lease.fencing_token != request.fencing_token:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot renew lease: supplied fencing token does not match active lease token",
                )

            if lease.status != LeaseStatus.ACQUIRED.value or lease.expires_at <= now:
                lease.status = LeaseStatus.EXPIRED.value
                lease.updated_at = now
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot renew expired or inactive lease; re-acquisition with new fencing token is required",
                )

            lease.expires_at = now + timedelta(seconds=request.duration_seconds)
            lease.updated_at = now
            await s.flush()

            await self._emit_audit_event(
                session=s,
                tenant_id=auth.tenant_id,
                action="RESOURCE_LEASE_RENEWED",
                details={
                    "lease_id": lease.id,
                    "resource_uri": lease.resource_uri,
                    "new_expires_at": lease.expires_at.isoformat(),
                    "fencing_token": lease.fencing_token,
                },
            )

            return self._map_to_response(lease)

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def list_leases(
        self,
        auth: AuthContext,
        resource_uri: str | None = None,
        holder_transaction_id: str | None = None,
        status_filter: LeaseStatus | None = None,
        limit: int = 50,
        offset: int = 0,
        session: AsyncSession | None = None,
    ) -> list[ResourceLeaseResponse]:
        """List tenant resource leases with safe filtering and pagination."""

        async def _execute(s: AsyncSession) -> list[ResourceLeaseResponse]:
            stmt = select(ResourceLease).where(ResourceLease.tenant_id == auth.tenant_id)
            if resource_uri:
                stmt = stmt.where(ResourceLease.resource_uri == canonicalize_resource_uri(resource_uri))
            if holder_transaction_id:
                stmt = stmt.where(ResourceLease.holder_transaction_id == holder_transaction_id)
            if status_filter:
                stmt = stmt.where(ResourceLease.status == status_filter.value)

            stmt = stmt.order_by(ResourceLease.created_at.desc()).limit(limit).offset(offset)
            res = await s.execute(stmt)
            leases = res.scalars().all()
            return [self._map_to_response(lease) for lease in leases]

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(auth.tenant_id) as s:
            return await _execute(s)

    async def validate_lease_for_action(
        self,
        tenant_id: str,
        transaction_id: str,
        target_resource: str,
        fencing_token: int | None = None,
        session: AsyncSession | None = None,
    ) -> PolicyDecision:
        """Validate resource conflict and fencing token at Gate 3 action authorization/execution boundaries.

        Returns PolicyDecision:
          - DENY / BLOCK if another transaction holds an active conflicting lease.
          - DENY / BLOCK if the action presents a stale fencing token (a higher token has been issued).
          - ALLOW if no conflicting lease exists or caller holds the active valid lease.
        """
        if not target_resource or not str(target_resource).strip():
            return PolicyDecision(decision=Decision.ALLOW, reason="No target resource specified for concurrency check")

        canonical_uri = canonicalize_resource_uri(target_resource)
        now = datetime.now(UTC)

        async def _execute(s: AsyncSession) -> PolicyDecision:
            # 1. If a fencing token is specified, ensure it has not been superseded by any newer lease
            if fencing_token is not None:
                token_stmt = select(func.coalesce(func.max(ResourceLease.fencing_token), 0)).where(
                    ResourceLease.tenant_id == tenant_id,
                    ResourceLease.resource_uri == canonical_uri,
                )
                token_res = await s.execute(token_stmt)
                max_token = int(token_res.scalar_one())
                if fencing_token < max_token:
                    return PolicyDecision(
                        decision=Decision.BLOCK,
                        reason=(
                            f"Stale fencing token {fencing_token}: superseding lease for resource "
                            f"'{canonical_uri}' has advanced to token {max_token}"
                        ),
                    )

            stmt = select(ResourceLease).where(
                ResourceLease.tenant_id == tenant_id,
                ResourceLease.status == LeaseStatus.ACQUIRED.value,
            )
            res = await s.execute(stmt)
            active_leases = res.scalars().all()

            found_matching_lease = False
            for lease in active_leases:
                if lease.expires_at <= now:
                    continue

                if are_resources_in_conflict(
                    canonical_uri,
                    ConcurrencyMode.EXCLUSIVE,
                    lease.resource_uri,
                    lease.concurrency_mode,
                ):
                    if lease.holder_transaction_id != transaction_id:
                        return PolicyDecision(
                            decision=Decision.BLOCK,
                            reason=(
                                f"Resource conflict: resource '{canonical_uri}' is locked under an active "
                                f"{lease.concurrency_mode} lease by transaction '{lease.holder_transaction_id}'"
                            ),
                        )

                    # Same transaction holds the lease: verify fencing token if supplied
                    if fencing_token is not None:
                        if fencing_token < lease.fencing_token:
                            return PolicyDecision(
                                decision=Decision.BLOCK,
                                reason=(
                                    f"Stale fencing token {fencing_token}: active lease for resource "
                                    f"'{canonical_uri}' has advanced to token {lease.fencing_token}"
                                ),
                            )
                        if lease.fencing_token == fencing_token:
                            found_matching_lease = True

            if fencing_token is not None and not found_matching_lease:
                return PolicyDecision(
                    decision=Decision.BLOCK,
                    reason=(
                        f"Resource lease with fencing token {fencing_token} on '{canonical_uri}' "
                        f"is no longer active or has expired"
                    ),
                )

            return PolicyDecision(decision=Decision.ALLOW, reason="Resource lease verified or unconstrained")

        if session is not None:
            return await _execute(session)
        async with get_tenant_session(tenant_id) as s:
            return await _execute(s)

    def _map_to_response(self, lease: ResourceLease) -> ResourceLeaseResponse:
        return ResourceLeaseResponse(
            id=lease.id,
            tenant_id=lease.tenant_id,
            resource_uri=lease.resource_uri,
            holder_agent_id=lease.holder_agent_id,
            holder_transaction_id=lease.holder_transaction_id,
            holder_handoff_id=lease.holder_handoff_id,
            concurrency_mode=ConcurrencyMode(lease.concurrency_mode),
            fencing_token=lease.fencing_token,
            status=LeaseStatus(lease.status),
            expires_at=lease.expires_at,
            released_at=lease.released_at,
            created_at=lease.created_at,
            updated_at=lease.updated_at,
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
        entry_id = f"aud_lse_{uuid.uuid4().hex}"
        payload_str = f"{prev_hash}:{entry_id}:{action}:{now.isoformat()}:{tenant_id}"
        chain_hash = compute_sha256(payload_str)

        rec = AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=seq,
            session_id=details.get("lease_id", "concurrency"),
            trace_id=f"concurrency-{details.get('lease_id', 'na')}",
            prompt_hash=compute_sha256(f"concurrency:{action}"),
            response_hash=compute_sha256(action),
            hrs_score=0.0,
            risk_tier="RESOURCE_CONCURRENCY",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type=f"CONCURRENCY_{action}",
            actor_identity_id=details.get("holder_agent_id", "system"),
            transaction_id=details.get("holder_transaction_id"),
            decision="ALLOW",
            policy_reference="resource_concurrency_policy",
            reason=f"Concurrency lease {action}",
            event_payload=details,
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
        session.add(rec)
        await session.flush()


concurrency_service = ResourceConcurrencyService()
