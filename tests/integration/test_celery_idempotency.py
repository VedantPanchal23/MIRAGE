"""Integration tests for Celery task idempotency across PostgreSQL, MongoDB, and RabbitMQ per ADR 0003."""

import asyncio
from typing import Any

import pytest

from db.mongo import MongoDuplicateTraceError, default_mongo_trace_service
from db.persistence import default_persistence_service
from shared.schemas import VerificationRequest
from workers.orchestrator import VerificationOrchestrator
from workers.tasks import async_verify_task


class TestCeleryTaskIdempotency:
    """Validate that task retries and duplicate deliveries never corrupt database state or audit chains."""

    @pytest.mark.asyncio
    async def test_sequential_duplicate_delivery(self, live_postgres_database: Any, live_mongo_database: Any) -> None:
        """Verify sequential duplicate delivery of a task returns existing result without database duplication."""
        if live_postgres_database is None:
            pytest.skip("Live PostgreSQL container not available")
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        session_id = "sess_idemp_seq_001"
        tenant_id = "tenant_idemp_seq"
        prompt = "Is the Earth spherical?"
        response = "Yes, the Earth is approximately spherical."

        # Attempt 1: Initial execution
        res1 = async_verify_task.run(
            prompt=prompt,
            response=response,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        assert res1["session_id"] == session_id
        assert res1["idempotent_duplicate"] is False

        # Verify initial PostgreSQL persistence
        assert default_persistence_service is not None
        sess1 = await default_persistence_service.get_session_by_id(tenant_id, session_id)
        assert sess1 is not None

        # Attempt 2: Duplicate execution with same session_id
        res2 = async_verify_task.run(
            prompt=prompt,
            response=response,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        assert res2["session_id"] == session_id
        assert res2["idempotent_duplicate"] is True

        # Verify exactly ONE session exists in PostgreSQL
        _, sessions_list = await default_persistence_service.list_sessions(tenant_id=tenant_id)
        matching_sessions = [s for s in sessions_list if s["session_id"] == session_id]
        assert len(matching_sessions) == 1

        # Verify audit hash chain integrity is intact and contains exactly 1 entry
        chain_report = await default_persistence_service.verify_audit_hash_chain(tenant_id)
        assert chain_report["valid"] is True
        assert chain_report["total_records_verified"] == 1

    @pytest.mark.asyncio
    async def test_concurrent_duplicate_delivery_serialization(
        self, live_postgres_database: Any, live_mongo_database: Any
    ) -> None:
        """Verify concurrent execution of duplicate tasks is serialized safely by PostgreSQL tenant row lock."""
        if live_postgres_database is None:
            pytest.skip("Live PostgreSQL container not available")
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        session_id = "sess_idemp_conc_002"
        tenant_id = "tenant_idemp_conc"
        prompt = "What is the boiling point of water?"
        response = "The boiling point of water is 100 degrees Celsius at standard atmospheric pressure."

        req1 = VerificationRequest(
            prompt=prompt,
            response=response,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        req2 = VerificationRequest(
            prompt=prompt,
            response=response,
            tenant_id=tenant_id,
            session_id=session_id,
        )

        orch1 = VerificationOrchestrator()
        orch2 = VerificationOrchestrator()

        # Run both orchestrations concurrently
        results = await asyncio.gather(
            orch1.verify_request(req1),
            orch2.verify_request(req2),
            return_exceptions=False,
        )

        assert len(results) == 2
        assert results[0].request_id == session_id
        assert results[1].request_id == session_id

        # Verify exactly ONE session was committed to PostgreSQL
        assert default_persistence_service is not None
        _, sessions = await default_persistence_service.list_sessions(tenant_id=tenant_id)
        matching = [s for s in sessions if s["session_id"] == session_id]
        assert len(matching) == 1

        # Verify audit hash chain has exactly 1 entry and is cryptographically unbroken
        chain_report = await default_persistence_service.verify_audit_hash_chain(tenant_id)
        assert chain_report["valid"] is True
        assert chain_report["total_records_verified"] == 1

    @pytest.mark.asyncio
    async def test_mongo_trace_duplicate_protection(self, live_mongo_database: Any) -> None:
        """Verify MongoDB unique index on session_id rejects duplicate trace insertion without corruption."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        if default_mongo_trace_service is None:
            pytest.skip("Default MongoTraceService not available")

        tenant_id = "tenant_mongo_dup"
        session_id = "sess_mongo_dup_003"
        trace_data = {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "trace_id": "tr_001",
            "model_id": "model_x",
            "raw_prompt": "Hello",
            "raw_response": "World",
            "verified_response": "World",
        }

        # First insert succeeds
        res1 = await default_mongo_trace_service.persist_verification_trace(tenant_id, trace_data)
        assert res1 == session_id

        # Second insert with same session_id raises MongoDuplicateTraceError
        with pytest.raises(MongoDuplicateTraceError):
            await default_mongo_trace_service.persist_verification_trace(tenant_id, trace_data)

        # Confirm original trace is preserved
        retrieved = await default_mongo_trace_service.get_trace_by_session_id(tenant_id, session_id)
        assert retrieved is not None
        assert retrieved["session_id"] == session_id
        assert retrieved["raw_prompt"] == "Hello"
