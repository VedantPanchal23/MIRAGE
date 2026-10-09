"""Phase 3 Security Tests: Gate 3 Action Assurance, Capabilities, DIFC, and Approvals."""

import uuid
from datetime import UTC, datetime

import pytest
from starlette.testclient import TestClient

from db import session as db_session
from db.models import ActionContract, ActorIdentity, AITransaction, Capability, Tenant, ToolDefinition, User
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


@pytest.mark.asyncio
async def test_action_proposed_without_capability_is_denied() -> None:
    """Security Invariant: An actor cannot execute a tool without an explicit capability grant."""
    tenant_id = f"sec_tenant_{uuid.uuid4().hex[:8]}"
    actor_sub = f"sec_actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Security Test Tenant", api_key_hash=uuid.uuid4().hex))
        await session.flush()
        session.add(
            User(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                external_subject=actor_sub,
                display_name="Sec User",
                role=Role.API_CLIENT.value,
            )
        )
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
        # Register a tool requiring "db:modify" capability
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="db_writer",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="db:modify",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        # Create an active transaction
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )

    # Actor has NO capability granted for "db:modify"
    proposal = {
        "transaction_id": txn_id,
        "tool_name": "db_writer",
        "action_type": "WRITE",
        "target_resource": "db://production_table",
        "parameters": {"row_id": 42, "new_value": "malicious"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
    }
    response = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == Decision.DENY.value
    assert data["state"] == ActionState.BLOCKED.value
    assert "Missing capability" in data["reason"]


@pytest.mark.asyncio
async def test_action_violating_capability_constraints_is_denied() -> None:
    """Security Invariant: Parameters violating scoped constraints (e.g. max_amount) are blocked."""
    tenant_id = f"sec_tenant_{uuid.uuid4().hex[:8]}"
    actor_sub = f"sec_actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Security Test Tenant", api_key_hash=uuid.uuid4().hex))
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
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="wire_transfer",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="finance:transfer",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        # Grant capability constrained to max_amount: 500
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="finance:transfer",
                resource_scope={},
                constraints={"max_amount": 500},
                max_autonomy_level=2,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )

    # Attempt to transfer 2500 (exceeding constraint of 500)
    proposal = {
        "transaction_id": txn_id,
        "tool_name": "wire_transfer",
        "action_type": "EXECUTE",
        "target_resource": "bank://account_999",
        "parameters": {"recipient": "attacker", "amount": 2500},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
    }
    response = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == Decision.DENY.value
    assert data["state"] == ActionState.BLOCKED.value
    assert "Capability constraint violation" in data["reason"]


@pytest.mark.asyncio
async def test_dangerous_triad_interlock_blocks_external_egress() -> None:
    """Security Invariant: Under DIFC, external egress is strictly blocked
    when untrusted and confidential data coexist.
    """
    tenant_id = f"sec_tenant_{uuid.uuid4().hex[:8]}"
    actor_sub = f"sec_actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Security Test Tenant", api_key_hash=uuid.uuid4().hex))
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
        # Register external egress tool
        session.add(
            ToolDefinition(
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="email_sender",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.EGRESS_EXTERNAL.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="email:send",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="email:send",
                resource_scope={},
                constraints={},
                max_autonomy_level=3,
                created_at=datetime.now(UTC),
            )
        )
        # Create transaction where TAINT_UNTRUSTED and TAINT_CONFIDENTIAL coexist (Dangerous Triad)
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[Taint.UNTRUSTED.value, Taint.CONFIDENTIAL.value],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )

    proposal = {
        "transaction_id": txn_id,
        "tool_name": "email_sender",
        "action_type": "EGRESS",
        "target_resource": "mailto:outside@evil.com",
        "parameters": {"recipient": "outside@evil.com", "body": "exfiltrated data"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
    }
    response = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == Decision.BLOCK.value
    assert data["state"] == ActionState.BLOCKED.value
    assert "Dangerous Triad Interlock" in data["reason"]


@pytest.mark.asyncio
async def test_salami_slicing_attack_triggers_approval_escalation() -> None:
    """Security Invariant: Cumulative blast radius across a sliding window prevents evasion via salami-slicing."""
    tenant_id = f"sec_tenant_{uuid.uuid4().hex[:8]}"
    actor_sub = f"sec_actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Security Test Tenant", api_key_hash=uuid.uuid4().hex))
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
        tool = ToolDefinition(
            id=f"tool_{uuid.uuid4().hex[:8]}",
            tenant_id=tenant_id,
            name="micro_transfer",
            tool_type=ToolType.NATIVE.value,
            egress_type=EgressType.INTERNAL_ISOLATED.value,
            trust_level=ToolTrustLevel.VERIFIED.value,
            required_capability="finance:micro",
            parameters_schema={"type": "object"},
            config={},
            active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(tool)
        await session.flush()
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="finance:micro",
                resource_scope={},
                constraints={},
                max_autonomy_level=3,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=10,
                taint_flags=[],
                context_sources=[],
            )
        )
        # Pre-seed multiple completed actions in the last 1 hour amounting to $950 cumulative spend
        now = datetime.now(UTC)
        for i in range(5):
            session.add(
                ActionContract(
                    id=f"act_hist_{i}_{uuid.uuid4().hex[:8]}",
                    tenant_id=tenant_id,
                    transaction_id=txn_id,
                    actor_identity_id=actor_id,
                    tool_id=tool.id,
                    tool_name="micro_transfer",
                    action_type="EXECUTE",
                    target_resource="bank://ledger",
                    parameters={"amount": 190.0},
                    normalized_parameters={"amount": 190.0},
                    parameters_hash="hash_dummy",
                    required_capability="finance:micro",
                    taint_flags=[],
                    risk_score=40,
                    blast_radius={"estimated_dollar_cost": 190.0, "target_environment": "DEV"},
                    state=ActionState.COMPLETED.value,
                    idempotency_key=f"idem_hist_{i}_{uuid.uuid4().hex[:8]}",
                    created_at=now,
                )
            )

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )

    # Next transfer of $100 would push cumulative window cost to $1050 > $1000 limit
    proposal = {
        "transaction_id": txn_id,
        "tool_name": "micro_transfer",
        "action_type": "EXECUTE",
        "target_resource": "bank://ledger",
        "parameters": {"amount": 100.0},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
        "blast_radius": {
            "target_environment": "DEV",
            "estimated_dollar_cost": 100.0,
        },
    }
    response = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == Decision.REQUIRE_APPROVAL.value
    assert data["is_salami_slice_violation"] is True
    assert "Salami-slicing threshold exceeded" in data["reason"]


@pytest.mark.asyncio
async def test_agent_cannot_self_grant_human_approvals() -> None:
    """Security Invariant: Agents / API Clients cannot self-grant human approvals. Requires SUPER_ADMIN / OPERATOR."""
    tenant_id = f"sec_tenant_{uuid.uuid4().hex[:8]}"
    actor_id = f"agent_actor_{uuid.uuid4().hex[:8]}"
    app = create_app()
    client = TestClient(app)

    # Attempt to call grant approval with API_CLIENT credentials
    client_headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_id, role=Role.API_CLIENT
    )
    grant_body = {"decision": "GRANT", "reason": "Self-authorizing high risk action"}
    response = client.post("/v1/approvals/appr_fake123/grant", json=grant_body, headers=client_headers)

    assert response.status_code == 403
    assert "Agents cannot self-grant approvals" in response.json()["detail"]


@pytest.mark.asyncio
async def test_parameter_tampering_after_approval_invalidates_execution() -> None:
    """Security Invariant: If parameters are tampered with after human sign-off, execution is rejected."""
    tenant_id = f"sec_tenant_{uuid.uuid4().hex[:8]}"
    actor_sub = f"sec_actor_{uuid.uuid4().hex[:8]}"
    actor_id = f"test_identity_{actor_sub}"
    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Security Test Tenant", api_key_hash=uuid.uuid4().hex))
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
                id=f"tool_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                name="deploy_service",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="ops:deploy",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        session.add(
            Capability(
                id=f"cap_{uuid.uuid4().hex[:8]}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="ops:deploy",
                resource_scope={},
                constraints={},
                max_autonomy_level=4,
                created_at=datetime.now(UTC),
            )
        )
        txn_id = f"txn_{uuid.uuid4().hex[:8]}"
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{uuid.uuid4().hex[:8]}",
                correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
                state="TURN_REASONING",
                max_turns=3,
                taint_flags=[],
                context_sources=[],
            )
        )

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )
    admin_headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id="admin_sec_01", role=Role.SUPER_ADMIN
    )

    # 1. Propose high risk action (blast radius target PROD, risk score > 80)
    proposal = {
        "transaction_id": txn_id,
        "tool_name": "deploy_service",
        "action_type": "EXECUTE",
        "target_resource": "k8s://production-cluster",
        "parameters": {"service": "payment-api", "version": "v1.0.1"},
        "idempotency_key": f"idem_prop_{uuid.uuid4().hex[:8]}",
        "blast_radius": {
            "target_environment": "PROD",
            "estimated_dollar_cost": 5000.0,
        },
    }
    prop_res = client.post("/v1/actions/propose", json=proposal, headers=headers)
    assert prop_res.status_code == 200
    prop_data = prop_res.json()
    assert prop_data["decision"] == Decision.REQUIRE_APPROVAL.value
    approval_id = prop_data["approval_id"]
    action_id = prop_data["action_id"]

    # 2. Admin grants approval for "payment-api:v1.0.1"
    grant_res = client.post(
        f"/v1/approvals/{approval_id}/grant",
        json={"decision": "GRANT", "reason": "Approved maintenance window"},
        headers=admin_headers,
    )
    assert grant_res.status_code == 200

    # 3. Simulate attacker tampering with parameters in the database after approval
    async with db_session.get_tenant_session(tenant_id) as session:
        from sqlalchemy import select
        res = await session.execute(select(ActionContract).where(ActionContract.id == action_id))
        contract = res.scalar_one()
        # Tamper normalized_parameters to point to malicious container
        contract.normalized_parameters = {"service": "payment-api", "version": "v999.malicious"}

    # 4. Attempt to execute the action: Parameter tamper check must reject execution
    exec_res = client.post("/v1/actions/execute", json={"action_id": action_id}, headers=headers)
    assert exec_res.status_code == 403
    assert "Parameter tampering detected" in exec_res.json()["detail"]
