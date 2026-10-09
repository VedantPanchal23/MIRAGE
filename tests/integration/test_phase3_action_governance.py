"""Integration Tests for Phase 3 Gate 3 Action Assurance and Tool Governance."""

import uuid
from datetime import UTC, datetime

import pytest
from starlette.testclient import TestClient

from db import session as db_session
from db.models import ActorIdentity, AITransaction, Capability, Tenant, ToolDefinition
from gateway.main import create_app
from shared.schemas.action import (
    ActionState,
    EgressType,
    ToolTrustLevel,
    ToolType,
)
from shared.schemas.auth import Role
from shared.schemas.control_plane import Decision, Taint
from tests.auth_factory import AuthTestFactory


@pytest.fixture
def phase3_setup() -> dict[str, str]:
    """Helper fixture providing tenant and identity metadata."""
    suffix = uuid.uuid4().hex[:8]
    actor_sub = f"actor_p3_{suffix}"
    admin_sub = f"admin_p3_{suffix}"
    return {
        "tenant_id": f"p3_ten_{suffix}",
        "actor_sub": actor_sub,
        "actor_id": f"test_identity_{actor_sub}",
        "admin_sub": admin_sub,
        "admin_id": f"test_identity_{admin_sub}",
        "suffix": suffix,
    }


@pytest.mark.integration
async def test_end_to_end_action_lifecycle(phase3_setup: dict[str, str]) -> None:
    """Validate full action contract lifecycle: PROPOSE -> AUTHORIZE -> EXECUTE -> POSTCONDITIONS -> OBSERVATION."""
    tenant_id = phase3_setup["tenant_id"]
    actor_sub = phase3_setup["actor_sub"]
    actor_id = phase3_setup["actor_id"]
    suffix = phase3_setup["suffix"]

    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Phase 3 Lifecycle", api_key_hash=uuid.uuid4().hex))
        await session.flush()
        session.add(
            ActorIdentity(
                id=actor_id,
                tenant_id=tenant_id,
                subject=actor_sub,
                principal_type="USER",
                role=Role.API_CLIENT.value,
            )
        )
        await session.flush()
        # Register tool
        session.add(
            ToolDefinition(
                id=f"tool_calc_{suffix}",
                tenant_id=tenant_id,
                name="math_service",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="compute:math",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        # Grant capability
        session.add(
            Capability(
                id=f"cap_calc_{suffix}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="compute:math",
                resource_scope={},
                constraints={},
                max_autonomy_level=3,
                created_at=datetime.now(UTC),
            )
        )
        # Active transaction
        txn_id = f"txn_calc_{suffix}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_txn_{suffix}",
                correlation_id=f"corr_txn_{suffix}",
                state="TURN_REASONING",
                max_turns=5,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )

    # 1. Propose Action with valid parameters and postcondition
    proposal = {
        "transaction_id": txn_id,
        "tool_name": "math_service",
        "action_type": "EXECUTE",
        "target_resource": "compute://alu",
        "parameters": {"expression": "2 + 2"},
        "idempotency_key": f"idem_prop_{suffix}",
        "blast_radius": {"target_environment": "DEV", "estimated_dollar_cost": 0.0},
        "postconditions": [
            {
                "assertion": "STATUS_EQUALS",
                "target": "status",
                "expected_value": "ok",
            }
        ],
    }

    prop_res = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert prop_res.status_code == 200
    prop_data = prop_res.json()
    assert prop_data["decision"] == Decision.ALLOW.value
    assert prop_data["state"] == ActionState.AUTHORIZED.value
    action_id = prop_data["action_id"]

    # 2. Execute Action via Tool Proxy
    exec_res = client.post("/v1/actions/execute", json={"action_id": action_id}, headers=headers)
    assert exec_res.status_code == 200
    exec_data = exec_res.json()
    assert exec_data["state"] == ActionState.COMPLETED.value
    assert exec_data["postconditions_satisfied"] is True
    assert Taint.UNTRUSTED.value in exec_data["taints"]

    # 3. Retrieve Contract Details
    get_res = client.get(f"/v1/actions/{action_id}", headers=headers)
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["id"] == action_id
    assert get_data["state"] == ActionState.COMPLETED.value
    assert get_data["parameters_hash"] is not None
    assert get_data["observed_result"] is not None


@pytest.mark.integration
async def test_atomic_action_batch_all_or_nothing(phase3_setup: dict[str, str]) -> None:
    """Validate all-or-nothing rollback semantics in atomic action batches."""
    tenant_id = phase3_setup["tenant_id"]
    actor_sub = phase3_setup["actor_sub"]
    actor_id = phase3_setup["actor_id"]
    suffix = phase3_setup["suffix"]

    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Phase 3 Batch", api_key_hash=uuid.uuid4().hex))
        await session.flush()
        session.add(
            ActorIdentity(
                id=actor_id,
                tenant_id=tenant_id,
                subject=actor_sub,
                principal_type="USER",
                role=Role.API_CLIENT.value,
            )
        )
        await session.flush()
        # Tool 1: read_records (authorized)
        session.add(
            ToolDefinition(
                id=f"tool_read_{suffix}",
                tenant_id=tenant_id,
                name="read_records",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="records:read",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        # Tool 2: drop_table (unauthorized)
        session.add(
            ToolDefinition(
                id=f"tool_drop_{suffix}",
                tenant_id=tenant_id,
                name="drop_table",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="admin:drop",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        # Grant capability ONLY for records:read
        session.add(
            Capability(
                id=f"cap_read_{suffix}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="records:read",
                resource_scope={},
                constraints={},
                max_autonomy_level=3,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_batch_{suffix}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_txn_{suffix}",
                correlation_id=f"corr_txn_{suffix}",
                state="TURN_REASONING",
                max_turns=5,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )

    batch_payload = {
        "transaction_id": txn_id,
        "actions": [
            {
                "transaction_id": txn_id,
                "tool_name": "read_records",
                "action_type": "READ",
                "target_resource": "db://users",
                "parameters": {"limit": 10},
                "idempotency_key": f"idem_b1_{suffix}",
            },
            {
                "transaction_id": txn_id,
                "tool_name": "drop_table",
                "action_type": "DELETE",
                "target_resource": "db://users",
                "parameters": {"table": "users"},
                "idempotency_key": f"idem_b2_{suffix}",
            },
        ],
    }

    res = client.post("/v1/actions/batch", json=batch_payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["batch_decision"] == Decision.BLOCK.value
    assert "Atomic batch rejected" in data["batch_reason"]
    # Both actions must be marked BLOCKED
    for act in data["actions"]:
        assert act["state"] == ActionState.BLOCKED.value


@pytest.mark.integration
async def test_l4_human_approval_grant_and_deny_lifecycle(phase3_setup: dict[str, str]) -> None:
    """Validate full human-in-the-loop lifecycle: proposal -> pending -> grant -> execute, and deny -> blocked."""
    tenant_id = phase3_setup["tenant_id"]
    actor_sub = phase3_setup["actor_sub"]
    actor_id = phase3_setup["actor_id"]
    admin_sub = phase3_setup["admin_sub"]
    suffix = phase3_setup["suffix"]

    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Phase 3 Approval Lifecycle", api_key_hash=uuid.uuid4().hex))
        await session.flush()
        session.add(
            ActorIdentity(
                id=actor_id,
                tenant_id=tenant_id,
                subject=actor_sub,
                principal_type="USER",
                role=Role.API_CLIENT.value,
            )
        )
        await session.flush()
        session.add(
            ToolDefinition(
                id=f"tool_sec_{suffix}",
                tenant_id=tenant_id,
                name="manage_secrets",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="sec:rotate",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Capability(
                id=f"cap_sec_{suffix}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="sec:rotate",
                resource_scope={},
                constraints={},
                max_autonomy_level=4,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_sec_{suffix}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_txn_{suffix}",
                correlation_id=f"corr_txn_{suffix}",
                state="TURN_REASONING",
                max_turns=5,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )
    admin_headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=admin_sub, role=Role.SUPER_ADMIN
    )

    # 1. Propose high risk action requiring human sign-off
    prop1 = {
        "transaction_id": txn_id,
        "tool_name": "manage_secrets",
        "action_type": "WRITE",
        "target_resource": "vault://production/jwt_key",
        "parameters": {"operation": "rotate_key"},
        "idempotency_key": f"idem_p1_{suffix}",
        "blast_radius": {"target_environment": "PROD", "estimated_dollar_cost": 2500.0},
    }
    r1 = client.post("/v1/actions/propose", json=prop1, headers=headers)
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["decision"] == Decision.REQUIRE_APPROVAL.value
    assert d1["state"] == ActionState.AWAITING_APPROVAL.value
    approval_id1 = d1["approval_id"]
    action_id1 = d1["action_id"]

    # 2. Check pending approvals list
    pending_res = client.get("/v1/approvals/pending", headers=admin_headers)
    assert pending_res.status_code == 200
    pending_items = pending_res.json()
    assert any(item["id"] == approval_id1 for item in pending_items)

    # 3. Super Admin grants approval
    grant_res = client.post(
        f"/v1/approvals/{approval_id1}/grant",
        json={"decision": "GRANT", "reason": "Authorized scheduled rotation"},
        headers=admin_headers,
    )
    assert grant_res.status_code == 200
    assert grant_res.json()["status"] == "GRANTED"

    # 4. Now execution succeeds
    exec_res1 = client.post("/v1/actions/execute", json={"action_id": action_id1}, headers=headers)
    assert exec_res1.status_code == 200
    assert exec_res1.json()["state"] == ActionState.COMPLETED.value

    # 5. Propose a second high risk action and DENY it
    prop2 = {
        "transaction_id": txn_id,
        "tool_name": "manage_secrets",
        "action_type": "WRITE",
        "target_resource": "vault://production/root_key",
        "parameters": {"operation": "purge_keys"},
        "idempotency_key": f"idem_p2_{suffix}",
        "blast_radius": {"target_environment": "PROD", "estimated_dollar_cost": 9999.0},
    }
    r2 = client.post("/v1/actions/propose", json=prop2, headers=headers)
    assert r2.status_code == 200
    d2 = r2.json()
    approval_id2 = d2["approval_id"]
    action_id2 = d2["action_id"]

    deny_res = client.post(
        f"/v1/approvals/{approval_id2}/deny",
        json={"decision": "DENY", "reason": "Unapproved destructive purge"},
        headers=admin_headers,
    )
    assert deny_res.status_code == 200
    assert deny_res.json()["status"] == "DENIED"

    # Attempting to execute denied action fails with 403
    exec_res2 = client.post("/v1/actions/execute", json={"action_id": action_id2}, headers=headers)
    assert exec_res2.status_code == 403
    assert "Action contract is in state 'BLOCKED'" in exec_res2.json()["detail"]
