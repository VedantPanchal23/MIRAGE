"""Integration tests for MongoDB verification trace persistence and dual-write failure semantics.

Governing Specifications:
- PRD.md §FR-AUD-01, §FR-AUD-04, §14
- Technical_Architecture.md §7.2, §8.3, §8.4, §9.1
- Security_Access.md §1.3, §4.3, §5, §9.1
- Testing_Strategy.md §5.5, §5.9
"""

import hashlib
import uuid
from typing import Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from analytics.store import default_session_store
from db.mongo import MongoPersistenceError, MongoTraceService
from db.persistence import (
    AmbiguousPostgresCommitError,
    DatabasePersistenceError,
    DefinitivePostgresPersistenceError,
    PostgresPersistenceService,
)
from gateway.main import create_app
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory


@pytest.mark.integration
class TestMongoTracePersistence:
    """Validate MongoDB trace persistence, lifecycle, indexes, and coordinated failure semantics."""

    @pytest.mark.asyncio
    async def test_trace_persistence_happy_path(self, live_mongo_database: Any) -> None:
        """Test A: Verifies full document structure, field fidelity, unhashed raw prompt/response."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        service = MongoTraceService()
        tenant_id = f"tenant_test_a_{uuid.uuid4().hex[:8]}"
        session_id = f"req_{uuid.uuid4().hex[:12]}"
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"

        trace_data: dict[str, Any] = {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "trace_id": trace_id,
            "model_id": "llama-3.1-70b-versatile",
            "raw_prompt": "What is the speed of sound at 20 degrees Celsius?",
            "raw_response": "The speed of sound in dry air at 20 °C is approximately 343 meters per second.",
            "verified_response": "The speed of sound in dry air at 20 °C is approximately 343 meters per second.",
            "hrs_result": {
                "hrs": 0.085,
                "tier": "LOW",
                "conformal_interval": {"lower": 0.04, "upper": 0.12},
                "signal_attribution": {"rav": 0.40, "scs": 0.30, "nli": 0.30, "ics": 0.0},
            },
            "claims": [
                {
                    "claim_id": "c1",
                    "text": "The speed of sound at 20 °C is 343 m/s.",
                    "type": "numerical",
                    "criticality": "high",
                    "status": "SUPPORTED",
                    "risk_score": 0.08,
                    "signal_scores": {"rav": 0.96, "scs": 0.94, "nli": 0.98},
                }
            ],
            "evidence_chunks": [
                {
                    "claim_index": 0,
                    "claim_text": "The speed of sound at 20 °C is 343 m/s.",
                    "chunks": [{"text": "In dry air at 20 °C, sound travels at 343 m/s.", "score": 0.97}],
                }
            ],
            "correction_metadata": {"correction_applied": False, "iterations": 0},
            "execution_metadata": {"execution_time_ms": 125.4, "pipeline_signals_used": ["rav", "scs", "nli"]},
            "pii_metadata": {"pii_flagged": False, "detected_counts": {}},
        }

        stored_id = await service.persist_verification_trace(tenant_id, trace_data)
        assert stored_id == session_id

        doc = await service.get_trace_by_session_id(tenant_id, session_id)
        assert doc is not None
        assert doc["session_id"] == session_id
        assert doc["tenant_id"] == tenant_id
        assert doc["trace_id"] == trace_id
        assert doc["raw_prompt"] == trace_data["raw_prompt"]
        assert doc["raw_response"] == trace_data["raw_response"]
        assert doc["claims"][0]["claim_id"] == "c1"
        assert len(doc["evidence_chunks"]) == 1
        assert doc["hrs_result"]["tier"] == "LOW"

    @pytest.mark.asyncio
    async def test_process_restart_survival_connection_cycling(self, live_mongo_database: Any) -> None:
        """Test B: Closes client pool, initializes brand-new client, and confirms trace remains durable."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        tenant_id = f"tenant_cycle_{uuid.uuid4().hex[:8]}"
        session_id = f"req_{uuid.uuid4().hex[:12]}"

        service1 = MongoTraceService()
        await service1.persist_verification_trace(
            tenant_id,
            {"session_id": session_id, "tenant_id": tenant_id, "trace_id": "tr_1", "raw_prompt": "Durable test"},
        )
        service1.close()

        # Initialize brand-new service instance simulating process restart
        service2 = MongoTraceService()
        doc = await service2.get_trace_by_session_id(tenant_id, session_id)
        assert doc is not None
        assert doc["raw_prompt"] == "Durable test"
        service2.close()

    @pytest.mark.asyncio
    async def test_index_verification(self, live_mongo_database: Any) -> None:
        """Test F: Inspects live MongoDB collection metadata, confirming all 4 indexes exist with correct specs."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        service = MongoTraceService()
        tenant_id = f"tenant_idx_{uuid.uuid4().hex[:8]}"
        session_id = f"req_{uuid.uuid4().hex[:12]}"

        await service.persist_verification_trace(
            tenant_id,
            {"session_id": session_id, "tenant_id": tenant_id, "trace_id": "tr_idx"},
        )

        coll = service.get_tenant_collection(tenant_id)
        indexes = await coll.index_information()

        # 1. session_id unique index
        assert "idx_session_id_unique" in indexes
        assert indexes["idx_session_id_unique"].get("unique") is True
        assert indexes["idx_session_id_unique"]["key"] == [("session_id", 1)]

        # 2. trace_id index
        assert "idx_trace_id" in indexes
        assert indexes["idx_trace_id"]["key"] == [("trace_id", 1)]

        # 3. created_at TTL index (90 days = 7776000s)
        assert "idx_created_at_ttl" in indexes
        assert indexes["idx_created_at_ttl"].get("expireAfterSeconds") == 7776000
        assert indexes["idx_created_at_ttl"]["key"] == [("created_at", 1)]

        # 4. created_at reverse chronological index
        assert "idx_created_at_desc" in indexes
        assert indexes["idx_created_at_desc"]["key"] == [("created_at", -1)]

    def test_verify_endpoint_rejects_with_http_503_when_mongodb_fails(self) -> None:
        """Test G: Injects MongoDB outage; proves /v1/verify aborts with HTTP 503 SERVICE_DEGRADED."""
        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_mongo_fail_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        payload = {
            "prompt": "What is the capital of Canada?",
            "response": "The capital of Canada is Ottawa.",
            "tenant_id": tenant_id,
        }

        default_session_store.clear_local_cache()
        initial_cache_count = len(default_session_store.sessions)

        simulated_mongo_error = MongoPersistenceError(
            "MongoDB persistence failed for session: ServerSelectionTimeoutError"
        )

        with (
            patch.object(
                MongoTraceService,
                "persist_verification_trace",
                side_effect=simulated_mongo_error,
            ),
            patch.object(
                PostgresPersistenceService,
                "persist_verification_transaction",
            ) as mock_pg_persist,
        ):
            response = client.post("/v1/verify", json=payload, headers=headers)

            # 1. Must return HTTP 503 SERVICE_UNAVAILABLE
            assert response.status_code == 503, f"Expected 503, got {response.status_code}: {response.text}"

            # 2. Standard error schema with SERVICE_DEGRADED
            data = response.json()
            assert "error" in data
            assert data["error"]["code"] == "SERVICE_DEGRADED"
            assert "Authoritative trace persistence is unavailable" in data["error"]["message"]

            # 3. PostgreSQL persistence must NEVER have been called
            mock_pg_persist.assert_not_called()

            # 4. In-memory session store must NOT have been updated
            assert len(default_session_store.sessions) == initial_cache_count

    @pytest.mark.asyncio
    async def test_postgres_commit_failure_triggers_compensating_mongo_delete(self, live_mongo_database: Any) -> None:
        """Test H: Best-effort rollback — PostgreSQL failure triggers compensating delete on MongoDB."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_comp_del_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        payload = {
            "prompt": "What is the atomic number of Gold?",
            "response": "The atomic number of Gold is 79.",
            "tenant_id": tenant_id,
        }

        simulated_pg_error = DefinitivePostgresPersistenceError("PostgreSQL constraint violation before commit")

        with patch.object(
            PostgresPersistenceService,
            "persist_verification_transaction",
            side_effect=simulated_pg_error,
        ):
            response = client.post("/v1/verify", json=payload, headers=headers)
            assert response.status_code == 503
            data = response.json()
            assert data["error"]["code"] == "SERVICE_DEGRADED"

        # Verify compensating delete removed the trace from MongoDB
        service = MongoTraceService()
        coll = service.get_tenant_collection(tenant_id)
        doc_count = await coll.count_documents({})
        assert doc_count == 0, f"Expected 0 documents after compensating delete, found {doc_count} orphaned traces!"

    @pytest.mark.asyncio
    async def test_ambiguous_postgres_commit_preserves_mongo_trace_and_returns_503(
        self,
        live_mongo_database: Any,
        live_postgres_database: Any,
    ) -> None:
        """Mandatory Test: Ambiguous PostgreSQL commit outcome preserves Mongo trace and returns 503."""
        if live_mongo_database is None or live_postgres_database is None:
            pytest.skip("Both live PostgreSQL and MongoDB containers required")

        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_amb_commit_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        payload = {
            "prompt": "What is the capital of Canada?",
            "response": "The capital of Canada is Ottawa.",
            "tenant_id": tenant_id,
        }

        simulated_amb_error = AmbiguousPostgresCommitError(
            "Connection reset by peer while awaiting PostgreSQL COMMIT acknowledgment"
        )

        with patch.object(
            PostgresPersistenceService,
            "persist_verification_transaction",
            side_effect=simulated_amb_error,
        ):
            response = client.post("/v1/verify", json=payload, headers=headers)

            # 1. HTTP 200 MUST NOT be returned on ambiguous commit
            assert response.status_code == 503
            data = response.json()
            assert data["error"]["code"] == "SERVICE_DEGRADED"

        # 2. Crucial Invariant: Mongo trace is NOT blindly deleted!
        # Because PostgreSQL may have committed, deleting the trace would cause permanent loss of trace data.
        service = MongoTraceService()
        coll = service.get_tenant_collection(tenant_id)
        doc_count = await coll.count_documents({})
        assert doc_count == 1, (
            "MongoDB trace MUST be preserved on ambiguous PostgreSQL commit outcome; it must NOT be blindly deleted."
        )

        trace_doc = await coll.find_one({})
        assert trace_doc is not None
        assert trace_doc["tenant_id"] == tenant_id
        session_id = trace_doc["session_id"]
        trace_id = trace_doc["trace_id"]

        # 3. Verify correlation information exists for reconciliation
        assert session_id.startswith("req_")
        assert bool(trace_id) and len(trace_id) >= 16

        # 4. Prove that a later probe/reconciliation can determine whether PostgreSQL committed
        pg_svc = PostgresPersistenceService()
        is_committed = await pg_svc.probe_session_committed(tenant_id=tenant_id, session_id=session_id)
        # In this mock simulation, the transaction did not actually commit
        assert is_committed is False

    @pytest.mark.asyncio
    async def test_compensating_delete_failure_leaves_orphan_and_returns_503(self, live_mongo_database: Any) -> None:
        """Test I (Window 5): If compensating delete also fails, HTTP 503 is returned and orphan is logged."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_fail_comp_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        payload = {
            "prompt": "Explain the Doppler effect.",
            "response": "The Doppler effect is the change in frequency of a wave in relation to an observer.",
            "tenant_id": tenant_id,
        }

        simulated_pg_error = DatabasePersistenceError("Simulated PostgreSQL write crash")
        simulated_del_error = MongoPersistenceError("Simulated MongoDB network drop during compensating delete")

        with (
            patch.object(
                PostgresPersistenceService,
                "persist_verification_transaction",
                side_effect=simulated_pg_error,
            ),
            patch.object(
                MongoTraceService,
                "delete_trace",
                side_effect=simulated_del_error,
            ),
        ):
            response = client.post("/v1/verify", json=payload, headers=headers)

            # 1. System must NEVER return HTTP 200 on an ambiguous or failed persistence outcome
            assert response.status_code == 503
            data = response.json()
            assert data["error"]["code"] == "SERVICE_DEGRADED"

        # 2. Because compensating delete failed, the document remains orphaned in MongoDB
        # proving that compensating dual-write is best-effort and does NOT provide 2PC atomicity.
        service = MongoTraceService()
        coll = service.get_tenant_collection(tenant_id)
        doc_count = await coll.count_documents({})
        assert doc_count == 1, (
            "Document should remain in MongoDB as an orphan when compensating delete fails; "
            "this orphan must be reconciled via background audit scan or MongoDB TTL expiration."
        )

    @pytest.mark.asyncio
    async def test_duplicate_session_id_retry_rejected_by_mongo_unique_index(self, live_mongo_database: Any) -> None:
        """Test J (Window 6): Duplicate session_id retry against MongoDB is rejected by unique index."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        service = MongoTraceService()
        tenant_id = f"tenant_retry_{uuid.uuid4().hex[:8]}"
        session_id = f"req_retry_{uuid.uuid4().hex[:12]}"

        trace_data: dict[str, Any] = {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "trace_id": f"trace_{uuid.uuid4().hex[:12]}",
            "model_id": "test-model",
            "raw_prompt": "First attempt",
            "raw_response": "First response",
        }

        # First insert succeeds
        s_id = await service.persist_verification_trace(tenant_id, trace_data)
        assert s_id == session_id

        # Second insert with identical session_id must raise MongoPersistenceError (DuplicateKeyError)
        with pytest.raises(MongoPersistenceError, match=r"(?i)(unique index violation|duplicate key)"):
            await service.persist_verification_trace(tenant_id, trace_data)

    @pytest.mark.asyncio
    async def test_live_dual_write_happy_path(self, live_postgres_database: Any, live_mongo_database: Any) -> None:
        """Test K: Live end-to-end verification writes to both PostgreSQL and MongoDB with matching IDs."""
        if live_postgres_database is None or live_mongo_database is None:
            pytest.skip("Both live PostgreSQL and MongoDB containers required")

        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_dual_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        prompt_text = "What is the boiling point of ethanol?"
        response_text = "The boiling point of ethanol at standard atmospheric pressure is 78.37 °C."
        payload = {
            "prompt": prompt_text,
            "response": response_text,
            "tenant_id": tenant_id,
        }

        resp = client.post("/v1/verify", json=payload, headers=headers)
        assert resp.status_code == 200
        res_data = resp.json()
        session_id = res_data["request_id"]
        trace_id = res_data["metadata"]["trace_id"]

        # 1. Verify PostgreSQL relational state
        pg_svc = PostgresPersistenceService()
        pg_sess = await pg_svc.get_session_by_id(tenant_id=tenant_id, session_id=session_id)
        assert pg_sess is not None
        assert pg_sess.tenant_id == tenant_id
        assert pg_sess.session_id == session_id
        assert pg_sess.trace_id == trace_id
        assert pg_sess.prompt_hash == hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
        assert pg_sess.response_hash == hashlib.sha256(response_text.encode("utf-8")).hexdigest()

        # 2. Verify MongoDB unstructured trace document
        mongo_svc = MongoTraceService()
        mongo_doc = await mongo_svc.get_trace_by_session_id(tenant_id=tenant_id, session_id=session_id)
        assert mongo_doc is not None
        assert mongo_doc["session_id"] == session_id
        assert mongo_doc["tenant_id"] == tenant_id
        assert mongo_doc["trace_id"] == trace_id
        assert mongo_doc["raw_prompt"] == prompt_text
        assert mongo_doc["raw_response"] == response_text
        assert "claims" in mongo_doc
        assert "evidence_chunks" in mongo_doc
        assert "hrs_result" in mongo_doc
