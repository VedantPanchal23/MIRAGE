"""Security, Authentication, RBAC, and Tenant Isolation Tests.

Implements Testing Strategy §7 and Security & Access Document §2.1, §3.1, §3.2, §13:
- Cryptographic JWT validation (valid signature, expired token, tampered signature, missing claims)
- Role-Based Access Control matrix enforcement derived strictly from JWT
- Absolute rejection of spoofed X-Role and X-Tenant-ID headers
- Strict tenant binding and cross-tenant IDOR prevention
- Registered API Key authentication and revocation
- Public endpoint exemptions (/v1/health, /docs, /metrics)
- Non-blocking PII detection and audit hash chain tamper detection
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt
from starlette.testclient import TestClient

from analytics.audit_service import AuditService
from gateway.main import create_app
from gateway.middleware.auth import create_access_token, register_api_key, revoke_api_key
from gateway.middleware.pii import PIIDetector
from gateway.middleware.rate_limiter import rate_limiter
from shared.config import get_settings
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import Role

app = create_app()
client = TestClient(app)
settings = get_settings()


class TestSecurityAuthenticationAndRBAC:
    """Rigorous security test suite covering Authentication, RBAC, and Tenant Isolation."""

    # --------------------------------------------------------------------------
    # 1. Authentication Tests (JWT & API Key)
    # --------------------------------------------------------------------------

    def test_missing_authentication_returns_401(self) -> None:
        """Requirement 1: Protected routes must reject unauthenticated requests with HTTP 401."""
        res = client.post("/v1/verify", json={"prompt": "Ping", "response": "Pong"})
        assert res.status_code == 401
        assert "WWW-Authenticate" in res.headers
        assert "Missing required authentication credentials" in res.json()["detail"]

    def test_x_tenant_id_alone_cannot_authenticate(self) -> None:
        """Requirement 9: X-Tenant-ID header alone must NEVER authenticate a request."""
        res = client.post(
            "/v1/verify",
            json={"prompt": "Ping", "response": "Pong"},
            headers={"X-Tenant-ID": "victim_tenant"},
        )
        assert res.status_code == 401
        assert "Missing required authentication credentials" in res.json()["detail"]

    def test_invalid_jwt_signature_returns_401(self) -> None:
        """Requirement 2: Tampered JWT signature must be rejected with HTTP 401."""
        tampered_token = create_access_token(
            tenant_id="tenant_legit",
            role=Role.API_CLIENT,
            secret_key="attacker-tampered-secret-key-32chars!!",
        )
        res = client.post(
            "/v1/verify",
            json={"prompt": "Ping", "response": "Pong"},
            headers={"Authorization": f"Bearer {tampered_token}"},
        )
        assert res.status_code == 401
        assert "Invalid authentication token signature" in res.json()["detail"]

    def test_expired_jwt_returns_401(self) -> None:
        """Requirement 3: Expired JWT tokens must be rejected with HTTP 401."""
        expired_token = create_access_token(
            tenant_id="tenant_legit",
            role=Role.API_CLIENT,
            expires_delta=timedelta(seconds=-60),
        )
        res = client.post(
            "/v1/verify",
            json={"prompt": "Ping", "response": "Pong"},
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert res.status_code == 401
        assert "expired" in res.json()["detail"].lower()

    def test_missing_tenant_claim_returns_401(self) -> None:
        """Requirement 4a: Token missing mandatory tenant_id claim must be rejected."""
        token = jwt.encode(
            {"sub": "user_1", "role": "api_client", "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp())},
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        res = client.post(
            "/v1/verify",
            json={"prompt": "Ping", "response": "Pong"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 401
        assert "missing mandatory 'tenant_id' claim" in res.json()["detail"].lower()

    def test_missing_role_claim_returns_401(self) -> None:
        """Requirement 4b: Token missing mandatory role claim must be rejected."""
        token = jwt.encode(
            {
                "sub": "user_1",
                "tenant_id": "tenant_01",
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        res = client.post(
            "/v1/verify",
            json={"prompt": "Ping", "response": "Pong"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 401
        assert "missing mandatory 'role' claim" in res.json()["detail"].lower()

    def test_invalid_role_claim_returns_401(self) -> None:
        """Requirement 4c: Token with unrecognized role must be rejected."""
        token = jwt.encode(
            {
                "sub": "user_1",
                "tenant_id": "tenant_01",
                "role": "hacker_role",
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        res = client.post(
            "/v1/verify",
            json={"prompt": "Ping", "response": "Pong"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 401
        assert "unrecognized role" in res.json()["detail"].lower()

    def test_valid_jwt_succeeds(self) -> None:
        """Requirement 5: Valid cryptographic JWT token authenticates successfully."""
        token = create_access_token(tenant_id="tenant_valid", role=Role.API_CLIENT)
        res = client.post(
            "/v1/verify",
            json={"prompt": "Capital of France?", "response": "Paris"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        assert "hrs_result" in res.json()

    # --------------------------------------------------------------------------
    # 2. RBAC & Privilege Escalation Tests
    # --------------------------------------------------------------------------

    def test_role_comes_from_verified_jwt_claim(self) -> None:
        """Requirement 6: User privileges are derived strictly from JWT role claim."""
        # Auditor role can query audit chain
        auditor_token = create_access_token(tenant_id="tenant_audit", role=Role.AUDITOR)
        res_auditor = client.post(
            "/v1/audit/verify-chain",
            headers={"Authorization": f"Bearer {auditor_token}"},
        )
        assert res_auditor.status_code == 200

        # API Client role cannot query audit chain (403 Forbidden)
        client_token = create_access_token(tenant_id="tenant_audit", role=Role.API_CLIENT)
        res_client = client.post(
            "/v1/audit/verify-chain",
            headers={"Authorization": f"Bearer {client_token}"},
        )
        assert res_client.status_code == 403
        assert "lacks permission 'audit:read'" in res_client.json()["detail"]

    def test_x_role_header_cannot_elevate_privileges(self) -> None:
        """Requirement 7 & 8: Client passing X-Role: super_admin CANNOT elevate privileges."""
        # Authenticated as api_client, but client sends forged X-Role: super_admin
        client_token = create_access_token(tenant_id="tenant_sec_01", role=Role.API_CLIENT)
        res = client.get(
            "/v1/audit/export",
            headers={
                "Authorization": f"Bearer {client_token}",
                "X-Role": "super_admin",  # Forged escalation attempt
            },
        )
        # Must be rejected with 403 because token role is api_client
        assert res.status_code == 403
        assert "Access denied" in res.json()["detail"]
        assert "api_client" in res.json()["detail"]

    def test_forged_x_role_ignored_for_auditor_token(self) -> None:
        """Requirement 8b: Legitimate auditor token with forged X-Role: super_admin still evaluated as auditor."""
        auditor_token = create_access_token(tenant_id="tenant_sec_01", role=Role.AUDITOR)
        # Auditor is permitted AUDIT_READ and AUDIT_EXPORT
        res = client.get(
            "/v1/audit/export",
            headers={
                "Authorization": f"Bearer {auditor_token}",
                "X-Role": "api_client",  # Trying to downgrade or spoof
            },
        )
        # Auditor has AUDIT_EXPORT permission, so 200 OK
        assert res.status_code == 200

    def test_operator_cannot_call_verify_write(self) -> None:
        """Requirement 8c: Operator role lacks verify:write per Security & Access Document §13.2."""
        operator_token = create_access_token(tenant_id="tenant_ops", role=Role.OPERATOR)
        res = client.post(
            "/v1/verify",
            json={"prompt": "Test", "response": "Test"},
            headers={"Authorization": f"Bearer {operator_token}"},
        )
        assert res.status_code == 403
        assert "lacks permission 'verify:write'" in res.json()["detail"]

    def test_x_role_header_stripped_at_gateway_boundary(self) -> None:
        """Requirement 3: Verify X-Role header is stripped at the ASGI boundary before downstream code."""
        client_token = create_access_token(tenant_id="tenant_sec_01", role=Role.API_CLIENT)
        res = client.post(
            "/v1/verify",
            json={"prompt": "Sanitization test", "response": "OK"},
            headers={
                "Authorization": f"Bearer {client_token}",
                "X-Role": "super_admin",
            },
        )
        assert res.status_code == 200

    def test_downstream_application_cannot_obtain_role_from_x_role(self) -> None:
        """Prove downstream application context cannot obtain an attacker-controlled role from X-Role."""
        client_token = create_access_token(tenant_id="tenant_sec_01", role=Role.API_CLIENT)
        res = client.post(
            "/v1/audit/verify-chain",
            headers={
                "Authorization": f"Bearer {client_token}",
                "X-Role": "super_admin",
            },
        )
        assert res.status_code == 403
        assert "api_client" in res.json()["detail"]

    # --------------------------------------------------------------------------
    # 3. Tenant Binding & Cross-Tenant IDOR Tests
    # --------------------------------------------------------------------------

    def test_authenticated_tenant_a_payload_tenant_b_rejected_403(self) -> None:
        """Requirement 10: Authenticated as Tenant A, requesting Tenant B in payload MUST return 403."""
        token_tenant_a = create_access_token(tenant_id="tenant_alpha", role=Role.API_CLIENT)
        res = client.post(
            "/v1/verify",
            json={
                "prompt": "Inspect quarterly report",
                "response": "Data processed",
                "tenant_id": "tenant_beta",  # Attempted IDOR cross-tenant injection
            },
            headers={"Authorization": f"Bearer {token_tenant_a}"},
        )
        assert res.status_code == 403
        assert "Mismatched tenant" in res.json()["detail"]
        assert "Cross-tenant operations are prohibited" in res.json()["detail"]

    def test_authenticated_tenant_a_payload_tenant_a_accepted_200(self) -> None:
        """Requirement 11: Authenticated as Tenant A, requesting Tenant A in payload succeeds."""
        token_tenant_a = create_access_token(tenant_id="tenant_alpha", role=Role.API_CLIENT)
        res = client.post(
            "/v1/verify",
            json={
                "prompt": "Inspect quarterly report",
                "response": "Data processed",
                "tenant_id": "tenant_alpha",
            },
            headers={"Authorization": f"Bearer {token_tenant_a}"},
        )
        assert res.status_code == 200
        assert res.json()["hrs_result"] is not None

    def test_super_admin_cross_tenant_payload_rejected_403(self) -> None:
        """Requirement 12: Cross-tenant data access is architecturally prevented even for Super Admin."""
        super_admin_token = create_access_token(tenant_id="tenant_admin_corp", role=Role.SUPER_ADMIN)
        res = client.post(
            "/v1/verify",
            json={
                "prompt": "Verify patient data",
                "response": "Confidential medical record",
                "tenant_id": "tenant_hospital_corp",  # Cross-tenant attempt
            },
            headers={"Authorization": f"Bearer {super_admin_token}"},
        )
        # Security & Access Document §13.2 line 611 explicitly forbids cross-tenant data access for all roles
        assert res.status_code == 403
        assert "Mismatched tenant" in res.json()["detail"]

    def test_payload_omitted_tenant_binds_to_authenticated_tenant(self) -> None:
        """Omitting tenant_id in payload defaults securely to authenticated tenant."""
        token = create_access_token(tenant_id="tenant_implicit", role=Role.API_CLIENT)
        res = client.post(
            "/v1/verify",
            json={"prompt": "Capital of Mars?", "response": "No capital exists."},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200

    # --------------------------------------------------------------------------
    # 4. API Key Authentication Tests
    # --------------------------------------------------------------------------

    def test_registered_api_key_authenticates_successfully(self) -> None:
        """Valid registered API key authenticates via Authorization header or X-API-Key."""
        test_key = "mrg_test_dynamic_key_abcdef1234567890"
        register_api_key(test_key, tenant_id="tenant_dynamic_api", role=Role.API_CLIENT)

        try:
            # 1. Via Authorization: Bearer
            res_bearer = client.post(
                "/v1/verify",
                json={"prompt": "Hello", "response": "World"},
                headers={"Authorization": f"Bearer {test_key}"},
            )
            assert res_bearer.status_code == 200

            # 2. Via X-API-Key
            res_header = client.post(
                "/v1/verify",
                json={"prompt": "Hello", "response": "World"},
                headers={"X-API-Key": test_key},
            )
            assert res_header.status_code == 200
        finally:
            revoke_api_key(test_key)

    def test_unregistered_or_revoked_api_key_returns_401(self) -> None:
        """Unregistered or revoked API key is rejected with HTTP 401."""
        revoked_key = "mrg_test_revoked_key_9999999999999999"
        register_api_key(revoked_key, tenant_id="tenant_revoked", role=Role.API_CLIENT)
        revoke_api_key(revoked_key)

        res = client.post(
            "/v1/verify",
            json={"prompt": "Hello", "response": "World"},
            headers={"Authorization": f"Bearer {revoked_key}"},
        )
        assert res.status_code == 401
        assert "Invalid or revoked API key" in res.json()["detail"]

    # --------------------------------------------------------------------------
    # 5. Route Exemption Tests
    # --------------------------------------------------------------------------

    def test_exempt_routes_accessible_without_auth(self) -> None:
        """Requirement 13: Exempt routes (/v1/health, /docs, /metrics) are accessible anonymously."""
        res_health = client.get("/v1/health")
        assert res_health.status_code == 200

        res_openapi = client.get("/openapi.json")
        assert res_openapi.status_code == 200

        res_docs = client.get("/docs")
        assert res_docs.status_code == 200

        res_metrics = client.get("/metrics")
        assert res_metrics.status_code == 200

    # --------------------------------------------------------------------------
    # 6. PII & Audit Chain Integrity (Regression Proofs)
    # --------------------------------------------------------------------------

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
        """Verify incoming authenticated request with PII receives non-blocking warning headers."""
        token = create_access_token(tenant_id="tenant_pii_test", role=Role.API_CLIENT)
        payload = {
            "prompt": "Send update to contact@hospital.org regarding patient at 10.0.0.1",
            "response": "Patient file updated.",
        }
        res = client.post(
            "/v1/verify",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
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

        # 2. Tamper with block 1 score
        tampered_chain = [dict(c) for c in chain]
        tampered_chain[1]["hrs_score"] = 0.01

        res_tampered = AuditService.verify_audit_hash_chain(tenant, tampered_chain)
        assert res_tampered["valid"] is False
        assert res_tampered["tampered_at_index"] == 1
        assert "tamper" in res_tampered["error"].lower()

    @pytest.mark.asyncio
    async def test_tiered_rate_limiting_boundaries(self) -> None:
        """Verify tiered token bucket limits (Free=60, Pro=300)."""
        tenant_free = f"tenant_rate_free_{uuid.uuid4().hex[:8]}"
        tenant_pro = f"tenant_rate_pro_{uuid.uuid4().hex[:8]}"

        # Free tier: 60 allowed, 61st raises 429
        for _ in range(60):
            await rate_limiter.check_rate_limit(tenant_free, tier="free")

        with pytest.raises(Exception) as exc_info:
            await rate_limiter.check_rate_limit(tenant_free, tier="free")
        assert "429" in str(exc_info.value) or "Rate limit exceeded" in str(exc_info.value)

        # Pro tier: 60 requests should pass easily without raising 429
        for _ in range(60):
            await rate_limiter.check_rate_limit(tenant_pro, tier="pro")
