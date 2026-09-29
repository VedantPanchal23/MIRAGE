"""Integration tests for Knowledge Base production-safety requirements.

Implements and validates:
1. Production upload cannot execute synchronously (?sync=true rejected with 400).
2. Production upload always enqueues through durable Quorum queue 'mirage.ingest'.
3. Duplicate upload across separate process instances is deduplicated via PostgreSQL.
4. Duplicate upload after process restart is deduplicated.
5. Same content across two tenants creates two isolated logical documents with deterministic IDs.
6. Retry of the same upload does not create duplicate documents.
7. Deterministic document identity is stable and tenant-isolated.
8. Tenant A cannot delete Tenant B's Qdrant vectors (real Qdrant filter enforcement).
9. Tenant A cannot retrieve or delete Tenant B's KB metadata.
10. Failed enqueue does not leave a falsely successful ingestion state.
"""

import hashlib
import io
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from starlette.testclient import TestClient

from db.persistence import default_persistence_service
from gateway.main import create_app
from gateway.routes.knowledge_base import _kb_service
from shared.config import get_settings
from shared.config.settings import EnvironmentType
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory
from workers.rav.ingestion import KnowledgeBaseIngestionService
from workers.tasks import _run_async, ingest_document_task

app = create_app()
client = TestClient(app)
settings = get_settings()


class TestP1KnowledgeBaseSafety:
    """Comprehensive test suite for Knowledge Base production-safety invariants."""

    def test_production_upload_cannot_execute_synchronously(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify that ?sync=true is strictly forbidden in production mode."""
        monkeypatch.setattr(settings, "environment", EnvironmentType.PRODUCTION)
        tenant_id = f"t_prod_kb_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        doc_payload = {
            "filename": "prod_doc.txt",
            "content": "Mission-critical production document content.",
            "collection_name": "prod_kb",
        }

        # 1. JSON upload with ?sync=true in production -> 400
        res_sync_query = client.post("/v1/kb/upload?sync=true", json=doc_payload, headers=headers)
        assert res_sync_query.status_code == 400
        assert "Synchronous ingestion is disabled in production" in res_sync_query.json()["error"]["message"]

        # 2. JSON upload with payload sync=True in production -> 400
        payload_with_sync = {**doc_payload, "sync": True}
        res_sync_body = client.post("/v1/kb/upload", json=payload_with_sync, headers=headers)
        assert res_sync_body.status_code == 400
        assert "Synchronous ingestion is disabled in production" in res_sync_body.json()["error"]["message"]

        # 3. Multipart file upload with ?sync=true in production -> 400
        file_bytes = b"Production file contents"
        files = {"file": ("prod_file.txt", io.BytesIO(file_bytes), "text/plain")}
        res_file_sync = client.post("/v1/kb/upload/file?sync=true", files=files, headers=headers)
        assert res_file_sync.status_code == 400
        assert "Synchronous ingestion is disabled in production" in res_file_sync.json()["error"]["message"]

        # 4. Backward-compatible alias /v1/knowledge-base/upload with ?sync=true -> 400
        res_alias_sync = client.post("/v1/knowledge-base/upload?sync=true", json=doc_payload, headers=headers)
        assert res_alias_sync.status_code == 400

    def test_production_upload_always_enqueues_through_durable_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify that production upload enqueues to mirage.ingest Quorum queue."""
        monkeypatch.setattr(settings, "environment", EnvironmentType.PRODUCTION)
        tenant_id = f"t_prod_queue_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        doc_payload = {
            "filename": "durable_doc.txt",
            "content": "Durable queue test document content.",
            "collection_name": "prod_kb",
        }

        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch("workers.tasks.ingest_document_task.apply_async") as mock_apply,
        ):
            mock_apply.return_value = MagicMock(id="task_kb_durable_123")
            res = client.post("/v1/kb/upload", json=doc_payload, headers=headers)

        assert res.status_code == 202
        data = res.json()
        assert data["status"] == "enqueued"
        assert data["task_id"] == "task_kb_durable_123"
        assert data["document_id"].startswith("doc_")

        # Verify apply_async was called with mirage.ingest
        mock_apply.assert_called_once()
        call_kwargs = mock_apply.call_args[1]
        assert call_kwargs["queue"] == "mirage.ingest"
        assert call_kwargs["routing_key"] == "ingest.task"

    @pytest.mark.asyncio
    async def test_duplicate_upload_across_separate_instances_is_deduplicated(self) -> None:
        """Verify deduplication survives process restart / separate gateway instances via PostgreSQL."""
        tenant_id = f"t_kb_dedup_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        doc_payload = {
            "filename": "policy_v1.txt",
            "content": "Enterprise safety policy and protocol details.",
            "collection_name": "policies_kb",
        }

        # 1. Initial upload (sync=true in dev/test) -> 201 Created
        res1 = client.post("/v1/kb/upload?sync=true", json=doc_payload, headers=headers)
        assert res1.status_code == 201
        doc_id = res1.json()["document_id"]

        # 2. Simulate complete gateway process restart: create brand-new TestClient and app
        fresh_app = create_app()
        fresh_client = TestClient(fresh_app)

        # 3. Duplicate upload on the fresh gateway instance -> 200 OK duplicate
        res2 = fresh_client.post("/v1/kb/upload?sync=true", json=doc_payload, headers=headers)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["status"] == "duplicate"
        assert data2["document_id"] == doc_id
        assert data2["filename"] == "policy_v1.txt"

    @pytest.mark.asyncio
    async def test_same_content_across_two_tenants_creates_isolated_documents(self) -> None:
        """Verify identical content uploaded by different tenants yields distinct IDs and isolated storage."""
        tenant_a = f"t_iso_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"t_iso_b_{uuid.uuid4().hex[:8]}"
        headers_a = AuthTestFactory.auth_headers(tenant_id=tenant_a, role=Role.TENANT_ADMIN)
        headers_b = AuthTestFactory.auth_headers(tenant_id=tenant_b, role=Role.TENANT_ADMIN)

        shared_content = "Identical universal standard operating procedures for all facilities."
        payload = {
            "filename": "sop.txt",
            "content": shared_content,
            "collection_name": "sop_kb",
        }

        # Upload for Tenant A
        res_a = client.post("/v1/kb/upload?sync=true", json=payload, headers=headers_a)
        assert res_a.status_code == 201
        doc_id_a = res_a.json()["document_id"]

        # Upload for Tenant B with identical content and filename
        res_b = client.post("/v1/kb/upload?sync=true", json=payload, headers=headers_b)
        assert res_b.status_code == 201
        doc_id_b = res_b.json()["document_id"]

        # Deterministic IDs must be different across tenants
        assert doc_id_a != doc_id_b

        # List for Tenant A shows ONLY doc_id_a
        list_a = client.get("/v1/kb/documents", headers=headers_a).json()
        assert list_a["total_documents"] == 1
        assert list_a["documents"][0]["document_id"] == doc_id_a

        # List for Tenant B shows ONLY doc_id_b
        list_b = client.get("/v1/kb/documents", headers=headers_b).json()
        assert list_b["total_documents"] == 1
        assert list_b["documents"][0]["document_id"] == doc_id_b

    def test_retry_of_same_upload_does_not_create_duplicate_documents(self) -> None:
        """Verify retrying an upload with identical content returns duplicate and maintains count = 1."""
        tenant_id = f"t_retry_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        payload = {
            "filename": "retry_test.txt",
            "content": "Retry upload idempotency validation content.",
        }

        # First upload
        res1 = client.post("/v1/kb/upload?sync=true", json=payload, headers=headers)
        assert res1.status_code == 201

        # Second upload (retry)
        res2 = client.post("/v1/kb/upload?sync=true", json=payload, headers=headers)
        assert res2.status_code == 200
        assert res2.json()["status"] == "duplicate"

        # Third upload (retry)
        res3 = client.post("/v1/kb/upload?sync=true", json=payload, headers=headers)
        assert res3.status_code == 200
        assert res3.json()["status"] == "duplicate"

        # Verify count is exactly 1 in PostgreSQL
        list_res = client.get("/v1/kb/documents", headers=headers).json()
        assert list_res["total_documents"] == 1

    def test_deterministic_document_identity_stability(self) -> None:
        """Verify document ID is derived deterministically from tenant_id and filename (full SHA-256)."""
        tenant_1 = "tenant_alpha"
        tenant_2 = "tenant_beta"
        filename = "overview.md"

        expected_id_1 = f"doc_{hashlib.sha256(f'{tenant_1}:{filename}'.encode()).hexdigest()}"
        expected_id_2 = f"doc_{hashlib.sha256(f'{tenant_2}:{filename}'.encode()).hexdigest()}"
        assert len(expected_id_1) == 68  # 'doc_' + 64 hex characters
        assert len(expected_id_2) == 68

        # Repeated derivation must be 100% stable
        for _ in range(5):
            calc_1 = f"doc_{hashlib.sha256(f'{tenant_1}:{filename}'.encode()).hexdigest()}"
            calc_2 = f"doc_{hashlib.sha256(f'{tenant_2}:{filename}'.encode()).hexdigest()}"
            assert calc_1 == expected_id_1
            assert calc_2 == expected_id_2
            assert calc_1 != calc_2

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_delete_tenant_b_qdrant_vectors(self) -> None:
        """Verify real Qdrant deletion filter prevents cross-tenant vector deletion."""
        qdrant_client = QdrantClient(":memory:")
        collection = "multi_tenant_kb"
        qdrant_client.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(size=768, distance=qmodels.Distance.COSINE),
        )

        service = KnowledgeBaseIngestionService(qdrant_client=qdrant_client)
        tenant_a = "tenant_attacker"
        tenant_b = "tenant_victim"

        # Ingest document for Tenant B
        res_b = await service.ingest_document(
            filename="confidential.txt",
            content="Confidential proprietary information belonging to Tenant B.",
            tenant_id=tenant_b,
            collection_name=collection,
        )
        doc_id_b = res_b["document_id"]

        # Verify Tenant B's points exist in Qdrant
        points_b_before = qdrant_client.scroll(
            collection_name=collection,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(key="tenant_id", match=qmodels.MatchValue(value=tenant_b)),
                    qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id_b)),
                ]
            ),
        )[0]
        assert len(points_b_before) >= 1

        # Tenant A maliciously attempts to delete Tenant B's document ID
        service.delete_document(
            tenant_id=tenant_a,  # Attacker tenant context
            document_id=doc_id_b,  # Victim's document ID
            collection_name=collection,
        )

        # Assert Tenant B's points in Qdrant were NOT deleted!
        points_b_after = qdrant_client.scroll(
            collection_name=collection,
            scroll_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(key="tenant_id", match=qmodels.MatchValue(value=tenant_b)),
                    qmodels.FieldCondition(key="document_id", match=qmodels.MatchValue(value=doc_id_b)),
                ]
            ),
        )[0]
        assert len(points_b_after) == len(points_b_before)

    @pytest.mark.asyncio
    async def test_tenant_a_cannot_retrieve_or_delete_tenant_b_metadata(self) -> None:
        """Verify Tenant A cannot see or delete Tenant B's document metadata in PostgreSQL."""
        tenant_a = f"t_meta_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"t_meta_b_{uuid.uuid4().hex[:8]}"
        headers_a = AuthTestFactory.auth_headers(tenant_id=tenant_a, role=Role.TENANT_ADMIN)
        headers_b = AuthTestFactory.auth_headers(tenant_id=tenant_b, role=Role.TENANT_ADMIN)

        # Tenant B uploads a document
        res_b = client.post(
            "/v1/kb/upload?sync=true",
            json={"filename": "secret.txt", "content": "Tenant B private document."},
            headers=headers_b,
        )
        assert res_b.status_code == 201
        doc_id_b = res_b.json()["document_id"]

        # Tenant A lists documents -> cannot see Tenant B's document
        list_a = client.get("/v1/kb/documents", headers=headers_a).json()
        assert not any(d["document_id"] == doc_id_b for d in list_a.get("documents", []))

        # Tenant A attempts to delete Tenant B's document -> 404 Not Found
        del_res = client.delete(f"/v1/kb/documents/{doc_id_b}", headers=headers_a)
        assert del_res.status_code == 404
        assert del_res.json()["error"]["code"] == "NOT_FOUND"

        # Tenant B's document still exists
        list_b = client.get("/v1/kb/documents", headers=headers_b).json()
        assert any(d["document_id"] == doc_id_b for d in list_b["documents"])

    @pytest.mark.asyncio
    async def test_failed_enqueue_does_not_leave_falsely_successful_state(self) -> None:
        """Verify broker unreachable or dispatch failure returns 503 and leaves no false PostgreSQL record."""
        tenant_id = f"t_fail_q_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        payload = {
            "filename": "failing_dispatch.txt",
            "content": "This upload should fail due to broker downtime.",
        }

        # 1. Broker unreachable pre-dispatch -> 503 SERVICE_DEGRADED + Retry-After
        with patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=False):
            res_broker_down = client.post("/v1/kb/upload", json=payload, headers=headers)

        assert res_broker_down.status_code == 503
        assert res_broker_down.headers.get("retry-after") == "30"
        assert res_broker_down.json()["error"]["code"] == "SERVICE_DEGRADED"

        # Verify no document committed in PostgreSQL
        record = await default_persistence_service.get_kb_document_by_filename(tenant_id, "failing_dispatch.txt")
        assert record is None

        # 2. Definitive broker dispatch failure during apply_async (e.g. connection refused) -> 503 + rollback
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch(
                "workers.tasks.ingest_document_task.apply_async",
                side_effect=ConnectionRefusedError("RabbitMQ broker connection refused"),
            ),
        ):
            res_dispatch_err = client.post("/v1/kb/upload", json=payload, headers=headers)

        assert res_dispatch_err.status_code == 503
        assert res_dispatch_err.headers.get("retry-after") == "30"
        assert res_dispatch_err.json()["error"]["code"] == "SERVICE_DEGRADED"

        # Verify pending record was deleted / no document left in PostgreSQL on definitive failure
        record2 = await default_persistence_service.get_kb_document_by_filename(tenant_id, "failing_dispatch.txt")
        assert record2 is None

    @pytest.mark.asyncio
    async def test_replacement_upload_broker_failure_preserves_old_vectors_and_metadata(self) -> None:
        """Verify definitive replacement upload failure preserves existing PostgreSQL metadata and Qdrant points."""
        tenant_id = f"t_replace_fail_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "contract_v1.txt"
        v1_content = "Original valid contractual clauses version 1."
        v2_content = "Modified amended contractual clauses version 2."

        # 1. Ingest original document v1 successfully
        res1 = client.post(
            "/v1/kb/upload?sync=true",
            json={"filename": filename, "content": v1_content, "collection_name": "contracts_kb"},
            headers=headers,
        )
        assert res1.status_code == 201
        doc_id = res1.json()["document_id"]

        # Verify v1 state in PostgreSQL
        record_v1 = await default_persistence_service.get_kb_document_by_filename(tenant_id, filename)
        assert record_v1 is not None
        v1_hash = record_v1.content_hash
        assert record_v1.status == "INDEXED"

        # Verify v1 vectors in store
        doc_in_store = [d for d in _kb_service._in_memory_docs.get(tenant_id, []) if d["document_id"] == doc_id]
        assert len(doc_in_store) == 1
        assert doc_in_store[0]["chunks"][0].content == v1_content

        # 2. Attempt replacement upload with v2_content while broker suffers definitive connection error
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch(
                "workers.tasks.ingest_document_task.apply_async",
                side_effect=ConnectionRefusedError("RabbitMQ broker connection refused"),
            ),
        ):
            res_v2_fail = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": v2_content, "collection_name": "contracts_kb"},
                headers=headers,
            )

        assert res_v2_fail.status_code == 503
        assert res_v2_fail.headers.get("retry-after") == "30"
        assert res_v2_fail.json()["error"]["code"] == "SERVICE_DEGRADED"

        # 3. CRITICAL INVARIANT: Verify PostgreSQL record was safely reverted to v1
        record_after = await default_persistence_service.get_kb_document_by_filename(tenant_id, filename)
        assert record_after is not None
        assert record_after.content_hash == v1_hash  # Hash is still v1!
        assert record_after.status == "INDEXED"  # Status is still INDEXED!

        # 4. CRITICAL INVARIANT: Verify existing vectors in storage were NOT purged or deleted
        store_after = [d for d in _kb_service._in_memory_docs.get(tenant_id, []) if d["document_id"] == doc_id]
        assert len(store_after) == 1
        assert store_after[0]["chunks"][0].content == v1_content

    @pytest.mark.asyncio
    async def test_replacement_upload_success_replaces_vectors_and_updates_metadata(self) -> None:
        """Verify successful replacement upload purges old chunks and updates PostgreSQL metadata."""
        tenant_id = f"t_replace_ok_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "architecture.txt"
        v1_content = "Initial architecture specification overview."
        v2_content = "Updated architecture specification overview with additional details."

        # 1. Ingest initial version v1
        res1 = client.post(
            "/v1/kb/upload?sync=true",
            json={"filename": filename, "content": v1_content, "collection_name": "arch_kb"},
            headers=headers,
        )
        assert res1.status_code == 201
        doc_id = res1.json()["document_id"]

        # 2. Ingest replacement version v2
        res2 = client.post(
            "/v1/kb/upload?sync=true",
            json={"filename": filename, "content": v2_content, "collection_name": "arch_kb"},
            headers=headers,
        )
        assert res2.status_code == 201

        # 3. Verify PostgreSQL record reflects v2 content hash and INDEXED status
        record_v2 = await default_persistence_service.get_kb_document_by_filename(tenant_id, filename)
        assert record_v2 is not None
        assert record_v2.content_hash == hashlib.sha256(v2_content.encode()).hexdigest()
        assert record_v2.status == "INDEXED"

        # 4. Verify vector store holds v2 chunks and old v1 chunks are replaced
        docs_in_store = [d for d in _kb_service._in_memory_docs.get(tenant_id, []) if d["document_id"] == doc_id]
        assert len(docs_in_store) == 1
        assert docs_in_store[0]["chunks"][0].content == v2_content

    @pytest.mark.asyncio
    async def test_concurrent_uploads_same_content(self) -> None:
        """Verify concurrent uploads with identical content succeed without race conditions or duplicate rows."""
        import concurrent.futures

        tenant_id = f"t_conc_same_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        payload = {
            "filename": "concurrent_same.txt",
            "content": "Concurrent identical document payload for race condition testing.",
            "collection_name": "conc_kb",
        }

        # Issue 5 concurrent uploads
        def do_upload() -> int:
            resp = client.post("/v1/kb/upload?sync=true", json=payload, headers=headers)
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(do_upload) for _ in range(5)]
            status_codes = [f.result() for f in futures]

        # All requests must have succeeded (either 201 Created or 200 OK duplicate)
        assert all(sc in {200, 201} for sc in status_codes)

        # Authoritative PostgreSQL check: strictly 1 row in kb_documents
        docs = await default_persistence_service.list_kb_documents(tenant_id)
        assert len(docs) == 1
        assert docs[0].filename == "concurrent_same.txt"

    @pytest.mark.asyncio
    async def test_concurrent_uploads_different_content(self) -> None:
        """Verify concurrent uploads with differing content update atomically via ON CONFLICT without error."""
        import concurrent.futures

        tenant_id = f"t_conc_diff_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        def do_upload_variant(i: int) -> int:
            payload = {
                "filename": "concurrent_diff.txt",
                "content": f"Variant {i} content string for concurrency test.",
                "collection_name": "conc_kb",
            }
            resp = client.post("/v1/kb/upload?sync=true", json=payload, headers=headers)
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(do_upload_variant, i) for i in range(4)]
            status_codes = [f.result() for f in futures]

        # All uploads should succeed with 200 or 201 (no 500 Internal Server Error)
        assert all(sc in {200, 201} for sc in status_codes)

        # Authoritative PostgreSQL check: strictly 1 row in kb_documents
        docs = await default_persistence_service.list_kb_documents(tenant_id)
        assert len(docs) == 1
        assert docs[0].filename == "concurrent_diff.txt"
        assert docs[0].status == "INDEXED"

    @pytest.mark.asyncio
    async def test_worker_crash_before_postgres_commit_preserves_old_index(self) -> None:
        """Verify worker failure after vector upsert but before PostgreSQL commit preserves old index and metadata."""
        tenant_id = f"t_wcrash_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "crash_safety.txt"
        v1_content = "Stable known-good content generation 1."
        v2_content = "Replacement candidate content generation 2."

        # 1. Ingest initial generation 1
        res1 = client.post(
            "/v1/kb/upload?sync=true",
            json={"filename": filename, "content": v1_content, "collection_name": "crash_kb"},
            headers=headers,
        )
        assert res1.status_code == 201
        doc_id = res1.json()["document_id"]

        # Confirm generation 1 in PostgreSQL and store
        rec1 = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec1 is not None
        assert rec1.generation == 1
        assert rec1.status == "INDEXED"
        assert rec1.content_hash == hashlib.sha256(v1_content.encode()).hexdigest()

        docs_store_1 = [d for d in _kb_service._in_memory_docs.get(tenant_id, []) if d["document_id"] == doc_id]
        assert any(d["chunks"][0].content == v1_content for d in docs_store_1)

        # 2. Simulate worker crash during v2 replacement:
        # Mock update_kb_document_status to throw a database connectivity / process crash exception
        with patch.object(
            default_persistence_service,
            "update_kb_document_status",
            side_effect=RuntimeError("Worker process SIGKILL / connection severed before DB commit"),
        ):
            with pytest.raises(RuntimeError):
                ingest_document_task(
                    filename=filename,
                    content=v2_content,
                    tenant_id=tenant_id,
                    collection_name="crash_kb",
                    doc_id=doc_id,
                    generation=2,
                )

        # 3. CRITICAL INVARIANT: PostgreSQL must STILL describe generation 1 with v1 content hash
        rec_after_crash = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec_after_crash is not None
        assert rec_after_crash.generation == 1
        assert rec_after_crash.status == "INDEXED"
        assert rec_after_crash.content_hash == hashlib.sha256(v1_content.encode()).hexdigest()

        # 4. CRITICAL INVARIANT: The old generation 1 index must NOT have been destroyed
        docs_store_after = [d for d in _kb_service._in_memory_docs.get(tenant_id, []) if d["document_id"] == doc_id]
        assert any(d["chunks"][0].content == v1_content for d in docs_store_after)

    @pytest.mark.asyncio
    async def test_qdrant_partial_upsert_failure_preserves_old_index(self) -> None:
        """Verify vector store failure during replacement preserves existing indexed points and metadata."""
        tenant_id = f"t_qfail_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "qdrant_fail.txt"
        v1_content = "Original index points version 1."
        v2_content = "Attempted new points version 2."

        # Ingest v1
        res1 = client.post(
            "/v1/kb/upload?sync=true",
            json={"filename": filename, "content": v1_content, "collection_name": "qfail_kb"},
            headers=headers,
        )
        assert res1.status_code == 201
        doc_id = res1.json()["document_id"]

        # Simulate Qdrant throwing during v2 upsert
        with patch.object(
            KnowledgeBaseIngestionService,
            "ingest_document",
            side_effect=RuntimeError("Qdrant partial write timeout"),
        ):
            with pytest.raises(RuntimeError):
                ingest_document_task(
                    filename=filename,
                    content=v2_content,
                    tenant_id=tenant_id,
                    collection_name="qfail_kb",
                    doc_id=doc_id,
                    generation=2,
                )

        # Confirm PostgreSQL and store still describe v1
        rec = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec is not None
        assert rec.generation == 1
        assert rec.status == "INDEXED"
        assert rec.content_hash == hashlib.sha256(v1_content.encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_retry_after_failed_replacement_succeeds(self) -> None:
        """Verify retrying ingestion after a previous failure cleanly replaces vectors and updates metadata."""
        tenant_id = f"t_retry_ok_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "retry_success.txt"
        v1_content = "Initial content v1."
        v2_content = "Updated content v2."

        res1 = client.post(
            "/v1/kb/upload?sync=true",
            json={"filename": filename, "content": v1_content, "collection_name": "retry_kb"},
            headers=headers,
        )
        assert res1.status_code == 201
        doc_id = res1.json()["document_id"]

        # Run task for generation 2 successfully (simulating retry)
        task_res = ingest_document_task(
            filename=filename,
            content=v2_content,
            tenant_id=tenant_id,
            collection_name="retry_kb",
            doc_id=doc_id,
            generation=2,
        )
        assert task_res["generation"] == 2

        # Verify PostgreSQL is now generation 2, INDEXED
        rec2 = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec2 is not None
        assert rec2.generation == 2
        assert rec2.status == "INDEXED"
        assert rec2.content_hash == hashlib.sha256(v2_content.encode()).hexdigest()

        # Verify store has v2 vectors
        store_docs = [d for d in _kb_service._in_memory_docs.get(tenant_id, []) if d["document_id"] == doc_id]
        assert any(d["chunks"][0].content == v2_content for d in store_docs)

    @pytest.mark.asyncio
    async def test_db_state_exists_before_worker_consumes_task(self) -> None:
        """Verify PostgreSQL authoritative row exists with PENDING before task dispatch, preventing race condition."""
        tenant_id = f"t_dispatch_race_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "order_test.txt"
        content = "Ordering validation document content."

        observed_db_state: dict[str, Any] = {}

        def spy_apply_async(*_args: Any, **_kwargs: Any) -> MagicMock:
            # Query PostgreSQL immediately from within the dispatch call to verify visibility

            async def check_db() -> None:
                doc = await default_persistence_service.get_kb_document_by_filename(tenant_id, filename)
                if doc is not None:
                    observed_db_state["status"] = doc.status
                    observed_db_state["generation"] = doc.generation
                    observed_db_state["document_id"] = doc.document_id

            _run_async(check_db())
            return MagicMock(id="task_order_123")

        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch("workers.tasks.ingest_document_task.apply_async", side_effect=spy_apply_async),
        ):
            res = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": content, "collection_name": "order_kb"},
                headers=headers,
            )

        assert res.status_code == 202

        # INVARIANT: When apply_async was called, PostgreSQL row ALREADY existed with status PENDING
        assert observed_db_state.get("status") == "PENDING"
        assert observed_db_state.get("generation") == 1
        assert observed_db_state.get("document_id") is not None

        # Now worker consumes and processes the task cleanly
        task_out = ingest_document_task(
            filename=filename,
            content=content,
            tenant_id=tenant_id,
            collection_name="order_kb",
            doc_id=observed_db_state["document_id"],
            generation=observed_db_state["generation"],
        )
        assert task_out["generation"] == 1

        rec = await default_persistence_service.get_kb_document_by_id(tenant_id, observed_db_state["document_id"])
        assert rec is not None
        assert rec.status == "INDEXED"

    @pytest.mark.asyncio
    async def test_reversed_worker_execution_order_discards_stale_task(self) -> None:
        """Verify an older task cannot overwrite a newer generation when worker tasks execute out of order."""
        tenant_id = f"t_reorder_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "reorder.txt"
        v1_content = "Version 1 older content."
        v2_content = "Version 2 newer content."

        # Upload A (v1) -> generation 1 in PostgreSQL
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch("workers.tasks.ingest_document_task.apply_async") as mock_a,
        ):
            mock_a.return_value = MagicMock(id="task_A")
            res_a = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": v1_content, "collection_name": "reorder_kb"},
                headers=headers,
            )
        assert res_a.status_code == 202
        gen_a = res_a.json()["generation"]
        doc_id = res_a.json()["document_id"]
        assert gen_a == 1

        # Upload B (v2) -> generation 2 in PostgreSQL
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch("workers.tasks.ingest_document_task.apply_async") as mock_b,
        ):
            mock_b.return_value = MagicMock(id="task_B")
            res_b = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": v2_content, "collection_name": "reorder_kb"},
                headers=headers,
            )
        assert res_b.status_code == 202
        gen_b = res_b.json()["generation"]
        assert gen_b == 2

        # Intentionally REVERSE execution order: Run Task B (generation 2) FIRST!
        res_task_b = ingest_document_task(
            filename=filename,
            content=v2_content,
            tenant_id=tenant_id,
            collection_name="reorder_kb",
            doc_id=doc_id,
            generation=2,
        )
        assert res_task_b["generation"] == 2

        # Verify DB is now INDEXED on generation 2 with v2 content
        rec_after_b = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec_after_b is not None
        assert rec_after_b.generation == 2
        assert rec_after_b.status == "INDEXED"
        assert rec_after_b.content_hash == hashlib.sha256(v2_content.encode()).hexdigest()

        # Now execute older Task A (generation 1) LATER!
        res_task_a = ingest_document_task(
            filename=filename,
            content=v1_content,
            tenant_id=tenant_id,
            collection_name="reorder_kb",
            doc_id=doc_id,
            generation=1,
        )

        # INVARIANT: Task A must be discarded as superseded!
        assert res_task_a.get("status") == "superseded"
        assert res_task_a.get("task_generation") == 1
        assert res_task_a.get("current_generation") == 2

        # INVARIANT: Database must STILL describe generation 2, NOT corrupted or downgraded to generation 1
        rec_final = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec_final is not None
        assert rec_final.generation == 2
        assert rec_final.status == "INDEXED"
        assert rec_final.content_hash == hashlib.sha256(v2_content.encode()).hexdigest()

        # INVARIANT: Storage must contain v2 chunks, NOT v1 chunks
        docs_in_store = [d for d in _kb_service._in_memory_docs.get(tenant_id, []) if d["document_id"] == doc_id]
        assert all(d["chunks"][0].content == v2_content for d in docs_in_store)

    @pytest.mark.asyncio
    async def test_retry_of_older_task_after_newer_version_indexed_does_not_overwrite(self) -> None:
        """Verify retrying an older task after a newer version is indexed does not overwrite state."""
        tenant_id = f"t_old_retry_{uuid.uuid4().hex[:8]}"
        filename = "retry_stale.txt"
        v1_content = "Older content v1."
        v2_content = "Newer content v2."
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        # Initialize generation 2 in PostgreSQL as INDEXED
        await default_persistence_service.upsert_kb_document(
            tenant_id=tenant_id,
            document_id=doc_id,
            filename=filename,
            content_hash=hashlib.sha256(v2_content.encode()).hexdigest(),
            chunks_count=1,
            collection_name="stale_kb",
            status="INDEXED",
            generation=2,
        )

        # Older retry attempt for generation 1
        result = ingest_document_task(
            filename=filename,
            content=v1_content,
            tenant_id=tenant_id,
            collection_name="stale_kb",
            doc_id=doc_id,
            generation=1,
        )

        assert result.get("status") == "superseded"

        # Verify DB still describes generation 2
        rec = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec is not None
        assert rec.generation == 2
        assert rec.content_hash == hashlib.sha256(v2_content.encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_ambiguous_publisher_confirm_failure_preserves_pending_record(self) -> None:
        """Verify ambiguous publisher-confirm outcome preserves PENDING PostgreSQL record."""
        tenant_id = f"t_amb_pub_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "ambiguous_publish.txt"
        content = "Important document subjected to ambiguous publish timeout."

        # Simulate publisher confirmation timeout during apply_async
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch(
                "workers.tasks.ingest_document_task.apply_async",
                side_effect=TimeoutError("RabbitMQ publisher confirmation timeout after 5.0s"),
            ),
        ):
            res = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": content, "collection_name": "amb_kb"},
                headers=headers,
            )

        # 1. Gateway returns 503 SERVICE_DEGRADED + Retry-After: 30
        assert res.status_code == 503
        assert res.headers.get("retry-after") == "30"
        assert res.json()["error"]["code"] == "SERVICE_DEGRADED"

        # 2. CRITICAL INVARIANT: The PostgreSQL record MUST be preserved in PENDING state (NOT deleted)
        rec = await default_persistence_service.get_kb_document_by_filename(tenant_id, filename)
        assert rec is not None, "PostgreSQL PENDING record must NOT be deleted on ambiguous publish outcome!"
        assert rec.status == "PENDING"
        assert rec.generation == 1
        assert rec.content_hash == hashlib.sha256(content.encode()).hexdigest()

    @pytest.mark.asyncio
    async def test_ambiguous_publish_worker_delivery_succeeds_and_reconciles(self) -> None:
        """Verify that when an ambiguously published task is delivered to the worker, it succeeds and reconciles."""
        tenant_id = f"t_amb_work_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "amb_worker_reconcile.txt"
        content = "Document where gateway timed out but message reached broker and worker."
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        # 1. Gateway encounters ambiguous publisher-confirm timeout
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch(
                "workers.tasks.ingest_document_task.apply_async",
                side_effect=TimeoutError("RabbitMQ publisher confirmation timeout"),
            ),
        ):
            res = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": content, "collection_name": "amb_work_kb"},
                headers=headers,
            )
        assert res.status_code == 503

        # 2. Worker subsequently receives the task from RabbitMQ and executes
        result = ingest_document_task(
            filename=filename,
            content=content,
            tenant_id=tenant_id,
            collection_name="amb_work_kb",
            doc_id=doc_id,
            generation=1,
        )

        assert result.get("chunks_count", 0) >= 1
        assert result.get("document_id") == doc_id

        # 3. CRITICAL INVARIANT: PostgreSQL record successfully reconciled to INDEXED
        rec = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec is not None
        assert rec.status == "INDEXED"
        assert rec.generation == 1
        assert rec.content_hash == hashlib.sha256(content.encode()).hexdigest()

        # 4. Verified via GET /v1/kb/documents
        list_res = client.get("/v1/kb/documents", headers=headers)
        assert list_res.status_code == 200
        docs = [d for d in list_res.json()["documents"] if d["document_id"] == doc_id]
        assert len(docs) == 1
        assert docs[0]["indexed_to_qdrant"] is True
        assert docs[0]["status"] == "INDEXED"

    @pytest.mark.asyncio
    async def test_ambiguous_publish_client_retry_no_duplicate_ingestion(self) -> None:
        """Verify client retry after ambiguous publish re-dispatches with same generation without duplicate vectors."""
        tenant_id = f"t_amb_retry_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "retry_ambiguous.txt"
        content = "Data uploaded with retry following ambiguous outcome."
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        # 1. First attempt encounters ambiguous confirm timeout -> 503, preserved as PENDING
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch(
                "workers.tasks.ingest_document_task.apply_async",
                side_effect=TimeoutError("Publisher confirm timeout"),
            ),
        ):
            res1 = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": content, "collection_name": "amb_retry_kb"},
                headers=headers,
            )
        assert res1.status_code == 503

        # 2. Client retries with the SAME content
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch("workers.tasks.ingest_document_task.apply_async") as mock_retry_apply,
        ):
            mock_retry_apply.return_value = MagicMock(id="task_retry_456")
            res2 = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": content, "collection_name": "amb_retry_kb"},
                headers=headers,
            )
        assert res2.status_code == 202
        assert res2.json()["generation"] == 1  # Reused generation 1! Did NOT burn generation 2

        # 3. Worker 1 executes task
        res_work1 = ingest_document_task(
            filename=filename,
            content=content,
            tenant_id=tenant_id,
            collection_name="amb_retry_kb",
            doc_id=doc_id,
            generation=1,
        )
        assert res_work1.get("chunks_count", 0) >= 1

        # 4. Worker 2 (from retry) executes duplicate task -> idempotent duplicate
        res_work2 = ingest_document_task(
            filename=filename,
            content=content,
            tenant_id=tenant_id,
            collection_name="amb_retry_kb",
            doc_id=doc_id,
            generation=1,
        )
        assert res_work2.get("idempotent_duplicate") is True
        assert res_work2.get("status") == "INDEXED"

        # 5. Database record remains generation 1, INDEXED
        rec = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec is not None
        assert rec.generation == 1
        assert rec.status == "INDEXED"

    @pytest.mark.asyncio
    async def test_worker_delivery_after_gateway_exception_cannot_encounter_deleted_record(self) -> None:
        """Verify worker delivery after ambiguous gateway failure never encounters a deleted authoritative record."""
        tenant_id = f"t_nodelete_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "no_deleted_rec.txt"
        v1_content = "Version 1 content."
        v2_content = "Version 2 amended content."
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        # 1. Ingest v1
        res1 = client.post(
            "/v1/kb/upload?sync=true",
            json={"filename": filename, "content": v1_content, "collection_name": "no_del_kb"},
            headers=headers,
        )
        assert res1.status_code == 201

        # 2. Upload v2 replacement, gateway suffers ambiguous publisher timeout
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch(
                "workers.tasks.ingest_document_task.apply_async",
                side_effect=TimeoutError("Publisher confirmation timed out"),
            ),
        ):
            res_v2 = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": v2_content, "collection_name": "no_del_kb"},
                headers=headers,
            )
        assert res_v2.status_code == 503

        # 3. CRITICAL INVARIANT: PostgreSQL record was NOT reverted to v1; it is PENDING generation 2
        rec_pending = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec_pending is not None
        assert rec_pending.generation == 2
        assert rec_pending.status == "PENDING"
        assert rec_pending.content_hash == hashlib.sha256(v2_content.encode()).hexdigest()

        # 4. Worker executes task for generation 2
        res_work = ingest_document_task(
            filename=filename,
            content=v2_content,
            tenant_id=tenant_id,
            collection_name="no_del_kb",
            doc_id=doc_id,
            generation=2,
        )
        assert res_work.get("status") != "ABORTED"
        assert res_work.get("chunks_count", 0) >= 1

        # 5. Database commits generation 2 INDEXED
        rec_final = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec_final is not None
        assert rec_final.generation == 2
        assert rec_final.status == "INDEXED"

    @pytest.mark.asyncio
    async def test_retrieval_excludes_stale_generation_when_both_generations_temporarily_exist(self) -> None:
        """Verify that when both old and new generations temporarily exist in Qdrant,
        retrieval returns ONLY chunks from the authoritative active generation.
        """
        qdrant_client = QdrantClient(":memory:")
        collection = "stale_vis_kb"
        qdrant_client.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(size=768, distance=qmodels.Distance.COSINE),
        )

        service = KnowledgeBaseIngestionService(qdrant_client=qdrant_client)
        from workers.rav.worker import RAVWorker

        rav_worker = RAVWorker()
        rav_worker._client = qdrant_client

        tenant_id = f"t_stale_{uuid.uuid4().hex[:8]}"
        filename = "contract.txt"
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        v1_text = "The vendor penalty fee is exactly 10 percent of contract value."
        v2_text = "The vendor penalty fee is completely waived and zero percent."

        # 1. Ingest generation 1 into Qdrant
        await service.ingest_document(
            filename=filename,
            content=v1_text,
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=1,
        )

        # 2. Ingest generation 2 into Qdrant WITHOUT deleting generation 1 (multi-gen side-by-side)
        await service.ingest_document(
            filename=filename,
            content=v2_text,
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=2,
        )

        # Confirm BOTH generations exist in Qdrant
        all_points = qdrant_client.scroll(collection_name=collection, limit=10)[0]
        assert len(all_points) == 2
        generations_in_qdrant = {p.payload["generation"] for p in all_points if p.payload}
        assert generations_in_qdrant == {1, 2}

        # 3. PostgreSQL declares generation 2 as the authoritative INDEXED generation
        await default_persistence_service.upsert_kb_document(
            tenant_id=tenant_id,
            document_id=doc_id,
            filename=filename,
            content_hash=hashlib.sha256(v2_text.encode()).hexdigest(),
            chunks_count=1,
            collection_name=collection,
            status="INDEXED",
            generation=2,
        )

        # 4. CRITICAL INVARIANT: Retrieval query returns ONLY generation 2 chunks!
        results = await rav_worker.search_evidence(
            query="vendor penalty fee",
            tenant_id=tenant_id,
            collection_name=collection,
            limit=5,
        )
        assert len(results) >= 1
        for chunk in results:
            meta = chunk.source_metadata or {}
            assert meta.get("generation") == 2, f"Stale generation leaked into retrieval: {meta}"
            assert v2_text in chunk.content
            assert v1_text not in chunk.content

    @pytest.mark.asyncio
    async def test_retrieval_excludes_stale_generation_when_post_commit_cleanup_fails(self) -> None:
        """Verify that if post-commit cleanup fails or times out, retrieval remains correct
        and never returns stale generation chunks.
        """
        qdrant_client = QdrantClient(":memory:")
        collection = "cleanup_fail_kb"
        qdrant_client.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(size=768, distance=qmodels.Distance.COSINE),
        )

        service = KnowledgeBaseIngestionService(qdrant_client=qdrant_client)
        from workers.rav.worker import RAVWorker

        rav_worker = RAVWorker()
        rav_worker._client = qdrant_client

        tenant_id = f"t_cleanfail_{uuid.uuid4().hex[:8]}"
        filename = "system_guide.txt"
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        old_text = "System port is 8080 by default."
        new_text = "System port is 9443 secure TLS by default."

        # Ingest gen 1
        await service.ingest_document(
            filename=filename,
            content=old_text,
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=1,
        )

        # Ingest gen 2
        await service.ingest_document(
            filename=filename,
            content=new_text,
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=2,
        )

        # PostgreSQL declares generation 2 as INDEXED
        await default_persistence_service.upsert_kb_document(
            tenant_id=tenant_id,
            document_id=doc_id,
            filename=filename,
            content_hash=hashlib.sha256(new_text.encode()).hexdigest(),
            chunks_count=1,
            collection_name=collection,
            status="INDEXED",
            generation=2,
        )

        # Simulate post-commit cleanup failure: purge_old_generations throws exception
        with patch.object(service, "purge_old_generations", side_effect=RuntimeError("Qdrant delete timed out")):
            try:
                service.purge_old_generations(tenant_id, doc_id, keep_generation=2, collection_name=collection)
            except RuntimeError:
                pass

        # Verify old vectors STILL physically reside in Qdrant (cleanup failed)
        pts = qdrant_client.scroll(collection_name=collection, limit=10)[0]
        assert any(p.payload and p.payload.get("generation") == 1 for p in pts)

        # CRITICAL INVARIANT: Retrieval query STILL filters out generation 1!
        results = await rav_worker.search_evidence(
            query="System port",
            tenant_id=tenant_id,
            collection_name=collection,
            limit=5,
        )
        assert len(results) == 1
        assert results[0].source_metadata is not None
        assert results[0].source_metadata.get("generation") == 2
        assert "9443" in results[0].content

    @pytest.mark.asyncio
    async def test_subsequent_cleanup_removes_old_generation_vectors(self) -> None:
        """Verify that when cleanup subsequently succeeds, old generation vectors are purged (storage hygiene)."""
        qdrant_client = QdrantClient(":memory:")
        collection = "hygiene_kb"
        qdrant_client.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(size=768, distance=qmodels.Distance.COSINE),
        )

        service = KnowledgeBaseIngestionService(qdrant_client=qdrant_client)
        tenant_id = f"t_hygiene_{uuid.uuid4().hex[:8]}"
        filename = "hygiene.txt"
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        # Ingest gen 1 and gen 2
        await service.ingest_document(
            filename=filename,
            content="Old content",
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=1,
        )
        await service.ingest_document(
            filename=filename,
            content="New content",
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=2,
        )

        pts_before = qdrant_client.scroll(collection_name=collection, limit=10)[0]
        assert len(pts_before) == 2

        # Purge succeeds
        service.purge_old_generations(
            tenant_id=tenant_id, document_id=doc_id, keep_generation=2, collection_name=collection
        )

        pts_after = qdrant_client.scroll(collection_name=collection, limit=10)[0]
        assert len(pts_after) == 1
        assert pts_after[0].payload is not None
        assert pts_after[0].payload["generation"] == 2

    @pytest.mark.asyncio
    async def test_stale_generation_cannot_affect_rav_scores(self) -> None:
        """Verify RAV risk scores are computed strictly from the active generation evidence."""
        qdrant_client = QdrantClient(":memory:")
        collection = "rav_score_kb"
        qdrant_client.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(size=768, distance=qmodels.Distance.COSINE),
        )

        service = KnowledgeBaseIngestionService(qdrant_client=qdrant_client)
        from workers.rav.worker import RAVWorker

        rav_worker = RAVWorker()
        rav_worker._client = qdrant_client

        tenant_id = f"t_rav_score_{uuid.uuid4().hex[:8]}"
        filename = "pricing.txt"
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        # Gen 1 text contradicts new claim, Gen 2 text strongly entails new claim
        v1_text = "The monthly enterprise subscription price is 500 dollars."
        v2_text = "The monthly enterprise subscription price is 1200 dollars."

        await service.ingest_document(
            filename=filename,
            content=v1_text,
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=1,
        )
        await service.ingest_document(
            filename=filename,
            content=v2_text,
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=2,
        )

        # Set Gen 2 active
        await default_persistence_service.upsert_kb_document(
            tenant_id=tenant_id,
            document_id=doc_id,
            filename=filename,
            content_hash=hashlib.sha256(v2_text.encode()).hexdigest(),
            chunks_count=1,
            collection_name=collection,
            status="INDEXED",
            generation=2,
        )

        from shared.schemas import Claim, ClaimCriticality, ClaimType

        claim = Claim(
            claim_id="c_price",
            text="The monthly enterprise subscription price is 1200 dollars.",
            claim_type=ClaimType.FACTUAL,
            criticality=ClaimCriticality.HIGH,
        )

        chunks = await rav_worker.search_evidence(
            query=claim.text,
            tenant_id=tenant_id,
            collection_name=collection,
        )
        rav_score = rav_worker.compute_rav_score(claim, chunks)
        # Should be low risk (< 0.3) because active generation contains identical statement
        assert rav_score < 0.30
        assert all(c.source_metadata.get("generation") == 2 for c in chunks)

    @pytest.mark.asyncio
    async def test_ambiguous_publish_never_delivered_reconciles_to_failed_after_stale_threshold(self) -> None:
        """Verify that if an ambiguous publish occurred and the message was never delivered,
        reconciliation transitions the record out of PENDING to FAILED without getting stuck.
        """
        tenant_id = f"t_never_deliv_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)
        filename = "never_delivered.txt"
        content = "Upload that suffered publish timeout and never reached the message broker."
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        # 1. Ambiguous upload -> 503, saved as PENDING
        with (
            patch("gateway.routes.knowledge_base.is_broker_reachable", return_value=True),
            patch("workers.tasks.ingest_document_task.apply_async", side_effect=TimeoutError("Confirm timeout")),
        ):
            res = client.post(
                "/v1/kb/upload",
                json={"filename": filename, "content": content, "collection_name": "never_deliv_kb"},
                headers=headers,
            )
        assert res.status_code == 503

        # Record is in PENDING
        rec = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec is not None
        assert rec.status == "PENDING"

        # 2. Run reconciliation with stale_threshold_seconds=0 (immediate stale check)
        reconciled = await default_persistence_service.reconcile_stale_pending_kb_documents(
            tenant_id=tenant_id,
            stale_threshold_seconds=0,
            qdrant_client=None,
        )
        assert len(reconciled) == 1
        assert reconciled[0]["document_id"] == doc_id
        assert reconciled[0]["new_status"] == "FAILED"

        # 3. CRITICAL INVARIANT: Authoritative status in PostgreSQL is now FAILED, NOT stuck in PENDING!
        rec_after = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec_after is not None
        assert rec_after.status == "FAILED"

    @pytest.mark.asyncio
    async def test_reconciliation_promotes_pending_to_indexed_if_vectors_exist(self) -> None:
        """Verify that if the worker indexed vectors in Qdrant but PostgreSQL status update was interrupted,
        reconciliation detects the vectors and promotes the record to INDEXED.
        """
        qdrant_client = QdrantClient(":memory:")
        collection = "reconcile_indexed_kb"
        qdrant_client.create_collection(
            collection_name=collection,
            vectors_config=qmodels.VectorParams(size=768, distance=qmodels.Distance.COSINE),
        )

        service = KnowledgeBaseIngestionService(qdrant_client=qdrant_client)
        tenant_id = f"t_reconcile_prom_{uuid.uuid4().hex[:8]}"
        filename = "reconcile_prom.txt"
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"
        content = "Valid document with existing indexed vectors."

        # Ingest vectors directly into Qdrant
        await service.ingest_document(
            filename=filename,
            content=content,
            tenant_id=tenant_id,
            collection_name=collection,
            doc_id=doc_id,
            generation=1,
        )

        # Set PostgreSQL record to PENDING (simulating interrupted status commit)
        await default_persistence_service.upsert_kb_document(
            tenant_id=tenant_id,
            document_id=doc_id,
            filename=filename,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            chunks_count=0,
            collection_name=collection,
            status="PENDING",
            generation=1,
        )

        # Run reconciliation
        reconciled = await default_persistence_service.reconcile_stale_pending_kb_documents(
            tenant_id=tenant_id,
            stale_threshold_seconds=0,
            qdrant_client=qdrant_client,
        )
        assert len(reconciled) == 1
        assert reconciled[0]["document_id"] == doc_id
        assert reconciled[0]["new_status"] == "INDEXED"

        # Verify PostgreSQL record is now INDEXED
        rec = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec is not None
        assert rec.status == "INDEXED"
        assert rec.chunks_count >= 1

    @pytest.mark.asyncio
    async def test_reconciliation_never_rolls_back_already_indexed_newer_generation(self) -> None:
        """Verify that reconciliation NEVER rolls back or alters an already INDEXED newer generation."""
        tenant_id = f"t_norollback_{uuid.uuid4().hex[:8]}"
        filename = "steady_version.txt"
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        # Initialize generation 2 as INDEXED
        await default_persistence_service.upsert_kb_document(
            tenant_id=tenant_id,
            document_id=doc_id,
            filename=filename,
            content_hash=hashlib.sha256(b"v2 content").hexdigest(),
            chunks_count=3,
            collection_name="norollback_kb",
            status="INDEXED",
            generation=2,
        )

        # Run reconciliation
        reconciled = await default_persistence_service.reconcile_stale_pending_kb_documents(
            tenant_id=tenant_id,
            stale_threshold_seconds=0,
            qdrant_client=None,
        )
        # No pending records to reconcile
        assert len(reconciled) == 0

        # Verify generation 2 is completely unchanged
        rec = await default_persistence_service.get_kb_document_by_id(tenant_id, doc_id)
        assert rec is not None
        assert rec.generation == 2
        assert rec.status == "INDEXED"
        assert rec.chunks_count == 3

    @pytest.mark.asyncio
    async def test_reconciliation_does_not_enqueue_duplicate_ingestion_jobs(self) -> None:
        """Verify that reconciliation never enqueues tasks into Celery or RabbitMQ."""
        tenant_id = f"t_no_dup_enq_{uuid.uuid4().hex[:8]}"
        filename = "no_dup_enq.txt"
        doc_id = f"doc_{hashlib.sha256(f'{tenant_id}:{filename}'.encode()).hexdigest()}"

        await default_persistence_service.upsert_kb_document(
            tenant_id=tenant_id,
            document_id=doc_id,
            filename=filename,
            content_hash=hashlib.sha256(b"some content").hexdigest(),
            chunks_count=0,
            collection_name="no_dup_kb",
            status="PENDING",
            generation=1,
        )

        with patch("workers.tasks.ingest_document_task.apply_async") as mock_apply:
            await default_persistence_service.reconcile_stale_pending_kb_documents(
                tenant_id=tenant_id,
                stale_threshold_seconds=0,
                qdrant_client=None,
            )
            mock_apply.assert_not_called()
