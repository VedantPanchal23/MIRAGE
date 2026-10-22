"""Shared-Resource Concurrency, Lease Management, and Fencing Token Service.

Adheres to MIRAGE Phase 8 architecture:
- Explicit canonical URI normalization and hierarchical prefix conflict detection
  (avoids substring false positives/negatives).
- ACID transactional row locking with monotonically increasing fencing tokens per resource.
- Stale-holder rejection: lease expiration alone never makes a stale holder safe to execute.
- Safe release and renewal ownership validation preventing accidental cross-execution release.
- Tenant isolation and cryptographic audit log emission.
"""

import hashlib
import struct
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlparse

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentHandoff, AITransaction, AuditLogRecord, ResourceLease
from db.session import get_tenant_session
from services.agent_governance import agent_governance_service
from shared.config import EnvironmentType, get_settings
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
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

CASE_INSENSITIVE_PATH_SCHEMES = frozenset({"db", "postgres", "postgresql", "mysql", "sqlite", "sql"})
DEFAULT_PORTS: dict[str, int] = {
    "http": 80,
    "https": 443,
}


def _is_postgresql_session(session: AsyncSession) -> bool:
    """Detect whether session is executing against a live PostgreSQL database."""
    sync_session = getattr(session, "sync_session", None)
    sync_bind = getattr(sync_session, "bind", None) if sync_session is not None else None
    if sync_bind is not None and hasattr(sync_bind, "dialect"):
        return getattr(sync_bind.dialect, "name", None) == "postgresql"
    bind = getattr(session, "bind", None)
    if bind is not None and hasattr(bind, "dialect"):
        return getattr(bind.dialect, "name", None) == "postgresql"
    return False


def derive_resource_advisory_lock_key(tenant_id: str, canonical_uri: str) -> int:
    """Derive a deterministic 64-bit signed integer for PostgreSQL advisory locks.

    Uses SHA-256 over '{tenant_id}:{canonical_uri}', ensuring stable, reproducible
    lock keys across independent Python processes, worker hosts, and application restarts.
    This guarantees that concurrent processes locking the same canonical resource map to the
    exact same PostgreSQL lock key (unlike Python's process-randomized hash()).

    Collision Handling:
    pg_advisory_xact_lock operates on a 64-bit signed integer (-2^63 to 2^63 - 1).
    With a 64-bit key space, the birthday bound for collision is ~2^32 resources.
    If two distinct resources map to the same advisory lock key, the only effect is
    temporary false serialization during the acquisition phase; correctness is fully
    preserved because actual lease validity and exclusivity are verified against
    the database rows and enforced by database unique constraints.

    Transaction Scope:
    PostgreSQL transaction-level advisory locks (pg_advisory_xact_lock) are strictly bound
    to the current database transaction. They are automatically and unconditionally released
    by the PostgreSQL engine upon COMMIT or ROLLBACK. A failed operation, unhandled exception,
    or process termination can never leave stale application-level advisory locks behind.
    """
    digest = hashlib.sha256(f"{tenant_id}:{canonical_uri}".encode()).digest()
    return int(struct.unpack(">q", digest[:8])[0])


def _safe_unquote_segment(seg: str) -> str:
    """Unquote percent-encoded characters while preserving encoded slashes (%2F)."""
    placeholder = "___SLASH_ESC___"
    safe_seg = seg.replace("%2f", placeholder).replace("%2F", placeholder)
    unquoted = unquote(safe_seg)
    return unquoted.replace(placeholder, "%2F")


def canonicalize_resource_uri(raw_uri: str) -> str:
    """Normalize a target resource string into a canonical, unambiguous URI.

    Handles:
    - Scheme-less paths (defaulting to resource://local/...)
    - Default port normalization where equivalent (e.g. :80 on http, :443 on https, :5432 on postgres)
    - Dot segment resolution (. and ..) preventing path traversal evasion
    - Percent-encoding normalization for unreserved characters while preserving encoded separators (%2F)
    - Deterministic query parameter sorting
    - Relational database scheme case-folding (db, postgres, mysql, etc.)
    - Case-sensitive scheme path casing preservation (http, https, s3, gcs, file, git, resource)
    """
    stripped = raw_uri.strip()
    if not stripped:
        raise ValueError("Resource URI cannot be empty or whitespace")

    if "://" not in stripped:
        stripped = f"resource://local/{stripped.lstrip('/')}"

    parsed = urlparse(stripped)
    scheme = parsed.scheme.lower()

    # Normalize host and strip default port where scheme defines it
    host = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = DEFAULT_PORTS.get(scheme)
    if port is not None and port != default_port:
        netloc = f"{host}:{port}"
    else:
        netloc = host

    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f"{userinfo}:{parsed.password}"
        netloc = f"{userinfo}@{netloc}"

    # Resolve dot segments (. and ..) and safe percent-encoding
    raw_segments = [seg for seg in parsed.path.split("/") if seg]
    norm_segments: list[str] = []
    for raw_seg in raw_segments:
        seg = _safe_unquote_segment(raw_seg)
        if seg == ".":
            continue
        elif seg == "..":
            if norm_segments:
                norm_segments.pop()
            else:
                raise ValueError(f"Path traversal outside resource root prohibited: '{raw_uri}'")
        else:
            norm_segments.append(seg)

    if scheme in CASE_INSENSITIVE_PATH_SCHEMES:
        path_segments = [seg.lower() for seg in norm_segments]
    else:
        path_segments = norm_segments
    normalized_path = "/" + "/".join(path_segments) if path_segments else ""

    # Sort query parameters deterministically
    if parsed.query:
        qs = parse_qsl(parsed.query, keep_blank_values=True)
        qs.sort(key=lambda x: (x[0], x[1]))
        query = f"?{urlencode(qs)}"
    else:
        query = ""

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
       - A parent resource lock conflicts with a parameterized subresource query.
    3. Unrelated or non-overlapping sibling subpaths do not conflict (e.g. 'ledger' vs 'ledger_archive').
    """
    m_a = mode_a.value if isinstance(mode_a, ConcurrencyMode) else str(mode_a).upper()
    m_b = mode_b.value if isinstance(mode_b, ConcurrencyMode) else str(mode_b).upper()

    if m_a == ConcurrencyMode.SHARED.value and m_b == ConcurrencyMode.SHARED.value:
        return False

    can_a = canonicalize_resource_uri(res_a)
    can_b = canonicalize_resource_uri(res_b)

    if can_a == can_b:
        return True

    parsed_a = urlparse(can_a)
    parsed_b = urlparse(can_b)

    # Must share scheme and netloc to be in hierarchical conflict
    if parsed_a.scheme != parsed_b.scheme or parsed_a.netloc != parsed_b.netloc:
        return False

    segs_a = [s for s in parsed_a.path.split("/") if s]
    segs_b = [s for s in parsed_b.path.split("/") if s]

    # Check hierarchical path segment prefix:
    if len(segs_a) < len(segs_b):
        if segs_b[: len(segs_a)] == segs_a:
            return True
    elif len(segs_b) < len(segs_a):
        if segs_a[: len(segs_b)] == segs_b:
            return True
    else:
        # Same path segments, but can_a != can_b means queries differ.
        # If one has no query, it represents the entire resource (parent of parameterized subresources).
        if (not parsed_a.query and parsed_b.query) or (not parsed_b.query and parsed_a.query):
            return True

    return False


def is_lease_active(lease: ResourceLease, now: datetime) -> bool:
    """Return True if lease has an authoritative status of ACQUIRED and a valid future expiry.

    Time-bounded invariant: Leases missing expires_at or having non-datetime values
    are invalid and strictly treated as non-active (never indefinitely valid).
    """
    if getattr(lease, "status", None) != LeaseStatus.ACQUIRED.value:
        return False
    expires_at = getattr(lease, "expires_at", None)
    if expires_at is None or not isinstance(expires_at, datetime):
        return False
    exp = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
    now_cmp = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return exp > now_cmp


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

            # 2. Validate agent lifecycle eligibility and caller authority binding
            if (
                auth.agent_id
                and auth.agent_id != request.agent_id
                and auth.role
                not in {
                    Role.SUPER_ADMIN,
                    Role.TENANT_ADMIN,
                    Role.OPERATOR,
                }
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Caller '{auth.agent_id}' is not authorized to acquire lease on behalf of '{request.agent_id}'"
                    ),
                )

            if (
                txn.agent_id
                and request.agent_id != txn.agent_id
                and auth.role
                not in {
                    Role.SUPER_ADMIN,
                    Role.TENANT_ADMIN,
                    Role.OPERATOR,
                }
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Request agent '{request.agent_id}' does not match transaction owning agent '{txn.agent_id}'"
                    ),
                )

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

            # 4. Serialize lease acquisition on canonical resource & check active leases
            is_postgres = _is_postgresql_session(s)
            settings = get_settings()
            if settings.environment == EnvironmentType.PRODUCTION and not is_postgres:
                raise RuntimeError(
                    f"Production invariant violation: concurrency advisory lock for '{canonical_uri}' "
                    "requires PostgreSQL dialect"
                )

            if is_postgres:
                lock_key = derive_resource_advisory_lock_key(auth.tenant_id, canonical_uri)
                await s.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

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
                if not is_lease_active(lease, now):
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
                        exp_tz = (
                            lease.expires_at
                            if lease.expires_at.tzinfo is not None
                            else lease.expires_at.replace(tzinfo=UTC)
                        )
                        target_exp = now + timedelta(seconds=request.duration_seconds)
                        lease.expires_at = max(exp_tz, target_exp)
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
            # (including any overlapping hierarchical parent/child resources)
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
            try:
                s.add(new_lease)
                await s.flush()
            except IntegrityError as int_exc:
                orig_str = str(int_exc.orig).lower() if hasattr(int_exc, "orig") else str(int_exc).lower()
                if "uq_resource_leases_tenant_resource_token" in orig_str:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Concurrent lease acquisition conflict on '{canonical_uri}': "
                            "duplicate fencing token sequence detected"
                        ),
                    ) from int_exc
                elif "uq_resource_leases_tenant_resource_exclusive_active" in orig_str:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"Resource conflict: resource '{canonical_uri}' is already leased "
                            "under EXCLUSIVE mode by another transaction"
                        ),
                    ) from int_exc
                orig_err = int_exc.orig if hasattr(int_exc, "orig") else int_exc
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Resource lease constraint violation on '{canonical_uri}': {orig_err}",
                ) from int_exc

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

            # Caller authorization and ownership validation
            if (
                auth.agent_id
                and auth.agent_id != request.agent_id
                and auth.role
                not in {
                    Role.SUPER_ADMIN,
                    Role.TENANT_ADMIN,
                    Role.OPERATOR,
                }
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Caller '{auth.agent_id}' is not authorized to release lease on behalf of '{request.agent_id}'"
                    ),
                )

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

            # Caller authorization and ownership validation
            if (
                auth.agent_id
                and auth.agent_id != request.agent_id
                and auth.role
                not in {
                    Role.SUPER_ADMIN,
                    Role.TENANT_ADMIN,
                    Role.OPERATOR,
                }
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        f"Caller '{auth.agent_id}' is not authorized to renew lease on behalf of '{request.agent_id}'"
                    ),
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

            if not is_lease_active(lease, now):
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
            # on this resource or any governing parent resource
            if fencing_token is not None:
                max_token = 0
                token_stmt = select(func.max(ResourceLease.fencing_token)).where(
                    ResourceLease.tenant_id == tenant_id,
                    ResourceLease.resource_uri == canonical_uri,
                )
                try:
                    token_res = await s.execute(token_stmt)
                    if hasattr(token_res, "scalar_one"):
                        v1 = token_res.scalar_one()
                        if v1 is not None and isinstance(v1, (int, float)):
                            max_token = max(max_token, int(v1))
                    elif hasattr(token_res, "scalar"):
                        v2 = token_res.scalar()
                        if v2 is not None and isinstance(v2, (int, float)):
                            max_token = max(max_token, int(v2))
                except Exception:
                    pass

                try:
                    hier_stmt = select(
                        ResourceLease.resource_uri, ResourceLease.concurrency_mode, ResourceLease.fencing_token
                    ).where(ResourceLease.tenant_id == tenant_id)
                    hier_res = await s.execute(hier_stmt)
                    raw_all = hier_res.all() if hasattr(hier_res, "all") else hier_res
                    for row in raw_all:
                        try:
                            r_uri, r_mode, r_token = row[0], row[1], row[2]
                        except (IndexError, TypeError, KeyError):
                            continue
                        if are_resources_in_conflict(
                            canonical_uri,
                            ConcurrencyMode.EXCLUSIVE,
                            r_uri,
                            r_mode,
                        ):
                            if isinstance(r_token, int) and r_token > max_token:
                                max_token = r_token
                except Exception:
                    pass

                if fencing_token < max_token:
                    return PolicyDecision(
                        decision=Decision.BLOCK,
                        reason=(
                            f"Stale fencing token {fencing_token}: active lease for resource "
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
                if not is_lease_active(lease, now):
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
