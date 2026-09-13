"""Knowledge Base Document Management Endpoints.

Implements Technical Architecture Document §2.10 & §8.2:
- POST /v1/knowledge-base/upload: Ingest text or documents, chunk with 512/64 recursive splitter, index to Qdrant
- GET /v1/knowledge-base/documents: List all documents uploaded by tenant
- DELETE /v1/knowledge-base/documents/{document_id}: Purge document chunks from Qdrant
"""

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from gateway.middleware.auth import get_current_tenant
from shared.logging import get_logger
from workers.rav.ingestion import KnowledgeBaseIngestionService

router = APIRouter(prefix="/v1/knowledge-base", tags=["Knowledge Base"])
logger = get_logger("kb_routes")

_kb_service = KnowledgeBaseIngestionService()


class UploadDocumentRequest(BaseModel):
    filename: str = Field(..., description="Name of the document")
    content: str = Field(..., description="Text content of the document")
    collection_name: str = Field(default="default_kb", description="Target Qdrant collection")


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: UploadDocumentRequest,
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    """Upload and index a document via JSON payload."""
    if not request.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document content cannot be empty",
        )

    result = await _kb_service.ingest_document(
        filename=request.filename,
        content=request.content,
        tenant_id=tenant_id,
        collection_name=request.collection_name,
    )
    return result


@router.post("/upload/file", status_code=status.HTTP_201_CREATED)
async def upload_document_file(
    file: UploadFile = File(...),
    collection_name: str = Form(default="default_kb"),
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    """Upload and index a file (TXT, MD, PDF, DOCX) via multipart form."""
    filename = file.filename or "uploaded_file.txt"
    content_bytes = await file.read()

    if not content_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    result = await _kb_service.ingest_document(
        filename=filename,
        content=content_bytes,
        tenant_id=tenant_id,
        collection_name=collection_name,
    )
    return result


@router.get("/documents")
async def list_documents(
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    """List all ingested knowledge base documents for the calling tenant."""
    docs = _kb_service.list_documents(tenant_id=tenant_id)
    return {"tenant_id": tenant_id, "total_documents": len(docs), "documents": docs}


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    tenant_id: str = Depends(get_current_tenant),
) -> dict[str, Any]:
    """Purge a document and all its chunks from the tenant's vector collection."""
    deleted = _kb_service.delete_document(tenant_id=tenant_id, document_id=document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found for tenant",
        )
    return {"status": "deleted", "document_id": document_id, "tenant_id": tenant_id}
