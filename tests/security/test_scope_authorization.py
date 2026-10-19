"""Security & Regression Tests for API-Key Scope Attenuation and Least-Privilege Enforcement.

Validates:
1. AuthContext.has_permission enforces role-boundary ceiling.
2. Wildcard "*" scope cannot escalate past an identity's assigned role.
3. Unknown or malformed scopes fail closed.
4. Least-privilege default ["verify:read"] denies mutating verify:write requests.
5. Endpoints (POST /v1/verify, GET /v1/output/{id}) strictly enforce attenuated scopes.
"""

from unittest.mock import AsyncMock, patch

from starlette.testclient import TestClient

from gateway.main import create_app
from gateway.middleware.auth import register_api_key, revoke_api_key
from shared.schemas.auth import AuthContext, Permission, Role
from shared.schemas.verification import VerificationResponse


def test_auth_context_has_permission_role_ceiling() -> None:
    """An identity cannot obtain permissions outside its assigned role even with wildcard scope."""
    # API_CLIENT with wildcard scope
    ctx = AuthContext(
        tenant_id="tenant_a",
        role=Role.API_CLIENT,
        capabilities=frozenset(["*"]),
        token_type="api_key",
    )
    # API_CLIENT has verify:read and verify:write
    assert ctx.has_permission(Permission.VERIFY_READ) is True
    assert ctx.has_permission(Permission.VERIFY_WRITE) is True

    # API_CLIENT MUST NOT obtain admin/config/audit export permissions
    assert ctx.has_permission(Permission.CONFIG_WRITE) is False
    assert ctx.has_permission(Permission.AUDIT_EXPORT) is False
    assert ctx.has_permission(Permission.CIRCUITS_MANAGE) is False


def test_auth_context_has_permission_unknown_scopes_fail_closed() -> None:
    """Unknown or malicious scopes never grant any permissions."""
    ctx = AuthContext(
        tenant_id="tenant_a",
        role=Role.API_CLIENT,
        capabilities=frozenset(["admin:all", "root", "unknown:action"]),
        token_type="api_key",
    )
    assert ctx.has_permission(Permission.VERIFY_READ) is False
    assert ctx.has_permission(Permission.VERIFY_WRITE) is False
    assert ctx.has_permission(Permission.CONFIG_WRITE) is False
    assert ctx.has_permission("invalid_perm_string") is False


def test_auth_context_has_permission_scope_attenuation() -> None:
    """Read-only API key cannot execute write actions, and empty scopes deny all actions."""
    # Read-only scope
    read_only_ctx = AuthContext(
        tenant_id="tenant_a",
        role=Role.API_CLIENT,
        capabilities=frozenset(["verify:read"]),
        token_type="api_key",
    )
    assert read_only_ctx.has_permission(Permission.VERIFY_READ) is True
    assert read_only_ctx.has_permission(Permission.VERIFY_WRITE) is False

    # Write-only scope
    write_only_ctx = AuthContext(
        tenant_id="tenant_a",
        role=Role.API_CLIENT,
        capabilities=frozenset(["verify:write"]),
        token_type="api_key",
    )
    assert write_only_ctx.has_permission(Permission.VERIFY_READ) is False
    assert write_only_ctx.has_permission(Permission.VERIFY_WRITE) is True

    # Empty scopes
    empty_ctx = AuthContext(
        tenant_id="tenant_a",
        role=Role.API_CLIENT,
        capabilities=frozenset(),
        token_type="api_key",
    )
    assert empty_ctx.has_permission(Permission.VERIFY_READ) is False
    assert empty_ctx.has_permission(Permission.VERIFY_WRITE) is False


def test_verify_endpoint_denies_read_only_api_key() -> None:
    """POST /v1/verify rejects API keys with only verify:read scope with HTTP 403."""
    app = create_app()
    client = TestClient(app)

    read_key = "mirage_live_read_only_key_123"
    register_api_key(read_key, "tenant_a", role=Role.API_CLIENT, scopes=["verify:read"])

    try:
        resp = client.post(
            "/v1/verify",
            headers={"X-API-Key": read_key},
            json={
                "prompt": "What is the capital of France?",
                "response": "The capital of France is Paris.",
                "tenant_id": "tenant_a",
            },
        )
        assert resp.status_code == 403
        assert "lacks permission 'verify:write'" in resp.text
    finally:
        revoke_api_key(read_key)


def test_verify_endpoint_allows_write_scoped_api_key() -> None:
    """POST /v1/verify allows API keys that explicitly possess verify:write scope."""
    from shared.schemas.hrs import ConformalInterval, HRSResult, RiskTier, SignalAttribution
    from shared.schemas.verification import VerificationMetadata

    app = create_app()
    client = TestClient(app)

    write_key = "mirage_live_write_key_456"
    register_api_key(write_key, "tenant_a", role=Role.API_CLIENT, scopes=["verify:write"])

    mock_resp = VerificationResponse(
        request_id="req-123",
        verified_response="The capital of France is Paris.",
        original_response="The capital of France is Paris.",
        hrs_result=HRSResult(
            hrs=0.05,
            raw_score=0.04,
            tier=RiskTier.LOW,
            conformal_interval=ConformalInterval(lower=0.01, upper=0.08),
            signal_attribution=SignalAttribution(nli=0.1, scs=0.0),
            claims_count=1,
            contradicted_claims_count=0,
            computation_latency_ms=8.5,
        ),
        claims=[],
        metadata=VerificationMetadata(
            trace_id="trc-123",
            execution_time_ms=12.5,
            pipeline_signals_used=["nli", "scs"],
        ),
    )

    try:
        with patch("gateway.routes.verify.orchestrator.verify_request", new_callable=AsyncMock) as mock_verify:
            mock_verify.return_value = mock_resp
            resp = client.post(
                "/v1/verify",
                headers={"X-API-Key": write_key},
                json={
                    "prompt": "What is the capital of France?",
                    "response": "The capital of France is Paris.",
                    "tenant_id": "tenant_a",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["verified_response"] == "The capital of France is Paris."
    finally:
        revoke_api_key(write_key)
