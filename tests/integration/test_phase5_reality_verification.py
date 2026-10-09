"""Integration tests for Gate 5 Outcome Assurance and Reality Verification REST API.

Tests:
1. End-to-end reality verification API flow: POST /v1/outcomes/verify.
2. Retrieval by ID and transaction listing under tenant boundaries.
3. Cross-tenant isolation verification (Tenant Beta cannot read Tenant Alpha outcomes).
4. Output <-> Outcome consistency reconciliation via POST /v1/outcomes/reconcile.
5. Eventual consistency verification via AsyncEventAdapter with bounded backoff.
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
    Tenant,
    ToolDefinition,
    User,
)
from gateway.main import create_app
from shared.schemas.action import ActionState, EgressType, ToolTrustLevel, ToolType
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory


@pytest.fixture
def phase5_setup() -> dict[str, str]:
    """Helper fixture providing unique tenant and identity metadata."""
    suffix = uuid.uuid4().hex[:8]
    actor_sub = f"actor_p5_{suffix}"
    return {
        "tenant_id": f"p5_ten_{suffix}",
        "actor_sub": actor_sub,
        "actor_id": f"test_identity_{actor_sub}",
        "suffix": suffix,
    }


async def _seed_test_environment(tenant_id: str, actor_id: str, actor_sub: str, suffix: str) -> tuple[str, str, str]:
    """Seed Tenant, User, ActorIdentity, ToolDefinition, AITransaction, and ActionContract."""
    txn_id = f"txn_p5_{suffix}"
    tool_id = f"tool_p5_{suffix}"
    act_id = f"act_p5_{suffix}"

    async with db_session.get_tenant_session(tenant_id) as session:
        session.add(Tenant(id=tenant_id, name=f"Tenant {suffix}", api_key_hash=uuid.uuid4().hex))
        await session.flush()

        user = User(
            id=f"usr_{suffix}",
            tenant_id=tenant_id,
            external_subject=actor_sub,
            display_name="Tester P5",
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
            ToolDefinition(
                id=tool_id,
                tenant_id=tenant_id,
                name="database_updater",
                description="Updates test records",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="db:write",
                parameters_schema={"type": "object"},
                config={},
                active=True,
            )
        )
        await session.flush()

        session.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_txn_{suffix}",
                correlation_id=f"corr_txn_{suffix}",
                state="EXECUTING",
                max_turns=5,
                turn_count=1,
                taint_flags=[],
                context_sources=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await session.flush()

        session.add(
            ActionContract(
                id=act_id,
                tenant_id=tenant_id,
                transaction_id=txn_id,
                actor_identity_id=actor_id,
                tool_id=tool_id,
                tool_name="database_updater",
                action_type="EXECUTE",
                target_resource="db://users/100",
                parameters={"status": "SUSPENDED", "user_id": 100},
                normalized_parameters={"status": "SUSPENDED", "user_id": 100},
                parameters_hash="hash_act_p5",
                required_capability="db:write",
                state=ActionState.COMPLETED.value,
                idempotency_key=f"idem_act_{suffix}",
                preconditions=[],
                postconditions=[{"assertion": "STATUS_EQUALS", "field": "status", "expected": "SUSPENDED"}],
                observed_result={"status": "SUSPENDED", "user_id": 100, "rows_affected": 1},
                created_at=datetime.now(UTC),
                authorized_at=datetime.now(UTC),
                executed_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
        )
        await session.flush()

    return txn_id, act_id, tool_id


@pytest.mark.integration
async def test_end_to_end_outcome_verification_api(phase5_setup: dict[str, str]) -> None:
    """Test full Gate 5 reality verification endpoint via REST API."""
    tenant_id = phase5_setup["tenant_id"]
    actor_id = phase5_setup["actor_id"]
    actor_sub = phase5_setup["actor_sub"]
    suffix = phase5_setup["suffix"]

    txn_id, act_id, _ = await _seed_test_environment(tenant_id, actor_id, actor_sub, suffix)

    client = TestClient(create_app())
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)

    req_payload = {
        "transaction_id": txn_id,
        "action_id": act_id,
        "observability_class": "OBS_DIRECT",
        "verifier_type": "DATABASE",
        "expected_postconditions": {
            "status": "SUSPENDED",
            "rows_affected": 1,
        },
        "adapter_config": {},
    }

    resp = client.post("/v1/outcomes/verify", json=req_payload, headers=headers)
    assert resp.status_code == 200, f"Verification failed: {resp.text}"
    data = resp.json()

    assert data["outcome_id"].startswith("outc_")
    assert data["transaction_id"] == txn_id
    assert data["action_id"] == act_id
    assert data["observability_class"] == "OBS_DIRECT"
    assert data["outcome_status"] == "SUCCESS_CONFIRMED"
    assert data["epistemic_confidence"] == 1.00
    assert len(data["verification_hash"]) == 64
    assert len(data["discrepancies"]) == 0

    outcome_id = data["outcome_id"]

    # Fetch by ID
    get_resp = client.get(f"/v1/outcomes/{outcome_id}", headers=headers)
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["outcome_id"] == outcome_id
    assert get_data["outcome_status"] == "SUCCESS_CONFIRMED"

    # List by transaction
    list_resp = client.get(f"/v1/outcomes/transaction/{txn_id}", headers=headers)
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert len(list_data) >= 1
    assert any(o["outcome_id"] == outcome_id for o in list_data)


@pytest.mark.integration
async def test_cross_tenant_outcome_isolation_strictly_enforced(phase5_setup: dict[str, str]) -> None:
    """Tenant Beta is strictly forbidden from viewing or accessing Tenant Alpha outcome records."""
    tenant_a = phase5_setup["tenant_id"]
    actor_id_a = phase5_setup["actor_id"]
    actor_sub_a = phase5_setup["actor_sub"]
    suffix_a = phase5_setup["suffix"]

    tenant_b = f"p5_beta_{uuid.uuid4().hex[:6]}"
    actor_sub_b = f"actor_beta_{uuid.uuid4().hex[:6]}"

    txn_id_a, act_id_a, _ = await _seed_test_environment(tenant_a, actor_id_a, actor_sub_a, suffix_a)

    client = TestClient(create_app())
    headers_a = AuthTestFactory.auth_headers(tenant_id=tenant_a, user_id=actor_sub_a, role=Role.API_CLIENT)
    headers_b = AuthTestFactory.auth_headers(tenant_id=tenant_b, user_id=actor_sub_b, role=Role.API_CLIENT)

    # 1. Tenant Alpha creates outcome record
    req_payload = {
        "transaction_id": txn_id_a,
        "action_id": act_id_a,
        "observability_class": "OBS_DIRECT",
        "verifier_type": "SIMULATED",
        "expected_postconditions": {"status": "SUSPENDED"},
        "adapter_config": {"simulated_state": {"status": "SUSPENDED"}},
    }

    create_resp = client.post("/v1/outcomes/verify", json=req_payload, headers=headers_a)
    assert create_resp.status_code == 200
    outcome_id = create_resp.json()["outcome_id"]

    # 2. Tenant Beta attempts to read Tenant Alpha's outcome record
    beta_get = client.get(f"/v1/outcomes/{outcome_id}", headers=headers_b)
    assert beta_get.status_code == 404, "Security failure: Tenant Beta accessed Tenant Alpha outcome record!"
    assert f"Outcome record '{outcome_id}' not found for tenant '{tenant_b}'" in beta_get.json()["detail"]


@pytest.mark.integration
async def test_output_outcome_reconciliation_api(phase5_setup: dict[str, str]) -> None:
    """Test POST /v1/outcomes/reconcile detecting epistemic conflicts."""
    tenant_id = phase5_setup["tenant_id"]
    actor_id = phase5_setup["actor_id"]
    actor_sub = phase5_setup["actor_sub"]
    suffix = phase5_setup["suffix"]

    txn_id, act_id, _ = await _seed_test_environment(tenant_id, actor_id, actor_sub, suffix)

    client = TestClient(create_app())
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)

    # 1. Create an OBS_INFERRED outcome record
    req_payload = {
        "transaction_id": txn_id,
        "action_id": act_id,
        "observability_class": "OBS_INFERRED",
        "verifier_type": "SIMULATED",
        "expected_postconditions": {"ack": True},
        "adapter_config": {"simulated_state": {"ack": True}},
    }
    resp = client.post("/v1/outcomes/verify", json=req_payload, headers=headers)
    assert resp.status_code == 200
    outcome_id = resp.json()["outcome_id"]

    # 2. Reconcile with text that falsely claims real-world verified completion
    reconcile_req = {
        "outcome_id": outcome_id,
        "response_text": "The transfer went through and funds have reached the recipient account.",
    }
    reconcile_resp = client.post("/v1/outcomes/reconcile", json=reconcile_req, headers=headers)
    assert reconcile_resp.status_code == 200
    reconcile_data = reconcile_resp.json()

    assert reconcile_data["is_consistent"] is False
    assert reconcile_data["epistemic_conflict_detected"] is True
    assert reconcile_data["recommended_disposition"] == "REWRITE_WITH_CAVEAT"
    assert any("Epistemic Invariant Violation" in r for r in reconcile_data["conflict_reasons"])


@pytest.mark.integration
async def test_eventual_consistency_async_event_adapter_api(phase5_setup: dict[str, str]) -> None:
    """Test eventual consistency polling reaching SUCCESS_EVENTUALLY_OBSERVED."""
    tenant_id = phase5_setup["tenant_id"]
    actor_id = phase5_setup["actor_id"]
    actor_sub = phase5_setup["actor_sub"]
    suffix = phase5_setup["suffix"]

    txn_id, act_id, _ = await _seed_test_environment(tenant_id, actor_id, actor_sub, suffix)

    client = TestClient(create_app())
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)

    progression = [
        {"replicas": 1, "status": "UPDATING"},
        {"replicas": 3, "status": "AVAILABLE"},
    ]

    req_payload = {
        "transaction_id": txn_id,
        "action_id": act_id,
        "observability_class": "OBS_EVENTUAL",
        "verifier_type": "ASYNC_EVENT",
        "expected_postconditions": {"status": "AVAILABLE", "replicas": 3},
        "adapter_config": {"simulated_progression": progression},
        "max_poll_attempts": 5,
        "poll_interval_seconds": 0.05,
        "timeout_seconds": 2.0,
    }

    resp = client.post("/v1/outcomes/verify", json=req_payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["outcome_status"] == "SUCCESS_EVENTUALLY_OBSERVED"
    assert data["epistemic_confidence"] == 0.95
    assert data["evidence_payload"]["poll_attempts"] == 2
    assert len(data["discrepancies"]) == 0
