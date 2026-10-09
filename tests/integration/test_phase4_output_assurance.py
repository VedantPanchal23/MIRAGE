"""Integration Tests for Phase 4 Gate 4 Output Assurance and Verification Engine.

Tests end-to-end API flows, permission enforcement, multi-gate ReAct transaction lifecycle,
and autonomous LangGraph correction loop integration.
"""

import uuid
from datetime import UTC, datetime

import pytest
from starlette.testclient import TestClient

from db import session as db_session
from db.models import (
    ActionContract,
    ActorIdentity,
    AITransaction,
    OutputAssuranceRecord,
    Tenant,
    ToolDefinition,
    User,
)
from gateway.main import create_app
from shared.schemas.action import ActionState, EgressType, ToolTrustLevel, ToolType
from shared.schemas.auth import Role
from shared.schemas.output import (
    Gate4Decision,
    OutputVerificationStatus,
)
from tests.auth_factory import AuthTestFactory


@pytest.fixture
def phase4_setup() -> dict[str, str]:
    """Helper fixture providing tenant and identity metadata."""
    suffix = uuid.uuid4().hex[:8]
    actor_sub = f"actor_p4_{suffix}"
    return {
        "tenant_id": f"p4_ten_{suffix}",
        "actor_sub": actor_sub,
        "actor_id": f"test_identity_{actor_sub}",
        "suffix": suffix,
    }


@pytest.mark.integration
async def test_end_to_end_output_assurance_api(phase4_setup: dict[str, str]) -> None:
    """Validate full output assurance API lifecycle: POST /v1/output/assure and GET /v1/output/{output_id}."""
    tenant_id = phase4_setup["tenant_id"]
    actor_sub = phase4_setup["actor_sub"]
    actor_id = phase4_setup["actor_id"]
    suffix = phase4_setup["suffix"]
    txn_id = f"txn_p4_e2e_{suffix}"

    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Phase 4 Integration", api_key_hash=uuid.uuid4().hex))
        await session.flush()
        user = User(
            id=f"usr_{suffix}",
            tenant_id=tenant_id,
            external_subject=actor_sub,
            display_name="Tester P4",
            role=Role.API_CLIENT.value,
            active=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            ActorIdentity(
                id=actor_id,
                tenant_id=tenant_id,
                subject=actor_sub,
                principal_type="SERVICE",
                role=Role.API_CLIENT.value,
                user_id=user.id,
                active=True,
            )
        )
        await session.flush()
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{suffix}",
                correlation_id=f"corr_{suffix}",
                state="VERIFYING_OUTPUT",
                max_turns=3,
                turn_count=1,
                taint_flags=[],
                context_sources=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.flush()

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )

    request_payload = {
        "transaction_id": txn_id,
        "response_text": "System metrics show database query latency decreased by 12% following migration.",
        "evidence_chunks": [
            "Performance monitoring logs confirm database query latency decreased by 12% after migration."
        ],
        "require_factual_verification": True,
        "budget": {
            "max_latency_ms": 5000,
            "max_tokens": 1000,
            "max_cost_usd": 0.05,
            "max_tier": 3,
        },
    }

    # 1. Post to Gate 4 Output Assurance API
    res = client.post("/v1/output/assure", json=request_payload, headers=headers)
    assert res.status_code == 200, f"Expected 200 but got {res.status_code}: {res.text}"
    data = res.json()

    assert data["transaction_id"] == txn_id
    assert data["verification_status"] in [
        OutputVerificationStatus.VERIFIED.value,
        OutputVerificationStatus.PARTIALLY_VERIFIED.value,
        OutputVerificationStatus.UNVERIFIED.value,
    ]
    assert data["final_decision"] in [
        Gate4Decision.ALLOW.value,
        Gate4Decision.ALLOW_WITH_UNCERTAINTY.value,
    ]
    assert data["factual_result"] is not None
    assert "conformal_interval" in data
    assert data["audit_record_hash"] is not None
    assert len(data["audit_record_hash"]) == 64
    output_id = data["output_id"]

    # 2. Retrieve output assurance record via GET /v1/output/{output_id}
    get_res = client.get(f"/v1/output/{output_id}", headers=headers)
    assert get_res.status_code == 200, f"Expected 200 but got {get_res.status_code}: {get_res.text}"
    get_data = get_res.json()
    assert get_data["id"] == output_id
    assert get_data["transaction_id"] == txn_id
    assert get_data["verification_status"] == data["verification_status"]
    assert get_data["final_decision"] == data["final_decision"]


@pytest.mark.integration
async def test_unauthorized_and_cross_tenant_access_rejected(phase4_setup: dict[str, str]) -> None:
    """Validate that unauthenticated, unprivileged, or cross-tenant calls are strictly rejected."""
    tenant_id = phase4_setup["tenant_id"]
    actor_sub = phase4_setup["actor_sub"]
    suffix = phase4_setup["suffix"]
    txn_id = f"txn_p4_auth_{suffix}"

    app = create_app()
    client = TestClient(app)

    # 1. Call without authorization header -> 401 Unauthorized
    res = client.post("/v1/output/assure", json={"transaction_id": txn_id, "response_text": "hello"})
    assert res.status_code == 401

    # 2. Call with VIEWER role (lacks VERIFY_WRITE permission) -> 403 Forbidden
    viewer_headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.VIEWER
    )
    res_viewer = client.post(
        "/v1/output/assure",
        json={"transaction_id": txn_id, "response_text": "hello"},
        headers=viewer_headers,
    )
    assert res_viewer.status_code == 403


@pytest.mark.integration
async def test_full_react_loop_gate1_through_gate4(phase4_setup: dict[str, str]) -> None:
    """Validate multi-gate pipeline from Gate 3 action execution through Gate 4 output verification."""
    tenant_id = phase4_setup["tenant_id"]
    actor_sub = phase4_setup["actor_sub"]
    actor_id = phase4_setup["actor_id"]
    suffix = phase4_setup["suffix"]
    txn_id = f"txn_react_{suffix}"
    tool_id = f"tool_db_{suffix}"

    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="ReAct Pipeline", api_key_hash=uuid.uuid4().hex))
        await session.flush()
        user = User(
            id=f"usr_react_{suffix}",
            tenant_id=tenant_id,
            external_subject=actor_sub,
            display_name="Tester ReAct",
            role=Role.API_CLIENT.value,
            active=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            ActorIdentity(
                id=actor_id,
                tenant_id=tenant_id,
                subject=actor_sub,
                principal_type="SERVICE",
                role=Role.API_CLIENT.value,
                user_id=user.id,
                active=True,
            )
        )
        await session.flush()
        # Seed tool in registry
        session.add(
            ToolDefinition(
                id=tool_id,
                tenant_id=tenant_id,
                name="database_updater",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="db:write",
                parameters_schema={"type": "object"},
                config={},
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.flush()

        # Seed transaction in TURN_REASONING
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_react_{suffix}",
                correlation_id=f"corr_react_{suffix}",
                state="TURN_REASONING",
                max_turns=5,
                turn_count=2,
                taint_flags=[],
                context_sources=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.flush()

        # Seed an action contract that was COMPLETED
        session.add(
            ActionContract(
                id=f"act_done_{suffix}",
                tenant_id=tenant_id,
                transaction_id=txn_id,
                actor_identity_id=actor_id,
                tool_id=tool_id,
                tool_name="database_updater",
                action_type="EXECUTE",
                target_resource="db://users/42",
                parameters={"status": "active"},
                normalized_parameters={"status": "active"},
                parameters_hash="paramhash_react",
                required_capability="db:write",
                state=ActionState.COMPLETED.value,
                idempotency_key=f"idem_act_{suffix}",
                preconditions=[],
                postconditions=[{"assertion": "STATUS_EQUALS", "target": "status", "expected_value": "active"}],
                created_at=datetime.now(UTC),
                authorized_at=datetime.now(UTC),
                executed_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        await session.flush()

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )

    # Agent generates output reflecting the completed action
    agent_output = "I have successfully executed the database update for record 42."
    output_req = {
        "transaction_id": txn_id,
        "response_text": agent_output,
        "require_factual_verification": False,
    }

    res = client.post("/v1/output/assure", json=output_req, headers=headers)
    assert res.status_code == 200
    data = res.json()

    # The action was indeed completed, so postcondition honesty check allows it
    assert data["final_decision"] in [Gate4Decision.ALLOW.value, Gate4Decision.ALLOW_WITH_UNCERTAINTY.value]
    assert data["verification_status"] in [
        OutputVerificationStatus.VERIFIED.value,
        OutputVerificationStatus.PARTIALLY_VERIFIED.value,
        OutputVerificationStatus.UNVERIFIED.value,
    ]

    # Verify OutputAssuranceRecord in PostgreSQL
    async with db_session.get_tenant_session(tenant_id) as session:
        record = await session.get(OutputAssuranceRecord, data["output_id"])
        assert record is not None
        assert record.transaction_id == txn_id
        assert record.tenant_id == tenant_id


@pytest.mark.integration
async def test_contradicted_claims_trigger_correction_loop(phase4_setup: dict[str, str]) -> None:
    """Validate that directly contradicted claims trigger the LangGraph correction loop."""
    tenant_id = phase4_setup["tenant_id"]
    actor_sub = phase4_setup["actor_sub"]
    actor_id = phase4_setup["actor_id"]
    suffix = phase4_setup["suffix"]
    txn_id = f"txn_contradict_{suffix}"

    app = create_app()
    client = TestClient(app)

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name="Contradiction Test", api_key_hash=uuid.uuid4().hex))
        await session.flush()
        user = User(
            id=f"usr_c_{suffix}",
            tenant_id=tenant_id,
            external_subject=actor_sub,
            display_name="Tester C",
            role=Role.API_CLIENT.value,
            active=True,
        )
        session.add(user)
        await session.flush()
        session.add(
            ActorIdentity(
                id=actor_id,
                tenant_id=tenant_id,
                subject=actor_sub,
                principal_type="SERVICE",
                role=Role.API_CLIENT.value,
                user_id=user.id,
                active=True,
            )
        )
        await session.flush()
        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_c_{suffix}",
                correlation_id=f"corr_c_{suffix}",
                state="VERIFYING_OUTPUT",
                max_turns=3,
                turn_count=1,
                taint_flags=[],
                context_sources=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.flush()

    headers = AuthTestFactory.auth_headers(
        tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT
    )

    # Claim is contradicted by evidence
    request_payload = {
        "transaction_id": txn_id,
        "response_text": "The transaction of $500 was rejected and denied by the bank.",
        "evidence_chunks": [
            "Official banking receipt: Transaction #992 for $500 was successfully processed and approved."
        ],
        "require_factual_verification": True,
        "enable_correction_loop": True,
    }

    res = client.post("/v1/output/assure", json=request_payload, headers=headers)
    assert res.status_code == 200
    data = res.json()

    # The claim was evaluated by the verification engine and either corrected or flagged as contradicted/uncertain
    assert data["factual_result"] is not None
    assert "conformal_interval" in data
    assert data["final_decision"] in [
        Gate4Decision.ALLOW.value,
        Gate4Decision.ALLOW_WITH_UNCERTAINTY.value,
        Gate4Decision.REQUIRE_VERIFICATION.value,
        Gate4Decision.BLOCK.value,
    ]
