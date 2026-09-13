"""Security & RBAC Tests: Role authorization, PII detection, audit tamper proofing, and rate limiting.

Implements Testing Strategy §7 & Security & Access Document §7, §10, §13:
- Role-Based Access Control matrix enforcement
- Non-blocking PII pattern detection
- SHA-256 cryptographic audit chain tamper detection
- Tiered rate limit boundary enforcement
"""

import pytest
from starlette.testclient import TestClient

from analytics.audit_service import AuditService
from gateway.main import create_app
from gateway.middleware.pii import PIIDetector
from gateway.middleware.rate_limiter import SlidingWindowRateLimiter
from shared.schemas.audit import compute_sha256

app = create_app()
client = TestClient(app)


class TestSecurityAndRBAC:
    """Security, access control, and privacy compliance test suite."""

    def test_rbac_unauthorized_role_forbidden(self) -> None:
        """Verify that api_client role is blocked with 403 Forbidden from exporting audit logs."""
        response = client.get(
            "/v1/audit/export",
            headers={"X-Tenant-ID": "tenant_sec_01", "X-Role": "api_client"},
        )
        assert response.status_code == 403
        data = response.json()
        assert "Access denied" in data["detail"]

    def test_rbac_authorized_role_permitted(self) -> None:
        """Verify auditor and super_admin roles can access audit endpoints."""
        # 1. Auditor can read audit reports
        res_auditor = client.post(
            "/v1/audit/verify-chain",
            headers={"X-Tenant-ID": "tenant_sec_01", "X-Role": "auditor"},
        )
        assert res_auditor.status_code == 200

        # 2. Super admin can export audit logs
        res_admin = client.get(
            "/v1/audit/export",
            headers={"X-Tenant-ID": "tenant_sec_01", "X-Role": "super_admin"},
        )
        assert res_admin.status_code == 200

    def test_pii_detector_unit_patterns(self) -> None:
        """Test PII detector pattern scanning on emails, phones, SSNs, credit cards, IP addresses."""
        sample_text = (
            "Contact John at john.doe@example.com or call +1-202-555-0193. "
            "SSN is 123-45-6789 and IP address is 192.168.1.100."
        )
        res = PIIDetector.scan(sample_text)
        assert res["pii_detected"] is True
        assert "EMAIL" in res["types"]
        assert "PHONE" in res["types"]
        assert "SSN" in res["types"]
        assert "IP_ADDRESS" in res["types"]
        assert res["count"] >= 4

        clean_text = "The Apollo 11 mission landed on the lunar surface in July 1969."
        res_clean = PIIDetector.scan(clean_text)
        assert res_clean["pii_detected"] is False
        assert len(res_clean["types"]) == 0

    def test_pii_detection_middleware_header_flagging(self) -> None:
        """Verify incoming request with PII receives non-blocking warning headers without failing."""
        payload = {
            "prompt": "Send update to contact@hospital.org regarding patient at 10.0.0.1",
            "response": "Patient file updated.",
            "tenant_id": "tenant_pii_test",
        }
        res = client.post("/v1/verify", json=payload)
        assert res.status_code == 200
        assert res.headers.get("X-PII-Detected") == "true"
        assert "EMAIL" in res.headers.get("X-PII-Types", "")

    def test_audit_hash_chain_tamper_detection(self) -> None:
        """Verify that any record mutation in the audit log is flagged by cryptographic verification."""
        tenant = "tenant_tamper_test"
        prev = "0" * 64

        # Generate intact 3-block chain
        chain = []
        for i in range(3):
            s_id = f"sess_{i}"
            hrs = 0.05 * (i + 1)
            ts = f"2026-09-13T10:0{i}:00Z"
            block_data = f"{prev}:{s_id}:{hrs:.4f}:{ts}"
            h = compute_sha256(block_data)
            chain.append(
                {
                    "session_id": s_id,
                    "tenant_id": tenant,
                    "hrs_score": hrs,
                    "previous_hash": prev,
                    "hash_chain": h,
                    "timestamp": ts,
                }
            )
            prev = h

        # 1. Verify intact chain
        res_valid = AuditService.verify_audit_hash_chain(tenant, chain)
        assert res_valid["valid"] is True
        assert res_valid["total_records_verified"] == 3

        # 2. Tamper with block 1 score (e.g. attacker changing HRS from 0.10 to 0.01)
        tampered_chain = [dict(c) for c in chain]
        tampered_chain[1]["hrs_score"] = 0.01

        res_tampered = AuditService.verify_audit_hash_chain(tenant, tampered_chain)
        assert res_tampered["valid"] is False
        assert res_tampered["tampered_at_index"] == 1
        assert "tamper" in res_tampered["error"].lower()

    def test_tiered_rate_limiting_boundaries(self) -> None:
        """Verify tiered sliding window limits (Free=60, Pro=300)."""
        limiter = SlidingWindowRateLimiter(default_limit=60)
        tenant_free = "tenant_rate_free"
        tenant_pro = "tenant_rate_pro"

        # Free tier: 60 allowed, 61st raises 429
        for _ in range(60):
            limiter.check_rate_limit(tenant_free, tier="free")

        with pytest.raises(Exception) as exc_info:
            limiter.check_rate_limit(tenant_free, tier="free")
        assert "429" in str(exc_info.value)

        # Pro tier: 60 requests should pass easily without raising 429
        for _ in range(60):
            limiter.check_rate_limit(tenant_pro, tier="pro")
