"""Gate 2 Context Assurance and Governed Memory REST endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from db import session as db_session
from db.models import GovernedMemory
from gateway.middleware.auth import get_current_auth
from services.context_assurance import (
    _append_audit,
    assemble_governed_context,
    create_governed_memory,
    list_governed_memories,
)
from shared.schemas.auth import AuthContext
from shared.schemas.context import (
    GovernedContextRequest,
    GovernedContextResponse,
    MemoryCreateRequest,
    MemoryResponse,
    MemoryScope,
)

router = APIRouter(prefix="/v1", tags=["Context Assurance & Memory"])


@router.post("/context/assemble", response_model=GovernedContextResponse)
async def assemble_context_endpoint(
    request: GovernedContextRequest, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> GovernedContextResponse:
    """Evaluate candidate evidence/memory items and construct the governed model context."""
    return await assemble_governed_context(auth, request)


@router.post("/memory", response_model=MemoryResponse, status_code=201)
async def create_memory_endpoint(
    request: MemoryCreateRequest, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> MemoryResponse:
    """Register a new Governed Memory entry with cryptographic attestation rules."""
    return await create_governed_memory(auth, request)


@router.get("/memory", response_model=list[MemoryResponse])
async def list_memory_endpoint(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    scope: MemoryScope | None = Query(default=None),
    memory_type: str | None = Query(default=None),
) -> list[MemoryResponse]:
    """Retrieve active governed memory items within the authorized tenant scope."""
    return await list_governed_memories(auth, scope=scope, memory_type=memory_type)


@router.delete("/memory/{memory_id}", status_code=200)
async def delete_memory_endpoint(
    memory_id: str, auth: Annotated[AuthContext, Depends(get_current_auth)]
) -> dict[str, str]:
    """Cryptographically delete a memory item and record audit provenance."""
    if auth.identity_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A resolved identity is required")

    async with db_session.get_tenant_session(auth.tenant_id) as session:
        record = await session.get(GovernedMemory, memory_id)
        if record is None or record.tenant_id != auth.tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found")

        await session.delete(record)
        await _append_audit(
            session,
            auth.tenant_id,
            auth.identity_id,
            memory_id,
            "MEMORY_DELETED",
            f"Memory {memory_id} shredded by operator",
            {"deleted_id": memory_id, "scope": record.scope},
        )
        await session.flush()
        return {"status": "success", "message": f"Memory {memory_id} successfully shredded"}
