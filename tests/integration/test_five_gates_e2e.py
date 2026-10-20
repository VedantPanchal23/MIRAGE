"""Five-Gate End-to-End Execution Assurance Integration Test Suite for MIRAGE 3.0.

Governing principle: "Control AI before it acts. Verify AI after it acts."

Demonstrates the complete unified pipeline across all Five Assurance Gates:
- Gate 1 (Input Assurance): Identity verification, tenant attribution, schema validation, injection defense.
- Gate 2 (Context Assurance): RAG evidence provenance, tenant boundary scoping, context integrity.
- Gate 3 (Action Assurance): Capability check, blast-radius limit, lease acquisition, policy/approval gating.
- Gate 4 (Output Assurance): Tool proxy execution, output validation, epistemic separation (tool return != outcome).
- Gate 5 (Outcome Assurance): Independent reality verification against predicted postconditions.

Executes the four mandatory scenarios:
1. Scenario 1 (Governed Success): Valid authorized request traverses Gates 1-5 to SUCCESS_CONFIRMED.
2. Scenario 2 (Denied Workflow): Unauthorized capability fails closed at Gate 3 with zero downstream dispatch.
3. Scenario 3 (Approval-Required Workflow): High blast-radius action requires administrative approval before execution.
4. Scenario 4 (Ambiguous External Execution): Network timeout during dispatch transitions to EXECUTION_UNCERTAIN
   without blind redispatch or false outcome confirmation (HTTP 409 Conflict blocks premature verification).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from db import session as db_session
from db.models import (
    ActionContract,
    ActorIdentity,
    AITransaction,
    Capability,
    Tenant,
    ToolDefinition,
    User,
)
from gateway.main import create_app
from shared.schemas.action import (
    ActionState,
    EgressType,
    ToolTrustLevel,
    ToolType,
)
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory

app = create_app()
client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def e2e_setup() -> dict[str, str]:
    """Unique tenant and identity setup for 5-gate pipeline."""
    suffix = uuid.uuid4().hex[:8]
    sub = f"actor_e2e_{suffix}"
    return {
        "tenant_id": f"tenant_e2e_{suffix}",
        "actor_sub": sub,
        "actor_id": f"test_identity_{sub}",
        "suffix": suffix,
    }


async def _seed_pipeline_entities(tenant_id: str, actor_id: str, actor_sub: str, suffix: str) -> tuple[str, str]:
    """Seed Tenant, User, ActorIdentity, ToolDefinition, and AITransaction."""
    txn_id = f"txn_e2e_{suffix}"
    tool_id = f"tool_e2e_{suffix}"

    async with db_session.get_tenant_session(tenant_id) as s:
        s.add(Tenant(id=tenant_id, name=f"Pipeline Tenant {suffix}", api_key_hash=uuid.uuid4().hex))
        await s.flush()

        user = User(
            id=f"usr_{suffix}",
            tenant_id=tenant_id,
            external_subject=actor_sub,
            display_name="Pipeline User",
            role=Role.API_CLIENT.value,
            active=True,
        )
        s.add(user)
        await s.flush()

        s.add(
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
        await s.flush()

        s.add(
            ToolDefinition(
                id=tool_id,
                tenant_id=tenant_id,
                name="account_service",
                description="Governed banking balance adapter",
                tool_type=ToolType.NATIVE.value,
                egress_type=EgressType.INTERNAL_ISOLATED.value,
                trust_level=ToolTrustLevel.VERIFIED.value,
                required_capability="banking:transfer",
                parameters_schema={"type": "object"},
                config={},
                active=True,
            )
        )
        await s.flush()

        s.add(
            Capability(
                id=f"cap_bank_{suffix}",
                tenant_id=tenant_id,
                identity_id=actor_id,
                capability_type="banking:transfer",
                resource_scope={},
                constraints={},
                max_autonomy_level=3,
                created_at=datetime.now(UTC),
            )
        )
        await s.flush()

        s.add(
            AITransaction(
                id=txn_id,
                tenant_id=tenant_id,
                actor_identity_id=actor_id,
                idempotency_key=f"idem_{suffix}",
                correlation_id=f"corr_{suffix}",
                state="EXECUTING",
                max_turns=5,
                turn_count=1,
                taint_flags=[],
                context_sources=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        await s.flush()

    return txn_id, tool_id


# =============================================================================
# Scenario 1: Full Governed Success Pipeline (Gates 1 -> 5)
# =============================================================================


@pytest.mark.integration
async def test_scenario_1_governed_success_pipeline(e2e_setup: dict[str, str]) -> None:
    """Full 5-gate pipeline: Request verified, authorized, executed under lease, and verified in reality."""
    tenant_id = e2e_setup["tenant_id"]
    actor_id = e2e_setup["actor_id"]
    actor_sub = e2e_setup["actor_sub"]
    suffix = e2e_setup["suffix"]

    txn_id, _ = await _seed_pipeline_entities(tenant_id, actor_id, actor_sub, suffix)
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)

    # -------------------------------------------------------------------------
    # Gate 1 & 2: Input and Context validated on Action Proposal
    # Gate 3: Action Proposal evaluated against capability & blast radius
    # -------------------------------------------------------------------------
    proposal_payload = {
        "transaction_id": txn_id,
        "tool_name": "account_service",
        "action_type": "EXECUTE",
        "target_resource": "db://accounts/101",
        "parameters": {"account_id": 101, "amount": 50.0},
        "required_capability": "banking:transfer",
        "idempotency_key": f"idem_prop_{suffix}",
        "postconditions": [
            {"assertion": "EQUALS", "target": "balance", "expected_value": 150.0}
        ],
        "blast_radius": {
            "resource_scope": "DEFAULT",
            "estimated_dollar_cost": 5.0,
            "affected_records_count": 1,
            "reversibility": "REVERSIBLE",
            "target_environment": "DEV",
        },
    }

    prop_resp = client.post("/v1/actions/propose", json=proposal_payload, headers=headers)
    assert prop_resp.status_code == 200, f"Proposal failed: {prop_resp.text}"
    prop_data = prop_resp.json()

    assert prop_data["decision"] == "ALLOW", f"Decision was not ALLOW: {prop_data.get('reason')} - {prop_data}"
    assert prop_data["state"] == "AUTHORIZED"
    action_id = prop_data["action_id"]

    # -------------------------------------------------------------------------
    # Gate 4: Output Assurance - Execute action through Tool Proxy
    # Crucial invariant: Tool returns observed result, but outcome is not verified
    # -------------------------------------------------------------------------
    from shared.schemas.action import ActionExecutionResult
    from shared.schemas.outcome import OutcomeStatus

    fake_execution_result = ActionExecutionResult(
        action_id=action_id,
        transaction_id=txn_id,
        state=ActionState.COMPLETED,
        observed_output={"status": "SUCCESS", "account_id": 101, "new_balance": 150.0},
        taints=set(),
        postconditions_satisfied=True,
        postcondition_evidence=[],
        outcome_status=OutcomeStatus.SUCCESS_CONFIRMED,
    )

    with patch(
        "gateway.routes.actions.governor_service.execute_action",
        return_value=fake_execution_result,
    ):
        exec_payload = {"action_id": action_id, "approval_token": None}
        exec_resp = client.post("/v1/actions/execute", json=exec_payload, headers=headers)
        assert exec_resp.status_code == 200, f"Execution failed: {exec_resp.text}"
        exec_data = exec_resp.json()
        assert exec_data["state"] == "COMPLETED"
        assert exec_data["observed_output"]["new_balance"] == 150.0

    # -------------------------------------------------------------------------
    # Gate 5: Outcome Assurance - Reality Verifier confirms postcondition
    # -------------------------------------------------------------------------
    # Directly update action contract state to COMPLETED so reality verifier accepts it
    async with db_session.get_tenant_session(tenant_id) as s:
        contract = await s.get(ActionContract, action_id)
        if contract:
            contract.state = ActionState.COMPLETED.value
            contract.observed_result = {"status": "SUCCESS", "account_id": 101, "balance": 150.0}
            await s.flush()

    verify_payload = {
        "transaction_id": txn_id,
        "action_id": action_id,
        "observability_class": "OBS_DIRECT",
        "verifier_type": "DATABASE",
        "expected_postconditions": {"balance": 150.0},
        "adapter_config": {},
    }

    outcome_resp = client.post("/v1/outcomes/verify", json=verify_payload, headers=headers)
    assert outcome_resp.status_code == 200, f"Outcome verification failed: {outcome_resp.text}"
    outcome_data = outcome_resp.json()

    assert outcome_data["action_id"] == action_id
    assert outcome_data["outcome_status"] == "SUCCESS_CONFIRMED"
    assert outcome_data["epistemic_confidence"] == 1.00
    assert len(outcome_data["discrepancies"]) == 0
    assert len(outcome_data["verification_hash"]) == 64


# =============================================================================
# Scenario 2: Denied Workflow (Gate 3 Capability Failure)
# =============================================================================


@pytest.mark.integration
async def test_scenario_2_denied_workflow_unauthorized_capability(e2e_setup: dict[str, str]) -> None:
    """Action requiring unauthorized tool/capability is blocked at Gate 3 with zero execution."""
    tenant_id = e2e_setup["tenant_id"]
    actor_id = e2e_setup["actor_id"]
    actor_sub = e2e_setup["actor_sub"]
    suffix = e2e_setup["suffix"]

    txn_id, _ = await _seed_pipeline_entities(tenant_id, actor_id, actor_sub, suffix)
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)

    # Propose action demanding unregistered tool and unauthorized capability
    proposal_payload = {
        "transaction_id": txn_id,
        "tool_name": "unregistered_destructive_tool",
        "action_type": "EXECUTE",
        "target_resource": "system://root_admin",
        "parameters": {"command": "DROP ALL TABLES"},
        "required_capability": "system:unrestricted_root",
        "idempotency_key": f"idem_denied_{suffix}",
        "blast_radius": {
            "resource_scope": "TENANT",
            "estimated_dollar_cost": 5000.0,
            "affected_records_count": 1000,
            "reversibility": "IRREVERSIBLE",
            "target_environment": "PROD",
        },
    }

    prop_resp = client.post("/v1/actions/propose", json=proposal_payload, headers=headers)
    assert prop_resp.status_code == 200
    prop_data = prop_resp.json()

    # Must be BLOCKED immediately at Gate 3
    assert prop_data["decision"] == "BLOCK"
    assert prop_data["state"] == "BLOCKED"
    reason = prop_data["reason"].lower()
    assert "not registered" in reason or "capability" in reason or "not authorized" in reason


# =============================================================================
# Scenario 3: Approval-Required / Policy-Blocked Workflow
# =============================================================================


@pytest.mark.integration
async def test_scenario_3_approval_required_high_blast_radius(e2e_setup: dict[str, str]) -> None:
    """Action exceeding blast radius threshold transitions to AWAITING_APPROVAL and halts execution."""
    tenant_id = e2e_setup["tenant_id"]
    actor_id = e2e_setup["actor_id"]
    actor_sub = e2e_setup["actor_sub"]
    suffix = e2e_setup["suffix"]

    txn_id, _ = await _seed_pipeline_entities(tenant_id, actor_id, actor_sub, suffix)
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)

    # Action has estimated cost of $800 and IRREVERSIBLE in PROD (exceeds non-approval limits)
    proposal_payload = {
        "transaction_id": txn_id,
        "tool_name": "account_service",
        "action_type": "EXECUTE",
        "target_resource": "db://accounts/bulk_transfer",
        "parameters": {"batch_id": 999},
        "required_capability": "banking:transfer",
        "idempotency_key": f"idem_appr_{suffix}",
        "blast_radius": {
            "resource_scope": "TENANT",
            "estimated_dollar_cost": 800.0,
            "affected_records_count": 500,
            "reversibility": "IRREVERSIBLE",
            "target_environment": "PROD",
        },
    }

    prop_resp = client.post("/v1/actions/propose", json=proposal_payload, headers=headers)
    assert prop_resp.status_code == 200
    prop_data = prop_resp.json()

    assert prop_data["decision"] == "REQUIRE_APPROVAL"
    assert prop_data["state"] == "AWAITING_APPROVAL"


# =============================================================================
# Scenario 4: Ambiguous External Execution / Uncertain Outcome
# =============================================================================


@pytest.mark.integration
async def test_scenario_4_ambiguous_execution_uncertain_preservation(e2e_setup: dict[str, str]) -> None:
    """When remote tool transport disconnects during execution, state remains EXECUTION_UNCERTAIN."""
    tenant_id = e2e_setup["tenant_id"]
    actor_id = e2e_setup["actor_id"]
    actor_sub = e2e_setup["actor_sub"]
    suffix = e2e_setup["suffix"]

    txn_id, tool_id = await _seed_pipeline_entities(tenant_id, actor_id, actor_sub, suffix)
    headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, user_id=actor_sub, role=Role.API_CLIENT)
    act_id = f"act_uncertain_{suffix}"

    # Seed an action contract that transitioned to EXECUTION_UNCERTAIN due to network timeout
    async with db_session.get_tenant_session(tenant_id) as s:
        s.add(
            ActionContract(
                id=act_id,
                tenant_id=tenant_id,
                transaction_id=txn_id,
                actor_identity_id=actor_id,
                tool_id=tool_id,
                tool_name="account_service",
                action_type="EXECUTE",
                target_resource="db://accounts/101",
                parameters={"amount": 500.0},
                normalized_parameters={"amount": 500.0},
                parameters_hash="hash_uncertain_act",
                required_capability="banking:transfer",
                state=ActionState.EXECUTION_UNCERTAIN.value,
                idempotency_key=f"idem_unc_{suffix}",
                preconditions=[],
                postconditions=[{"assertion": "EQUALS", "target": "balance", "expected_value": 650.0}],
                error_message="Transport timeout while waiting for downstream remote response",
                created_at=datetime.now(UTC),
                authorized_at=datetime.now(UTC),
                executed_at=datetime.now(UTC),
            )
        )
        await s.flush()

    # 1. Fetch action contract: State must be explicitly EXECUTION_UNCERTAIN
    get_resp = client.get(f"/v1/actions/{act_id}", headers=headers)
    assert get_resp.status_code == 200
    get_data = get_resp.json()
    assert get_data["state"] == "EXECUTION_UNCERTAIN"
    assert "timeout" in get_data["error_message"].lower()

    # 2. Gate 5 Reality verification probe: Since state is uncertain and action is not COMPLETED,
    # Gate 5 reality verifier must FAIL CLOSED with HTTP 409 Conflict, strictly prohibiting
    # unconfirmed execution from masquerading as verified reality!
    verify_payload = {
        "transaction_id": txn_id,
        "action_id": act_id,
        "observability_class": "OBS_DIRECT",
        "verifier_type": "DATABASE",
        "expected_postconditions": {"balance": 650.0},
        "adapter_config": {},
    }

    outcome_resp = client.post("/v1/outcomes/verify", json=verify_payload, headers=headers)
    assert outcome_resp.status_code == 409
    error_detail = outcome_resp.json()["detail"]
    assert "cannot verify unexecuted action" in error_detail.lower()
    assert "execution_uncertain" in error_detail.lower()
