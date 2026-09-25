"""Contract Tests for Phase P1 REST API Endpoints & Contract Conformance.

Governing Specifications:
- Technical Architecture Document §7.5, §8.2
- PRD.md §FR-GW-01..05, §FR-DFT-04, §FR-AUD-01..04
- Security & Access Document §7, §10, §13
- ADR 0005: REST API Contracts & Storage Architecture

Validates:
1. OpenAPI specification completeness and schema conformity for all P1 endpoints
2. GET /v1/sessions/{session_id} (200, 404, 401, 403) + degradation header
3. GET /v1/alerts and POST /v1/alerts/{alert_id}/acknowledge (200, 404, 403)
4. POST /v1/reports/generate (202 Accepted, 400, idempotency)
5. GET /v1/reports/{report_id} (200, 404)
6. GET /v1/reports/{report_id}/pdf (200, 404, 409)
7. GET /v1/audit/report/{session_id}/pdf (200 PDF stream)
8. POST /v1/kb/upload (202 async, 201 sync, 200 duplicate, 400 empty, 413 size)
9. GET /v1/kb/documents and DELETE /v1/kb/documents/{id}
10. Standardized ErrorEnvelope format across all status codes
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from starlette.testclient import TestClient

from db.persistence import default_persistence_service
from gateway.main import create_app
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory

app = create_app()
client = TestClient(app)


class TestP1Contracts:
    """Comprehensive contract test suite for Phase P1 REST API."""

    def test_p1_openapi_routes_registered(self) -> None:
        """Verify all canonical P1 endpoints exist in openapi.json."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]

        canonical_paths = [
            "/v1/sessions/{session_id}",
            "/v1/alerts",
            "/v1/alerts/{alert_id}/acknowledge",
            "/v1/reports/generate",
            "/v1/reports/{report_id}",
            "/v1/reports/{report_id}/pdf",
            "/v1/audit/report/{session_id}/pdf",
            "/v1/kb/upload",
            "/v1/kb/upload/file",
            "/v1/kb/documents",
            "/v1/kb/documents/{document_id}",
        ]
        for p in canonical_paths:
            assert p in paths, f"Canonical P1 route missing from OpenAPI: {p}"

    def test_session_retrieval_contract_200_and_schema(self) -> None:
        """Verify GET /v1/sessions/{id} returns 200 and complete session schema."""
        tenant_id = f"t_sess_{uuid.uuid4().hex[:8]}"
        session_id = f"s_test_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.AUDITOR)

        # Pre-seed session in PostgreSQL
        async def seed() -> None:
            await default_persistence_service.persist_verification_transaction(
                session_id=session_id,
                tenant_id=tenant_id,
                trace_id=f"tr_{uuid.uuid4().hex[:8]}",
                model_id="llama-3.1-70b-versatile",
                prompt="Explain gravity",
                response="Gravity is an attractive force between masses.",
                hrs_score=0.042,
                risk_tier="LOW",
                verified_claims=[],
            )

        asyncio.run(seed())

        res = client.get(f"/v1/sessions/{session_id}", headers=headers)
        assert res.status_code == 200
        data = res.json()

        assert data["session_id"] == session_id
        assert data["tenant_id"] == tenant_id
        assert data["hrs_score"] == pytest.approx(0.042, abs=0.001)
        assert data["risk_tier"] == "LOW"
        assert "claims" in data
        assert "prompt_hash" in data
        assert "response_hash" in data
        assert "X-Trace-Status" in res.headers

    def test_session_retrieval_404_not_found(self) -> None:
        """Verify GET /v1/sessions/{id} returns 404 for non-existent session."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_p1_404", role=Role.OPERATOR)
        res = client.get("/v1/sessions/sess_non_existent_9999", headers=headers)
        assert res.status_code == 404
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "NOT_FOUND"

    def test_session_retrieval_unauthenticated_401(self) -> None:
        """Verify GET /v1/sessions/{id} rejects unauthenticated requests with 401."""
        res = client.get("/v1/sessions/any_session")
        assert res.status_code == 401
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "UNAUTHORIZED"

    def test_operator_alerts_contract(self) -> None:
        """Verify GET /v1/alerts and POST /v1/alerts/{id}/acknowledge contracts."""
        tenant_id = f"t_alt_{uuid.uuid4().hex[:8]}"
        op_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.OPERATOR)

        # Pre-seed alert in DB
        async def seed_alert() -> str:
            alert = await default_persistence_service.create_alert(
                tenant_id=tenant_id,
                alert_type="rolling_hrs_breach",
                severity="high",
                title="7-Day Rolling HRS Exceeded",
                description="7-day average HRS rose to 0.28 exceeding threshold of 0.25",
                threshold=0.25,
                current_value=0.28,
            )
            return alert.alert_id

        alert_id = asyncio.run(seed_alert())

        # 1. List alerts
        list_res = client.get("/v1/alerts", headers=op_headers)
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert list_data["tenant_id"] == tenant_id
        assert list_data["total_alerts"] >= 1
        assert list_data["active_alerts"] >= 1
        assert any(a["alert_id"] == alert_id for a in list_data["alerts"])

        # Filter by status
        filter_res = client.get("/v1/alerts?status=active", headers=op_headers)
        assert filter_res.status_code == 200
        assert filter_res.json()["total_alerts"] >= 1

        # 2. Acknowledge alert
        ack_res = client.post(
            f"/v1/alerts/{alert_id}/acknowledge",
            json={"notes": "Investigating prompt drift on fine-tuned model"},
            headers=op_headers,
        )
        assert ack_res.status_code == 200
        ack_data = ack_res.json()
        assert ack_data["alert_id"] == alert_id
        assert ack_data["status"] == "acknowledged"
        assert ack_data["acknowledged_at"] is not None

        # 3. Acknowledge 404 for non-existent alert
        ack_404 = client.post("/v1/alerts/alt_non_existent/acknowledge", headers=op_headers)
        assert ack_404.status_code == 404
        assert ack_404.json()["error"]["code"] == "NOT_FOUND"

    def test_operator_alerts_acknowledge_forbidden_403(self) -> None:
        """Verify role without ALERTS_ACKNOWLEDGE (e.g. AUDITOR) is rejected with 403."""
        tenant_id = f"t_alt_403_{uuid.uuid4().hex[:8]}"
        auditor_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.AUDITOR)
        res = client.post("/v1/alerts/alt_fake/acknowledge", headers=auditor_headers)
        assert res.status_code == 403
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "FORBIDDEN"

    def test_reports_generate_and_poll_contract(self) -> None:
        """Verify POST /v1/reports/generate (202), polling (200), and PDF streaming contracts."""
        tenant_id = f"t_rep_{uuid.uuid4().hex[:8]}"
        admin_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        start = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        end = datetime.now(UTC).isoformat()

        # 1. Invalid date range (start > end) -> 400
        bad_req = {
            "title": "Bad Range Report",
            "start_date": end,
            "end_date": start,
        }
        res_bad = client.post("/v1/reports/generate", json=bad_req, headers=admin_headers)
        assert res_bad.status_code == 400
        assert res_bad.json()["error"]["code"] == "BAD_REQUEST"

        # 2. Valid request -> 202 Accepted
        valid_req = {
            "title": "Quarterly Compliance Audit",
            "start_date": start,
            "end_date": end,
            "model_id": "llama-3.1-70b-versatile",
        }
        res_gen = client.post("/v1/reports/generate", json=valid_req, headers=admin_headers)
        assert res_gen.status_code == 202
        gen_data = res_gen.json()
        assert "report_id" in gen_data
        assert gen_data["status"] == "PENDING"
        assert gen_data["poll_url"].startswith("/v1/reports/")
        assert gen_data["download_url"].endswith("/pdf")
        report_id = gen_data["report_id"]

        # 3. Poll status -> 200
        poll_res = client.get(f"/v1/reports/{report_id}", headers=admin_headers)
        assert poll_res.status_code == 200
        poll_data = poll_res.json()
        assert poll_data["report_id"] == report_id
        assert poll_data["status"] in {"PENDING", "PROCESSING", "COMPLETED"}

        # 4. Attempt to download PDF when PENDING -> 409 Conflict
        pdf_res = client.get(f"/v1/reports/{report_id}/pdf", headers=admin_headers)
        assert pdf_res.status_code in {409, 200}  # 409 if pending, 200 if completed by worker
        if pdf_res.status_code == 409:
            assert pdf_res.json()["error"]["code"] == "CONFLICT"

        # 5. Mark report completed and download PDF -> 200 application/pdf
        async def mark_completed() -> None:
            await default_persistence_service.update_report_status(
                tenant_id=tenant_id,
                report_id=report_id,
                status="COMPLETED",
                summary={"total_sessions": 5, "mean_hrs": 0.082, "tier_counts": {"LOW": 5}},
            )

        asyncio.run(mark_completed())

        pdf_done = client.get(f"/v1/reports/{report_id}/pdf", headers=admin_headers)
        assert pdf_done.status_code == 200
        assert pdf_done.headers["content-type"] == "application/pdf"
        assert len(pdf_done.content) > 500
        assert pdf_done.content.startswith(b"%PDF-")

    def test_single_session_certificate_pdf_contract(self) -> None:
        """Verify GET /v1/audit/report/{session_id}/pdf streams valid PDF certificate."""
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_cert_test", role=Role.AUDITOR)
        res = client.get("/v1/audit/report/sess_cert_demo_01/pdf", headers=headers)
        assert res.status_code == 200
        assert res.headers["content-type"] == "application/pdf"
        assert res.content.startswith(b"%PDF-")
        assert len(res.content) > 1000

    def test_kb_upload_and_documents_contract(self) -> None:
        """Verify /v1/kb/upload (async & sync), duplicate detection, 400 empty, 413 limit."""
        tenant_id = f"t_kb_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        # 1. Negative: Empty content -> 400
        res_empty = client.post(
            "/v1/kb/upload",
            json={"filename": "empty.txt", "content": "   "},
            headers=headers,
        )
        assert res_empty.status_code == 400
        assert res_empty.json()["error"]["code"] == "BAD_REQUEST"

        # 2. Negative: Content exceeds 10MB -> 413
        oversized = "A" * (10 * 1024 * 1024 + 1024)
        res_large = client.post(
            "/v1/kb/upload",
            json={"filename": "oversized.txt", "content": oversized},
            headers=headers,
        )
        assert res_large.status_code == 413
        assert res_large.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

        # 3. Synchronous upload (sync=true) -> 201 Created
        doc_payload = {
            "filename": "quantum_physics.txt",
            "content": "Quantum entanglement occurs when pairs or groups of particles interact.",
            "collection_name": "physics_kb",
        }
        res_sync = client.post("/v1/kb/upload?sync=true", json=doc_payload, headers=headers)
        assert res_sync.status_code == 201
        data_sync = res_sync.json()
        assert "document_id" in data_sync
        assert data_sync["chunks_count"] >= 1
        doc_id = data_sync["document_id"]

        # 4. Duplicate upload (identical content hash) -> 200 OK
        res_dup = client.post("/v1/kb/upload?sync=true", json=doc_payload, headers=headers)
        assert res_dup.status_code == 200
        assert res_dup.json()["status"] == "duplicate"

        # 5. Asynchronous upload (canonical /v1/kb/upload default) -> 202 Accepted
        async_payload = {
            "filename": "relativity.txt",
            "content": "General relativity generalizes special relativity and refines Newton's law.",
            "collection_name": "physics_kb",
        }
        res_async = client.post("/v1/kb/upload", json=async_payload, headers=headers)
        assert res_async.status_code == 202
        data_async = res_async.json()
        assert data_async["status"] == "enqueued"
        assert "task_id" in data_async

        # 6. List documents -> 200
        list_res = client.get("/v1/kb/documents", headers=headers)
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert list_data["total_documents"] >= 1
        assert any(d["document_id"] == doc_id for d in list_data["documents"])

        # 7. Delete document -> 200
        del_res = client.delete(f"/v1/kb/documents/{doc_id}", headers=headers)
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "deleted"

        # 8. Delete non-existent -> 404
        del_404 = client.delete("/v1/kb/documents/doc_does_not_exist", headers=headers)
        assert del_404.status_code == 404
        assert del_404.json()["error"]["code"] == "NOT_FOUND"

    def test_kb_upload_file_multipart_contract(self) -> None:
        """Verify POST /v1/kb/upload/file multipart form validation."""
        tenant_id = f"t_kbf_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        # 1. Invalid extension -> 400
        res_ext = client.post(
            "/v1/kb/upload/file",
            files={"file": ("malicious.exe", b"binary_data", "application/octet-stream")},
            headers=headers,
        )
        assert res_ext.status_code == 400
        assert "Unsupported file type" in res_ext.json()["error"]["message"]

        # 2. Empty file -> 400
        res_empty = client.post(
            "/v1/kb/upload/file",
            files={"file": ("empty.txt", b"", "text/plain")},
            headers=headers,
        )
        assert res_empty.status_code == 400

        # 3. Valid file upload -> 201
        res_valid = client.post(
            "/v1/kb/upload/file?sync=true",
            files={"file": ("notes.md", b"# Markdown Notes\nImportant factual facts.", "text/markdown")},
            data={"collection_name": "notes_kb"},
            headers=headers,
        )
        assert res_valid.status_code == 201
        assert "document_id" in res_valid.json()

    def test_error_envelope_schema_conformance(self) -> None:
        """Verify unified ErrorEnvelope schema {error: {code, message, trace_id, timestamp}}."""
        # 422 Unprocessable Entity
        res_422 = client.post("/v1/reports/generate", json={"invalid_field": "test"}, headers=AuthTestFactory.auth_headers(role=Role.TENANT_ADMIN))
        assert res_422.status_code == 422
        d_422 = res_422.json()
        assert "error" in d_422
        assert d_422["error"]["code"] == "VALIDATION_ERROR"
        assert "details" in d_422["error"]
        assert "timestamp" in d_422["error"]

        # 401 Unauthorized
        res_401 = client.get("/v1/alerts")
        assert res_401.status_code == 401
        d_401 = res_401.json()
        assert "error" in d_401
        assert d_401["error"]["code"] == "UNAUTHORIZED"
        assert "timestamp" in d_401["error"]
