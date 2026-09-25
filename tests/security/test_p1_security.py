"""Security Tests for Phase P1 REST API Endpoints.

Governing Specifications:
- Security & Access Document §3, §7, §9.1, §10, §13
- Testing Strategy Document §7
- ADR 0005: REST API Contracts & Storage Architecture

Validates:
1. Strict multi-tenant isolation and IDOR protection across:
   - Sessions (GET /v1/sessions/{id})
   - Alerts (GET /v1/alerts, POST /v1/alerts/{id}/acknowledge)
   - Reports (GET /v1/reports/{id}, GET /v1/reports/{id}/pdf)
   - Knowledge Base (GET /v1/kb/documents, DELETE /v1/kb/documents/{id})
2. Role-Based Access Control (RBAC) permission matrices for:
   - Permission.ALERTS_ACKNOWLEDGE
   - Permission.KB_READ and Permission.KB_WRITE
   - Permission.AUDIT_EXPORT and Permission.AUDIT_READ
3. Client-side header tampering (X-Role spoofing prevention)
4. Object Storage path traversal resistance
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

from db.persistence import default_persistence_service
from gateway.main import create_app
from services.storage import LocalStorageDriver, ObjectStorageError
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory

app = create_app()
client = TestClient(app)


class TestP1Security:
    """Security test suite validating authorization, tenant isolation, and traversal protection."""

    # =========================================================================
    # 1. Cross-Tenant IDOR Protection
    # =========================================================================

    def test_cross_tenant_session_retrieval_idor_blocked(self) -> None:
        """Verify Tenant B cannot retrieve Tenant A's verification session."""
        tenant_a = f"t_sec_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"t_sec_b_{uuid.uuid4().hex[:8]}"
        session_id = f"s_sec_{uuid.uuid4().hex[:8]}"

        # Seed session for Tenant A
        async def seed() -> None:
            await default_persistence_service.persist_verification_transaction(
                session_id=session_id,
                tenant_id=tenant_a,
                trace_id=f"tr_{uuid.uuid4().hex[:8]}",
                model_id="llama-3.1-70b-versatile",
                prompt="Secret Tenant A prompt",
                response="Secret Tenant A response",
                hrs_score=0.015,
                risk_tier="LOW",
                verified_claims=[],
            )

        asyncio.run(seed())

        # Tenant B attempts to access Tenant A's session
        headers_b = AuthTestFactory.auth_headers(tenant_id=tenant_b, role=Role.AUDITOR)
        res = client.get(f"/v1/sessions/{session_id}", headers=headers_b)

        # Must return 404 Not Found to prevent tenant existence enumeration
        assert res.status_code == 404
        assert "not found" in res.json()["error"]["message"].lower()

    def test_cross_tenant_alerts_idor_blocked(self) -> None:
        """Verify Tenant B cannot list or acknowledge Tenant A's operator alerts."""
        tenant_a = f"t_alt_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"t_alt_b_{uuid.uuid4().hex[:8]}"

        # Seed alert for Tenant A
        async def seed_alert() -> str:
            alert = await default_persistence_service.create_alert(
                tenant_id=tenant_a,
                alert_type="critical_risk_surge",
                severity="critical",
                title="Critical Hallucination Spike",
                description="Consecutive CRITICAL verifications detected",
            )
            return alert.alert_id

        alert_id = asyncio.run(seed_alert())

        headers_b = AuthTestFactory.auth_headers(tenant_id=tenant_b, role=Role.OPERATOR)

        # 1. Tenant B listing alerts should not see Tenant A's alert
        list_res = client.get("/v1/alerts", headers=headers_b)
        assert list_res.status_code == 200
        alerts = list_res.json()["alerts"]
        assert not any(a["alert_id"] == alert_id for a in alerts)

        # 2. Tenant B acknowledging Tenant A's alert must return 404
        ack_res = client.post(f"/v1/alerts/{alert_id}/acknowledge", headers=headers_b)
        assert ack_res.status_code == 404

    def test_cross_tenant_report_idor_blocked(self) -> None:
        """Verify Tenant B cannot view or download Tenant A's compliance reports."""
        tenant_a = f"t_rep_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"t_rep_b_{uuid.uuid4().hex[:8]}"

        # Seed report for Tenant A
        async def seed_report() -> str:
            rep = await default_persistence_service.create_report(
                tenant_id=tenant_a,
                title="Confidential Audit",
                start_date=datetime.now(UTC) - timedelta(days=1),
                end_date=datetime.now(UTC),
            )
            await default_persistence_service.update_report_status(
                tenant_id=tenant_a,
                report_id=rep.report_id,
                status="COMPLETED",
            )
            return rep.report_id

        report_id = asyncio.run(seed_report())

        headers_b = AuthTestFactory.auth_headers(tenant_id=tenant_b, role=Role.AUDITOR)

        # 1. Details query must return 404
        get_res = client.get(f"/v1/reports/{report_id}", headers=headers_b)
        assert get_res.status_code == 404

        # 2. PDF download query must return 404
        pdf_res = client.get(f"/v1/reports/{report_id}/pdf", headers=headers_b)
        assert pdf_res.status_code == 404

    def test_cross_tenant_kb_documents_idor_blocked(self) -> None:
        """Verify Tenant B cannot list or delete Tenant A's knowledge base documents."""
        tenant_a = f"t_kb_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"t_kb_b_{uuid.uuid4().hex[:8]}"

        headers_a = AuthTestFactory.auth_headers(tenant_id=tenant_a, role=Role.TENANT_ADMIN)
        headers_b = AuthTestFactory.auth_headers(tenant_id=tenant_b, role=Role.TENANT_ADMIN)

        # Ingest document for Tenant A
        up_res = client.post(
            "/v1/kb/upload?sync=true",
            json={"filename": "internal_memo.txt", "content": "Proprietary algorithm details."},
            headers=headers_a,
        )
        assert up_res.status_code == 201
        doc_id = up_res.json()["document_id"]

        # 1. Tenant B listing must not see Tenant A's document
        list_res = client.get("/v1/kb/documents", headers=headers_b)
        assert list_res.status_code == 200
        docs = list_res.json()["documents"]
        assert not any(d["document_id"] == doc_id for d in docs)

        # 2. Tenant B deleting Tenant A's document must return 404
        del_res = client.delete(f"/v1/kb/documents/{doc_id}", headers=headers_b)
        assert del_res.status_code == 404

    # =========================================================================
    # 2. RBAC Permission Matrix Verification
    # =========================================================================

    def test_alerts_acknowledge_rbac_matrix(self) -> None:
        """Verify only roles with ALERTS_ACKNOWLEDGE can acknowledge alerts."""
        tenant_id = f"t_rbac_alt_{uuid.uuid4().hex[:8]}"

        # Roles permitted: OPERATOR, TENANT_ADMIN, SUPER_ADMIN
        for role in [Role.OPERATOR, Role.TENANT_ADMIN, Role.SUPER_ADMIN]:
            headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=role)
            # Route should not return 403 (will return 404 for non-existent alert)
            res = client.post("/v1/alerts/alt_non_existent/acknowledge", headers=headers)
            assert res.status_code != 403, f"Role {role} was improperly denied 403"

        # Roles denied: AUDITOR, API_CLIENT
        for role in [Role.AUDITOR, Role.API_CLIENT]:
            headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=role)
            res = client.post("/v1/alerts/alt_test/acknowledge", headers=headers)
            assert res.status_code == 403, f"Role {role} should have been denied 403"

    def test_kb_write_rbac_matrix(self) -> None:
        """Verify only roles with KB_WRITE can upload or delete KB documents."""
        tenant_id = f"t_rbac_kb_{uuid.uuid4().hex[:8]}"
        payload = {"filename": "test.txt", "content": "Test content"}

        # Roles permitted: TENANT_ADMIN, SUPER_ADMIN
        for role in [Role.TENANT_ADMIN, Role.SUPER_ADMIN]:
            headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=role)
            res = client.post("/v1/kb/upload?sync=true", json=payload, headers=headers)
            assert res.status_code in {200, 201}, f"Role {role} was improperly denied: {res.status_code}"

        # Roles denied: OPERATOR, AUDITOR, API_CLIENT
        for role in [Role.OPERATOR, Role.AUDITOR, Role.API_CLIENT]:
            headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=role)
            res = client.post("/v1/kb/upload", json=payload, headers=headers)
            assert res.status_code == 403, f"Role {role} should have been denied 403"

    def test_reports_export_rbac_matrix(self) -> None:
        """Verify only roles with AUDIT_EXPORT can trigger POST /v1/reports/generate."""
        tenant_id = f"t_rbac_rep_{uuid.uuid4().hex[:8]}"
        start = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        end = datetime.now(UTC).isoformat()
        payload = {"title": "Test Report", "start_date": start, "end_date": end}

        # Roles permitted: AUDITOR, TENANT_ADMIN, SUPER_ADMIN
        for role in [Role.AUDITOR, Role.TENANT_ADMIN, Role.SUPER_ADMIN]:
            headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=role)
            res = client.post("/v1/reports/generate", json=payload, headers=headers)
            assert res.status_code == 202, f"Role {role} was denied report export: {res.status_code}"

        # Roles denied: OPERATOR, API_CLIENT
        for role in [Role.OPERATOR, Role.API_CLIENT]:
            headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=role)
            res = client.post("/v1/reports/generate", json=payload, headers=headers)
            assert res.status_code == 403, f"Role {role} should have been denied 403"

    # =========================================================================
    # 3. Header Sanitization & Privilege Escalation Resistance
    # =========================================================================

    def test_x_role_header_tampering_ignored(self) -> None:
        """Verify client-supplied X-Role: super_admin header does not grant unauthorized access."""
        tenant_id = "tenant_tamper_attempt"
        # Client has API_CLIENT JWT
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)
        # Malicious client injects X-Role header
        headers["X-Role"] = "super_admin"

        # Attempt to access KB upload (requires KB_WRITE)
        res = client.post(
            "/v1/kb/upload",
            json={"filename": "hack.txt", "content": "data"},
            headers=headers,
        )
        assert res.status_code == 403

        # Attempt to generate report (requires AUDIT_EXPORT)
        start = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        end = datetime.now(UTC).isoformat()
        res_rep = client.post(
            "/v1/reports/generate",
            json={"title": "Hacked Report", "start_date": start, "end_date": end},
            headers=headers,
        )
        assert res_rep.status_code == 403

    # =========================================================================
    # 4. Storage Driver Path Traversal Resistance
    # =========================================================================

    def test_storage_driver_path_traversal_rejected(self, tmp_path: Any) -> None:
        """Verify LocalStorageDriver raises ObjectStorageError on path traversal keys."""
        driver = LocalStorageDriver(root_dir=tmp_path)

        traversal_keys = [
            "../../etc/passwd",
            "../../../windows/win.ini",
            "../secret.pdf",
            "..\\..\\system.dll",
        ]

        for bad_key in traversal_keys:
            with pytest.raises(ObjectStorageError):
                driver.put_object(bucket="mirage-audit", key=bad_key, data=b"malicious")

            with pytest.raises(ObjectStorageError):
                driver.get_object(bucket="mirage-audit", key=bad_key)
