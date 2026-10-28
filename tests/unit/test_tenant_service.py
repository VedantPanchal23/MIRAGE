"""Unit tests for Tenant Administration and Lifecycle Service."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, status

from db.models import (
    ActorIdentity,
    ApiCredential,
    AuditLogRecord,
    Tenant,
    TenantAuditLedger,
    TenantBudgetRecord,
    User,
)
from services.tenant_service import TenantService
from shared.schemas.auth import AuthContext, Role
from shared.schemas.tenant import TenantCreateRequest, TenantStatus


@pytest.fixture
def super_admin_auth() -> AuthContext:
    return AuthContext(
        tenant_id="default_tenant",
        role=Role.SUPER_ADMIN,
        user_id="super_admin_usr",
        identity_id="id_super_admin",
        principal_type="user",
        token_type="jwt",
    )


@pytest.fixture
def tenant_admin_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        role=Role.TENANT_ADMIN,
        user_id="tenant_admin_usr",
        identity_id="id_tenant_admin",
        principal_type="user",
        token_type="jwt",
    )


@pytest.fixture
def viewer_auth() -> AuthContext:
    return AuthContext(
        tenant_id="tenant_alpha",
        role=Role.VIEWER,
        user_id="viewer_usr",
        identity_id="id_viewer",
        principal_type="user",
        token_type="jwt",
    )


@pytest.mark.asyncio
async def test_provision_tenant_super_admin_success(super_admin_auth: AuthContext) -> None:
    """Super Admin can provision a new tenant with initial actor, budget, ledger, and audit."""
    service = TenantService()
    req = TenantCreateRequest(
        name="Acme Corporation",
        tenant_id="acme_corp",
        tier="enterprise",
    )

    mock_session = AsyncMock()
    # No existing tenant for s.get(Tenant, target_id)
    mock_session.get.return_value = None

    # Latest audit query for _record_audit
    mock_res_audit = MagicMock()
    mock_res_audit.first.return_value = None
    mock_session.execute.return_value = mock_res_audit

    added_objects: list[object] = []
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        resp = await service.create_tenant(auth=super_admin_auth, req=req)

        assert resp.id == "acme_corp"
        assert resp.name == "Acme Corporation"
        assert resp.status == TenantStatus.ACTIVE
        assert resp.tier == "enterprise"

        # Verify added models: Tenant, ActorIdentity, TenantBudgetRecord, TenantAuditLedger, AuditLogRecord
        types_added = [type(o) for o in added_objects]
        assert Tenant in types_added
        assert ActorIdentity in types_added
        assert TenantBudgetRecord in types_added
        assert TenantAuditLedger in types_added
        assert AuditLogRecord in types_added


@pytest.mark.asyncio
async def test_provision_tenant_non_super_admin_rejected(tenant_admin_auth: AuthContext) -> None:
    """Non-Super Admin role cannot provision tenants."""
    service = TenantService()
    req = TenantCreateRequest(name="Acme Corporation", tenant_id="acme_corp")

    with pytest.raises(HTTPException) as exc_info:
        await service.create_tenant(auth=tenant_admin_auth, req=req)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "strictly restricted to SUPER_ADMIN" in exc_info.value.detail


@pytest.mark.asyncio
async def test_provision_duplicate_tenant_rejected(super_admin_auth: AuthContext) -> None:
    """Attempting to provision a tenant with an existing ID is rejected with 409 Conflict."""
    service = TenantService()
    req = TenantCreateRequest(name="Existing Tenant", tenant_id="existing_tenant")

    mock_session = AsyncMock()
    existing_tenant = Tenant(
        id="existing_tenant",
        name="Existing Tenant",
        tier="free",
        status=TenantStatus.ACTIVE.value,
        created_at=datetime.now(UTC),
    )
    mock_session.get.return_value = existing_tenant

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.create_tenant(auth=super_admin_auth, req=req)

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert "already exists" in exc_info.value.detail


@pytest.mark.asyncio
async def test_suspend_tenant_success(super_admin_auth: AuthContext) -> None:
    """Super Admin can suspend an active tenant with a recorded reason and audit event."""
    service = TenantService()
    target_tenant = Tenant(
        id="target_tenant",
        name="Target Tenant",
        status=TenantStatus.ACTIVE.value,
        tier="enterprise",
        scs_enabled=True,
        pii_detection_enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = target_tenant

    mock_res_audit = MagicMock()
    mock_res_audit.first.return_value = None
    mock_session.execute.return_value = mock_res_audit

    added_objects: list[object] = []
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        resp = await service.suspend_tenant(
            auth=super_admin_auth,
            tenant_id="target_tenant",
            reason="Billing delinquent",
        )

        assert resp.id == "target_tenant"
        assert resp.status == TenantStatus.SUSPENDED
        assert resp.suspension_reason == "Billing delinquent"
        assert target_tenant.status == TenantStatus.SUSPENDED.value

        # Verify audit event recorded
        audit_events = [o for o in added_objects if isinstance(o, AuditLogRecord)]
        assert len(audit_events) == 1
        assert audit_events[0].event_type == "ADMIN_TENANT_SUSPENDED"
        assert audit_events[0].event_payload["reason"] == "Billing delinquent"


@pytest.mark.asyncio
async def test_suspend_already_suspended_tenant_rejected(super_admin_auth: AuthContext) -> None:
    """Cannot suspend a tenant that is already suspended."""
    service = TenantService()
    suspended_tenant = Tenant(
        id="suspended_tenant",
        name="Suspended Tenant",
        status=TenantStatus.SUSPENDED.value,
        tier="free",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = suspended_tenant

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.suspend_tenant(auth=super_admin_auth, tenant_id="suspended_tenant", reason="test")

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert "already SUSPENDED" in exc_info.value.detail


@pytest.mark.asyncio
async def test_reactivate_suspended_tenant_success(super_admin_auth: AuthContext) -> None:
    """Super Admin can reactivate a suspended tenant."""
    service = TenantService()
    suspended_tenant = Tenant(
        id="suspended_tenant",
        name="Suspended Tenant",
        status=TenantStatus.SUSPENDED.value,
        suspension_reason="Under investigation",
        tier="free",
        scs_enabled=True,
        pii_detection_enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = suspended_tenant

    mock_res_audit = MagicMock()
    mock_res_audit.first.return_value = None
    mock_session.execute.return_value = mock_res_audit
    mock_session.add = MagicMock()

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        resp = await service.reactivate_tenant(auth=super_admin_auth, tenant_id="suspended_tenant")

        assert resp.status == TenantStatus.ACTIVE
        assert resp.suspension_reason is None
        assert suspended_tenant.status == TenantStatus.ACTIVE.value
        assert suspended_tenant.suspension_reason is None


@pytest.mark.asyncio
async def test_reactivate_active_tenant_rejected(super_admin_auth: AuthContext) -> None:
    """Cannot reactivate an already active tenant."""
    service = TenantService()
    active_tenant = Tenant(
        id="active_tenant",
        name="Active Tenant",
        status=TenantStatus.ACTIVE.value,
        tier="free",
        scs_enabled=True,
        pii_detection_enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = active_tenant

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        with pytest.raises(HTTPException) as exc_info:
            await service.reactivate_tenant(auth=super_admin_auth, tenant_id="active_tenant")

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert "is ACTIVE" in exc_info.value.detail


@pytest.mark.asyncio
async def test_offboard_tenant_success(super_admin_auth: AuthContext) -> None:
    """Super Admin can offboard a tenant, which invalidates active credentials and marks status OFFBOARDED."""
    service = TenantService()
    target_tenant = Tenant(
        id="target_tenant",
        name="Target Tenant",
        status=TenantStatus.ACTIVE.value,
        tier="free",
        scs_enabled=True,
        pii_detection_enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    mock_session = AsyncMock()
    # 1. find tenant via s.get
    mock_session.get.return_value = target_tenant

    # 2. find active credentials via s.execute
    cred1 = ApiCredential(
        id="cred_1",
        tenant_id="target_tenant",
        identity_id="id_1",
        name="Key 1",
        key_prefix="mirage_live_k1",
        key_hash="hash1",
        scopes=["*"],
        revoked_at=None,
    )
    mock_res_creds = MagicMock()
    mock_res_creds.scalars.return_value.all.return_value = [cred1]

    mock_res_audit = MagicMock()
    mock_res_audit.first.return_value = None

    def mock_exec_side_effect(stmt, *_args, **_kwargs):
        if "api_credentials" in str(stmt).lower():
            return mock_res_creds
        return mock_res_audit

    mock_session.execute.side_effect = mock_exec_side_effect
    mock_session.add = MagicMock()

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        resp = await service.offboard_tenant(auth=super_admin_auth, tenant_id="target_tenant")

        assert resp.status == TenantStatus.OFFBOARDED
        assert target_tenant.status == TenantStatus.OFFBOARDED.value
        assert cred1.revoked_at is not None


@pytest.mark.asyncio
async def test_cross_tenant_access_denied(tenant_admin_auth: AuthContext) -> None:
    """Tenant Admin cannot access metadata of another tenant."""
    service = TenantService()

    with pytest.raises(HTTPException) as exc_info:
        await service.get_tenant(auth=tenant_admin_auth, tenant_id="tenant_beta")

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert "Cross-tenant access prohibited" in exc_info.value.detail


@pytest.mark.asyncio
async def test_register_tenant_success() -> None:
    """Self-service onboarding successfully provisions tenant, user, API key, and returns credentials."""
    from shared.schemas.tenant import TenantRegistrationRequest

    service = TenantService()
    req = TenantRegistrationRequest(
        name="Nova Health AI",
        admin_email="admin@novahealth.ai",
        tenant_id="nova_health",
        tier="business",
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = None

    mock_res_audit = MagicMock()
    mock_res_audit.first.return_value = None
    mock_session.execute.return_value = mock_res_audit

    added_objects: list[object] = []
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    with patch("db.session.get_tenant_session") as mock_get_sess:
        mock_get_sess.return_value.__aenter__.return_value = mock_session

        resp = await service.register_tenant(req=req)

        assert resp.tenant_id == "nova_health"
        assert resp.name == "Nova Health AI"
        assert resp.tier == "business"
        assert resp.api_key.startswith("mirage_live_")
        assert resp.access_token is not None
        assert resp.token_type == "bearer"

        # Check all models were registered
        types_added = [type(o) for o in added_objects]
        assert Tenant in types_added
        assert User in types_added
        assert ActorIdentity in types_added
        assert ApiCredential in types_added
        assert TenantBudgetRecord in types_added
        assert TenantAuditLedger in types_added

