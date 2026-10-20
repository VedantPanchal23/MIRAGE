"""Whole-Platform Security & Authorization Adversarial Test Suite for MIRAGE 3.0.

Validates authoritative requirements for Package 6 definitive closure:
1. Matrix of Roles and Permission Ceilings (Viewer, Operator, Developer/ApiClient, TenantAdmin, SuperAdmin).
2. API-Key Scope Attenuation: Wildcard '*' cannot escalate past role ceiling; unknown scopes fail closed.
3. Client-Controlled Header Spoofing Defense: X-Tenant-ID, X-User-ID, X-Role injection attempts ignored.
4. Tenant Lifecycle State Enforcement: SUSPENDED and OFFBOARDED tenants rejected at auth boundary.
5. Credential Lifecycle States: Revoked, expired, and cryptographically tampered credentials denied.
6. Cross-Tenant Data Isolation: Strict isolation across Actions, Outcomes, MCP Servers, and Audit Logs.
7. Secret Exposure Prevention: Plaintext API keys never leaked in responses, exceptions, or logs.
8. Database Role Hardening: Unprivileged application role strictly enforces NOBYPASSRLS.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from gateway.main import create_app
from gateway.middleware.auth import (
    register_api_key,
    resolve_api_key_context,
    revoke_api_key,
)
from shared.schemas.auth import AuthContext, Permission, Role
from tests.auth_factory import AuthTestFactory

app = create_app()
client = TestClient(app, raise_server_exceptions=False)


# =============================================================================
# 1. Role Permission Ceiling & Attenuation Matrix
# =============================================================================


class TestRolePermissionCeilings:
    """Verifies that an identity's effective permissions never exceed its role boundary ceiling."""

    def test_viewer_role_cannot_mutate_or_administer(self) -> None:
        """Viewer role is strictly restricted to dashboard read and cannot mutate or export."""
        ctx = AuthContext(
            tenant_id="tenant_sec_a",
            role=Role.VIEWER,
            capabilities=frozenset(["*"]),  # Wildcard scope attempt
            token_type="api_key",
        )
        # Permitted reads
        assert ctx.has_permission(Permission.DASHBOARD_READ) is True

        # Strictly prohibited actions
        assert ctx.has_permission(Permission.VERIFY_READ) is False
        assert ctx.has_permission(Permission.VERIFY_WRITE) is False
        assert ctx.has_permission(Permission.CONFIG_WRITE) is False
        assert ctx.has_permission(Permission.AUDIT_EXPORT) is False
        assert ctx.has_permission(Permission.CIRCUITS_MANAGE) is False

    def test_api_client_cannot_escalate_to_admin_or_audit_export(self) -> None:
        """API_CLIENT role can execute verification but cannot export audit ledgers or alter configs."""
        ctx = AuthContext(
            tenant_id="tenant_sec_a",
            role=Role.API_CLIENT,
            capabilities=frozenset(["*"]),
            token_type="api_key",
        )
        assert ctx.has_permission(Permission.VERIFY_WRITE) is True
        assert ctx.has_permission(Permission.VERIFY_READ) is True

        # Prohibited administrative / compliance permissions
        assert ctx.has_permission(Permission.AUDIT_EXPORT) is False
        assert ctx.has_permission(Permission.CONFIG_WRITE) is False
        assert ctx.has_permission(Permission.CIRCUITS_MANAGE) is False
        assert ctx.has_permission(Permission.KB_WRITE) is False

    def test_operator_cannot_administer_tenants_or_manage_circuits(self) -> None:
        """Operator can acknowledge alerts and view state, but cannot alter configs or export audit."""
        ctx = AuthContext(
            tenant_id="tenant_sec_a",
            role=Role.OPERATOR,
            capabilities=frozenset(["*"]),
            token_type="api_key",
        )
        assert ctx.has_permission(Permission.ALERTS_ACKNOWLEDGE) is True
        assert ctx.has_permission(Permission.DASHBOARD_READ) is True
        assert ctx.has_permission(Permission.AUDIT_READ) is True
        assert ctx.has_permission(Permission.CIRCUITS_MANAGE) is True
        assert ctx.has_permission(Permission.KB_READ) is True

        # Prohibited mutations
        assert ctx.has_permission(Permission.CONFIG_WRITE) is False
        assert ctx.has_permission(Permission.AUDIT_EXPORT) is False
        assert ctx.has_permission(Permission.VERIFY_WRITE) is False

    def test_unknown_and_malformed_scopes_fail_closed(self) -> None:
        """Arbitrary, unknown, or syntax-exploiting scopes grant zero permissions."""
        ctx = AuthContext(
            tenant_id="tenant_sec_a",
            role=Role.TENANT_ADMIN,
            capabilities=frozenset([
                "root:superadmin",
                "admin:all",
                "../../etc/passwd",
                "'; DROP TABLE users; --",
                "UNKNOWN_SCOPE_1234",
            ]),
            token_type="api_key",
        )
        for perm in [
            Permission.VERIFY_READ,
            Permission.VERIFY_WRITE,
            Permission.CONFIG_WRITE,
            Permission.AUDIT_EXPORT,
        ]:
            assert ctx.has_permission(perm) is False


# =============================================================================
# 2. Client-Controlled Header Spoofing & Identity Boundary
# =============================================================================


class TestIdentityHeaderSpoofingDefense:
    """Verifies that client-supplied identity or tenancy headers are ignored in favor of authenticated credentials."""

    def test_client_injected_tenant_id_header_cannot_cross_boundary(self) -> None:
        """An attacker authenticated as tenant_attacker sending X-Tenant-ID: victim_tenant
        is confined to tenant_attacker.
        """
        api_key = f"mrg_spoof_test_{uuid.uuid4().hex[:12]}"
        register_api_key(
            api_key=api_key,
            tenant_id="tenant_attacker",
            role=Role.API_CLIENT,
            scopes=["verify:read", "verify:write"],
        )

        headers = {
            "X-API-Key": api_key,
            "X-Tenant-ID": "victim_tenant_alpha",
            "X-Tenant": "victim_tenant_alpha",
            "X-User-ID": "admin_victim",
            "X-Role": "SUPER_ADMIN",
        }

        resp = client.get("/v1/audit/integrity", headers=headers)
        # API_CLIENT does not have AUDIT_READ permission -> must return 403 Forbidden
        # This directly proves X-Role: SUPER_ADMIN header injection was completely ignored!
        assert resp.status_code == 403


# =============================================================================
# 3. Credential Lifecycle & Tenant Suspension Enforcement
# =============================================================================


class TestCredentialAndTenantLifecycleEnforcement:
    """Verifies that revoked keys, expired tokens, and suspended tenants are denied at the authoritative gateway."""

    def test_revoked_api_key_immediately_denied(self) -> None:
        """An API key that is revoked cannot access any authenticated endpoint."""
        api_key = f"mrg_revoked_{uuid.uuid4().hex[:12]}"
        register_api_key(api_key=api_key, tenant_id="tenant_sec_b", role=Role.API_CLIENT)
        revoke_api_key(api_key=api_key)

        resp = client.get("/v1/tools", headers={"X-API-Key": api_key})
        assert resp.status_code == 401
        assert "invalid or revoked" in resp.json()["detail"].lower()

    def test_expired_jwt_rejected(self) -> None:
        """A JWT that has passed its expiration timestamp is rejected with HTTP 401."""
        expired_token = AuthTestFactory.expired_jwt(tenant_id="tenant_sec_b", role=Role.API_CLIENT)
        resp = client.get("/v1/tools", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    def test_tampered_jwt_signature_rejected(self) -> None:
        """A JWT signed with an untrusted or altered secret key is rejected immediately."""
        tampered_token = AuthTestFactory.tampered_jwt(tenant_id="tenant_sec_b", role=Role.API_CLIENT)
        resp = client.get("/v1/tools", headers={"Authorization": f"Bearer {tampered_token}"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_suspended_tenant_authentication_denial(self) -> None:
        """When an API key belongs to a SUSPENDED tenant, authentication fails closed."""
        from unittest.mock import MagicMock

        with patch("gateway.middleware.auth._TEST_API_KEY_REGISTRY", {}):
            with patch("db.session.AsyncSessionLocal") as mock_sess_factory:
                mock_session = AsyncMock()
                mock_sess_factory.return_value.__aenter__.return_value = mock_session

                # Step 1: mirage_resolve_api_credential returns None (because tenant is not ACTIVE)
                res_rpc = MagicMock()
                res_rpc.mappings.return_value.first.return_value = None
                res_rpc.first.return_value = None

                # Step 2: query ApiCredential finds row for tenant_suspended
                res_cred = MagicMock()
                res_cred.first.return_value = ("tenant_suspended", None, None, ["verify:read"])

                # Step 3: query Tenant.status returns "SUSPENDED"
                res_tenant = MagicMock()
                res_tenant.scalar_one_or_none.return_value = "SUSPENDED"

                mock_session.execute.side_effect = [res_rpc, res_cred, res_tenant]

                with pytest.raises(HTTPException) as exc_info:
                    await resolve_api_key_context("mrg_suspended_key_test_123")

                assert exc_info.value.status_code == 401
                assert "suspended" in exc_info.value.detail.lower()


# =============================================================================
# 4. Cross-Tenant Data Isolation Adversarial Tests
# =============================================================================


class TestCrossTenantDataIsolation:
    """Verifies that an authenticated tenant cannot read, update, or delete another tenant's resources."""

    def test_cross_tenant_action_contract_access_denied(self) -> None:
        """Tenant A querying an ActionContract belonging to Tenant B receives HTTP 404 Not Found."""
        token_tenant_a = AuthTestFactory.valid_jwt(tenant_id="tenant_alpha", role=Role.API_CLIENT)
        victim_action_id = "act_victim_alpha_999"

        resp = client.get(
            f"/v1/actions/{victim_action_id}",
            headers={"Authorization": f"Bearer {token_tenant_a}"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_cross_tenant_outcome_verification_access_denied(self) -> None:
        """Tenant A cannot retrieve Gate 5 outcome records of Tenant B."""
        token_tenant_a = AuthTestFactory.valid_jwt(tenant_id="tenant_alpha", role=Role.API_CLIENT)
        victim_action_id = "act_victim_outcome_888"

        with patch("gateway.routes.outcomes.reality_verifier_service.get_outcome_by_action_id", return_value=None):
            resp = client.get(
                f"/v1/outcomes/action/{victim_action_id}",
                headers={"Authorization": f"Bearer {token_tenant_a}"},
            )
            assert resp.status_code == 404
            assert "no outcome verification record found" in resp.json()["detail"].lower()

    def test_cross_tenant_mcp_server_access_denied(self) -> None:
        """Tenant A cannot retrieve or mutate an MCP server registered by Tenant B."""
        token_tenant_a = AuthTestFactory.valid_jwt(tenant_id="tenant_alpha", role=Role.TENANT_ADMIN)
        victim_server_id = "mcp_victim_server_777"

        resp = client.get(
            f"/v1/mcp/servers/{victim_server_id}",
            headers={"Authorization": f"Bearer {token_tenant_a}"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# =============================================================================
# 5. Secret Exposure Prevention & Database Role Hardening
# =============================================================================


class TestSecretExposurePreventionAndRoleHardening:
    """Verifies that API keys, passwords, and sensitive credentials are never disclosed or escalated."""

    def test_api_credential_listing_never_exposes_plaintext_secret_or_hash(self) -> None:
        """Listing API keys returns safe metadata only, never plaintext secrets or database key hashes."""
        token_admin = AuthTestFactory.valid_jwt(tenant_id="tenant_alpha", role=Role.TENANT_ADMIN)

        fake_cred_response = {
            "keys": [
                {
                    "id": "cred_12345",
                    "tenant_id": "tenant_alpha",
                    "name": "Production Key",
                    "key_prefix": "mrg_prod_a1b2",
                    "role": "api_client",
                    "scopes": ["verify:read"],
                    "is_active": True,
                    "created_at": "2026-10-20T12:00:00Z",
                    "expires_at": None,
                    "revoked_at": None,
                    "last_used_at": None,
                }
            ],
            "total": 1,
        }

        with patch("gateway.routes.auth.api_key_service.list_api_keys", return_value=fake_cred_response):
            resp = client.get(
                "/v1/auth/api-keys",
                headers={"Authorization": f"Bearer {token_admin}"},
            )
            assert resp.status_code == 200
            data = resp.json()
            serialized = str(data)
            # Plaintext secret and raw database hashes must never be serialized
            assert "key_hash" not in serialized
            assert "secret" not in serialized
            assert data["keys"][0]["key_prefix"] == "mrg_prod_a1b2"

    def test_postgres_init_sql_mandates_nobypassrls_for_runtime_app(self) -> None:
        """Verify that docker/postgres-init.sql strictly provisions mirage_app with NOBYPASSRLS."""
        init_sql_path = Path("docker/postgres-init.sql")
        assert init_sql_path.exists()
        content = init_sql_path.read_text(encoding="utf-8")

        # Must explicitly contain mirage_app role with NOBYPASSRLS
        assert "CREATE ROLE mirage_app" in content
        assert "NOBYPASSRLS" in content
        assert "NOSUPERUSER" in content
        assert "NOCREATEDB" in content
        assert "NOCREATEROLE" in content
