"""Focused regression test verifying PostgreSQL failure semantics on /v1/verify.

Governing Specification: Technical Architecture §8.3 & §9.1, Security & Access §3.
Production Invariant:
    PostgreSQL persistence unavailable
            ↓
    authoritative persistence fails
            ↓
    DatabasePersistenceError
            ↓
    HTTP 503 SERVICE_UNAVAILABLE (code: SERVICE_DEGRADED)
            ↓
    NO successful verification response claiming persistence succeeded
            ↓
    NO authoritative data silently downgraded to memory
"""

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from analytics.store import default_session_store
from db.persistence import DatabasePersistenceError, PostgresPersistenceService
from gateway.main import create_app
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory


@pytest.mark.integration
class TestPostgresFailureSemantics:
    """Prove that PostgreSQL failure aborts verification with HTTP 503 without silent fallback."""

    def test_verify_endpoint_rejects_with_http_503_when_postgres_fails(self) -> None:
        """Verify POST /v1/verify aborts with HTTP 503 and does not write to in-memory store."""
        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_fail_test_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        payload = {
            "prompt": "What is the boiling point of water at sea level?",
            "response": "The boiling point of water at sea level is 100 degrees Celsius.",
            "tenant_id": tenant_id,
        }

        # Clear in-memory cache baseline
        default_session_store.clear_local_cache()
        initial_cache_count = len(default_session_store.sessions)

        # Inject failure at authoritative PostgreSQL persistence boundary
        simulated_db_error = DatabasePersistenceError(
            "Database persistence transaction failed: [WinError 1225] Connection refused"
        )

        with patch.object(
            PostgresPersistenceService,
            "persist_verification_transaction",
            side_effect=simulated_db_error,
        ):
            response = client.post("/v1/verify", json=payload, headers=headers)

        # 1. Must return HTTP 503 Service Unavailable (NOT HTTP 200, NOT HTTP 500)
        assert response.status_code == 503, f"Expected HTTP 503, got {response.status_code}: {response.text}"

        # 2. Must conform to standard error schema with SERVICE_DEGRADED
        data = response.json()
        assert "error" in data, f"Expected error envelope in response: {data}"
        assert data["error"]["code"] == "SERVICE_DEGRADED"
        assert "Authoritative database persistence is unavailable" in data["error"]["message"]
        assert "trace_id" in data["error"]
        assert "timestamp" in data["error"]

        # 3. Must NOT return any successful verification payload
        assert "verified_response" not in data
        assert "hrs_result" not in data
        assert "claims" not in data
        assert "metadata" not in data

        # 4. Must NOT silently downgrade to in-memory store
        assert len(default_session_store.sessions) == initial_cache_count
        _, tenant_sessions = default_session_store.list_sessions(tenant_id=tenant_id)
        assert len(tenant_sessions) == 0, "Failed session was unexpectedly written to in-memory store"

    @pytest.mark.asyncio
    async def test_verify_endpoint_succeeds_when_postgres_is_healthy(self, live_postgres_database: Any) -> None:
        """Verify POST /v1/verify succeeds with HTTP 200 when PostgreSQL is available."""
        if live_postgres_database is None:
            pytest.skip("Live PostgreSQL container not available")

        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_healthy_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        payload = {
            "prompt": "What is the speed of light in vacuum?",
            "response": "The speed of light in vacuum is approximately 299,792,458 meters per second.",
            "tenant_id": tenant_id,
        }

        response = client.post("/v1/verify", json=payload, headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "verified_response" in data
        assert "hrs_result" in data
        session_id = data["request_id"]

        # Verify session is authoritatively recorded in PostgreSQL
        svc = PostgresPersistenceService()
        db_session = await svc.get_session_by_id(tenant_id=tenant_id, session_id=session_id)
        assert db_session is not None
        assert db_session.tenant_id == tenant_id
