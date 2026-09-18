"""Security and multi-tenant isolation tests for MongoDB trace persistence.

Governing Specifications:
- Security_Access.md §1.3, §4.3, §5, §9.1
- Testing_Strategy.md §5.9, §7.1
"""

import uuid
from typing import Any

import pymongo
import pytest
from pymongo.errors import OperationFailure

from db.mongo import MongoTraceService, _validate_identifier


@pytest.mark.security
class TestMongoTenantIsolation:
    """Validate strict multi-tenant isolation and NoSQL injection resistance in MongoDB."""

    @pytest.mark.asyncio
    async def test_cross_tenant_session_idor_denied(self, live_mongo_database: Any) -> None:
        """Test C: Tenant B cannot access Tenant A's trace by session_id."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        service = MongoTraceService()
        tenant_a = f"tenant_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:8]}"
        session_id_a = f"req_{uuid.uuid4().hex[:12]}"
        trace_id_a = f"trace_{uuid.uuid4().hex[:12]}"

        # Tenant A persists a trace
        trace_data = {
            "session_id": session_id_a,
            "tenant_id": tenant_a,
            "trace_id": trace_id_a,
            "model_id": "llama-3.1-70b",
            "raw_prompt": "Confidential prompt of Tenant A",
            "raw_response": "Confidential response of Tenant A",
        }
        await service.persist_verification_trace(tenant_a, trace_data)

        # Tenant A can read its own trace
        doc_a = await service.get_trace_by_session_id(tenant_a, session_id_a)
        assert doc_a is not None
        assert doc_a["session_id"] == session_id_a
        assert doc_a["tenant_id"] == tenant_a
        assert doc_a["raw_prompt"] == "Confidential prompt of Tenant A"

        # Tenant B queries using Tenant A's session_id -> Must return None (denied/not found)
        doc_b = await service.get_trace_by_session_id(tenant_b, session_id_a)
        assert doc_b is None, "Tenant B successfully accessed Tenant A's trace via session_id IDOR!"

    @pytest.mark.asyncio
    async def test_cross_tenant_trace_idor_denied(self, live_mongo_database: Any) -> None:
        """Test D: Tenant B cannot access Tenant A's trace by distributed trace_id."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        service = MongoTraceService()
        tenant_a = f"tenant_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:8]}"
        session_id_a = f"req_{uuid.uuid4().hex[:12]}"
        trace_id_a = f"trace_{uuid.uuid4().hex[:12]}"

        trace_data = {
            "session_id": session_id_a,
            "tenant_id": tenant_a,
            "trace_id": trace_id_a,
            "model_id": "llama-3.1-70b",
            "raw_prompt": "Classified Tenant A data",
        }
        await service.persist_verification_trace(tenant_a, trace_data)

        # Tenant B queries using Tenant A's trace_id -> Must return None
        doc_b = await service.get_trace_by_trace_id(tenant_b, trace_id_a)
        assert doc_b is None, "Tenant B successfully accessed Tenant A's trace via trace_id IDOR!"

    @pytest.mark.asyncio
    async def test_tenant_namespace_physical_isolation(self, live_mongo_database: Any) -> None:
        """Test E: Verify traces are physically routed to traces_{tenant_id} collections."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        service = MongoTraceService()
        tenant_a = f"tenant_phys_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"tenant_phys_b_{uuid.uuid4().hex[:8]}"
        session_id = f"req_{uuid.uuid4().hex[:12]}"

        trace_data = {
            "session_id": session_id,
            "tenant_id": tenant_a,
            "trace_id": f"trace_{uuid.uuid4().hex[:8]}",
            "model_id": "llama-3.1-70b",
        }
        await service.persist_verification_trace(tenant_a, trace_data)

        # Inspect collections in MongoDB directly
        db = service.get_database()
        coll_a = db[f"traces_{tenant_a}"]
        coll_b = db[f"traces_{tenant_b}"]

        doc_in_a = await coll_a.find_one({"session_id": session_id})
        assert doc_in_a is not None
        assert doc_in_a["tenant_id"] == tenant_a

        # Document must NOT exist in Tenant B's collection
        doc_in_b = await coll_b.find_one({"session_id": session_id})
        assert doc_in_b is None

    def test_nosql_injection_payloads_strictly_rejected(self) -> None:
        """Test I: Verify strict scalar validator rejects NoSQL injection payloads before Motor queries."""
        # 1. Operators as dictionaries
        with pytest.raises(TypeError, match="Expected string"):
            _validate_identifier("tenant_id", {"$ne": None})  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Expected string"):
            _validate_identifier("session_id", {"$gt": ""})  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Expected string"):
            _validate_identifier("trace_id", {"$regex": ".*"})  # type: ignore[arg-type]

        # 2. Non-string types
        with pytest.raises(TypeError, match="Expected string"):
            _validate_identifier("tenant_id", 12345)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Expected string"):
            _validate_identifier("tenant_id", None)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="Expected string"):
            _validate_identifier("tenant_id", ["tenant_a", "tenant_b"])  # type: ignore[arg-type]

        # 3. Malformed strings with special characters / path traversal / SQL injection
        with pytest.raises(ValueError, match="invalid characters"):
            _validate_identifier("tenant_id", "tenant$injection")

        with pytest.raises(ValueError, match="invalid characters"):
            _validate_identifier("tenant_id", "traces.system.users")

        with pytest.raises(ValueError, match="invalid characters"):
            _validate_identifier("tenant_id", "tenant'; DROP TABLE; --")

        with pytest.raises(ValueError, match="invalid characters"):
            _validate_identifier("session_id", "req_{$gt: ''}")

        with pytest.raises(ValueError, match="cannot be empty"):
            _validate_identifier("tenant_id", "   ")

        # 4. Exceeds max length
        with pytest.raises(ValueError, match="exceeds maximum length"):
            _validate_identifier("tenant_id", "a" * 65)

        # 5. Valid alphanumeric + hyphen + underscore must pass
        valid_id = "tenant-prod_01"
        assert _validate_identifier("tenant_id", valid_id) == valid_id

    def test_least_privilege_app_user_denied_admin_access(self, live_mongo_database: Any) -> None:
        """Test J: Application user mirage_app has readWrite on mirage_traces but is DENIED on admin."""
        if live_mongo_database is None:
            pytest.skip("Live MongoDB container not available")

        app_url = getattr(live_mongo_database, "app_url", None)
        assert app_url is not None, "app_url not found on live_mongo_database fixture"

        # Connect as mirage_app
        client = pymongo.MongoClient(app_url)
        app_db = client["mirage_traces"]

        # Write to mirage_traces must SUCCEED
        test_coll = app_db["test_privilege"]
        res = test_coll.insert_one({"test": "ok"})
        assert res.inserted_id is not None
        found = test_coll.find_one({"test": "ok"})
        assert found is not None
        test_coll.drop()

        # Administrative command on admin database must be DENIED
        admin_db = client["admin"]
        with pytest.raises(OperationFailure) as exc_info:
            admin_db.command("serverStatus")

        assert "not authorized" in str(exc_info.value).lower()
        client.close()
