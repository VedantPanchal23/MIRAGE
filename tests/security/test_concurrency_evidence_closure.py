"""MIRAGE 3.0 — Comprehensive Concurrency & Transactional Evidence Closure Tests.

Covers:
1. Multi-tenant concurrent audit writes: concurrent calls across distinct tenants
   preserve isolated monotonic sequence numbers (1..N) and independent unbroken hash chains.
2. Atomic rollback on audit append failure: failure during outcome verification rolls back
   OutcomeVerificationRecord, ActionContract mutation, AuditLogRecord, and TenantAuditLedger atomically.
3. PostgreSQL transaction-scoped advisory locks: confirms pg_advisory_xact_lock acquisition
   and automatic release upon transaction commit/rollback.
4. Simultaneous approval consumption concurrency: concurrent workers racing to execute
   the same single-use approval are serialized by row locks (with_for_update); exactly one succeeds,
   the competitor fails closed (HTTP 409 or 403), and no duplicate executions occur.
5. Approval rollback on aborted pre-dispatch: failure prior to pre-dispatch commit rolls back
   the approval state to GRANTED.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from db import session as db_session
from services.action_governor import ActionGovernorService
from services.reality_verifier import RealityVerifierService
from shared.schemas.action import (
    ActionExecutionRequest,
    ActionState,
    ApprovalStatus,
    compute_contract_binding_hash,
    compute_parameters_hash,
)
from shared.schemas.audit import GENESIS_ROOT_HASH
from shared.schemas.auth import AuthContext, Role
from shared.schemas.outcome import (
    ObservabilityClass,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
)


@pytest.fixture
def sync_engine(live_postgres_database: Any) -> Any:
    _ = live_postgres_database
    sync_url = os.environ.get("DATABASE_SYNC_URL")
    assert sync_url is not None, "DATABASE_SYNC_URL must be configured by live_postgres_database fixture"
    eng = create_engine(sync_url, pool_size=10, max_overflow=10)
    yield eng
    eng.dispose()


@pytest.mark.security
class TestConcurrencyEvidenceClosure:
    """Rigorous live PostgreSQL concurrency, advisory lock, and transaction rollback tests."""

    @pytest.mark.asyncio
    async def test_concurrent_audit_writes_multi_tenant_isolation(self, sync_engine: Any) -> None:
        """Concurrent reality verifier appends across multiple tenants remain completely isolated.

        Tenant A and Tenant B execute concurrent verifications simultaneously.
        Each tenant must achieve:
        - Independent monotonic sequence numbers (1..N)
        - Independent unbroken cryptographic hash chains from GENESIS_ROOT_HASH
        - Zero cross-tenant sequence number contamination or hash pointer cross-referencing.
        """
        tenant_a = f"t_conc_iso_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"t_conc_iso_b_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        workers_per_tenant = 4

        tenants_data = {
            tenant_a: {"actions": [], "txns": []},
            tenant_b: {"actions": [], "txns": []},
        }

        with sync_engine.connect() as conn:
            for t_id in (tenant_a, tenant_b):
                conn.execute(
                    text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:id, :name, :hash, :now)"),
                    {"id": t_id, "name": f"Tenant {t_id}", "hash": uuid.uuid4().hex[:32], "now": now},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at)
                        VALUES (:aid, :tid, 'actor_iso', 'SERVICE', 'OPERATOR', true, :now)
                        ON CONFLICT (id) DO NOTHING;
                        """
                    ),
                    {"aid": f"actor_{t_id}", "tid": t_id, "now": now},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO tool_registry (id, tenant_id, name, required_capability, created_at, updated_at)
                        VALUES (:tool_id, :tid, 'service_tool', 'service:execute', :now, :now)
                        ON CONFLICT (id) DO NOTHING;
                        """
                    ),
                    {"tool_id": f"tool_{t_id}", "tid": t_id, "now": now},
                )

                for i in range(workers_per_tenant):
                    a_id = f"act_{t_id}_{i}_{uuid.uuid4().hex[:6]}"
                    tx_id = f"txn_{t_id}_{i}_{uuid.uuid4().hex[:6]}"
                    tenants_data[t_id]["actions"].append(a_id)
                    tenants_data[t_id]["txns"].append(tx_id)

                    conn.execute(
                        text(
                            """
                            INSERT INTO ai_transactions (
                                id, tenant_id, actor_identity_id, idempotency_key, correlation_id,
                                state, max_turns, created_at, updated_at
                            )
                            VALUES (:txnid, :tid, :aid, :txnid, :txnid, 'RUNNING', 10, :now, :now);
                            """
                        ),
                        {"txnid": tx_id, "tid": t_id, "aid": f"actor_{t_id}", "now": now},
                    )

                    conn.execute(
                        text(
                            """
                            INSERT INTO action_contracts (
                                id, tenant_id, transaction_id, actor_identity_id, tool_id, tool_name,
                                action_type, target_resource, parameters, normalized_parameters, parameters_hash,
                                required_capability, taint_flags, risk_score, blast_radius, state, idempotency_key,
                                preconditions, postconditions, created_at
                            ) VALUES (
                                :aid, :tid, :txnid, :actorid, :toolid, 'service_tool',
                                'EXECUTE', 'db://cluster/primary', '{}'::jsonb, '{}'::jsonb,
                                '0000000000000000000000000000000000000000000000000000000000000000',
                                'service:execute', '[]'::jsonb, 0, '{}'::jsonb, 'COMPLETED', :idem,
                                '[]'::jsonb, '[{"target": "status", "expected_value": "OK"}]'::jsonb, :now
                            );
                            """
                        ),
                        {
                            "aid": a_id,
                            "tid": t_id,
                            "txnid": tx_id,
                            "actorid": f"actor_{t_id}",
                            "toolid": f"tool_{t_id}",
                            "idem": f"idem_{t_id}_{i}",
                            "now": now,
                        },
                    )
            conn.commit()

        service = RealityVerifierService()

        async def _run_verify(tid: str, idx: int) -> Any:
            auth = AuthContext(
                tenant_id=tid,
                user_id=f"op_{tid}",
                role=Role.OPERATOR,
                identity_id=f"actor_{tid}",
            )
            req = OutcomeVerificationRequest(
                transaction_id=tenants_data[tid]["txns"][idx],
                action_id=tenants_data[tid]["actions"][idx],
                observability_class=ObservabilityClass.OBS_DIRECT,
                verifier_type=OutcomeVerifierType.SIMULATED,
                expected_postconditions={"status": "OK"},
                adapter_config={"simulated_state": {"status": "OK"}, "allow_simulated_for_test": True},
            )
            return await service.verify_action_outcome(req, auth)

        # Run all workers across both tenants concurrently
        tasks = []
        for i in range(workers_per_tenant):
            tasks.append(_run_verify(tenant_a, i))
            tasks.append(_run_verify(tenant_b, i))

        results = await asyncio.gather(*tasks)
        assert len(results) == workers_per_tenant * 2

        with sync_engine.connect() as conn:
            for t_id in (tenant_a, tenant_b):
                rows = conn.execute(
                    text(
                        """
                        SELECT sequence_number, prev_hash, chain_hash, entry_id
                        FROM audit_logs
                        WHERE tenant_id = :tenant_id
                        ORDER BY sequence_number ASC;
                        """
                    ),
                    {"tenant_id": t_id},
                ).fetchall()

                assert len(rows) == workers_per_tenant, f"Tenant {t_id} must have {workers_per_tenant} audit entries"
                sequences = [r[0] for r in rows]
                assert sequences == list(range(1, workers_per_tenant + 1)), (
                    f"Tenant {t_id} sequence numbers must be 1..{workers_per_tenant}, got {sequences}"
                )

                # Verify cryptographic chain unbroken for this tenant
                assert rows[0][1] == GENESIS_ROOT_HASH, f"Tenant {t_id} first entry must chain from GENESIS_ROOT_HASH"
                for i in range(1, workers_per_tenant):
                    assert rows[i][1] == rows[i - 1][2], (
                        f"Tenant {t_id} chain break at index {i}: prev_hash {rows[i][1]} != previous {rows[i-1][2]}"
                    )

                # Verify tenant audit ledger head
                head = conn.execute(
                    text(
                        """
                        SELECT sequence_number, head_chain_hash, head_entry_id
                        FROM tenant_audit_ledgers
                        WHERE tenant_id = :tenant_id;
                        """
                    ),
                    {"tenant_id": t_id},
                ).fetchone()

                assert head is not None
                assert head[0] == workers_per_tenant
                assert head[1] == rows[-1][2]
                assert head[2] == rows[-1][3]

    @pytest.mark.asyncio
    async def test_audit_transaction_atomic_rollback_on_failure(self, sync_engine: Any) -> None:
        """A failure during audit trail appending atomically rolls back all changes.

        Confirms that:
        - OutcomeVerificationRecord is not committed
        - ActionContract outcome_status and state are reverted
        - AuditLogRecord is not committed
        - TenantAuditLedger head sequence number does not advance.
        """
        tenant_id = f"t_conc_rb_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        a_id = f"act_rb_{uuid.uuid4().hex[:6]}"
        tx_id = f"txn_rb_{uuid.uuid4().hex[:6]}"

        with sync_engine.connect() as conn:
            conn.execute(
                text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:id, 'RB Test', :hash, :now)"),
                {"id": tenant_id, "hash": uuid.uuid4().hex[:32], "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at)
                    VALUES (:aid, :tid, 'actor_rb', 'SERVICE', 'OPERATOR', true, :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"aid": f"actor_{tenant_id}", "tid": tenant_id, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO tool_registry (id, tenant_id, name, required_capability, created_at, updated_at)
                    VALUES (:tool_id, :tid, 'service_tool', 'service:execute', :now, :now)
                    ON CONFLICT (id) DO NOTHING;
                    """
                ),
                {"tool_id": f"tool_{tenant_id}", "tid": tenant_id, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ai_transactions (
                        id, tenant_id, actor_identity_id, idempotency_key, correlation_id,
                        state, max_turns, created_at, updated_at
                    )
                    VALUES (:txnid, :tid, :aid, :txnid, :txnid, 'RUNNING', 10, :now, :now);
                    """
                ),
                {"txnid": tx_id, "tid": tenant_id, "aid": f"actor_{tenant_id}", "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO action_contracts (
                        id, tenant_id, transaction_id, actor_identity_id, tool_id, tool_name,
                        action_type, target_resource, parameters, normalized_parameters, parameters_hash,
                        required_capability, taint_flags, risk_score, blast_radius, state, idempotency_key,
                        preconditions, postconditions, created_at
                    ) VALUES (
                        :aid, :tid, :txnid, :actorid, :toolid, 'service_tool',
                        'EXECUTE', 'db://cluster/primary', '{}'::jsonb, '{}'::jsonb,
                        '0000000000000000000000000000000000000000000000000000000000000000',
                        'service:execute', '[]'::jsonb, 0, '{}'::jsonb, 'COMPLETED', :idem,
                        '[]'::jsonb, '[{"target": "status", "expected_value": "OK"}]'::jsonb, :now
                    );
                    """
                ),
                {
                    "aid": a_id,
                    "tid": tenant_id,
                    "txnid": tx_id,
                    "actorid": f"actor_{tenant_id}",
                    "toolid": f"tool_{tenant_id}",
                    "idem": f"idem_rb_{uuid.uuid4().hex[:6]}",
                    "now": now,
                },
            )
            conn.commit()

        service = RealityVerifierService()
        auth = AuthContext(
            tenant_id=tenant_id,
            user_id="op_rb",
            role=Role.OPERATOR,
            identity_id=f"actor_{tenant_id}",
        )
        req = OutcomeVerificationRequest(
            transaction_id=tx_id,
            action_id=a_id,
            observability_class=ObservabilityClass.OBS_DIRECT,
            verifier_type=OutcomeVerifierType.SIMULATED,
            expected_postconditions={"status": "OK"},
            adapter_config={"simulated_state": {"status": "OK"}, "allow_simulated_for_test": True},
        )

        # Patch _append_audit_trail_entry to simulate database or ledger-head crash
        with patch.object(
            service,
            "_append_audit_trail_entry",
            side_effect=RuntimeError("Simulated ledger failure during audit append"),
        ):
            with pytest.raises(RuntimeError, match="Simulated ledger failure during audit append"):
                await service.verify_action_outcome(req, auth)

        # Verify atomic rollback in PostgreSQL
        with sync_engine.connect() as conn:
            # 1. No outcome verification record exists
            outcomes = conn.execute(
                text("SELECT count(*) FROM outcome_verification_records WHERE tenant_id = :tid AND action_id = :aid"),
                {"tid": tenant_id, "aid": a_id},
            ).scalar()
            assert outcomes == 0, "OutcomeVerificationRecord must not be committed upon rollback"

            # 2. No audit log entry exists
            audits = conn.execute(
                text("SELECT count(*) FROM audit_logs WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            ).scalar()
            assert audits == 0, "AuditLogRecord must not be committed upon rollback"

            # 3. ActionContract state remains COMPLETED and outcome_status is NULL
            contract_row = conn.execute(
                text("SELECT state, outcome_status FROM action_contracts WHERE id = :aid"),
                {"aid": a_id},
            ).fetchone()
            assert contract_row is not None
            assert contract_row[0] == ActionState.COMPLETED.value
            assert contract_row[1] is None, "ActionContract outcome_status must remain NULL"

            # 4. Tenant audit ledger head does not exist or has sequence_number == 0
            head = conn.execute(
                text("SELECT sequence_number FROM tenant_audit_ledgers WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            ).fetchone()
            assert head is None or head[0] == 0, "TenantAuditLedger sequence must not advance on rollback"

    @pytest.mark.asyncio
    async def test_advisory_lock_is_transaction_scoped(self, sync_engine: Any) -> None:
        """PostgreSQL transaction-scoped advisory lock is acquired and released automatically."""
        tenant_id = f"t_adv_{uuid.uuid4().hex[:8]}"

        async with db_session.get_tenant_session(tenant_id) as session:
            # Lock is acquired inside session.begin()
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('tenant_audit_ledger:' || :tenant_id))"),
                {"tenant_id": tenant_id},
            )
            # Verify lock is active in pg_locks
            res = await session.execute(
                text(
                    """
                    SELECT count(*) FROM pg_locks
                    WHERE locktype = 'advisory' AND objid = hashtext('tenant_audit_ledger:' || :tenant_id)::oid;
                    """
                ),
                {"tenant_id": tenant_id},
            )
            count = res.scalar()
            assert count == 1, "Advisory lock must be active during transaction"

        # After session exit (commit/close), verify lock is released
        with sync_engine.connect() as conn:
            res = conn.execute(
                text(
                    """
                    SELECT count(*) FROM pg_locks
                    WHERE locktype = 'advisory' AND objid = hashtext('tenant_audit_ledger:' || :tenant_id)::oid;
                    """
                ),
                {"tenant_id": tenant_id},
            ).scalar()
            assert res == 0, "Transaction-scoped advisory lock must be released immediately upon commit/rollback"

    @pytest.mark.asyncio
    async def test_simultaneous_approval_consumption_race_condition(self, sync_engine: Any) -> None:
        """Simultaneous concurrent calls attempting to execute using the same approval token.

        Demonstrates that:
        - Row-level lock (`with_for_update`) on ActionContract and ActionApproval serializes callers.
        - Exactly ONE concurrent caller succeeds and marks the approval CONSUMED.
        - The competing concurrent caller fails closed with HTTP 409 or HTTP 403.
        - Exactly ONE execution occurs, preventing duplicate side effects.
        """
        tenant_id = f"t_appr_race_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        actor_sub = f"actor_{uuid.uuid4().hex[:8]}"
        actor_id = f"ident_{actor_sub}"
        tool_id = f"tool_{uuid.uuid4().hex[:8]}"
        cap_id = f"cap_{uuid.uuid4().hex[:8]}"
        tx_id = f"txn_{uuid.uuid4().hex[:8]}"
        action_id = f"act_{uuid.uuid4().hex[:8]}"
        approval_id = f"appr_{uuid.uuid4().hex[:8]}"

        tool_name = "controlled_test_probe"
        required_capability = "probe:execute"
        params = {"operation": "health_check"}
        norm_params = params
        cost = 2500.0

        p_hash = compute_parameters_hash(norm_params)
        binding_hash = compute_contract_binding_hash(
            tenant_id=tenant_id,
            transaction_id=tx_id,
            action_id=action_id,
            tool_name=tool_name,
            action_type="EXECUTE",
            target_resource="system://probe",
            parameters_hash=p_hash,
            required_capability=required_capability,
            estimated_dollar_cost=cost,
            taint_flags=[],
        )

        with sync_engine.connect() as conn:
            conn.execute(
                text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:id, 'Race Test', :hash, :now)"),
                {"id": tenant_id, "hash": uuid.uuid4().hex[:32], "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at)
                    VALUES (:aid, :tid, :sub, 'USER', 'API_CLIENT', true, :now);
                    """
                ),
                {"aid": actor_id, "tid": tenant_id, "sub": actor_sub, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO tool_registry (
                        id, tenant_id, name, tool_type, egress_type, trust_level,
                        required_capability, active, created_at, updated_at
                    )
                    VALUES (:tool_id, :tid, :tname, 'NATIVE', 'INTERNAL_ISOLATED', 'VERIFIED', :cap, true, :now, :now);
                    """
                ),
                {"tool_id": tool_id, "tid": tenant_id, "tname": tool_name, "cap": required_capability, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO capabilities (
                        id, tenant_id, identity_id, capability_type, max_autonomy_level, created_at
                    )
                    VALUES (:cid, :tid, :aid, :cap, 4, :now);
                    """
                ),
                {"cid": cap_id, "tid": tenant_id, "aid": actor_id, "cap": required_capability, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ai_transactions (
                        id, tenant_id, actor_identity_id, idempotency_key, correlation_id,
                        state, max_turns, created_at, updated_at
                    )
                    VALUES (:txnid, :tid, :aid, :txnid, :txnid, 'TURN_REASONING', 10, :now, :now);
                    """
                ),
                {"txnid": tx_id, "tid": tenant_id, "aid": actor_id, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO action_contracts (
                        id, tenant_id, transaction_id, actor_identity_id, tool_id, tool_name,
                        action_type, target_resource, parameters, normalized_parameters, parameters_hash,
                        required_capability, taint_flags, risk_score, blast_radius, state, idempotency_key,
                        preconditions, postconditions, approval_id, created_at
                    ) VALUES (
                        :aid, :tid, :txnid, :actorid, :toolid, :toolname,
                        'EXECUTE', 'system://probe',
                        '{"operation": "health_check"}'::jsonb,
                        '{"operation": "health_check"}'::jsonb,
                        :phash, :reqcap, '[]'::jsonb, 75,
                        '{"target_environment": "PROD", "estimated_dollar_cost": 2500.0}'::jsonb,
                        'AUTHORIZED', :idem, '[]'::jsonb, '[]'::jsonb, :apprid, :now
                    );
                    """
                ),
                {
                    "aid": action_id,
                    "tid": tenant_id,
                    "txnid": tx_id,
                    "actorid": actor_id,
                    "toolid": tool_id,
                    "toolname": tool_name,
                    "phash": p_hash,
                    "reqcap": required_capability,
                    "idem": f"idem_act_{uuid.uuid4().hex[:6]}",
                    "apprid": approval_id,
                    "now": now,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO action_approvals (
                        id, tenant_id, action_id, transaction_id, required_role, status,
                        parameters_hash, requested_by, decided_by, decision_reason, expires_at, created_at, decided_at
                    ) VALUES (
                        :apprid, :tid, :aid, :txnid, 'SUPER_ADMIN', 'GRANTED',
                        :bhash, :reqby, 'admin_super', 'Granted probe execution', :exp, :now, :now
                    );
                    """
                ),
                {
                    "apprid": approval_id,
                    "tid": tenant_id,
                    "aid": action_id,
                    "txnid": tx_id,
                    "bhash": binding_hash,
                    "reqby": actor_id,
                    "exp": now + timedelta(hours=1),
                    "now": now,
                },
            )
            conn.commit()

        governor = ActionGovernorService()
        auth = AuthContext(
            tenant_id=tenant_id,
            user_id=actor_sub,
            role=Role.API_CLIENT,
            identity_id=actor_id,
        )
        req = ActionExecutionRequest(action_id=action_id)

        # Launch two simultaneous execution attempts racing for the single approval
        results = await asyncio.gather(
            governor.execute_action(auth, req),
            governor.execute_action(auth, req),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        assert len(successes) == 1, f"Exactly one execution must succeed, got {len(successes)}: {results}"
        assert len(failures) == 1, f"Exactly one execution must fail, got {len(failures)}: {results}"

        winning_result = successes[0]
        assert winning_result.state in (ActionState.EXECUTED, ActionState.COMPLETED)
        assert winning_result.observed_output.get("probe_executed") is True

        losing_exc = failures[0]
        assert isinstance(losing_exc, HTTPException), f"Failure must be HTTPException, got {type(losing_exc)}"
        # Loser observes either 409 (contract is already EXECUTING/EXECUTED) or 403 (approval already CONSUMED)
        assert losing_exc.status_code in (403, 409)
        assert any(
            phrase in losing_exc.detail.lower()
            for phrase in ["already been consumed", "currently executing", "already executed"]
        )

        # Verify database state in PostgreSQL
        with sync_engine.connect() as conn:
            appr_row = conn.execute(
                text("SELECT status FROM action_approvals WHERE id = :apprid"),
                {"apprid": approval_id},
            ).fetchone()
            assert appr_row is not None
            assert appr_row[0] == ApprovalStatus.CONSUMED.value

            contract_row = conn.execute(
                text("SELECT state FROM action_contracts WHERE id = :aid"),
                {"aid": action_id},
            ).fetchone()
            assert contract_row is not None
            assert contract_row[0] in (ActionState.EXECUTED.value, ActionState.COMPLETED.value)

    @pytest.mark.asyncio
    async def test_approval_rollback_on_pre_dispatch_aborted_transaction(self, sync_engine: Any) -> None:
        """Failure before pre-dispatch transaction commits rolls back approval to GRANTED."""
        tenant_id = f"t_appr_rb_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        actor_sub = f"actor_{uuid.uuid4().hex[:8]}"
        actor_id = f"ident_{actor_sub}"
        tool_id = f"tool_{uuid.uuid4().hex[:8]}"
        cap_id = f"cap_{uuid.uuid4().hex[:8]}"
        tx_id = f"txn_{uuid.uuid4().hex[:8]}"
        action_id = f"act_{uuid.uuid4().hex[:8]}"
        approval_id = f"appr_{uuid.uuid4().hex[:8]}"

        tool_name = "controlled_test_probe"
        required_capability = "probe:execute"
        params = {"operation": "health_check"}
        cost = 2500.0

        p_hash = compute_parameters_hash(params)
        binding_hash = compute_contract_binding_hash(
            tenant_id=tenant_id,
            transaction_id=tx_id,
            action_id=action_id,
            tool_name=tool_name,
            action_type="EXECUTE",
            target_resource="system://probe",
            parameters_hash=p_hash,
            required_capability=required_capability,
            estimated_dollar_cost=cost,
            taint_flags=[],
        )

        with sync_engine.connect() as conn:
            conn.execute(
                text("INSERT INTO tenants (id, name, api_key_hash, created_at) VALUES (:id, 'RB Appr', :hash, :now)"),
                {"id": tenant_id, "hash": uuid.uuid4().hex[:32], "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO actor_identities (id, tenant_id, subject, principal_type, role, active, created_at)
                    VALUES (:aid, :tid, :sub, 'USER', 'API_CLIENT', true, :now);
                    """
                ),
                {"aid": actor_id, "tid": tenant_id, "sub": actor_sub, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO tool_registry (
                        id, tenant_id, name, tool_type, egress_type, trust_level,
                        required_capability, active, created_at, updated_at
                    )
                    VALUES (:tool_id, :tid, :tname, 'NATIVE', 'INTERNAL_ISOLATED', 'VERIFIED', :cap, true, :now, :now);
                    """
                ),
                {"tool_id": tool_id, "tid": tenant_id, "tname": tool_name, "cap": required_capability, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO capabilities (
                        id, tenant_id, identity_id, capability_type, max_autonomy_level, created_at
                    )
                    VALUES (:cid, :tid, :aid, :cap, 4, :now);
                    """
                ),
                {"cid": cap_id, "tid": tenant_id, "aid": actor_id, "cap": required_capability, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ai_transactions (
                        id, tenant_id, actor_identity_id, idempotency_key, correlation_id,
                        state, max_turns, created_at, updated_at
                    )
                    VALUES (:txnid, :tid, :aid, :txnid, :txnid, 'TURN_REASONING', 10, :now, :now);
                    """
                ),
                {"txnid": tx_id, "tid": tenant_id, "aid": actor_id, "now": now},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO action_contracts (
                        id, tenant_id, transaction_id, actor_identity_id, tool_id, tool_name,
                        action_type, target_resource, parameters, normalized_parameters, parameters_hash,
                        required_capability, taint_flags, risk_score, blast_radius, state, idempotency_key,
                        preconditions, postconditions, approval_id, created_at
                    ) VALUES (
                        :aid, :tid, :txnid, :actorid, :toolid, :toolname,
                        'EXECUTE', 'system://probe',
                        '{"operation": "health_check"}'::jsonb,
                        '{"operation": "health_check"}'::jsonb,
                        :phash, :reqcap, '[]'::jsonb, 75,
                        '{"target_environment": "PROD", "estimated_dollar_cost": 2500.0}'::jsonb,
                        'AUTHORIZED', :idem, '[]'::jsonb, '[]'::jsonb, :apprid, :now
                    );
                    """
                ),
                {
                    "aid": action_id,
                    "tid": tenant_id,
                    "txnid": tx_id,
                    "actorid": actor_id,
                    "toolid": tool_id,
                    "toolname": tool_name,
                    "phash": p_hash,
                    "reqcap": required_capability,
                    "idem": f"idem_act_rb_{uuid.uuid4().hex[:6]}",
                    "apprid": approval_id,
                    "now": now,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO action_approvals (
                        id, tenant_id, action_id, transaction_id, required_role, status,
                        parameters_hash, requested_by, decided_by, decision_reason, expires_at, created_at, decided_at
                    ) VALUES (
                        :apprid, :tid, :aid, :txnid, 'SUPER_ADMIN', 'GRANTED',
                        :bhash, :reqby, 'admin_super', 'Granted probe execution', :exp, :now, :now
                    );
                    """
                ),
                {
                    "apprid": approval_id,
                    "tid": tenant_id,
                    "aid": action_id,
                    "txnid": tx_id,
                    "bhash": binding_hash,
                    "reqby": actor_id,
                    "exp": now + timedelta(hours=1),
                    "now": now,
                },
            )
            conn.commit()

        governor = ActionGovernorService()
        auth = AuthContext(
            tenant_id=tenant_id,
            user_id=actor_sub,
            role=Role.API_CLIENT,
            identity_id=actor_id,
        )
        req = ActionExecutionRequest(action_id=action_id)

        # Inject an exception immediately after approval validation inside _pre_dispatch_and_commit_executing
        with patch.object(
            governor,
            "_revalidate_execution_capability",
            side_effect=RuntimeError("Simulated infrastructure fault during pre-dispatch"),
        ):
            with pytest.raises(RuntimeError, match="Simulated infrastructure fault during pre-dispatch"):
                await governor.execute_action(auth, req)

        # Verify that ActionApproval rolled back to GRANTED and ActionContract remains AUTHORIZED
        with sync_engine.connect() as conn:
            appr = conn.execute(
                text("SELECT status FROM action_approvals WHERE id = :apprid"),
                {"apprid": approval_id},
            ).fetchone()
            assert appr is not None
            assert appr[0] == ApprovalStatus.GRANTED.value, "Approval status must roll back to GRANTED upon abort"

            contract = conn.execute(
                text("SELECT state FROM action_contracts WHERE id = :aid"),
                {"aid": action_id},
            ).fetchone()
            assert contract is not None
            assert contract[0] == ActionState.AUTHORIZED.value, "ActionContract must remain AUTHORIZED upon abort"
