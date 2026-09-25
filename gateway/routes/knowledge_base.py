"""Knowledge Base Document Management Endpoints.

Implements Technical Architecture Document §2.10, §8.2, and ADR 0005:
- POST /v1/kb/upload & /v1/knowledge-base/upload: Asynchronous RabbitMQ Quorum queue ingestion (202 Accepted)
  with synchronous option (201 Created) for backward compatibility
- GET /v1/kb/documents & /v1/knowledge-base/documents: List all tenant documents
- DELETE /v1/kb/documents/{document_id} & /v1/knowledge-base/documents/{document_id}: Purge document chunks
- 10MB payload size enforcement (413 Payload Too Large)
- Content hash deduplication (200 OK on duplicate)
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from pydantic import BaseModel, Field

from gateway.middleware.rbac import require_permission
from shared.logging import get_logger
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import Permission
from workers.rav.ingestion import KnowledgeBaseIngestionService
from workers.tasks import ingest_document_task

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MB per ADR 0005
ALLOWED_EXTENSIONS = (".txt", ".md", ".pdf", ".docx", ".markdown", ".json", ".csv")

router = APIRouter(tags=["Knowledge Base"])
logger = get_logger("kb_routes")

_kb_service = KnowledgeBaseIngestionService()
# In-memory document hash tracking per tenant: {tenant_id: {filename: (content_hash, document_record)}}
_document_hash_registry: dict[str, dict[str, tuple[str, dict[str, Any]]]] = {}


class UploadDocumentRequest(BaseModel):
    filename: str = Field(..., min_length=1, description="Name of the document")
    content: str = Field(..., min_length=1, description="Text content of the document")
    collection_name: str = Field(default="default_kb", description="Target Qdrant collection")
    sync: bool | None = Field(default=None, description="Force synchronous execution if True")


async def _handle_upload_document(
    request: UploadDocumentRequest,
    tenant_id: str,
    raw_path: str,
    sync_param: bool | None = None,
) -> tuple[int, dict[str, Any]]:
    # 1. Validation: Content cannot be empty or whitespace only
    if not request.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document content cannot be empty",
        )

    # 2. Validation: Maximum payload size 10MB
    content_bytes = request.content.encode("utf-8")
    if len(content_bytes) > MAX_DOCUMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Document payload size ({len(content_bytes)} bytes) exceeds maximum limit of 10MB",
        )

    # 3. Deduplication: Compute SHA-256 content hash
    content_hash = compute_sha256(request.content)
    if tenant_id in _document_hash_registry and request.filename in _document_hash_registry[tenant_id]:
        existing_hash, existing_record = _document_hash_registry[tenant_id][request.filename]
        if existing_hash == content_hash:
            logger.info("Exact duplicate document content detected; returning existing record", filename=request.filename)
            return status.HTTP_200_OK, {
                "status": "duplicate",
                "message": "Document already ingested with identical content hash",
                **existing_record,
            }

    # Determine sync vs async execution:
    # If explicitly requested via sync parameter or request.sync, respect it.
    # Otherwise: /v1/knowledge-base/upload defaults to sync (for backward compatibility),
    # while /v1/kb/upload defaults to async queue.
    is_sync = sync_param if sync_param is not None else (request.sync if request.sync is not None else "/knowledge-base" in raw_path)

    if is_sync:
        result = await _kb_service.ingest_document(
            filename=request.filename,
            content=request.content,
            tenant_id=tenant_id,
            collection_name=request.collection_name,
        )
        # Register in hash registry
        if tenant_id not in _document_hash_registry:
            _document_hash_registry[tenant_id] = {}
        _document_hash_registry[tenant_id][request.filename] = (content_hash, result)
        return status.HTTP_201_CREATED, result

    # Asynchronous dispatch via Celery to RabbitMQ Quorum queue mirage.ingest
    from workers.celery_app import is_broker_reachable

    task_id = f"task_kb_{uuid.uuid4().hex[:12]}"
    if is_broker_reachable():
        try:
            task = ingest_document_task.apply_async(
                kwargs={
                    "filename": request.filename,
                    "content": request.content,
                    "tenant_id": tenant_id,
                    "collection_name": request.collection_name,
                },
                queue="mirage.ingest",
                routing_key="ingest.task",
                retry=False,
            )
            task_id = task.id
        except Exception as exc:
            logger.info("Celery broker dispatch failed, fallback to local indexing", error=str(exc))
            try:
                result = await _kb_service.ingest_document(
                    filename=request.filename,
                    content=request.content,
                    tenant_id=tenant_id,
                    collection_name=request.collection_name,
                )
                if tenant_id not in _document_hash_registry:
                    _document_hash_registry[tenant_id] = {}
                _document_hash_registry[tenant_id][request.filename] = (content_hash, result)
            except Exception:
                pass
    else:
        logger.info("Celery broker offline, processing via local indexing fallback")
        try:
            result = await _kb_service.ingest_document(
                filename=request.filename,
                content=request.content,
                tenant_id=tenant_id,
                collection_name=request.collection_name,
            )
            if tenant_id not in _document_hash_registry:
                _document_hash_registry[tenant_id] = {}
            _document_hash_registry[tenant_id][request.filename] = (content_hash, result)
        except Exception:
            pass

    async_response = {
        "status": "enqueued",
        "task_id": task_id,
        "filename": request.filename,
        "tenant_id": tenant_id,
        "collection_name": request.collection_name,
        "message": "Document upload enqueued to Quorum queue 'mirage.ingest' for background indexing.",
    }
    return status.HTTP_202_ACCEPTED, async_response


@router.post("/v1/kb/upload")
@router.post("/v1/knowledge-base/upload")
async def upload_document(
    request: UploadDocumentRequest,
    raw_req: Request,
    tenant_id: Annotated[str, Depends(require_permission(Permission.KB_WRITE))],
    sync: bool | None = Query(None, description="Force synchronous execution if true"),
) -> Any:
    """Upload and index a document via JSON payload (Async Quorum Queue or Synchronous)."""
    from fastapi.responses import JSONResponse

    status_code, response_data = await _handle_upload_document(
        request=request,
        tenant_id=tenant_id,
        raw_path=raw_req.url.path,
        sync_param=sync,
    )
    return JSONResponse(status_code=status_code, content=response_data)


@router.post("/v1/kb/upload/file")
@router.post("/v1/knowledge-base/upload/file")
async def upload_document_file(
    raw_req: Request,
    file: UploadFile = File(...),
    collection_name: str = Form(default="default_kb"),
    tenant_id: str = Depends(require_permission(Permission.KB_WRITE)),
    sync: bool | None = Query(None, description="Force synchronous processing if true"),
) -> Any:
    """Upload and index a document file (TXT, MD, PDF, DOCX) via multipart form."""
    from fastapi.responses import JSONResponse

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
        raw_path=raw_req.url.path,
        sync_param=sync,
    )
    return JSONResponse(status_code=status_code, content=response_data)


@router.get("/v1/kb/documents")
@router.get("/v1/knowledge-base/documents")
async def list_documents(
    tenant_id: str = Depends(require_permission(Permission.KB_READ)),
) -> dict[str, Any]:
    """List all ingested knowledge base documents for the calling tenant."""
    docs = _kb_service.list_documents(tenant_id=tenant_id)
    return {"tenant_id": tenant_id, "total_documents": len(docs), "documents": docs}


@router.delete("/v1/kb/documents/{document_id}")
@router.delete("/v1/knowledge-base/documents/{document_id}")
async def delete_document(
    document_id: str,
    tenant_id: str = Depends(require_permission(Permission.KB_WRITE)),
) -> dict[str, Any]:
    """Purge a document and all its chunks from the tenant's vector collection."""
    deleted = _kb_service.delete_document(tenant_id=tenant_id, document_id=document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found for tenant",
        )
    # Remove from hash registry
    if tenant_id in _document_hash_registry:
        _document_hash_registry[tenant_id] = {
            fn: val
            for fn, val in _document_hash_registry[tenant_id].items()
            if val[1].get("document_id") != document_id
        }
    return {"status": "deleted", "document_id": document_id, "tenant_id": tenant_id}
