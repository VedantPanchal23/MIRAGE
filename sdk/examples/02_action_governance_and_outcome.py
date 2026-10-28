"""Example 2: Governed Action Execution and Reality Verification (Gate 3 -> Gate 5).

Demonstrates:
- Proposing an ActionContract to Gate 3 Action Assurance.
- Executing the authorized action through the Tool Proxy.
- Epistemic Outcome Independence: A tool execution return value is NOT proof of reality.
- Collecting independent observation and submitting to Gate 5 for reality verification.
"""

import os
import sys
import uuid

from mirage_sdk import (
    ActionProposal,
    ActionType,
    BlastRadiusAssessment,
    IndependentObservation,
    MirageAuthorizationError,
    MirageClient,
    OutcomeVerificationRequest,
    PostconditionRule,
)


def main() -> None:
    api_key = os.environ.get("MIRAGE_API_KEY")
    base_url = os.environ.get("MIRAGE_BASE_URL", "http://localhost:8000")

    # If no valid API key is set in environment, auto-provision a local sandbox tenant
    if not api_key or api_key == "mirage_test_key_sample":
        print("[DX] No MIRAGE_API_KEY detected. Provisioning local sandbox developer tenant...")
        try:
            with MirageClient(api_key="bootstrap_temp", base_url=base_url) as boot_client:
                tenant_res = boot_client.register_tenant(
                    {
                        "name": "Local Dev Sandbox",
                        "admin_email": f"developer_{uuid.uuid4().hex[:6]}@mirage.local",
                        "tier": "developer",
                    }
                )
                api_key = tenant_res["api_key"]
                print(f"[OK] Onboarded sandbox tenant '{tenant_res['tenant_id']}' with active API key.\n")
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Sandbox onboarding skipped ({exc}). Falling back to test key.")
            api_key = api_key or "mirage_test_key_sample"

    with MirageClient(api_key=api_key, base_url=base_url) as client:
        tx_id = f"tx_{uuid.uuid4().hex[:12]}"
        order_id = "ord_45678"

        print("1. Registering tool 'database.update_order_status' in Gate 3 registry...")
        client.register_tool(
            {
                "name": "database.update_order_status",
                "description": "Updates order fulfillment status in relational database",
                "tool_type": "NATIVE",
                "egress_type": "INTERNAL_ISOLATED",
                "trust_level": "VERIFIED",
                "required_capability": "orders:write",
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["order_id", "status"],
                },
                "active": True,
            }
        )

        print(f"\n2. Proposing action contract for transaction {tx_id}...")
        proposal = ActionProposal(
            transaction_id=tx_id,
            tool_name="database.update_order_status",
            action_type=ActionType.WRITE,
            target_resource=f"orders:{order_id}",
            parameters={"order_id": order_id, "status": "COMPLETED"},
            idempotency_key=f"idem_{uuid.uuid4().hex[:16]}",
            postconditions=[
                PostconditionRule(
                    assertion="STATUS_EQUALS",
                    target=f"orders:{order_id}.status",
                    expected_value="COMPLETED",
                    description="Order status must transition to COMPLETED in database",
                )
            ],
            blast_radius=BlastRadiusAssessment(
                resource_scope="ORDERS",
                estimated_dollar_cost=250.0,
                reversibility="REVERSIBLE",
                target_environment="DEV",
            ),
        )

        try:
            decision = client.propose_action(proposal)
        except MirageAuthorizationError as exc:
            print(f"[ACCESS DENIED] Scope or policy rejected action: {exc.message}")
            sys.exit(1)

        print(f"   Gate 3 Decision:   {decision.decision}")
        print(f"   Action ID:         {decision.action_id}")
        print(f"   Risk Score:        {decision.risk_score}")
        print(f"   Fencing Token:     {decision.fencing_token}")

        if decision.decision != "ALLOW":
            print(f"Action not permitted: {decision.reason}")
            return

        print("\n3. Executing authorized action contract through Governed Tool Proxy...")
        exec_result = client.execute_action(decision.action_id)
        print(f"   Execution State:   {exec_result.state}")
        print(f"   Observed Output:   {exec_result.observed_output}")

        # IMPORTANT: Epistemic Outcome Independence
        # Tool response HTTP 200 does not prove the database row was safely updated!
        print("\n4. Performing independent Gate 5 Reality Verification...")
        # Simulate independent observation gathered from DB read replica / audit log:
        observation = IndependentObservation(
            target_resource=f"orders:{order_id}",
            observed_state={
                f"orders:{order_id}.status": "COMPLETED",
                "order_id": order_id,
                "status": "COMPLETED",
            },
        )

        outcome = client.verify_outcome(
            action_id=decision.action_id,
            request=OutcomeVerificationRequest(
                transaction_id=tx_id,
                action_id=decision.action_id,
                expected_postconditions={"status": "COMPLETED"},
                observation=observation,
            ),
        )

        print("--- Gate 5 Outcome Assurance Contract ---")
        print(f"   Outcome ID:        {outcome.outcome_id}")
        print(f"   Outcome Status:    {outcome.outcome_status}")
        print(f"   Epistemic Conf:    {outcome.epistemic_confidence * 100:.1f}%")
        print(f"   Discrepancies:     {outcome.discrepancies}")
        print(f"   Verification Hash: {outcome.verification_hash}")


if __name__ == "__main__":
    main()
