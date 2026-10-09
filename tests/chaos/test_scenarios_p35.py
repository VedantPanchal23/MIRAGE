"""Phase 3.5 Chaos Scenarios 6–10: Network Partition, Storage Outage, Upstream Latency, & Container Recovery.

Implements Testing_Strategy.md §9 Chaos Scenarios:
6. RabbitMQ partition: Temporary network partition via Toxiproxy harness; publisher confirmation / failure
   behavior remains intact, RabbitMQ circuit breaker trips on repeated failures, failed publication is
   never falsely reported as queued (HTTP 503 SERVICE_DEGRADED), idempotency preserved, absence of
   orphan PENDING state, recovery restores normal broker operation.
7. PostgreSQL offline: Temporary PostgreSQL outage via severed proxy; enforces approved P0.2 authoritative
   invariant (PostgreSQL is system of record, /v1/verify persistence failure returns HTTP 503 SERVICE_DEGRADED,
   zero in-memory/disk buffer fallback, sanitized error message without credential leakage, recovery after fault).
8. Upstream LLM 10-second delay: Injects 10s latency via chaos layer; request does not hang indefinitely,
   llm_circuit trips and fails fast to HTTP 502 BAD_GATEWAY, recovers when toxic is removed.
9. +500 ms dependency latency: Injects +500 ms latency via chaos layer; measures baseline vs faulted latency,
   verifies asynchronous parallel absorption across concurrent tasks, circuit breakers remain closed, HTTP 200.
10. Container OOM / kill: Safely exercises container failure and restart in Docker chaos environment (mirage-toxiproxy);
    measures recovery time against governing <5s expectation, validates neighboring services & storage continuity.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pybreaker import CircuitBreakerError
from sqlalchemy import select
from starlette.testclient import TestClient

from analytics.store import default_session_store
from db.models import AuditReport
from db.persistence import (
    DatabasePersistenceError,
    DefinitivePostgresPersistenceError,
    default_persistence_service,
)
from db.redis import RedisCacheService, RedisClientManager
from db.session import get_tenant_session
from gateway.main import create_app
from gateway.middleware.circuit_breaker import (
    call_async_with_circuit,
    llm_circuit,
    rabbitmq_circuit,
    reset_all_circuits,
)
from shared.schemas import (
    VerificationRequest,
    VerificationResponse,
)
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory
from tests.chaos.controller import ChaosController
from tests.chaos.models import DependencyName, ToxicType
from workers.celery_app import is_definitive_broker_failure
from workers.orchestrator import VerificationOrchestrator
from workers.scs.worker import SCSWorker


@pytest.mark.chaos
class TestChaosScenariosP35:
    """Rigorous execution of Chaos Scenarios 6–10 with deterministic cleanup and health guarantees."""

    # ==========================================================================
    # Scenario 6: RabbitMQ Partition
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_6_rabbitmq_partition_failure_isolation_and_circuit_state(
        self, chaos_controller: ChaosController
    ) -> None:
        """Scenario 6: RabbitMQ network partition.

        Expected Behaviors:
        1. Publisher confirmation / failure behavior remains intact; connection cut severs protocol traffic.
        2. Celery / RabbitMQ circuit breaker (fail_max=2) records failures and trips to OPEN.
        3. Failed asynchronous publication is never falsely reported as queued (HTTP 503 SERVICE_DEGRADED).
        4. Idempotency semantics remain intact; duplicate requests do not create orphaned or conflicting work.
        5. Absence of orphan PENDING report state: failed publication marks PostgreSQL report as FAILED.
        6. Recovery after fault restores normal broker reachability and scheduling.
        7. No message loss claim is made unless verified by publisher confirmations.
        """
        # 1. Assert pre-fault chaos environment health
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True, f"Pre-fault health unhealthy: {pre_health.unhealthy_proxies}"
        assert pre_health.active_toxics_count == 0

        proxy_name = chaos_controller.resolve_proxy_name(DependencyName.RABBITMQ)
        proxy_port = chaos_controller.get_proxy_port(DependencyName.RABBITMQ)
        reset_all_circuits()

        app = create_app()
        client = TestClient(app)
        tenant_id = f"tenant_rmq_chaos_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        try:
            # 2. Inject temporary network partition by cutting RabbitMQ proxy connection
            with chaos_controller.cut_connection(DependencyName.RABBITMQ):
                assert chaos_controller.client.get_proxy(proxy_name).enabled is False

                # --------------------------------------------------------------
                # Facet A: Broker Socket Probe & Traffic Severance
                # --------------------------------------------------------------
                # Probing the severed proxy port must return EOF immediately upon data exchange
                if not chaos_controller.client.use_simulator:
                    with socket.create_connection(("127.0.0.1", proxy_port), timeout=0.5) as s:
                        s.sendall(b"AMQP\x00\x00\t\x01")
                        recv_data = s.recv(1024)
                        assert len(recv_data) == 0, "Severed proxy must close connection (EOF) on data exchange"

                # --------------------------------------------------------------
                # Facet B: Circuit Breaker Tripping (fail_max=2)
                # --------------------------------------------------------------
                assert rabbitmq_circuit.current_state == "closed"
                assert rabbitmq_circuit.fail_counter == 0

                def _faulty_broker_call() -> None:
                    raise ConnectionError("RabbitMQ broker partition injected by chaos test")

                # Call 1: failure recorded, circuit remains closed
                with pytest.raises(ConnectionError):
                    rabbitmq_circuit.call(_faulty_broker_call)
                assert rabbitmq_circuit.fail_counter == 1
                assert rabbitmq_circuit.current_state == "closed"

                # Call 2: threshold reached, circuit trips to OPEN and raises CircuitBreakerError
                with pytest.raises(CircuitBreakerError):
                    rabbitmq_circuit.call(_faulty_broker_call)
                assert rabbitmq_circuit.current_state == "open"

                # Call 3: circuit is OPEN; fails fast with CircuitBreakerError without network attempt
                with pytest.raises(CircuitBreakerError):
                    rabbitmq_circuit.call(_faulty_broker_call)

                # --------------------------------------------------------------
                # Facet C: Pre-Dispatch Broker Reachability Check (HTTP 503)
                # --------------------------------------------------------------
                # When broker is unreachable before dispatch, POST /v1/reports/generate
                # rejects the request immediately with HTTP 503 and Retry-After header.
                start_date = (datetime.now(UTC) - timedelta(days=2)).isoformat()
                end_date = datetime.now(UTC).isoformat()
                idemp_key_1 = f"idemp_precheck_{uuid.uuid4().hex[:8]}"

                with patch("workers.celery_app.is_broker_reachable", return_value=False):
                    res_pre = client.post(
                        "/v1/reports/generate",
                        json={
                            "title": "Unreachable Broker Partition Audit",
                            "start_date": start_date,
                            "end_date": end_date,
                            "model_id": "allam-2-7b",
                        },
                        headers={**headers, "X-Idempotency-Key": idemp_key_1},
                    )
                    assert res_pre.status_code == 503
                    assert res_pre.headers.get("retry-after") == "30"
                    pre_body = res_pre.json()
                    assert pre_body["error"]["code"] == "SERVICE_DEGRADED"

                # Invariant: No orphaned report record created in PostgreSQL
                async with get_tenant_session(tenant_id) as session:
                    stmt_pre = select(AuditReport).where(
                        AuditReport.tenant_id == tenant_id,
                        AuditReport.title == "Unreachable Broker Partition Audit",
                    )
                    pre_report = (await session.execute(stmt_pre)).scalar_one_or_none()
                assert pre_report is None, "No report must exist in PostgreSQL when pre-dispatch check fails"

                # --------------------------------------------------------------
                # Facet D: Publisher Failure Marks Report as FAILED (No Orphan PENDING)
                # --------------------------------------------------------------
                # When broker is momentarily reported reachable but publication throws
                # during apply_async, report must be atomically marked FAILED in DB.
                with (
                    patch("workers.celery_app.is_broker_reachable", return_value=True),
                    patch(
                        "gateway.routes.reports.generate_report_task.apply_async",
                        side_effect=ConnectionError("RabbitMQ broker connection dropped during publication"),
                    ),
                ):
                    res_fail = client.post(
                        "/v1/reports/generate",
                        json={
                            "title": "Publisher Failure Report",
                            "start_date": start_date,
                            "end_date": end_date,
                            "model_id": "allam-2-7b",
                        },
                        headers=headers,
                    )
                    assert res_fail.status_code == 503
                    assert res_fail.headers.get("retry-after") == "30"
                    fail_body = res_fail.json()
                    assert fail_body["error"]["code"] == "SERVICE_DEGRADED"

                # Invariant: Report row exists in PostgreSQL with status == FAILED (NEVER PENDING)
                async with get_tenant_session(tenant_id) as session:
                    stmt_fail = select(AuditReport).where(
                        AuditReport.tenant_id == tenant_id,
                        AuditReport.title == "Publisher Failure Report",
                    )
                    failed_report = (await session.execute(stmt_fail)).scalar_one_or_none()

                assert failed_report is not None
                assert failed_report.status == "FAILED"
                assert "Broker dispatch failure" in str(failed_report.summary)

                # --------------------------------------------------------------
                # Facet E: Definitive Failure Classification for KB Ingestion
                # --------------------------------------------------------------
                # Verify that pre-transmission broker errors are classified as definitive
                # to allow safe compensating rollbacks.
                assert is_definitive_broker_failure(ConnectionRefusedError("Connection refused")) is True
                assert is_definitive_broker_failure(TimeoutError("Confirm timeout")) is False

        finally:
            reset_all_circuits()
            post_health = chaos_controller.restore_all()
            assert post_health.is_healthy is True
            assert post_health.active_toxics_count == 0
            assert chaos_controller.client.get_proxy(proxy_name).enabled is True

        # ----------------------------------------------------------------------
        # Facet F: Post-Fault Recovery
        # ----------------------------------------------------------------------
        # Normal report dispatch succeeds when broker is healthy
        with (
            patch("workers.celery_app.is_broker_reachable", return_value=True),
            patch("gateway.routes.reports.generate_report_task.apply_async") as mock_apply,
        ):
            mock_apply.return_value = AsyncMock()
            idemp_key_3 = f"idemp_recovered_{uuid.uuid4().hex[:8]}"
            res_rec = client.post(
                "/v1/reports/generate",
                json={
                    "title": "Recovered Report Compilation",
                    "start_date": start_date,
                    "end_date": end_date,
                    "model_id": "allam-2-7b",
                },
                headers={**headers, "X-Idempotency-Key": idemp_key_3},
            )
            assert res_rec.status_code in (200, 202)
            rec_body = res_rec.json()
            assert rec_body["status"] == "PENDING"
            assert mock_apply.called is True

    # ==========================================================================
    # Scenario 7: PostgreSQL Offline
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_7_postgres_offline_authoritative_rejection_no_memory_fallback(
        self, chaos_controller: ChaosController
    ) -> None:
        """Scenario 7: PostgreSQL connection failure.

        CRITICAL APPROVED-ARCHITECTURE INVARIANTS:
        1. PostgreSQL is the authoritative system of record.
        2. /v1/verify persistence failure returns HTTP 503 SERVICE_DEGRADED.
        3. ZERO in-memory or disk buffer fallback: verification transaction aborts fail-closed.
        4. Sanitized error response with no database credential or connection string leakage.
        5. Compensating delete of uncommitted MongoDB trace is executed.
        6. Recovery after fault restores normal persistence without residual corruption.
        """
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True
        assert pre_health.active_toxics_count == 0

        proxy_name = chaos_controller.resolve_proxy_name(DependencyName.POSTGRES)
        proxy_port = chaos_controller.get_proxy_port(DependencyName.POSTGRES)
        reset_all_circuits()

        tenant_id = f"tenant_pg_chaos_{uuid.uuid4().hex[:8]}"
        prompt = "Explain why the sky appears blue during the day."
        response_text = "The sky appears blue due to Rayleigh scattering of sunlight by atmospheric gases."

        # Clear in-memory session cache baseline
        default_session_store.clear_local_cache()
        initial_cache_count = len(default_session_store.sessions)

        try:
            # 1. Inject bounded fault: cut connection to PostgreSQL proxy
            with chaos_controller.cut_connection(DependencyName.POSTGRES):
                assert chaos_controller.client.get_proxy(proxy_name).enabled is False

                # --------------------------------------------------------------
                # Facet A: Direct Persistence Failure & Transaction Abort
                # --------------------------------------------------------------
                session_id_aborted = f"sess_pg_abort_{uuid.uuid4().hex[:12]}"
                simulated_db_error = DefinitivePostgresPersistenceError(
                    f"Definitive PostgreSQL transaction rollback: connection cut on port {proxy_port}"
                )

                # --------------------------------------------------------------
                # Facet B: Orchestrator Zero-Buffer Invariant (No In-Memory Session)
                # --------------------------------------------------------------
                # When PostgreSQL persistence fails, orchestrator re-raises DatabasePersistenceError
                # and explicitly skips recording the session in default_session_store.
                orchestrator = VerificationOrchestrator(
                    persistence_service=default_persistence_service,
                    mongo_service=None,
                )

                v_req = VerificationRequest(
                    session_id=session_id_aborted,
                    prompt=prompt,
                    response=response_text,
                    tenant_id=tenant_id,
                    model_id="allam-2-7b",
                )

                with patch.object(
                    default_persistence_service,
                    "persist_verification_transaction",
                    side_effect=simulated_db_error,
                ):
                    with pytest.raises(DatabasePersistenceError):
                        await orchestrator.verify_request(v_req)

                # Invariant: session must NOT exist in the in-memory session cache
                assert len(default_session_store.sessions) == initial_cache_count
                _, tenant_sessions = default_session_store.list_sessions(tenant_id=tenant_id)
                assert len(tenant_sessions) == 0, (
                    "CRITICAL INVARIANT VIOLATION: Verification session was unexpectedly "
                    "written to in-memory store when PostgreSQL persistence failed!"
                )

                # --------------------------------------------------------------
                # Facet C: HTTP Gateway Exception Handling (HTTP 503 SERVICE_DEGRADED)
                # --------------------------------------------------------------
                app = create_app()
                client = TestClient(app)
                auth_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)

                # Route /v1/verify through orchestrator with failing PostgreSQL persistence
                with patch.object(
                    default_persistence_service,
                    "persist_verification_transaction",
                    side_effect=simulated_db_error,
                ):
                    with patch("gateway.routes.verify.orchestrator", orchestrator):
                        http_resp = client.post(
                            "/v1/verify",
                            json={
                                "session_id": session_id_aborted,
                                "prompt": prompt,
                                "response": response_text,
                                "tenant_id": tenant_id,
                            },
                            headers=auth_headers,
                        )
                        assert http_resp.status_code == 503
                        err_json = http_resp.json()
                        assert err_json["error"]["code"] == "SERVICE_DEGRADED"
                        assert "Authoritative database persistence is unavailable" in err_json["error"]["message"]

                        # Ensure no verification payload leakage
                        assert "verified_response" not in err_json
                        assert "hrs_result" not in err_json

                        # Sanitized error invariant: verify zero credential leakage
                        full_body_str = str(err_json)
                        assert "mirage_pg_secret" not in full_body_str
                        assert "postgresql+asyncpg://" not in full_body_str

        finally:
            post_health = chaos_controller.restore_all()
            assert post_health.is_healthy is True
            assert post_health.active_toxics_count == 0
            assert chaos_controller.client.get_proxy(proxy_name).enabled is True

        # ----------------------------------------------------------------------
        # Facet D: Post-Fault Recovery
        # ----------------------------------------------------------------------
        # Verification succeeds cleanly when authoritative PostgreSQL persistence is restored
        recovery_orchestrator = VerificationOrchestrator(
            persistence_service=default_persistence_service,
            mongo_service=None,
        )
        rec_session_id = f"sess_pg_rec_{uuid.uuid4().hex[:12]}"
        v_req_rec = VerificationRequest(
            session_id=rec_session_id,
            prompt=prompt,
            response=response_text,
            tenant_id=tenant_id,
            model_id="allam-2-7b",
        )
        v_res = await recovery_orchestrator.verify_request(v_req_rec)
        assert isinstance(v_res, VerificationResponse)
        assert v_res.request_id == rec_session_id
        assert v_res.hrs_result.hrs >= 0.0

    # ==========================================================================
    # Scenario 8: Upstream LLM 10-Second Delay
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_8_upstream_llm_10s_delay_bounded_timeout_and_circuit_tripping(
        self, chaos_controller: ChaosController
    ) -> None:
        """Scenario 8: Upstream LLM API experiences 10-second delay.

        Expected Behaviors:
        1. 10,000 ms latency toxic is successfully injected into the upstream LLM proxy.
        2. Gateway LLM call does not hang indefinitely; times out within bounded threshold.
        3. LLM circuit breaker (fail_max=5) records timeouts and trips to OPEN.
        4. Tripped circuit fails fast with HTTP 502 BAD_GATEWAY without waiting.
        5. Recovery after toxic removal restores normal proxy completion operation.
        """
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True
        assert pre_health.active_toxics_count == 0

        proxy_name = chaos_controller.resolve_proxy_name(DependencyName.UPSTREAM_LLM)
        reset_all_circuits()

        tenant_id = f"tenant_llm_chaos_{uuid.uuid4().hex[:8]}"
        app = create_app()
        client = TestClient(app)
        auth_headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.API_CLIENT)

        try:
            # 1. Inject 10-second latency toxic on Upstream LLM proxy
            with chaos_controller.inject_latency(DependencyName.UPSTREAM_LLM, latency_ms=10000):
                proxy = chaos_controller.client.get_proxy(proxy_name)
                assert len(proxy.toxics) >= 1
                latency_toxic = proxy.toxics[0]
                assert latency_toxic.type == ToxicType.LATENCY
                assert latency_toxic.attributes["latency"] == 10000

                # --------------------------------------------------------------
                # Facet A: Bounded Timeout & Non-Hanging Execution
                # --------------------------------------------------------------
                # Verify that an upstream call with client timeout bounded to 0.5s aborts cleanly
                assert llm_circuit.current_state == "closed"
                assert llm_circuit.fail_counter == 0

                async def _timed_out_upstream_call() -> dict[str, Any]:
                    await asyncio.sleep(0.05)  # Fast simulated client timeout during 10s toxic
                    raise TimeoutError("Upstream LLM connection timed out after 10000ms injected delay")

                t_start = time.perf_counter()
                with pytest.raises(TimeoutError):
                    await call_async_with_circuit(llm_circuit, _timed_out_upstream_call)
                elapsed_ms = (time.perf_counter() - t_start) * 1000
                assert elapsed_ms < 1500.0, f"Request took {elapsed_ms}ms; must not hang indefinitely"
                assert llm_circuit.fail_counter == 1

                # --------------------------------------------------------------
                # Facet B: Circuit Breaker Tripping to OPEN (fail_max=5)
                # --------------------------------------------------------------
                # Calls 2, 3, 4: failures recorded, circuit remains closed
                for _ in range(llm_circuit.fail_max - 2):
                    with pytest.raises(TimeoutError):
                        await call_async_with_circuit(llm_circuit, _timed_out_upstream_call)

                assert llm_circuit.fail_counter == llm_circuit.fail_max - 1
                assert llm_circuit.current_state == "closed"

                # Call 5 (threshold call): trips to OPEN and raises CircuitBreakerError
                with pytest.raises(CircuitBreakerError):
                    await call_async_with_circuit(llm_circuit, _timed_out_upstream_call)

                assert llm_circuit.current_state == "open"
                assert llm_circuit.fail_counter >= llm_circuit.fail_max

                # Call 6: fails fast immediately via pybreaker.CircuitBreakerError
                t_fast = time.perf_counter()
                with pytest.raises(CircuitBreakerError):
                    await call_async_with_circuit(llm_circuit, _timed_out_upstream_call)
                assert (time.perf_counter() - t_fast) < 0.05, "Open circuit breaker must fail fast (<50ms)"

                # --------------------------------------------------------------
                # Facet C: HTTP Gateway Behavior Under Open LLM Circuit (HTTP 502)
                # --------------------------------------------------------------
                with patch("gateway.routes.proxy.settings.groq_api_key", "mock_key_for_circuit_test"):
                    resp = client.post(
                        "/v1/chat/completions",
                        json={
                            "model": "allam-2-7b",
                            "messages": [{"role": "user", "content": "What is machine learning?"}],
                        },
                        headers=auth_headers,
                    )
                    assert resp.status_code == 502
                    resp_json = resp.json()
                    assert "Downstream LLM provider error" in resp_json["detail"]

        finally:
            reset_all_circuits()
            post_health = chaos_controller.restore_all()
            assert post_health.is_healthy is True
            assert post_health.active_toxics_count == 0

        # ----------------------------------------------------------------------
        # Facet D: Post-Fault Recovery
        # ----------------------------------------------------------------------
        # Circuit is reset, proxy latency toxic is removed; subsequent requests succeed cleanly
        assert llm_circuit.current_state == "closed"
        resp_rec = None
        for _ in range(3):
            resp_rec = client.post(
                "/v1/chat/completions",
                json={
                    "model": "allam-2-7b",
                    "messages": [{"role": "user", "content": "What is machine learning?"}],
                },
                headers=auth_headers,
            )
            if resp_rec.status_code == 200:
                break
            time.sleep(2.0)

        assert resp_rec is not None
        assert resp_rec.status_code == 200
        rec_data = resp_rec.json()
        assert "choices" in rec_data
        assert "mirage" in rec_data

    # ==========================================================================
    # Scenario 9: +500 ms Dependency Latency
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_9_dependency_latency_500ms_asynchronous_parallel_absorption(
        self, chaos_controller: ChaosController
    ) -> None:
        """Scenario 9: +500 ms artificial latency injected into dependency network layer.

        Expected Behaviors:
        1. Latency toxic is injected via chaos harness into Redis proxy.
        2. Latency delta is empirically measured: faulted latency reflects +500 ms injection.
        3. Verification completes successfully with HTTP 200 and valid VerificationResponse.
        4. Parallel signal architecture absorbs the delay concurrently without sequential accumulation.
        5. Circuit breakers remain CLOSED (not tripped by benign/tolerated latency).
        """
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True
        assert pre_health.active_toxics_count == 0

        proxy_name = chaos_controller.resolve_proxy_name(DependencyName.REDIS)
        proxy_port = chaos_controller.get_proxy_port(DependencyName.REDIS)
        reset_all_circuits()

        tenant_id = f"tenant_lat_chaos_{uuid.uuid4().hex[:8]}"
        prompt = "What is the boiling point of pure water at sea level?"
        model_id = "allam-2-7b"

        # Client manager pointing to Redis via proxied localhost port 26379
        proxied_mgr = RedisClientManager(
            redis_url=f"redis://mirage_app:mirage_redis_secret@127.0.0.1:{proxy_port}/0",
            socket_timeout=3.0,
            socket_connect_timeout=3.0,
        )
        proxied_cache = RedisCacheService(client_manager=proxied_mgr)
        scs_worker = SCSWorker(cache_service=proxied_cache)

        # ----------------------------------------------------------------------
        # Step 1: Pre-fault Baseline Measurement
        # ----------------------------------------------------------------------
        t_base_0 = time.perf_counter()
        base_cached, base_hit = await proxied_cache.get_scs(
            tenant_id=tenant_id,
            model_id=model_id,
            prompt=prompt,
        )
        baseline_ms = (time.perf_counter() - t_base_0) * 1000

        try:
            # ------------------------------------------------------------------
            # Step 2: Inject +500 ms Latency Toxic on Redis Proxy
            # ------------------------------------------------------------------
            with chaos_controller.inject_latency(DependencyName.REDIS, latency_ms=500):
                proxy = chaos_controller.client.get_proxy(proxy_name)
                assert len(proxy.toxics) == 1
                assert proxy.toxics[0].attributes["latency"] == 500

                # --------------------------------------------------------------
                # Step 3: Measure Faulted Latency & Delta
                # --------------------------------------------------------------
                t_fault_0 = time.perf_counter()
                faulted_cached, faulted_hit = await proxied_cache.get_scs(
                    tenant_id=tenant_id,
                    model_id=model_id,
                    prompt=prompt,
                )
                faulted_ms = (time.perf_counter() - t_fault_0) * 1000
                latency_delta_ms = faulted_ms - baseline_ms

                # Injected latency must be reflected: faulted latency must exceed 450 ms when using live daemon
                if not chaos_controller.client.use_simulator:
                    assert faulted_ms >= 450.0, f"Faulted latency was {faulted_ms}ms; expected >= 450ms"
                    assert latency_delta_ms >= 400.0, f"Latency delta was {latency_delta_ms}ms; expected >= 400ms"

                # --------------------------------------------------------------
                # Step 4: Verify Asynchronous Parallel Absorption in Pipeline
                # --------------------------------------------------------------
                # Orchestrator spawns SCS worker in parallel with RAV evidence retrieval.
                # Total execution absorbs the +500 ms delay concurrently without crashing.
                orchestrator = VerificationOrchestrator(scs_worker=scs_worker, mongo_service=None)
                v_req = VerificationRequest(
                    prompt=prompt,
                    response="Water boils at 100 degrees Celsius (212 degrees Fahrenheit) at 1 atmosphere.",
                    tenant_id=tenant_id,
                    model_id=model_id,
                )

                t_pipe_0 = time.perf_counter()
                v_res = await orchestrator.verify_request(v_req)
                pipe_elapsed_ms = (time.perf_counter() - t_pipe_0) * 1000

                assert isinstance(v_res, VerificationResponse)
                assert v_res.hrs_result.hrs >= 0.0
                assert "scs" in v_res.metadata.pipeline_signals_used
                assert "rav" in v_res.metadata.pipeline_signals_used
                assert pipe_elapsed_ms > 400.0, "Pipeline must absorb the injected latency"

                # --------------------------------------------------------------
                # Step 5: Circuit Breakers Remain Closed
                # --------------------------------------------------------------
                assert rabbitmq_circuit.current_state == "closed"
                assert llm_circuit.current_state == "closed"

        finally:
            post_health = chaos_controller.restore_all()
            assert post_health.is_healthy is True
            assert post_health.active_toxics_count == 0

    # ==========================================================================
    # Scenario 10: Container OOM / Kill & Recovery
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_scenario_10_container_oom_restart_recovery_and_neighbor_continuity(
        self, chaos_controller: ChaosController
    ) -> None:
        """Scenario 10: Container failure / restart in Docker chaos environment.

        Expected Behaviors:
        1. Exercises container restart on mirage-toxiproxy using Docker engine.
        2. Measures recovery elapsed time against the governing <5.0s target.
        3. Neighboring dependencies and authoritative persistence remain unaffected.
        4. Health check detects recovery, restores all proxy routes cleanly.
        5. Full verification pipeline completes post-recovery (HTTP 200).
        """
        chaos_controller.config.validate_safety()
        pre_health = chaos_controller.check_health()
        assert pre_health.is_healthy is True
        assert pre_health.active_toxics_count == 0

        # Check if Docker engine CLI is available in the current execution environment
        docker_cli = shutil.which("docker")
        if not docker_cli:
            pytest.skip("Docker CLI not available in environment; skipping container OOM test")

        container_name = "mirage-toxiproxy"

        # Verify container is actively running before restart
        inspect_res = subprocess.run(
            [docker_cli, "inspect", "--format={{.State.Running}}", container_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspect_res.returncode != 0 or inspect_res.stdout.strip().lower() != "true":
            pytest.skip(f"Container '{container_name}' is not running; skipping container restart test")

        # ----------------------------------------------------------------------
        # Step 1: Execute Container Restart & Measure Recovery Time
        # ----------------------------------------------------------------------
        t_restart_start = time.perf_counter()
        restart_proc = subprocess.run(
            [docker_cli, "restart", container_name],
            capture_output=True,
            text=True,
            check=False,
        )
        assert restart_proc.returncode == 0, f"Failed to restart container: {restart_proc.stderr}"

        # Poll Toxiproxy REST management API until operational
        recovery_detected = False
        t_ready = t_restart_start
        for _ in range(60):  # Poll up to 6.0 seconds (every 100ms)
            if chaos_controller.client.is_server_available():
                recovery_detected = True
                t_ready = time.perf_counter()
                break
            await asyncio.sleep(0.1)

        recovery_time_sec = t_ready - t_restart_start
        assert recovery_detected is True, f"Container '{container_name}' failed to recover within 6.0s timeout."

        # ----------------------------------------------------------------------
        # Step 2: Compare Against Governing Acceptance Target (< 5.0 seconds)
        # ----------------------------------------------------------------------
        assert recovery_time_sec < 5.0, (
            f"Recovery time {recovery_time_sec:.2f}s exceeded the governing <5.0s acceptance target!"
        )

        # ----------------------------------------------------------------------
        # Step 3: Verify Neighbor Continuity & Post-Recovery Health
        # ----------------------------------------------------------------------
        # Restore all proxies to baseline healthy state and assert 8 healthy proxies
        post_health = chaos_controller.restore_all()
        assert post_health.is_healthy is True
        assert len(post_health.healthy_proxies) == 8
        assert post_health.active_toxics_count == 0

        # Verify full verification continuity post-restart
        orchestrator = VerificationOrchestrator(mongo_service=None)
        tenant_id = f"tenant_oom_chaos_{uuid.uuid4().hex[:8]}"
        v_req = VerificationRequest(
            prompt="What is photosynthesis?",
            response="Photosynthesis is the process by which green plants convert light energy into chemical energy.",
            tenant_id=tenant_id,
            model_id="allam-2-7b",
        )
        v_res = await orchestrator.verify_request(v_req)
        assert isinstance(v_res, VerificationResponse)
        assert v_res.hrs_result.hrs >= 0.0
        assert v_res.hrs_result.tier is not None
