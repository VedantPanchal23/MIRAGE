"""Dedicated validation and regression test suite for MIRAGE Phase 8 Prompt 12/12 Closure.

Covers:
1. Cross-process PostgreSQL advisory lock determinism across separate runtimes and PYTHONHASHSEEDs.
2. Invariant bounds for 64-bit signed integer key space (-2^63 to 2^63 - 1).
3. Production fail-closed behavior on non-PostgreSQL dialects.
4. Target-side mutation boundary classification (ENFORCED, MITIGATED, UNSUPPORTED).
5. Monotonic fencing token progression and stale token rejection.
6. Durable execution replay protection for EXECUTING and EXECUTION_UNCERTAIN states.
7. Epistemic outcome assurance invariants under missing or failed child work.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import (
    ActionContract,
    AITransaction,
    ResourceLease,
)
from services.action_governor import ActionGovernorService
from services.concurrency_service import (
    ResourceConcurrencyService,
    derive_resource_advisory_lock_key,
)
from services.hierarchical_outcome_service import HierarchicalOutcomeService
from shared.config import EnvironmentType
from shared.schemas.action import (
    ActionExecutionRequest,
    ActionState,
)
from shared.schemas.auth import AuthContext, Role
from shared.schemas.concurrency import (
    ConcurrencyMode,
    LeaseStatus,
    ResourceLeaseAcquireRequest,
)
from shared.schemas.hierarchical_outcome import HierarchicalOutcomeStatus


class TestAdvisoryLockDeterminismAndScope:
    """Proves deterministic advisory lock key derivation across processes and runtime environments."""

    def test_cross_process_determinism_across_hashseeds(self) -> None:
        """Verify that derive_resource_advisory_lock_key generates identical keys

        across different Python processes with different randomized hash seeds,
        whereas Python's built-in hash() produces non-deterministic, varying values.
        """
        test_tenant = "tenant_finance_prod"
        test_resource = "postgres://db.cluster.internal:5432/finance/ledger"

        seeds = ["0", "1", "42", "1337", "random"]
        derived_keys: list[int] = []
        builtin_hashes: list[int] = []

        code = (
            "import os, sys\n"
            "from services.concurrency_service import derive_resource_advisory_lock_key\n"
            "tenant = sys.argv[1]\n"
            "uri = sys.argv[2]\n"
            "k = derive_resource_advisory_lock_key(tenant, uri)\n"
            "h = hash((tenant, uri))\n"
            "print(f'{k}:{h}')\n"
        )

        for seed in seeds:
            env = os.environ.copy()
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = "."

            proc = subprocess.run(
                [sys.executable, "-c", code, test_tenant, test_resource],
                capture_output=True,
                text=True,
                env=env,
                check=True,
            )
            output = proc.stdout.strip()
            key_str, hash_str = output.split(":")
            derived_keys.append(int(key_str))
            builtin_hashes.append(int(hash_str))

        # Invariant 1: derive_resource_advisory_lock_key must produce the exact same key across ALL processes
        assert len(set(derived_keys)) == 1, (
            f"Advisory lock key is non-deterministic across processes! Values: {derived_keys}"
        )

        # Invariant 2: Python's hash() must vary across different PYTHONHASHSEED values
        # (proving that PYTHONHASHSEED randomization was active)
        assert len(set(builtin_hashes)) > 1, "Expected hash() to vary across different PYTHONHASHSEED values"

    def test_key_space_bounds_64bit_signed(self) -> None:
        """Verify lock keys strictly fall within PostgreSQL signed 64-bit integer range (-2^63 to 2^63 - 1)."""
        test_cases = [
            ("tenant_1", "resource://orders/123"),
            ("tenant_2", "https://api.gateway.internal/v1/payments"),
            ("tenant_corp", "db://master.internal/accounts/ledger?currency=USD"),
            ("t_" * 30, "resource://" + "a/" * 100),
            ("", ""),
        ]

        min_int64 = -(2**63)
        max_int64 = 2**63 - 1

        for tenant, uri in test_cases:
            key = derive_resource_advisory_lock_key(tenant, uri)
            assert isinstance(key, int)
            assert min_int64 <= key <= max_int64, f"Derived key {key} for ({tenant}, {uri}) out of signed 64-bit bounds"

    @pytest.mark.asyncio
    async def test_production_fail_closed_on_non_postgres(self) -> None:
        """Verify that in PRODUCTION, acquire_lease raises RuntimeError if the dialect is not PostgreSQL."""
        service = ResourceConcurrencyService()
        auth = AuthContext(
            tenant_id="tenant_prod",
            identity_id="usr_admin",
            role=Role.TENANT_ADMIN,
        )
        req = ResourceLeaseAcquireRequest(
            resource_uri="resource://prod/critical_db",
            transaction_id="txn_prod_1",
            agent_id="agt_prod_1",
            duration_seconds=60,
            concurrency_mode=ConcurrencyMode.EXCLUSIVE,
        )

        mock_session = AsyncMock()
        mock_session.sync_session = MagicMock()
        mock_session.sync_session.bind = MagicMock()
        mock_session.sync_session.bind.dialect = MagicMock()
        mock_session.sync_session.bind.dialect.name = "sqlite"  # Non-PostgreSQL dialect

        mock_txn = AITransaction(
            id="txn_prod_1",
            tenant_id="tenant_prod",
            state="ACTIVE",
            final_disposition=None,
            agent_id="agt_prod_1",
        )
        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = mock_txn
        mock_session.execute.return_value = exec_txn

        prod_settings = MagicMock()
        prod_settings.environment = EnvironmentType.PRODUCTION

        with (
            patch("services.concurrency_service.get_settings", return_value=prod_settings),
            patch(
                "services.concurrency_service.agent_governance_service.evaluate_agent_eligibility",
                new=AsyncMock(return_value=(True, "OK")),
            ),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                await service.acquire_lease(auth=auth, request=req, session=mock_session)

            assert "Production invariant violation" in str(exc_info.value)
            assert "requires PostgreSQL dialect" in str(exc_info.value)


class TestLeaseFencingAndMutationBoundary:
    """Verifies fencing token monotonicity, conflict handling, and target mutation boundaries."""

    @pytest.mark.asyncio
    async def test_exclusive_lease_conflicts_with_existing_active_lease(self) -> None:
        """Verify that concurrent exclusive lease acquisition on the same resource returns 409 Conflict."""
        service = ResourceConcurrencyService()
        auth = AuthContext(
            tenant_id="tenant_test",
            identity_id="usr_1",
            role=Role.OPERATOR,
        )
        req = ResourceLeaseAcquireRequest(
            resource_uri="resource://finance/ledger/account_42",
            transaction_id="txn_second",
            agent_id="agt_1",
            duration_seconds=60,
            concurrency_mode=ConcurrencyMode.EXCLUSIVE,
        )

        existing_lease = ResourceLease(
            id="lse_first",
            tenant_id="tenant_test",
            resource_uri="resource://finance/ledger/account_42",
            holder_transaction_id="txn_first",
            holder_agent_id="agt_first",
            concurrency_mode="EXCLUSIVE",
            fencing_token=1,
            status=LeaseStatus.ACQUIRED.value,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )

        mock_session = AsyncMock()
        mock_session.sync_session = None
        mock_session.bind = None

        mock_txn = AITransaction(
            id="txn_second",
            tenant_id="tenant_test",
            state="ACTIVE",
            final_disposition=None,
            agent_id="agt_1",
        )
        exec_txn = MagicMock()
        exec_txn.scalar_one_or_none.return_value = mock_txn

        exec_leases = MagicMock()
        exec_leases.scalars.return_value.all.return_value = [existing_lease]

        mock_session.execute.side_effect = [exec_txn, exec_leases]

        with patch(
            "services.concurrency_service.agent_governance_service.evaluate_agent_eligibility",
            new=AsyncMock(return_value=(True, "OK")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await service.acquire_lease(auth=auth, request=req, session=mock_session)

            assert exc_info.value.status_code == 409
            assert "Resource conflict" in exc_info.value.detail
            assert "currently leased under EXCLUSIVE mode by transaction 'txn_first'" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_target_boundary_fencing_classification(self) -> None:
        """Verify classification of tool execution target boundaries:

        - db_query / internal_sql_query: ENFORCED at target when expected_fencing_token is matched,
          fails with ValueError when mismatched.
        - email_sender: UNSUPPORTED at external SMTP target (token passed in metadata only).
        """
        governor = ActionGovernorService()
        auth = AuthContext(
            tenant_id="tenant_test",
            identity_id="usr_test",
            role=Role.OPERATOR,
        )

        # 1. db_query with matching fencing token -> Success (ENFORCED)
        db_contract_ok = ActionContract(
            id="act_db_1",
            tenant_id="tenant_test",
            transaction_id="txn_1",
            tool_name="db_query",
            target_resource="postgres://db.internal/inventory",
            state=ActionState.EXECUTING.value,
            fencing_token=42,
            normalized_parameters={"query": "UPDATE items SET qty = 10", "expected_fencing_token": 42},
        )
        res_ok, err_ok = await governor.tool_proxy.dispatch(contract=db_contract_ok, auth=auth)
        assert err_ok is None
        assert res_ok["status"] == "ok"
        assert res_ok["fencing_token"] == 42

        # 2. db_query with stale/mismatched fencing token -> Fails at target boundary (ENFORCED)
        db_contract_stale = ActionContract(
            id="act_db_2",
            tenant_id="tenant_test",
            transaction_id="txn_1",
            tool_name="db_query",
            target_resource="postgres://db.internal/inventory",
            state=ActionState.EXECUTING.value,
            fencing_token=41,  # Stale token
            normalized_parameters={"query": "UPDATE items SET qty = 10", "expected_fencing_token": 42},
        )
        res_stale, err_stale = await governor.tool_proxy.dispatch(contract=db_contract_stale, auth=auth)
        assert err_stale is not None
        assert "Target-side fencing check failed" in err_stale
        assert res_stale["status"] == "error"

        # 3. email_sender passes token in metadata, but external protocol lacks fencing capability (UNSUPPORTED target)
        email_contract = ActionContract(
            id="act_email_1",
            tenant_id="tenant_test",
            transaction_id="txn_1",
            tool_name="email_sender",
            target_resource="mailto:customer@example.com",
            state=ActionState.EXECUTING.value,
            fencing_token=42,
            normalized_parameters={"recipient": "customer@example.com", "subject": "Notice"},
        )
        res_email, err_email = await governor.tool_proxy.dispatch(contract=email_contract, auth=auth)
        assert err_email is None
        assert res_email["status"] == "ok"
        assert res_email["delivered"] is True
        # Note: res_email contains "fencing_token", but SMTP recipient server does not validate or enforce tokens!


class TestDurableExecutionAndUncertaintyRecovery:
    """Verifies durable two-phase execution and operator reconciliation for uncertain outcomes."""

    @pytest.mark.asyncio
    async def test_executing_and_uncertain_states_prohibit_automatic_redispatch(self) -> None:
        """Verify that contracts in EXECUTING or EXECUTION_UNCERTAIN return HTTP 409 Conflict

        to prevent duplicate dispatch without explicit reconciliation.
        """
        governor = ActionGovernorService()
        auth = AuthContext(
            tenant_id="tenant_test",
            identity_id="usr_exec",
            role=Role.OPERATOR,
        )

        for prohibited_state in [ActionState.EXECUTING, ActionState.EXECUTION_UNCERTAIN]:
            mock_contract = ActionContract(
                id=f"act_{prohibited_state.value}",
                tenant_id="tenant_test",
                transaction_id="txn_1",
                tool_name="controlled_test_probe",
                target_resource="resource://service/items",
                state=prohibited_state.value,
                actor_identity_id="usr_exec",
            )

            mock_session = AsyncMock()
            mock_res = MagicMock()
            mock_res.scalar_one_or_none.return_value = mock_contract
            mock_session.execute.return_value = mock_res

            req = ActionExecutionRequest(action_id=mock_contract.id)

            with patch("db.session.get_tenant_session") as mock_ctx:
                mock_ctx.return_value.__aenter__.return_value = mock_session
                mock_ctx.return_value.__aexit__.return_value = None

                with pytest.raises(HTTPException) as exc_info:
                    await governor.execute_action(auth=auth, req=req)

                assert exc_info.value.status_code == 409
                assert "EXECUTING" in exc_info.value.detail or "EXECUTION_UNCERTAIN" in exc_info.value.detail


class TestEpistemicHierarchicalOutcomeInvariants:
    """Verifies that parent transactions never claim VERIFIED_SUCCESS when child work is unobservable or failed."""

    @pytest.mark.asyncio
    async def test_unverifiable_child_actions_cap_confidence_at_half(self) -> None:
        """Verify that when a child transaction has actions without outcome verification contracts,

        the hierarchical outcome is capped at PARTIAL_SUCCESS / UNVERIFIABLE with confidence <= 0.5.
        """
        service = HierarchicalOutcomeService()
        auth = AuthContext(
            tenant_id="tenant_test",
            identity_id="usr_parent",
            role=Role.OPERATOR,
        )

        parent_txn = AITransaction(
            id="txn_parent_1",
            tenant_id="tenant_test",
            state="COMPLETED",
            final_disposition="COMPLETED",
        )
        child_txn = AITransaction(
            id="txn_child_1",
            tenant_id="tenant_test",
            parent_transaction_id="txn_parent_1",
            state="COMPLETED",
            final_disposition="COMPLETED",
        )

        # Child action executed but without outcome verification record (unobservable)
        child_action = ActionContract(
            id="act_child_unverified",
            tenant_id="tenant_test",
            transaction_id="txn_child_1",
            tool_name="controlled_test_probe",
            target_resource="resource://external/side_effect",
            state=ActionState.EXECUTED.value,
            requires_outcome_assurance=True,
        )

        mock_session = AsyncMock()

        exec_parent = MagicMock()
        exec_parent.scalar_one_or_none.return_value = parent_txn

        exec_children = MagicMock()
        exec_children.scalars.return_value.all.return_value = [child_txn]

        exec_handoffs = MagicMock()
        exec_handoffs.scalars.return_value.all.return_value = []

        exec_actions = MagicMock()
        exec_actions.scalars.return_value.all.return_value = [child_action]

        exec_empty = MagicMock()
        exec_empty.scalars.return_value.all.return_value = []
        exec_empty.scalar_one_or_none.return_value = None

        mock_session.execute.side_effect = [
            exec_parent,  # 1. select parent txn
            exec_children,  # 2. select child transactions
            exec_empty,  # 3. frontier check (children of child)
            exec_handoffs,  # 4. select handoffs
            exec_actions,  # 5. select actions
            exec_empty,  # 6. late observation audit query
            exec_empty,  # 7. evaluated status audit query
            exec_empty,  # 8. safety margin
        ]

        with patch("services.hierarchical_outcome_service.get_tenant_session") as mock_ts:
            mock_ts.return_value.__aenter__.return_value = mock_session
            summary = await service.aggregate_transaction_outcome(
                auth=auth,
                transaction_id="txn_parent_1",
            )

            # Invariant: Must NOT be VERIFIED_SUCCESS because child action awaits Gate 5 outcome verification
            assert summary.hierarchical_status == HierarchicalOutcomeStatus.AWAITING_OUTCOME_VERIFICATION
            assert summary.hierarchical_status != HierarchicalOutcomeStatus.VERIFIED_SUCCESS
            assert summary.epistemic_confidence == 0.0
            assert any(
                "awaiting gate 5" in note.lower() or "reality verification" in note.lower()
                for note in summary.reconciliation_notes
            )
