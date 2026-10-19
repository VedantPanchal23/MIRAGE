"""Unit tests for API Key Lifecycle Management Service."""

import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

from db.models import ApiCredential, AuditLogRecord, Tenant
from services.api_key_service import ApiKeyService
from shared.schemas.api_key import ApiKeyCreateRequest, ApiKeyRotateRequest
from shared.schemas.auth import AuthContext, Role
from shared.schemas.tenant import TenantStatus


@pytest.fixture
def tenant_admin_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        role=Role.TENANT_ADMIN,
        user_id="usr_admin_alpha",
        identity_id="id_admin_alpha",
        principal_type="user",
        token_type="jwt",
    )


@pytest.fixture
def super_admin_auth() -> AuthContext:
    return AuthContext(
        tenant_id="default_tenant",
        role=Role.SUPER_ADMIN,
        user_id="usr_super_admin",
        identity_id="id_super_admin",
        principal_type="user",
        token_type="jwt",
    )


@pytest.fixture
def viewer_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        role=Role.VIEWER,
        user_id="usr_viewer",
        identity_id="id_viewer",
        principal_type="user",
        token_type="jwt",
    )


@pytest.mark.asyncio
async def test_generate_api_key_success(tenant_admin_auth: AuthContext) -> None:
    """Generate high-entropy API key: returns raw secret once, stores only SHA-256 hash."""
    service = ApiKeyService()
    req = ApiKeyCreateRequest(
        name="Ingestion Key",
        scopes=["verify:read", "verify:write"],
        expires_in_days=30,
    )

    mock_session = AsyncMock()
    # 1. Tenant check via s.get(Tenant, target_tenant)
    active_tenant = Tenant(
        id="tenant_alpha",
        name="Tenant Alpha",
        status=TenantStatus.ACTIVE.value,
        tier="enterprise",
        created_at=datetime.now(UTC),
    )
    mock_session.get.return_value = active_tenant

    # 2. Audit record latest query
    mock_res_audit = MagicMock()
    mock_res_audit.first.return_value = None
    mock_session.execute.return_value = mock_res_audit

    added_objects: list[object] = []
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        resp = await service.create_api_key(auth=tenant_admin_auth, req=req)

        # Invariants:
        assert resp.key_secret.startswith("mirage_live_")
        assert len(resp.key_secret) > 40
        assert resp.name == "Ingestion Key"
        assert resp.scopes == ["verify:read", "verify:write"]
        assert resp.key_prefix == resp.key_secret[:16]

        # Model inspection:
        cred = next(o for o in added_objects if isinstance(o, ApiCredential))
        assert cred.name == "Ingestion Key"
        assert cred.key_prefix == resp.key_prefix
        # Database stores ONLY the SHA-256 hash
        expected_hash = hashlib.sha256(resp.key_secret.encode("utf-8")).hexdigest()
        assert cred.key_hash == expected_hash
        assert not hasattr(cred, "key_secret") or cred.__dict__.get("key_secret") is None

        # Audit event does NOT leak secret
        audit = next(o for o in added_objects if isinstance(o, AuditLogRecord))
        assert audit.event_type == "AUTH_API_KEY_CREATED"
        assert "key_secret" not in audit.event_payload
        assert audit.event_payload["key_prefix"] == resp.key_prefix


@pytest.mark.asyncio
async def test_generate_api_key_suspended_tenant_rejected(tenant_admin_auth: AuthContext) -> None:
    """Cannot generate API key for a suspended or inactive tenant."""
    service = ApiKeyService()
    req = ApiKeyCreateRequest(name="Test Key")

    mock_session = AsyncMock()
    suspended_tenant = Tenant(
        id="tenant_alpha",
        name="Tenant Alpha",
        status=TenantStatus.SUSPENDED.value,
        tier="free",
        created_at=datetime.now(UTC),
    )
    mock_session.get.return_value = suspended_tenant

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.create_api_key(auth=tenant_admin_auth, req=req)

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "inactive tenant" in exc_info.value.detail


@pytest.mark.asyncio
async def test_rotate_api_key_immediate_success(tenant_admin_auth: AuthContext) -> None:
    """Rotating API key with immediate revocation revokes old key and creates new key."""
    service = ApiKeyService()
    now = datetime.now(UTC)

    old_cred = ApiCredential(
        id="old_key_id",
        tenant_id="tenant_alpha",
        identity_id="id_admin_alpha",
        name="Primary Worker Key",
        key_prefix="mirage_live_old1",
        key_hash="oldhash123",
        scopes=["*"],
        revoked_at=None,
        created_at=now - timedelta(days=10),
    )

    mock_session = AsyncMock()
    # s.get(ApiCredential, key_id)
    mock_session.get.return_value = old_cred

    mock_res_audit = MagicMock()
    mock_res_audit.first.return_value = None
    mock_session.execute.return_value = mock_res_audit

    added_objects: list[object] = []
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        req = ApiKeyRotateRequest(immediate_revocation=True)
        resp = await service.rotate_api_key(auth=tenant_admin_auth, key_id="old_key_id", req=req)

        # Old key is immediately revoked
        assert old_cred.revoked_at is not None

        # New key is returned with secret
        assert resp.key_secret.startswith("mirage_live_")
        assert resp.id != "old_key_id"
        assert resp.name == "Primary Worker Key (Rotated)"


@pytest.mark.asyncio
async def test_rotate_api_key_grace_period_success(tenant_admin_auth: AuthContext) -> None:
    """Rotating API key with grace period bounds the old key's expiry without immediate revocation."""
    service = ApiKeyService()
    now = datetime.now(UTC)

    old_cred = ApiCredential(
        id="old_key_id",
        tenant_id="tenant_alpha",
        identity_id="id_admin_alpha",
        name="Primary Worker Key",
        key_prefix="mirage_live_old1",
        key_hash="oldhash123",
        scopes=["*"],
        expires_at=now + timedelta(days=30),
        revoked_at=None,
        created_at=now - timedelta(days=10),
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = old_cred

    mock_res_audit = MagicMock()
    mock_res_audit.first.return_value = None
    mock_session.execute.return_value = mock_res_audit
    mock_session.add = MagicMock()

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        req = ApiKeyRotateRequest(immediate_revocation=False, grace_period_seconds=3600)
        resp = await service.rotate_api_key(auth=tenant_admin_auth, key_id="old_key_id", req=req)

        # Old key is NOT revoked yet, but expires_at is bounded to grace period (~1 hr from now)
        assert old_cred.revoked_at is None
        assert old_cred.expires_at is not None
        assert old_cred.expires_at <= datetime.now(UTC) + timedelta(seconds=3610)

        # New key is returned
        assert resp.key_secret.startswith("mirage_live_")


@pytest.mark.asyncio
async def test_revoke_api_key_success(tenant_admin_auth: AuthContext) -> None:
    """Revoking an active API key sets revoked_at and logs audit event."""
    service = ApiKeyService()
    now = datetime.now(UTC)

    cred = ApiCredential(
        id="key_to_revoke",
        tenant_id="tenant_alpha",
        identity_id="id_admin_alpha",
        name="Deprecated Key",
        key_prefix="mirage_live_dep1",
        key_hash="hashdep",
        scopes=["*"],
        revoked_at=None,
        created_at=now - timedelta(days=5),
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = cred

    mock_res_audit = MagicMock()
    mock_res_audit.first.return_value = None
    mock_session.execute.return_value = mock_res_audit

    added_objects: list[object] = []
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        meta = await service.revoke_api_key(auth=tenant_admin_auth, key_id="key_to_revoke")

        assert meta.id == "key_to_revoke"
        assert meta.is_active is False
        assert cred.revoked_at is not None

        # Audit event recorded
        audit = next(o for o in added_objects if isinstance(o, AuditLogRecord))
        assert audit.event_type == "AUTH_API_KEY_REVOKED"
        assert audit.event_payload["key_id"] == "key_to_revoke"


@pytest.mark.asyncio
async def test_cross_tenant_key_access_denied(tenant_admin_auth: AuthContext) -> None:
    """Tenant Admin cannot access or revoke an API key belonging to another tenant."""
    service = ApiKeyService()
    now = datetime.now(UTC)

    other_tenant_cred = ApiCredential(
        id="foreign_key",
        tenant_id="tenant_beta",
        identity_id="id_beta",
        name="Beta Key",
        key_prefix="mirage_live_beta",
        key_hash="foreignhash",
        scopes=["*"],
        revoked_at=None,
        created_at=now,
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = other_tenant_cred

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.revoke_api_key(auth=tenant_admin_auth, key_id="foreign_key")

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert "Cross-tenant" in exc_info.value.detail
