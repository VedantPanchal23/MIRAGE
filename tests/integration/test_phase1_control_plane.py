"""Real PostgreSQL coverage for the Phase 1 identity and transaction foundation."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from db import session as db_session
from db.models import ActorIdentity, Capability, Policy, Tenant
from services.control_plane import create_transaction, transition_transaction, validate_capability
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext, Role
from shared.schemas.control_plane import (
    CapabilityValidationRequest,
    Decision,
    TransactionCreateRequest,
    TransactionState,
    TransactionTransitionRequest,
)


@pytest.mark.integration
async def test_identity_lookup_capability_and_transaction_lifecycle() -> None:
    """Persisted identity, capabilities, RLS, idempotency, and state transitions work together."""
    suffix = uuid.uuid4().hex[:10]
    tenant_id = f"phase1_{suffix}"
    identity_id = f"identity_{suffix}"
    policy_id = f"policy_{suffix}"
    capability_id = f"capability_{suffix}"
    auth = AuthContext(
        tenant_id=tenant_id,
        role=Role.API_CLIENT,
        user_id="phase1-user",
        identity_id=identity_id,
        principal_type="api_client",
        token_type="api_key",
    )

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Phase 1", api_key_hash=compute_sha256(suffix)))
        await session.flush()
        session.add(
            ActorIdentity(
                id=identity_id,
                tenant_id=tenant_id,
                subject="phase1-user",
                principal_type="api_client",
                role=Role.API_CLIENT.value,
                active=True,
            )
        )
        session.add(
            Policy(
                id=policy_id,
                tenant_id=tenant_id,
                name="allow-safe-input",
                version=1,
                rules={"effect": "ALLOW", "max_risk": 50},
                status="active",
            )
        )
        session.add(
            Capability(
                id=capability_id,
                tenant_id=tenant_id,
                identity_id=identity_id,
                capability_type="records:read",
                resource_scope={"collection": "safe"},
                constraints={},
                max_autonomy_level=1,
            )
        )

    capability = await validate_capability(
        auth,
        CapabilityValidationRequest(
            capability_id=capability_id,
            capability_type="records:read",
            resource={"collection": "safe"},
            requested_autonomy_level=1,
        ),
    )
    assert capability.decision == Decision.ALLOW

    create = TransactionCreateRequest(
        content="Summarize this untrusted customer message.",
        idempotency_key=f"idempotency-{suffix}",
        correlation_id=f"correlation-{suffix}",
        policy_id=policy_id,
        max_turns=2,
    )
    transaction = await create_transaction(auth, create)
    duplicate = await create_transaction(auth, create)
    assert duplicate.id == transaction.id
    assert transaction.state == TransactionState.PENDING
    assert "TAINT_UNTRUSTED" in {item.value for item in transaction.taints}

    analyzing = await transition_transaction(
        auth,
        transaction.id,
        TransactionTransitionRequest(
            target_state=TransactionState.ANALYZING,
            expected_version=0,
            reason="begin gate 1",
        ),
    )
    assert analyzing.version == 1
    with pytest.raises(HTTPException) as raised:
        await transition_transaction(
            auth,
            transaction.id,
            TransactionTransitionRequest(
                target_state=TransactionState.COMPLETED,
                expected_version=1,
                reason="invalid skip",
            ),
        )
    assert raised.value.status_code == 409

    async with db_session.AsyncSessionLocal() as session:
        resolved = await session.execute(
            text("SELECT * FROM mirage_resolve_jwt_identity(:subject, :tenant_id)"),
            {"subject": "phase1-user", "tenant_id": tenant_id},
        )
        assert resolved.mappings().one()["identity_id"] == identity_id


@pytest.mark.integration
async def test_revoked_or_wrong_tenant_capability_is_denied() -> None:
    """Capability identity and tenant binding fail closed."""
    suffix = uuid.uuid4().hex[:10]
    tenant_id = f"capability_{suffix}"
    identity_id = f"identity_{suffix}"
    capability_id = f"capability_{suffix}"
    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Capability", api_key_hash=compute_sha256(suffix)))
        await session.flush()
        session.add(
            ActorIdentity(
                id=identity_id, tenant_id=tenant_id, subject="subject", principal_type="api_client", role="api_client"
            )
        )
        session.add(
            Capability(
                id=capability_id,
                tenant_id=tenant_id,
                identity_id=identity_id,
                capability_type="external:send",
                resource_scope={},
                constraints={},
                max_autonomy_level=0,
                revoked_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    result = await validate_capability(
        AuthContext(tenant_id=tenant_id, role=Role.API_CLIENT, user_id="subject", identity_id=identity_id),
        CapabilityValidationRequest(capability_id=capability_id, capability_type="external:send"),
    )
    assert result.decision == Decision.DENY
