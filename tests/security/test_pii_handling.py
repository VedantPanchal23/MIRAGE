"""Security and integration verification of PII detection, storage, and minimization.

Governing Specifications:
- Security_Access.md §4.1, §4.3, §4.4
- Technical_Architecture.md §18
- PRD.md §FR-AUD-01

Governing Policy Verification:
1. PII detection is FLAGGING ONLY — non-blocking, non-redacting. Upstream enterprise application
   is responsible for full masking/redaction if raw PII must not leave the caller.
2. Gateway attaches security warning headers: X-PII-Detected, X-PII-Types, X-PII-Count.
3. PostgreSQL: Strictly hashes prompt and response (SHA-256). Raw PII strings are never stored in PostgreSQL.
4. MongoDB: Persists pii_metadata with types and counts only. Raw extracted PII pattern tokens are
   NEVER logged or structured into pii_metadata fields.
5. MongoDB Raw Storage: Raw prompt and response are stored as "Critical" classified data in MongoDB
   traces (subject to AES-256 encryption at rest, TLS in transit, and 90-day retention hard deletion).
"""

import hashlib
import uuid
from typing import Any

import pytest
from starlette.testclient import TestClient

from db.mongo import MongoTraceService
from db.persistence import PostgresPersistenceService
from gateway.main import create_app
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory


@pytest.mark.security
class TestPIIHandlingAndPolicyCompliance:
    """Rigorous verification of PII flagging, storage minimization, and governing policy compliance."""

    @pytest.mark.asyncio
    async def test_pii_end_to_end_governing_policy_compliance(
        self,
        live_postgres_database: Any,
        live_mongo_database: Any,
    ) -> None:
        """Verify representative PII in prompt/response across Gateway, PostgreSQL, and MongoDB."""
        if live_postgres_database is None or live_mongo_database is None:
            pytest.skip("Both live PostgreSQL and MongoDB containers required")

        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_pii_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)

        # Representative PII payload: SSN, Phone, Email, IP Address
        prompt_with_pii = "Admit patient John Doe (SSN: 123-45-6789, Phone: +1-555-867-5309) to ward 4."
        response_with_pii = (
            "Patient John Doe assigned to Dr. Smith (contact: smith@hospital.org). "
            "Telemetry monitor node IP: 192.168.1.150."
        )

        payload = {
            "prompt": prompt_with_pii,
            "response": response_with_pii,
            "tenant_id": tenant_id,
        }

        # 1. Execute verification request through Gateway
        response = client.post("/v1/verify", json=payload, headers=headers)

        # Invariant 1: Non-blocking HTTP 200 (Security_Access.md §4.3)
        # "PII detection is FLAGGING only — it adds a pii_detected: true warning to the response metadata
        # but does NOT block or redact."
        assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}: {response.text}"

        # Invariant 2: Non-blocking warning headers attached
        assert response.headers.get("X-PII-Detected") == "true"
        assert int(response.headers.get("X-PII-Count", "0")) >= 4
        detected_types_header = response.headers.get("X-PII-Types", "")
        for expected_type in ["SSN", "PHONE", "EMAIL", "IP_ADDRESS"]:
            assert expected_type in detected_types_header, f"Expected {expected_type} in {detected_types_header}"

        res_data = response.json()
        session_id = res_data["request_id"]

        # Invariant 3: Gateway does NOT mutate or redact response content
        # "Full PII masking/redaction is the responsibility of the enterprise application upstream of MIRAGE."
        assert "smith@hospital.org" in res_data["verified_response"]

        # 2. Verify PostgreSQL Authoritative Persistence Minimization
        # Security_Access.md §4.3: "By default, prompts are hashed (SHA-256) and only the hash
        # is stored in PostgreSQL for deduplication and caching."
        pg_svc = PostgresPersistenceService()
        pg_sess = await pg_svc.get_session_by_id(tenant_id=tenant_id, session_id=session_id)
        assert pg_sess is not None

        expected_prompt_hash = hashlib.sha256(prompt_with_pii.encode("utf-8")).hexdigest()
        expected_response_hash = hashlib.sha256(response_with_pii.encode("utf-8")).hexdigest()

        assert pg_sess.prompt_hash == expected_prompt_hash
        assert pg_sess.response_hash == expected_response_hash

        # 3. Verify MongoDB Trace Persistence & Metadata Handling
        # Security_Access.md §4.3: "Raw prompt text is stored only in MongoDB verification traces."
        # Security_Access.md §4.3: "PII patterns are never logged, even in encrypted MongoDB traces —
        # only the PII type and count are logged."
        mongo_svc = MongoTraceService()
        trace_doc = await mongo_svc.get_trace_by_session_id(tenant_id=tenant_id, session_id=session_id)
        assert trace_doc is not None

        pii_meta = trace_doc.get("pii_metadata", {})
        assert pii_meta.get("pii_flagged") is True
        assert pii_meta.get("total_count") >= 4
        assert set(pii_meta.get("detected_types", [])).issuperset({"SSN", "PHONE", "EMAIL", "IP_ADDRESS"})

        # Crucial Invariant: The extracted PII pattern values (e.g. "123-45-6789") are NEVER logged
        # or stored into pii_metadata fields
        assert "raw_matches" not in pii_meta
        assert "matched_values" not in pii_meta
        assert "tokens" not in pii_meta

        # Permitted Raw Storage: The full raw prompt/response is retained in MongoDB traces
        # classified as "Critical" data under Security_Access.md §4.4 (encrypted at rest, 90-day TTL)
        assert trace_doc["raw_prompt"] == prompt_with_pii
        assert trace_doc["raw_response"] == response_with_pii

    @pytest.mark.asyncio
    async def test_pii_clean_payload_reports_no_flagging(
        self,
        live_postgres_database: Any,
        live_mongo_database: Any,
    ) -> None:
        """Verify that requests without PII report pii_flagged=False across all layers."""
        if live_postgres_database is None or live_mongo_database is None:
            pytest.skip("Both live PostgreSQL and MongoDB containers required")

        app = create_app()
        client = TestClient(app)

        tenant_id = f"tenant_clean_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)

        payload = {
            "prompt": "What is the speed of light in vacuum?",
            "response": "The speed of light in vacuum is exactly 299,792,458 meters per second.",
            "tenant_id": tenant_id,
        }

        response = client.post("/v1/verify", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.headers.get("X-PII-Detected") == "false"

        res_data = response.json()
        session_id = res_data["request_id"]

        mongo_svc = MongoTraceService()
        trace_doc = await mongo_svc.get_trace_by_session_id(tenant_id=tenant_id, session_id=session_id)
        assert trace_doc is not None
        pii_meta = trace_doc.get("pii_metadata", {})
        assert pii_meta.get("pii_flagged") is False
        assert pii_meta.get("total_count") == 0
        assert pii_meta.get("detected_types") == []
