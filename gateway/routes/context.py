"""Gate 2 Context Assurance and Phase 7 Governed Memory REST endpoints.

MIRAGE memory is governed state, not unrestricted conversation storage.
Memory may influence future decisions only when its provenance, tenant,
purpose, permissions, freshness, and applicable policy permit that use.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from db import session as db_session
from db.models import GovernedMemory
from gateway.middleware.auth import get_current_auth
from services.context_assurance import (
    assemble_governed_context,
)
from services.governed_memory import (
    create_governed_memory_record,
    delete_governed_memory_record,
    dispute_governed_memory_record,
    enforce_memory_retention_sweep,
    get_governed_memory_record,
    search_governed_memory_records,
    set_governed_memory_legal_hold,
    update_governed_memory_record,
)
from shared.schemas.auth import AuthContext
from shared.schemas.context import (
    GovernedContextRequest,
    GovernedContextResponse,
    MemoryScope,
)
from shared.schemas.memory import (
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
    TrustLevel,
)

router = APIRouter(prefix="/v1", tags=["Context Assurance & Governed Memory"])


@router.post("/context/assemble", response_model=GovernedContextResponse)
async def assemble_context_endpoint(
    request: GovernedContextRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> GovernedContextResponse:
    """Evaluate candidate evidence/memory items and construct the governed model context."""
    return await assemble_governed_context(auth, request)


@router.post("/memory", response_model=GovernedMemoryRecordResponse, status_code=201)
async def create_memory_endpoint(
    request: GovernedMemoryCreateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> GovernedMemoryRecordResponse:
    """Register a new Governed Memory record with classification, purpose binding, and attestation rules."""
    return await create_governed_memory_record(auth, request)


@router.get("/memory", response_model=list[GovernedMemoryRecordResponse])
async def list_memory_endpoint(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    scope: MemoryScope | None = Query(default=None),
    memory_type: str | None = Query(default=None),
    category: MemoryCategory | None = Query(default=None),
    purpose: MemoryPurpose | None = Query(default=None),
    lifecycle_state: MemoryLifecycleState | None = Query(default=None),
    trust_level: TrustLevel | None = Query(default=None),
) -> list[GovernedMemoryRecordResponse]:
    """Retrieve active governed memory items within the authorized tenant scope and filters."""
    async with db_session.get_tenant_session(auth.tenant_id) as session:
        stmt = select(GovernedMemory).where(
            GovernedMemory.tenant_id == auth.tenant_id,
            GovernedMemory.lifecycle_state != MemoryLifecycleState.DELETED.value,
        )
        if scope:
            stmt = stmt.where(GovernedMemory.scope == scope.value)
        if memory_type:
            stmt = stmt.where(GovernedMemory.memory_type == memory_type)
        if category:
            stmt = stmt.where(GovernedMemory.memory_category == category.value)
        if purpose:
            stmt = stmt.where(GovernedMemory.purpose == purpose.value)
        if lifecycle_state:
            stmt = stmt.where(GovernedMemory.lifecycle_state == lifecycle_state.value)
        if trust_level:
            stmt = stmt.where(GovernedMemory.trust_level == trust_level.value)

        records = (await session.execute(stmt)).scalars().all()
        from services.governed_memory import _to_record_response

        return [_to_record_response(r) for r in records]


@router.get("/memory/{memory_id}", response_model=GovernedMemoryRecordResponse)
async def get_memory_endpoint(
    memory_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> GovernedMemoryRecordResponse:
    """Retrieve an individual governed memory record by ID with full provenance lineage."""
    return await get_governed_memory_record(auth, memory_id)


@router.put("/memory/{memory_id}", response_model=GovernedMemoryRecordResponse)
async def update_memory_endpoint(
    memory_id: str,
    request: GovernedMemoryUpdateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> GovernedMemoryRecordResponse:
    """Update memory by versioning: supersedes the current record and stores an incremented version."""
    return await update_governed_memory_record(auth, memory_id, request)


@router.post("/memory/{memory_id}/dispute", response_model=GovernedMemoryRecordResponse)
async def dispute_memory_endpoint(
    memory_id: str,
    request: GovernedMemoryDisputeRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> GovernedMemoryRecordResponse:
    """Formally dispute a memory record, degrading confidence and flagging for review."""
    return await dispute_governed_memory_record(auth, memory_id, request)


@router.post("/memory/{memory_id}/hold", response_model=GovernedMemoryRecordResponse)
async def hold_memory_endpoint(
    memory_id: str,
    request: GovernedMemoryHoldRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> GovernedMemoryRecordResponse:
    """Place or release a legal/regulatory hold protecting memory against deletion and expiry."""
    return await set_governed_memory_legal_hold(auth, memory_id, request)


@router.delete("/memory/{memory_id}", response_model=DeletionPropagationResult, status_code=200)
async def delete_memory_endpoint(
    memory_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> DeletionPropagationResult:
    """Cryptographically shred memory content and propagate deletion across configured stores."""
    return await delete_governed_memory_record(auth, memory_id)


@router.post("/memory/search", response_model=GovernedMemorySearchResponse)
async def search_memory_endpoint(
    request: GovernedMemorySearchRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> GovernedMemorySearchResponse:
    """Purpose-bound semantic and keyword search across governed memory with traceable explanations."""
    return await search_governed_memory_records(auth, request)


@router.post("/memory/maintenance/sweep", response_model=MemoryMaintenanceSweepResponse)
async def sweep_memory_endpoint(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> MemoryMaintenanceSweepResponse:
    """Enforce TTL and retention policies by transitioning expired memories to EXPIRED status."""
    return await enforce_memory_retention_sweep(auth)


@router.get("/memory/{memory_id}/provenance", response_model=dict[str, Any])
async def get_memory_provenance_endpoint(
    memory_id: str,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
) -> dict[str, Any]:
    """Inspect complete provenance chain, derivation history, and audit linkages for a memory record."""
    record = await get_governed_memory_record(auth, memory_id)
    return {
        "memory_id": record.id,
        "tenant_id": record.tenant_id,
        "version": record.version,
        "superseded_by_id": record.superseded_by_id,
        "source_type": record.source_type,
        "source_uri": record.source_uri,
        "source_transaction_id": record.source_transaction_id,
        "source_action_id": record.source_action_id,
        "derivation_chain": record.derivation_chain,
        "content_hash": record.content_hash,
        "attestation_status": record.attestation_status,
        "attested_by": record.attested_by,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }
