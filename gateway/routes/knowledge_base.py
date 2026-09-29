"""Knowledge Base Document Management Endpoints.

Implements Technical Architecture Document §2.10, §8.2, Security & Access §9.1, and ADR 0005:
- POST /v1/kb/upload & /v1/knowledge-base/upload: Asynchronous RabbitMQ Quorum queue ingestion (202 Accepted)
  with synchronous option (201 Created) strictly restricted to non-production environments
- GET /v1/kb/documents & /v1/knowledge-base/documents: Authoritative list of tenant documents from PostgreSQL
- DELETE /v1/kb/documents/{document_id} & /v1/knowledge-base/documents/{document_id}: Purge document chunks
  strictly scoped to tenant_id and document_id in both Qdrant and PostgreSQL
- 10MB payload size enforcement (413 Payload Too Large)
- Content hash deduplication backed by PostgreSQL with RLS (200 OK on duplicate)
- Deterministic document identity derived from tenant_id and filename
"""

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from db.persistence import default_persistence_service
from gateway.middleware.rbac import require_permission
from shared.config import get_settings
from shared.config.settings import EnvironmentType
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import Permission
from workers.celery_app import is_broker_reachable, is_definitive_broker_failure
from workers.rav.ingestion import KnowledgeBaseIngestionService
from workers.tasks import ingest_document_task

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MB per ADR 0005
ALLOWED_EXTENSIONS = (".txt", ".md", ".pdf", ".docx", ".markdown", ".json", ".csv")

router = APIRouter(tags=["Knowledge Base"])
logger = get_logger("kb_routes")
_kb_service = KnowledgeBaseIngestionService()


class UploadDocumentRequest(BaseModel):
    filename: str = Field(..., min_length=1, description="Name of the document")
    content: str = Field(..., min_length=1, description="Text content of the document")
    collection_name: str = Field(default="default_kb", description="Target Qdrant collection")
    sync: bool | None = Field(default=None, description="Force synchronous execution if True (non-prod only)")


async def _handle_upload_document(
    request: UploadDocumentRequest,
    tenant_id: str,
    sync_param: bool | None = None,
) -> tuple[int, dict[str, Any]]:
    # 1. Validation: Content cannot be empty or whitespace only
    if not request.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document content cannot be empty",
        )

    # 2. Validation: Maximum payload size 10MB
    content_bytes = request.content.encode()
    if len(content_bytes) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Document payload size ({len(content_bytes)} bytes) exceeds maximum limit of 10MB",
        )

    # 3. Environment check: Synchronous ingestion is strictly forbidden in production
    settings = get_settings()
    is_production = (
        settings.environment == EnvironmentType.PRODUCTION or str(settings.environment).lower() == "production"
    )

    requested_sync = sync_param if sync_param is not None else request.sync
    if is_production and requested_sync:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Synchronous ingestion is disabled in production. All document uploads must be enqueued asynchronously."
            ),
        )

    is_sync = bool(requested_sync) if not is_production else False

    # 4. Content hashing and deterministic document identity (full SHA-256 digest)
    content_hash = compute_sha256(request.content)
    doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{request.filename}'.encode()).hexdigest()}"

    # 5. Persistent Deduplication via PostgreSQL
    existing_doc = await default_persistence_service.get_kb_document_by_filename(
        tenant_id=tenant_id, filename=request.filename
    )
    if existing_doc is not None and existing_doc.content_hash == content_hash:
        if existing_doc.status == "INDEXED":
            logger.info(
                "Exact duplicate document content detected; returning existing record",
                filename=request.filename,
                tenant_id=tenant_id,
                document_id=existing_doc.document_id,
            )
            return status.HTTP_200_OK, {
                "status": "duplicate",
                "message": "Document already ingested with identical content hash",
                "document_id": existing_doc.document_id,
                "filename": existing_doc.filename,
                "chunks_count": existing_doc.chunks_count,
                "upload_timestamp": existing_doc.created_at.isoformat(),
                "indexed_to_qdrant": True,
            }
        logger.info(
            "Pending document upload detected for identical content; re-enqueuing task with same generation",
            filename=request.filename,
            tenant_id=tenant_id,
            document_id=existing_doc.document_id,
            generation=existing_doc.generation,
        )

    # 6. Synchronous processing path (non-production only)
    if is_sync:
        target_gen = (existing_doc.generation + 1) if existing_doc else 1
        result = await _kb_service.ingest_document(
            filename=request.filename,
            content=request.content,
            tenant_id=tenant_id,
            collection_name=request.collection_name,
            doc_id=doc_id,
            generation=target_gen,
        )
        await default_persistence_service.upsert_kb_document(
            tenant_id=tenant_id,
            document_id=doc_id,
            filename=request.filename,
            content_hash=content_hash,
            chunks_count=result.get("chunks_count", 0),
            collection_name=request.collection_name,
            status="INDEXED",
            generation=target_gen,
        )
        _kb_service.purge_old_generations(
            tenant_id=tenant_id,
            document_id=doc_id,
            keep_generation=target_gen,
            collection_name=request.collection_name,
        )
        return status.HTTP_201_CREATED, result

    # 7. Asynchronous durable ingestion path via RabbitMQ Quorum queue mirage.ingest
    # Check broker reachability BEFORE creating/mutating records
    if not is_broker_reachable():
        logger.error("Celery message broker unreachable for KB ingestion", tenant_id=tenant_id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service degraded: Message broker unavailable for KB ingestion",
            headers={"Retry-After": "30"},
        )

    # Snapshot previous state for compensating rollback if dispatch fails definitively
    prev_status: str | None = existing_doc.status if existing_doc else None
    prev_hash: str | None = existing_doc.content_hash if existing_doc else None
    prev_chunks: int = existing_doc.chunks_count if existing_doc else 0
    prev_gen: int = existing_doc.generation if existing_doc else 0

    # Persist authoritative PENDING row in PostgreSQL BEFORE dispatching to RabbitMQ
    # Guarantees that when the worker consumes from the queue, the authoritative row already exists
    if existing_doc and existing_doc.status == "PENDING" and existing_doc.content_hash == content_hash:
        target_gen = existing_doc.generation
    elif existing_doc:
        target_gen = existing_doc.generation + 1
    else:
        target_gen = 1

    doc_record = await default_persistence_service.upsert_kb_document(
        tenant_id=tenant_id,
        document_id=doc_id,
        filename=request.filename,
        content_hash=content_hash,
        chunks_count=existing_doc.chunks_count if existing_doc else 0,
        collection_name=request.collection_name,
        status="PENDING",
        generation=target_gen,
    )
    assigned_generation = doc_record.generation

    # Dispatch to Celery worker with the assigned generation
    try:
        task = ingest_document_task.apply_async(
            kwargs={
                "filename": request.filename,
                "content": request.content,
                "tenant_id": tenant_id,
                "collection_name": request.collection_name,
                "doc_id": doc_id,
                "generation": assigned_generation,
            },
            queue="mirage.ingest",
            routing_key="ingest.task",
            retry=False,
        )
        task_id = task.id
    except Exception as exc:
        if is_definitive_broker_failure(exc):
            logger.error(
                "Celery broker dispatch definitively failed (pre-transmission); "
                "executing compensating rollback in PostgreSQL",
                error=str(exc),
                document_id=doc_id,
            )
            if prev_status is not None and prev_hash is not None:
                # Revert existing document to its previous valid known-good indexed state
                await default_persistence_service.upsert_kb_document(
                    tenant_id=tenant_id,
                    document_id=doc_id,
                    filename=request.filename,
                    content_hash=prev_hash,
                    chunks_count=prev_chunks,
                    collection_name=request.collection_name,
                    status=prev_status,
                    generation=prev_gen,
                )
            else:
                # New document failed dispatch: clean up pending record so no orphaned state remains
                await default_persistence_service.delete_kb_document(tenant_id=tenant_id, document_id=doc_id)

            detail_msg = "Service degraded: Failed to enqueue document ingestion task (broker unreachable)"
        else:
            # Ambiguous publish outcome (e.g. publisher confirm timeout or connection drop during wait):
            # The message may have already reached RabbitMQ Quorum queue.
            # CRITICAL DISTRIBUTED INVARIANT: Must NEVER delete or revert the PostgreSQL PENDING record!
            # The worker task may already be enqueued and will execute against this authoritative record.
            logger.warning(
                "Ambiguous RabbitMQ publisher confirmation outcome; "
                "preserving PENDING PostgreSQL record for worker reconciliation",
                error=str(exc),
                document_id=doc_id,
                generation=assigned_generation,
            )
            detail_msg = "Service degraded: Message broker dispatch unconfirmed. Ingestion task may be pending."

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail_msg,
            headers={"Retry-After": "30"},
        ) from exc

    async_response = {
        "status": "enqueued",
        "task_id": task_id,
        "document_id": doc_id,
        "filename": request.filename,
        "tenant_id": tenant_id,
        "collection_name": request.collection_name,
        "generation": assigned_generation,
        "message": "Document upload enqueued to Quorum queue 'mirage.ingest' for background indexing.",
    }
    return status.HTTP_202_ACCEPTED, async_response


@router.post("/v1/kb/upload")
@router.post("/v1/knowledge-base/upload")
async def upload_document(
    request: UploadDocumentRequest,
    tenant_id: Annotated[str, Depends(require_permission(Permission.KB_WRITE))],
    sync: bool | None = Query(None, description="Force synchronous execution if true (non-prod only)"),
) -> Any:
    """Upload and index a document via JSON payload (Async Quorum Queue default)."""
    status_code, response_data = await _handle_upload_document(
        request=request,
        tenant_id=tenant_id,
        sync_param=sync,
    )
    return JSONResponse(status_code=status_code, content=response_data)


@router.post("/v1/kb/upload/file")
@router.post("/v1/knowledge-base/upload/file")
async def upload_document_file(
    file: UploadFile = File(...),
    collection_name: str = Form(default="default_kb"),
    tenant_id: str = Depends(require_permission(Permission.KB_WRITE)),
    sync: bool | None = Query(None, description="Force synchronous processing if true (non-prod only)"),
) -> Any:
    """Upload and index a document file (TXT, MD, PDF, DOCX) via multipart form."""
    filename = file.filename or "uploaded_file.txt"

    # Check file extension
    if not filename.lower().endswith(ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed formats: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    if len(content_bytes) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Uploaded file size ({len(content_bytes)} bytes) exceeds maximum limit of 10MB",
        )

    # Decode or extract content text
    content_text = _kb_service.extract_text_from_bytes(content_bytes, filename)
    req_obj = UploadDocumentRequest(
        filename=filename,
        content=content_text,
        collection_name=collection_name,
    )
    status_code, response_data = await _handle_upload_document(
        request=req_obj,
        tenant_id=tenant_id,
        sync_param=sync,
    )
    return JSONResponse(status_code=status_code, content=response_data)


@router.get("/v1/kb/documents")
@router.get("/v1/knowledge-base/documents")
async def list_documents(
    tenant_id: str = Depends(require_permission(Permission.KB_READ)),
) -> dict[str, Any]:
    # Reconcile any stale PENDING documents on inspection
    try:
        await default_persistence_service.reconcile_stale_pending_kb_documents(
            tenant_id=tenant_id,
            qdrant_client=_kb_service.client,
        )
    except Exception as exc:
        logger.warning("Could not reconcile stale pending documents on listing", error=str(exc))

    docs = await default_persistence_service.list_kb_documents(tenant_id=tenant_id)
    formatted_docs = [
        {
            "document_id": d.document_id,
            "filename": d.filename,
            "chunks_count": d.chunks_count,
            "upload_timestamp": d.created_at.isoformat(),
            "indexed_to_qdrant": d.status == "INDEXED",
            "status": d.status,
            "generation": d.generation,
        }
        for d in docs
    ]
    return {"tenant_id": tenant_id, "total_documents": len(formatted_docs), "documents": formatted_docs}


@router.delete("/v1/kb/documents/{document_id}")
@router.delete("/v1/knowledge-base/documents/{document_id}")
async def delete_document(
    document_id: str,
    tenant_id: str = Depends(require_permission(Permission.KB_WRITE)),
) -> dict[str, Any]:
    """Purge a document and all its chunks scoped strictly to tenant_id from vector store and PostgreSQL."""
    existing = await default_persistence_service.get_kb_document_by_id(tenant_id=tenant_id, document_id=document_id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found for tenant",
        )

    # Purge vectors from Qdrant strictly scoped to tenant_id and document_id
    _kb_service.delete_document(
        tenant_id=tenant_id,
        document_id=document_id,
        collection_name=existing.collection_name,
    )

    # Purge metadata from PostgreSQL
    await default_persistence_service.delete_kb_document(tenant_id=tenant_id, document_id=document_id)

    return {"status": "deleted", "document_id": document_id, "tenant_id": tenant_id}
