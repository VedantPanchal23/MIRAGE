"""Phase 7 Governed Memory Service — Classification, Lifecycle, Purpose Isolation, and Retention.

MIRAGE memory is governed state, not unrestricted conversation storage.
Memory may influence future decisions only when its provenance, tenant,
purpose, permissions, freshness, and applicable policy permit that use.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select

from db import session as db_session
from db.models import AuditLogRecord, GovernedMemory
from shared.config import get_settings
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import Taint
from shared.schemas.memory import (
    AttestationStatus,
    DeletionPropagationResult,
    GovernedMemoryCreateRequest,
    GovernedMemoryDisputeRequest,
    GovernedMemoryHoldRequest,
    GovernedMemoryRecordResponse,
    GovernedMemorySearchRequest,
    GovernedMemorySearchResponse,
    GovernedMemoryUpdateRequest,
    MemoryCategory,
    MemoryLifecycleState,
    MemoryMaintenanceSweepResponse,
    MemoryPurpose,
    MemoryScope,
    MemorySearchResultItem,
    PropagationStatus,
    RetentionPolicy,
    TrustLevel,
    compute_memory_integrity_hash,
)

logger = get_logger("governed_memory_service")

# Regex detectors for secret leakage and indirect prompt injection
_SECRET_PATTERNS = (
    re.compile(
        r"\b(?:api[_-]?key|password|secret|private[_-]?key)\b\s*[:=]\s*['\"]?[A-Za-z0-9\-_./~+]{8,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
)
_PII_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
)
_INJECTION_PATTERNS = (
    re.compile(r"\b(ignore|disregard)\b.{0,40}\b(previous|prior|system|above|instructions)\b", re.IGNORECASE),
    re.compile(r"\b(system prompt|developer message|jailbreak|DAN mode|developer mode)\b", re.IGNORECASE),
    re.compile(r"\b(leak your prompt|leak instructions|repeat everything above|reveal instructions)\b", re.IGNORECASE),
    re.compile(r"!\[.*?\]\(https?://[^\s\)]+\?[^\s\)]*\)", re.IGNORECASE),
    re.compile(r"(?:^|\n)(?:System|User|Assistant|Human)\s*:\s*", re.IGNORECASE),
    re.compile(r"<\|im_start\|>(?:system|user|assistant)", re.IGNORECASE),
    re.compile(r"\[/?INST\]", re.IGNORECASE),
)


def verify_pipeline_attestation(
    auth: AuthContext,
    content: str,
    governance_metadata: dict[str, Any],
    pipeline_signature: str | None = None,
) -> tuple[bool, str]:
    """Verify cryptographic authenticity of a trusted pipeline attestation.

    Enforces the pipeline verification boundary (docs/Memory.md §4.4).
    A caller-supplied `attestation_status == PIPELINE_SIGNED`, identity claim,
    or arbitrary signature string is NEVER trusted on its own.

    In the current MIRAGE release, external pipeline PKI / cryptographic
    signing notary infrastructure is unconfigured at this ingestion boundary.
    The boundary fails closed: unverified or forged pipeline claims are rejected.
    """
    _ = (auth, content, governance_metadata)
    if not pipeline_signature:
        return False, "Missing cryptographic pipeline signature for claimed pipeline attestation"

    # Verifiable pipeline-signature PKI infrastructure is unconfigured at this boundary.
    # Fail closed: reject caller-supplied credentials rather than accepting unverified signatures.
    return (
        False,
        "Cryptographic pipeline signature verification is unconfigured and unavailable at this boundary. "
        "Pipeline-attested creation fails closed.",
    )


class MultiStorePropagator:
    """Manages synchronization of memory records to secondary vector, cache, and document backends."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def propagate_upsert(self, memory: GovernedMemory) -> tuple[PropagationStatus, dict[str, Any]]:
        """Index memory in vector store (Qdrant) and cache (Redis) if configured."""
        details: dict[str, Any] = {"postgres": "synced"}
        overall = PropagationStatus.PROPAGATED

        # Optional Qdrant Vector indexing
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models as qmodels

            # Determine whether Qdrant is reachable
            q_client = QdrantClient(
                host=self.settings.qdrant_host,
                port=self.settings.qdrant_port,
                api_key=self.settings.qdrant_api_key,
                https=self.settings.qdrant_https,
                timeout=2.0,
            )
            collection_name = f"memories_{memory.tenant_id}"
            try:
                collections = q_client.get_collections().collections
                exists = any(c.name == collection_name for c in collections)
                if not exists:
                    q_client.create_collection(
                        collection_name=collection_name,
                        vectors_config=qmodels.VectorParams(size=384, distance=qmodels.Distance.COSINE),
                    )
                # Compute mock/deterministic embedding or insert payload point
                # Use uuid5 for point ID to guarantee Qdrant UUID compatibility
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, memory.id))
                vector = [0.01 * (i % 50) for i in range(384)]
                q_client.upsert(
                    collection_name=collection_name,
                    points=[
                        qmodels.PointStruct(
                            id=point_id,
                            vector=vector,
                            payload={
                                "memory_id": memory.id,
                                "tenant_id": memory.tenant_id,
                                "category": memory.memory_category,
                                "purpose": memory.purpose,
                                "content": memory.content[:1000],
                            },
                        )
                    ],
                )
                details["qdrant"] = "indexed"
            except Exception as q_exc:
                details["qdrant"] = f"skipped_or_unavailable: {str(q_exc)[:100]}"
        except Exception:
            details["qdrant"] = "library_not_used"

        return overall, details

    async def propagate_delete(self, memory: GovernedMemory) -> DeletionPropagationResult:
        """Propagate physical shredding across secondary storage engines."""
        errors: dict[str, str] = {}
        postgres_shredded = True
        qdrant_purged: bool | None = None
        redis_invalidated: bool | None = None
        mongo_purged: bool | None = None

        # 1. Qdrant Deletion
        if self.settings.qdrant_host:
            try:
                from qdrant_client import QdrantClient

                q_client = QdrantClient(
                    host=self.settings.qdrant_host,
                    port=self.settings.qdrant_port,
                    api_key=self.settings.qdrant_api_key,
                    https=self.settings.qdrant_https,
                    timeout=2.0,
                )
                collection_name = f"memories_{memory.tenant_id}"
                try:
                    point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, memory.id))
                    q_client.delete(collection_name=collection_name, points_selector=[point_id])
                    qdrant_purged = True
                except Exception as exc:
                    errors["qdrant"] = str(exc)[:200]
                    qdrant_purged = False
            except Exception as exc:
                errors["qdrant"] = f"qdrant_client_init_error: {str(exc)[:150]}"
                qdrant_purged = False
        else:
            qdrant_purged = None

        # 2. Redis Cache Eviction
        if self.settings.redis_url:
            try:
                import redis.asyncio as aioredis

                r = aioredis.from_url(self.settings.redis_url, socket_timeout=1.0)
                cache_key = f"mirage:memory:{memory.tenant_id}:{memory.id}"
                await r.delete(cache_key)
                await r.aclose()
                redis_invalidated = True
            except Exception as exc:
                errors["redis"] = str(exc)[:200]
                redis_invalidated = False
        else:
            redis_invalidated = None

        confirmed_evictions: list[str] = []
        if qdrant_purged is True:
            confirmed_evictions.append("Qdrant vector index purged")
        if redis_invalidated is True:
            confirmed_evictions.append("Redis cache invalidated")

        if errors:
            overall_status = PropagationStatus.PARTIAL_FAILURE
            error_keys = ", ".join(errors.keys())
            message = (
                f"Memory {memory.id} logically sanitized and tombstoned in primary store with "
                f"partial secondary-store eviction failures: {error_keys}"
            )
        elif confirmed_evictions:
            overall_status = PropagationStatus.PROPAGATED
            evicted_str = ", ".join(confirmed_evictions)
            message = (
                f"Memory {memory.id} logically sanitized and tombstoned; "
                f"external copies confirmed evicted ({evicted_str})"
            )
        else:
            overall_status = PropagationStatus.PROPAGATED
            message = (
                f"Memory {memory.id} logically sanitized and tombstoned in primary store "
                "(no external secondary stores configured)"
            )

        return DeletionPropagationResult(
            memory_id=memory.id,
            tenant_id=memory.tenant_id,
            postgres_shredded=postgres_shredded,
            qdrant_purged=qdrant_purged,
            redis_invalidated=redis_invalidated,
            mongo_purged=mongo_purged,
            overall_status=overall_status,
            error_details=errors,
            message=message,
        )


_propagator = MultiStorePropagator()


async def _append_audit(
    session: Any,
    tenant_id: str,
    actor_id: str,
    target_id: str,
    event_type: str,
    decision: str,
    reason: str,
    payload: dict[str, Any],
) -> None:
    """Append memory governance decision to tamper-evident cryptographic audit log."""
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

    # Redact any sensitive content in audit payload
    clean_payload = dict(payload)
    if "content" in clean_payload:
        clean_payload["content_hash"] = compute_sha256(str(clean_payload.pop("content")))

    session.add(
        AuditLogRecord(
            entry_id=entry_id,
            tenant_id=tenant_id,
            sequence_number=seq,
            session_id=target_id,
            trace_id="governed-memory",
            prompt_hash=compute_sha256(""),
            response_hash=compute_sha256(""),
            hrs_score=0.0,
            risk_tier="MEMORY_GOVERNANCE",
            claims_count=0,
            claims_summary=[],
            correction_applied=False,
            event_type=event_type,
            actor_identity_id=actor_id,
            transaction_id=target_id,
            decision=decision,
            reason=reason,
            event_payload=clean_payload,
            prev_hash=prev_hash,
            chain_hash=chain_hash,
            created_at=now,
        )
    )


def _to_record_response(r: GovernedMemory) -> GovernedMemoryRecordResponse:
    """Transform SQLAlchemy model to typed GovernedMemoryRecordResponse."""
    return GovernedMemoryRecordResponse(
        id=r.id,
        tenant_id=r.tenant_id,
        owner_id=r.owner_id,
        memory_type=r.memory_type,
        memory_category=MemoryCategory(r.memory_category)
        if r.memory_category in MemoryCategory._value2member_map_
        else MemoryCategory.USER_FACT,
        purpose=MemoryPurpose(r.purpose)
        if r.purpose in MemoryPurpose._value2member_map_
        else MemoryPurpose.GENERAL,
        lifecycle_state=MemoryLifecycleState(r.lifecycle_state)
        if r.lifecycle_state in MemoryLifecycleState._value2member_map_
        else MemoryLifecycleState.ACTIVE,
        trust_level=TrustLevel(r.trust_level)
        if r.trust_level in TrustLevel._value2member_map_
        else TrustLevel.PROVISIONAL,
        scope=MemoryScope(r.scope)
        if r.scope in MemoryScope._value2member_map_
        else MemoryScope.ORGANIZATIONAL,
        content=r.content,
        content_hash=r.content_hash,
        version=r.version,
        superseded_by_id=r.superseded_by_id,
        attestation_status=AttestationStatus(r.attestation_status)
        if r.attestation_status in AttestationStatus._value2member_map_
        else AttestationStatus.NONE,
        attested_by=r.attested_by,
        taint=Taint(r.taint) if r.taint in Taint._value2member_map_ else Taint.INTERNAL,
        confidence=r.confidence,
        retention_policy=RetentionPolicy(r.retention_policy)
        if r.retention_policy in RetentionPolicy._value2member_map_
        else RetentionPolicy.STANDARD,
        retention_exception_reason=r.retention_exception_reason,
        ttl_seconds=r.ttl_seconds,
        expires_at=r.expires_at,
        source_type=r.source_type,
        source_uri=r.source_uri,
        source_transaction_id=r.source_transaction_id,
        source_action_id=r.source_action_id,
        derivation_chain=r.derivation_chain or [],
        propagation_status=PropagationStatus(r.propagation_status)
        if r.propagation_status in PropagationStatus._value2member_map_
        else PropagationStatus.PROPAGATED,
        propagation_details=r.propagation_details or {},
        dispute_reason=r.dispute_reason,
        idempotency_key=r.idempotency_key,
        metadata_payload=r.metadata_payload or {},
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


# =============================================================================
# CORE GOVERNED MEMORY SERVICE METHODS
# =============================================================================


async def create_governed_memory_record(
    auth: AuthContext,
    request: GovernedMemoryCreateRequest,
) -> GovernedMemoryRecordResponse:
    """Create a new governed memory record enforcing epistemic separation, DLP, and tenant isolation."""
    if not auth.identity_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A resolved identity is required")

    # 1. Epistemic Separation & Attestation Authority Check
    # (docs/Memory.md §4.4: Models and autonomous agents can NEVER self-attest).
    is_human_authority = auth.role in {Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR}

    # Pipeline Attestation Boundary:
    # A caller-supplied attestation_status == PIPELINE_SIGNED or signature field is NEVER
    # trusted as self-proof. It must be cryptographically authenticated at the boundary.
    claims_pipeline = (
        request.attestation_status == AttestationStatus.PIPELINE_SIGNED
        or getattr(request, "pipeline_signature", None) is not None
    )
    if claims_pipeline:
        is_valid_pipeline, pipeline_err = verify_pipeline_attestation(
            auth=auth,
            content=request.content,
            governance_metadata={
                "tenant_id": auth.tenant_id,
                "category": request.memory_category.value,
                "purpose": request.purpose.value,
                "scope": request.scope.value,
            },
            pipeline_signature=getattr(request, "pipeline_signature", None),
        )
        if not is_valid_pipeline:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Pipeline attestation rejected: {pipeline_err}. "
                    "Autonomous agents and unprivileged callers cannot self-attest memory "
                    "or forge pipeline credentials."
                ),
            )

    # Principal scope check: unprivileged callers cannot specify a different owner_id for USER/AGENT scopes
    valid_callers = {c for c in (auth.user_id, auth.identity_id) if c}
    if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR}:
        if request.scope in {MemoryScope.USER, MemoryScope.AGENT} and request.owner_id not in valid_callers:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Cannot create {request.scope.value}-scoped memory for another principal: "
                    "owner_id must match authenticated caller"
                ),
            )

    # 2. Epistemic Invariant: Model-generated extractions or untrusted retrieved text can NEVER be ATTESTED or VERIFIED
    req_trust = getattr(request, "trust_level", None)
    is_verified_trust = req_trust in {TrustLevel.VERIFIED, "VERIFIED"}
    if request.memory_category in {
        MemoryCategory.GENERATED_SUMMARY,
        MemoryCategory.INFERRED_PREFERENCE,
        MemoryCategory.UNTRUSTED_RETRIEVED,
    } and (request.memory_type == "ATTESTED" or is_verified_trust):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Model-generated or untrusted category '{request.memory_category.value}' "
                "cannot be created as ATTESTED memory."
            ),
        )

    if request.memory_type == "ATTESTED":
        if not is_human_authority:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Autonomous agents cannot self-attest memory. Only authorized human operators "
                    "or signed ingestion pipelines may create ATTESTED memory."
                ),
            )
        attestation = AttestationStatus.HUMAN_VERIFIED
        attested_by = auth.user_id or auth.identity_id
        initial_trust = TrustLevel.VERIFIED
        initial_confidence = 0.95
    else:
        if is_verified_trust and not is_human_authority:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Autonomous agents and unprivileged callers cannot assign VERIFIED trust level.",
            )
        attestation = AttestationStatus.NONE
        attested_by = None
        initial_trust = TrustLevel.PROVISIONAL
        initial_confidence = 0.50

    if request.memory_category in {
        MemoryCategory.GENERATED_SUMMARY,
        MemoryCategory.INFERRED_PREFERENCE,
        MemoryCategory.UNTRUSTED_RETRIEVED,
    }:
        initial_trust = TrustLevel.PROVISIONAL
        initial_confidence = min(initial_confidence, 0.50)

    # 3. Sensitive Data / Secret Scanner (DLP Minimization)
    if any(p.search(request.content) for p in _SECRET_PATTERNS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Sensitive secrets or credential tokens detected in memory content. "
                "Write rejected under DLP policy."
            ),
        )

    # 4. Indirect Prompt Injection Scanner
    has_injection = any(p.search(request.content) for p in _INJECTION_PATTERNS)
    taint_value = request.declared_taint.value
    memory_type = request.memory_type
    if has_injection:
        initial_trust = TrustLevel.UNTRUSTED
        initial_confidence = 0.05
        taint_value = Taint.UNTRUSTED.value
        memory_type = "ADVISORY"
        attestation = AttestationStatus.NONE
        attested_by = None

    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=request.ttl_seconds) if request.ttl_seconds else None
    version = 1
    content_hash = compute_memory_integrity_hash(
        tenant_id=auth.tenant_id,
        content=request.content,
        version=version,
        category=request.memory_category.value,
        purpose=request.purpose.value,
    )
    record_id = f"mem_{uuid.uuid4().hex}"

    # Serialize derivation steps
    derivation_list = [step.model_dump(mode="json") for step in request.derivation_chain]
    derivation_list.append(
        {
            "step_type": "CREATION",
            "agent_id": auth.identity_id,
            "description": f"Created {request.memory_category.value} memory for purpose {request.purpose.value}",
            "timestamp": now.isoformat(),
        }
    )

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        # Check idempotency if key provided
        if request.idempotency_key:
            existing = await session.execute(
                select(GovernedMemory).where(
                    GovernedMemory.tenant_id == auth.tenant_id,
                    GovernedMemory.idempotency_key == request.idempotency_key,
                )
            )
            existing_row = existing.scalars().first()
            if existing_row:
                return _to_record_response(existing_row)

        record = GovernedMemory(
            id=record_id,
            tenant_id=auth.tenant_id,
            owner_id=request.owner_id,
            memory_type=memory_type,
            memory_category=request.memory_category.value,
            purpose=request.purpose.value,
            lifecycle_state=MemoryLifecycleState.ACTIVE.value,
            trust_level=initial_trust.value,
            scope=request.scope.value,
            content=request.content,
            content_hash=content_hash,
            version=version,
            superseded_by_id=None,
            attestation_status=attestation.value,
            attested_by=attested_by,
            taint=taint_value,
            confidence=initial_confidence,
            retention_policy=request.retention_policy.value,
            retention_exception_reason=request.retention_exception_reason,
            ttl_seconds=request.ttl_seconds,
            expires_at=expires_at,
            source_type=request.source_type,
            source_uri=request.source_uri,
            source_transaction_id=request.source_transaction_id,
            source_action_id=request.source_action_id,
            derivation_chain=derivation_list,
            propagation_status=PropagationStatus.PROPAGATED.value,
            propagation_details={"postgres": "synced"},
            dispute_reason=None,
            idempotency_key=request.idempotency_key,
            metadata_payload=request.metadata_payload,
            created_at=now,
            updated_at=now,
        )
        session.add(record)

        await _append_audit(
            session=session,
            tenant_id=auth.tenant_id,
            actor_id=auth.identity_id,
            target_id=record_id,
            event_type="governed_memory_created",
            decision="MEMORY_CREATED",
            reason=(
                f"Created {request.memory_category.value} memory (version {version})"
                if not has_injection
                else (
                    f"Created {request.memory_category.value} memory (version {version}) "
                    "[quarantined: prompt injection detected]"
                )
            ),
            payload={
                "memory_category": request.memory_category.value,
                "purpose": request.purpose.value,
                "memory_type": memory_type,
                "attestation_status": attestation.value,
                "trust_level": initial_trust.value,
                "retention_policy": request.retention_policy.value,
                "content": request.content,
            },
        )
        await session.flush()

        # Multi-store propagation
        prop_status, prop_details = await _propagator.propagate_upsert(record)
        record.propagation_status = prop_status.value
        record.propagation_details = prop_details
        await session.flush()

        return _to_record_response(record)


async def get_governed_memory_record(auth: AuthContext, memory_id: str) -> GovernedMemoryRecordResponse:
    """Retrieve an individual governed memory record enforcing tenant and scope isolation."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        record = await session.get(GovernedMemory, memory_id)
        if not record or record.tenant_id != auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found")

        # Scope-based authorization check
        _enforce_scope_read_access(auth, record)

        return _to_record_response(record)


async def update_governed_memory_record(
    auth: AuthContext,
    memory_id: str,
    request: GovernedMemoryUpdateRequest,
) -> GovernedMemoryRecordResponse:
    """Update memory by versioning: supersedes current record and creates an incremented version."""
    if not auth.identity_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A resolved identity is required")

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        record = await session.get(GovernedMemory, memory_id, with_for_update=True)
        if not record or record.tenant_id != auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found")

        # 1. Scope and State Invariant Checks
        _enforce_scope_write_access(auth, record)

        if record.lifecycle_state == MemoryLifecycleState.DELETED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot update a deleted memory record")
        if record.lifecycle_state == MemoryLifecycleState.SUPERSEDED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot update superseded record (superseded by {record.superseded_by_id})",
            )
        if record.lifecycle_state == MemoryLifecycleState.EXPIRED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot update an expired memory record")
        if record.trust_level == TrustLevel.REVOKED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot update a memory record with REVOKED trust",
            )
        if record.retention_policy == RetentionPolicy.LEGAL_HOLD.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Memory record is under active LEGAL_HOLD and cannot be mutated",
            )

        # 2. Optimistic Concurrency Control
        if request.expected_version is not None and record.version != request.expected_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Version mismatch: current is {record.version}, expected {request.expected_version}",
            )

        # 3. DLP Secret Scan on updated content
        if any(p.search(request.content) for p in _SECRET_PATTERNS):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Sensitive secrets or credential tokens detected in memory content. "
                    "Update rejected under DLP policy."
                ),
            )

        # 4. Indirect Prompt Injection & Trust Escalation Prevention
        has_injection = any(p.search(request.content) for p in _INJECTION_PATTERNS)
        is_human_authority = auth.role in {Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR}

        if has_injection:
            target_trust = TrustLevel.UNTRUSTED.value
            target_memory_type = "ADVISORY"
            target_attestation = AttestationStatus.NONE.value
            target_attested_by = None
            target_confidence = 0.05
            target_taint = Taint.UNTRUSTED.value
        elif not is_human_authority:
            # Autonomous agent modifying memory cannot inherit or retain VERIFIED trust or ATTESTED memory_type
            target_trust = TrustLevel.PROVISIONAL.value
            target_memory_type = "ADVISORY"
            target_attestation = AttestationStatus.NONE.value
            target_attested_by = None
            target_confidence = min(record.confidence, 0.50)
            target_taint = request.declared_taint.value if request.declared_taint else record.taint
        else:
            target_trust = record.trust_level
            target_memory_type = record.memory_type
            target_attestation = record.attestation_status
            target_attested_by = record.attested_by
            target_confidence = record.confidence
            target_taint = request.declared_taint.value if request.declared_taint else record.taint

        now = datetime.now(UTC)
        new_version = record.version + 1
        new_record_id = f"mem_{uuid.uuid4().hex}"
        target_purpose = request.purpose.value if request.purpose else record.purpose
        target_retention = request.retention_policy.value if request.retention_policy else record.retention_policy
        ttl = request.ttl_seconds if request.ttl_seconds is not None else record.ttl_seconds
        expires_at = now + timedelta(seconds=ttl) if ttl else None

        new_content_hash = compute_memory_integrity_hash(
            tenant_id=auth.tenant_id,
            content=request.content,
            version=new_version,
            category=record.memory_category,
            purpose=target_purpose,
        )

        # Build derivation chain
        derivation = list(record.derivation_chain or [])
        derivation.append(
            {
                "step_type": "VERSION_UPDATE",
                "agent_id": auth.identity_id,
                "previous_id": record.id,
                "previous_version": record.version,
                "new_version": new_version,
                "reason": request.update_reason,
                "timestamp": now.isoformat(),
            }
        )

        new_record = GovernedMemory(
            id=new_record_id,
            tenant_id=auth.tenant_id,
            owner_id=record.owner_id,
            memory_type=target_memory_type,
            memory_category=record.memory_category,
            purpose=target_purpose,
            lifecycle_state=MemoryLifecycleState.ACTIVE.value,
            trust_level=target_trust,
            scope=record.scope,
            content=request.content,
            content_hash=new_content_hash,
            version=new_version,
            superseded_by_id=None,
            attestation_status=target_attestation,
            attested_by=target_attested_by,
            taint=target_taint,
            confidence=target_confidence,
            retention_policy=target_retention,
            retention_exception_reason=None,
            ttl_seconds=ttl,
            expires_at=expires_at,
            source_type=record.source_type,
            source_uri=record.source_uri,
            source_transaction_id=record.source_transaction_id,
            source_action_id=record.source_action_id,
            derivation_chain=derivation,
            propagation_status=PropagationStatus.PROPAGATED.value,
            propagation_details={"postgres": "synced"},
            dispute_reason=None,
            idempotency_key=None,
            metadata_payload=record.metadata_payload,
            created_at=now,
            updated_at=now,
        )
        session.add(new_record)

        # Mark previous record as SUPERSEDED
        record.lifecycle_state = MemoryLifecycleState.SUPERSEDED.value
        record.superseded_by_id = new_record_id
        record.updated_at = now

        await _append_audit(
            session=session,
            tenant_id=auth.tenant_id,
            actor_id=auth.identity_id,
            target_id=new_record_id,
            event_type="governed_memory_version_created",
            decision="MEMORY_VERSION_CREATED",
            reason=f"Superseded {record.id} (v{record.version}) with {new_record_id} (v{new_version})",
            payload={
                "previous_id": record.id,
                "previous_version": record.version,
                "new_version": new_version,
                "update_reason": request.update_reason,
            },
        )
        await session.flush()

        # Propagate secondary stores
        prop_status, prop_details = await _propagator.propagate_upsert(new_record)
        new_record.propagation_status = prop_status.value
        new_record.propagation_details = prop_details
        await session.flush()

        return _to_record_response(new_record)


async def dispute_governed_memory_record(
    auth: AuthContext,
    memory_id: str,
    request: GovernedMemoryDisputeRequest,
) -> GovernedMemoryRecordResponse:
    """Formally dispute a stored memory record, demoting trust and logging justification."""
    if not auth.identity_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A resolved identity is required")

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        record = await session.get(GovernedMemory, memory_id, with_for_update=True)
        if not record or record.tenant_id != auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found")

        if record.lifecycle_state == MemoryLifecycleState.DELETED.value:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cannot dispute a deleted memory record")

        now = datetime.now(UTC)
        record.lifecycle_state = MemoryLifecycleState.DISPUTED.value
        record.trust_level = TrustLevel.DISPUTED.value
        record.confidence = min(record.confidence, 0.40)
        record.dispute_reason = request.dispute_reason
        record.updated_at = now

        derivation = list(record.derivation_chain or [])
        derivation.append(
            {
                "step_type": "DISPUTED",
                "reported_by": request.reported_by or auth.identity_id,
                "reason": request.dispute_reason,
                "timestamp": now.isoformat(),
            }
        )
        record.derivation_chain = derivation

        await _append_audit(
            session=session,
            tenant_id=auth.tenant_id,
            actor_id=auth.identity_id,
            target_id=record.id,
            event_type="governed_memory_disputed",
            decision="MEMORY_DISPUTED",
            reason=f"Memory disputed: {request.dispute_reason}",
            payload={"dispute_reason": request.dispute_reason, "confidence": record.confidence},
        )
        await session.flush()
        return _to_record_response(record)


async def set_governed_memory_legal_hold(
    auth: AuthContext,
    memory_id: str,
    request: GovernedMemoryHoldRequest,
) -> GovernedMemoryRecordResponse:
    """Apply or release a legal/regulatory hold on a memory record."""
    if not auth.identity_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A resolved identity is required")

    # Authorize role: Placing a hold requires TENANT_ADMIN or SUPER_ADMIN (or OPERATOR for placing).
    # Releasing a legal hold strictly requires TENANT_ADMIN or SUPER_ADMIN (OPERATOR lacks legal authority).
    if request.hold_active:
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators or operators can place legal holds on memory records",
            )
    else:
        if auth.role not in {Role.SUPER_ADMIN, Role.TENANT_ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only tenant administrators or super administrators have legal authority to release legal holds",
            )

    justification = (request.justification or "").strip()
    if not justification:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A non-empty justification is required for legal hold operations",
        )

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        record = await session.get(GovernedMemory, memory_id, with_for_update=True)
        if not record or record.tenant_id != auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found")

        if record.lifecycle_state == MemoryLifecycleState.DELETED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot place or modify legal hold on a deleted memory record",
            )

        now = datetime.now(UTC)
        if request.hold_active:
            record.retention_policy = RetentionPolicy.LEGAL_HOLD.value
            record.retention_exception_reason = justification
            decision = "MEMORY_LEGAL_HOLD_APPLIED"
        else:
            record.retention_policy = RetentionPolicy.STANDARD.value
            record.retention_exception_reason = None
            decision = "MEMORY_LEGAL_HOLD_RELEASED"
            # If TTL expired while under legal hold, transition to EXPIRED on release
            if record.expires_at and record.expires_at <= now:
                record.lifecycle_state = MemoryLifecycleState.EXPIRED.value

        record.updated_at = now
        await _append_audit(
            session=session,
            tenant_id=auth.tenant_id,
            actor_id=auth.identity_id or "operator",
            target_id=record.id,
            event_type="governed_memory_hold_changed",
            decision=decision,
            reason=request.justification,
            payload={"hold_active": request.hold_active, "justification": request.justification},
        )
        await session.flush()
        return _to_record_response(record)


async def delete_governed_memory_record(
    auth: AuthContext,
    memory_id: str,
) -> DeletionPropagationResult:
    """Logically sanitize and tombstone memory content in PostgreSQL and propagate eviction across secondary stores."""
    if not auth.identity_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A resolved identity is required")

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        record = await session.get(GovernedMemory, memory_id, with_for_update=True)
        if not record or record.tenant_id != auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found")

        _enforce_scope_write_access(auth, record)

        # Legal Hold Immunity check
        if record.retention_policy == RetentionPolicy.LEGAL_HOLD.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Deletion prohibited: memory record is under active LEGAL_HOLD",
            )

        now = datetime.now(UTC)
        prev_hash = record.content_hash
        is_already_deleted = record.lifecycle_state == MemoryLifecycleState.DELETED.value

        # Logically sanitize and tombstone raw payload
        record.lifecycle_state = MemoryLifecycleState.DELETED.value
        record.content = "[LOGICALLY SANITIZED / TOMBSTONED]"
        record.content_hash = compute_sha256(f"{auth.tenant_id}:TOMBSTONED:{record.id}:{now.isoformat()}")
        record.updated_at = now

        # Append to audit chain
        await _append_audit(
            session=session,
            tenant_id=auth.tenant_id,
            actor_id=auth.identity_id,
            target_id=record.id,
            event_type="governed_memory_tombstoned" if not is_already_deleted else "governed_memory_retry_tombstoned",
            decision="MEMORY_DELETED",
            reason=(
                "Logically sanitized and tombstoned by authorized caller"
                if not is_already_deleted
                else "Re-propagated eviction retry"
            ),
            payload={"deleted_id": record.id, "previous_hash": prev_hash, "scope": record.scope},
        )
        await session.flush()

        # Multi-store deletion propagation
        prop_res = await _propagator.propagate_delete(record)
        record.propagation_status = prop_res.overall_status.value
        qdrant_stat = (
            "purged" if prop_res.qdrant_purged
            else ("failed" if prop_res.qdrant_purged is False else "unconfigured")
        )
        redis_stat = (
            "invalidated" if prop_res.redis_invalidated
            else ("failed" if prop_res.redis_invalidated is False else "unconfigured")
        )
        record.propagation_details = {
            "postgres": "tombstoned",
            "qdrant": qdrant_stat,
            "redis": redis_stat,
            "errors": prop_res.error_details,
        }
        await session.flush()

        return prop_res


async def search_governed_memory_records(
    auth: AuthContext,
    request: GovernedMemorySearchRequest,
) -> GovernedMemorySearchResponse:
    """Purpose-bound, authorized memory retrieval with freshness scoring and traceable explanations."""
    now = datetime.now(UTC)
    results: list[MemorySearchResultItem] = []
    exclusion_reasons: dict[str, int] = {}
    total_evaluated = 0

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        # Base query locked to current tenant
        stmt = select(GovernedMemory).where(GovernedMemory.tenant_id == auth.tenant_id)

        # Purpose filtering: return items specifically matching requested purpose or GENERAL
        if request.purpose != MemoryPurpose.GENERAL:
            stmt = stmt.where(or_(GovernedMemory.purpose == request.purpose.value, GovernedMemory.purpose == "GENERAL"))

        if request.category:
            stmt = stmt.where(GovernedMemory.memory_category == request.category.value)
        if request.scope:
            stmt = stmt.where(GovernedMemory.scope == request.scope.value)

        candidates = (await session.execute(stmt)).scalars().all()
        total_evaluated = len(candidates)

        for mem in candidates:
            # 1. Lifecycle State Exclusion
            if mem.lifecycle_state == MemoryLifecycleState.DELETED.value:
                exclusion_reasons["deleted_state"] = exclusion_reasons.get("deleted_state", 0) + 1
                continue
            if mem.lifecycle_state == MemoryLifecycleState.SUPERSEDED.value and not request.include_superseded:
                exclusion_reasons["superseded_state"] = exclusion_reasons.get("superseded_state", 0) + 1
                continue
            if mem.lifecycle_state == MemoryLifecycleState.EXPIRED.value:
                exclusion_reasons["expired_state"] = exclusion_reasons.get("expired_state", 0) + 1
                continue

            # 2. TTL Expiry Check
            if mem.expires_at and mem.expires_at <= now and mem.retention_policy != RetentionPolicy.LEGAL_HOLD.value:
                exclusion_reasons["ttl_expired"] = exclusion_reasons.get("ttl_expired", 0) + 1
                continue

            # 3. Scope Access Authorization Check
            try:
                _enforce_scope_read_access(auth, mem)
            except HTTPException:
                exclusion_reasons["scope_unauthorized"] = exclusion_reasons.get("scope_unauthorized", 0) + 1
                continue

            # 4. Trust Level Filter
            if request.min_trust_level:
                trust_order = [TrustLevel.UNTRUSTED, TrustLevel.DISPUTED, TrustLevel.PROVISIONAL, TrustLevel.VERIFIED]
                item_trust = (
                    TrustLevel(mem.trust_level)
                    if mem.trust_level in TrustLevel._value2member_map_
                    else TrustLevel.PROVISIONAL
                )
                if trust_order.index(item_trust) < trust_order.index(request.min_trust_level):
                    exclusion_reasons["insufficient_trust"] = exclusion_reasons.get("insufficient_trust", 0) + 1
                    continue

            # 5. Query matching and relevance
            relevance = 1.0
            indicators: list[str] = []
            if request.query:
                query_words = set(request.query.lower().split())
                content_words = set(mem.content.lower().split())
                matched = query_words.intersection(content_words)
                if not matched:
                    exclusion_reasons["query_unmatched"] = exclusion_reasons.get("query_unmatched", 0) + 1
                    continue
                relevance = round(len(matched) / max(1, len(query_words)), 3)
                indicators.append(f"matched_{len(matched)}_terms")

            # 6. Freshness decay calculation
            age_days = (now - mem.created_at).total_seconds() / 86400.0
            freshness_factor = max(0.60, 1.0 - min(0.40, (age_days / 180.0) * 0.20))
            effective_trust = round(mem.confidence * freshness_factor, 3)

            if effective_trust < request.min_confidence:
                exclusion_reasons["confidence_too_low"] = exclusion_reasons.get("confidence_too_low", 0) + 1
                continue

            inclusion_reason = (
                f"Matched purpose '{mem.purpose}', trust '{mem.trust_level}', effective trust {effective_trust:.2f}"
            )

            results.append(
                MemorySearchResultItem(
                    id=mem.id,
                    content=mem.content,
                    memory_category=MemoryCategory(mem.memory_category)
                    if mem.memory_category in MemoryCategory._value2member_map_
                    else MemoryCategory.USER_FACT,
                    purpose=MemoryPurpose(mem.purpose)
                    if mem.purpose in MemoryPurpose._value2member_map_
                    else MemoryPurpose.GENERAL,
                    trust_level=TrustLevel(mem.trust_level)
                    if mem.trust_level in TrustLevel._value2member_map_
                    else TrustLevel.PROVISIONAL,
                    lifecycle_state=MemoryLifecycleState(mem.lifecycle_state)
                    if mem.lifecycle_state in MemoryLifecycleState._value2member_map_
                    else MemoryLifecycleState.ACTIVE,
                    confidence=mem.confidence,
                    relevance_score=relevance,
                    effective_trust_score=effective_trust,
                    is_attested=mem.memory_type == "ATTESTED",
                    taint=Taint(mem.taint) if mem.taint in Taint._value2member_map_ else Taint.INTERNAL,
                    provenance_uri=mem.source_uri,
                    inclusion_reason=inclusion_reason,
                    match_indicators=indicators,
                )
            )

        # Sort by effective trust and relevance
        results.sort(key=lambda r: (r.effective_trust_score, r.relevance_score), reverse=True)
        trimmed = results[: request.limit]

        return GovernedMemorySearchResponse(
            tenant_id=auth.tenant_id,
            purpose=request.purpose,
            results=trimmed,
            total_evaluated=total_evaluated,
            excluded_count=total_evaluated - len(trimmed),
            exclusion_reasons=exclusion_reasons,
        )


async def enforce_memory_retention_sweep(auth: AuthContext) -> MemoryMaintenanceSweepResponse:
    """Enforce TTL and retention schedules: transitions expired memories to EXPIRED status."""
    now = datetime.now(UTC)
    expired_count = 0
    legal_holds = 0

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        # Find active records past their expiration timestamp
        stmt = select(GovernedMemory).where(
            GovernedMemory.tenant_id == auth.tenant_id,
            GovernedMemory.lifecycle_state == MemoryLifecycleState.ACTIVE.value,
        )
        records = (await session.execute(stmt)).scalars().all()

        for mem in records:
            if mem.retention_policy == RetentionPolicy.LEGAL_HOLD.value:
                legal_holds += 1
                continue
            if mem.expires_at and mem.expires_at <= now:
                mem.lifecycle_state = MemoryLifecycleState.EXPIRED.value
                mem.updated_at = now
                expired_count += 1

        if expired_count > 0:
            await _append_audit(
                session=session,
                tenant_id=auth.tenant_id,
                actor_id=auth.identity_id or "system",
                target_id="sweep",
                event_type="governed_memory_retention_sweep",
                decision="MEMORY_EXPIRY_SWEEP",
                reason=f"Retention sweep transitioned {expired_count} records to EXPIRED",
                payload={"expired_count": expired_count, "legal_holds": legal_holds},
            )
            await session.flush()

        active_count = len(records) - expired_count
        return MemoryMaintenanceSweepResponse(
            tenant_id=auth.tenant_id,
            expired_count=expired_count,
            unexpired_active_count=active_count,
            legal_holds_protected=legal_holds,
            timestamp=now,
        )


# =============================================================================
# SCOPE AUTHORIZATION HELPERS
# =============================================================================


def _enforce_scope_read_access(auth: AuthContext, record: GovernedMemory) -> None:
    """Enforce principal and scope authorization for read access."""
    if auth.role in {Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR}:
        return
    valid_callers = {c for c in (auth.user_id, auth.identity_id) if c}
    if record.scope in {MemoryScope.USER.value, MemoryScope.AGENT.value} and record.owner_id not in valid_callers:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Cross-principal access denied for {record.scope}-scoped memory",
        )


def _enforce_scope_write_access(auth: AuthContext, record: GovernedMemory) -> None:
    """Enforce principal and scope authorization for mutating access."""
    if auth.role in {Role.SUPER_ADMIN, Role.TENANT_ADMIN, Role.OPERATOR}:
        return
    valid_callers = {c for c in (auth.user_id, auth.identity_id) if c}
    if record.scope in {MemoryScope.USER.value, MemoryScope.AGENT.value} and record.owner_id not in valid_callers:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Unauthorized: only owner or administrator may mutate {record.scope}-scoped memory",
        )
