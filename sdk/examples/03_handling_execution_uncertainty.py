"""Example 3: Handling Execution Uncertainty and Stranded Action Recovery.

Demonstrates:
- What happens when a mutating request encounters a network timeout.
- The critical invariant: Blind redispatch / automatic retry of mutating requests is FORBIDDEN.
- Inspecting action state via get_action(action_id) to determine whether the remote side-effect landed.
- Listing stranded actions and performing idempotent reconciliation via reconcile_action.
"""

import os

from mirage_sdk import (
    ActionState,
    MirageClient,
    MirageError,
    MirageExecutionUncertainError,
)


def main() -> None:
    api_key = os.environ.get("MIRAGE_API_KEY", "mirage_test_key_sample")
    base_url = os.environ.get("MIRAGE_BASE_URL", "http://localhost:8000")

    # Use a low client timeout to demonstrate timeout handling
    with MirageClient(api_key=api_key, base_url=base_url, timeout=0.001) as client:
        action_id = "act_demo_sample_123"

        print(f"Simulating mutating action execution for {action_id}...")

        try:
            # When a mutating action times out or loses connection in flight:
            client.execute_action(action_id)
        except MirageExecutionUncertainError as exc:
            print("\n[CRITICAL EXECUTION UNCERTAINTY DETECTED]")
            print(f"  Message:   {exc.message}")
            print(f"  Action ID: {exc.action_id}")
            print(f"  State:     {exc.state}")
            print(
                "\n  INVARIANT: Mutating actions must NEVER be automatically retried.\n"
                "  The remote tool may have already committed state changes before the timeout."
            )

    # Recovery workflow using a normal timeout client:
    with MirageClient(api_key=api_key, base_url=base_url, timeout=30.0) as recovery_client:
        print("\n--- Stranded Action Recovery Protocol ---")

        # Step 1: List any stranded actions in EXECUTING or EXECUTION_UNCERTAIN
        stranded_list = recovery_client.list_stranded_actions(older_than_seconds=0)
        print(f"Found {len(stranded_list)} stranded action(s) across the tenant.")
        for sa in stranded_list:
            print(f"  Stranded Action: {sa.action_id} (tool: {sa.tool_name}, state: {sa.state})")

        # Step 2: Idempotent reconciliation
        # Once an operator or automated probe verifies external ground truth,
        # reconcile the stranded action to a terminal state (COMPLETED or FAILED) with rationale:
        target_action = stranded_list[0].action_id if stranded_list else "act_demo_sample_123"
        try:
            reconcile_result = recovery_client.reconcile_action(
                action_id=target_action,
                resolution_state=ActionState.FAILED,
                rationale="Timed out during network transmission; probe confirmed mutation did not commit",
                verified_evidence={"remote_verified_present": False},
            )
            print(f"Reconciled {target_action} -> New State: {reconcile_result.state}")
        except MirageError as exc:
            print(f"Reconciliation note (mock/demo): {exc}")


if __name__ == "__main__":
    main()
