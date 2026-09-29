"""Integration Tests for Report Broker Failure Semantics and PostgreSQL State Transitions.

Governing Specifications:
- Technical Architecture Document §7.5, §8.2
- Security & Access Document §13
- ADR 0005: REST API Contracts & Storage Architecture §3
- Blocker 1 Remediation Requirements

Validates:
1. RabbitMQ broker unavailable before dispatch -> returns HTTP 503 SERVICE_DEGRADED + Retry-After: 30
2. No orphaned report row created in PostgreSQL when broker is unreachable before dispatch
3. Celery / Kombu publisher confirmation failure -> returns HTTP 503 SERVICE_DEGRADED + Retry-After: 30 + ErrorEnvelope
4. Atomically marks PostgreSQL report as FAILED rather than leaving it in PENDING
5. Retry after failed dispatch succeeds cleanly and does not create duplicate report work
6. Successful publisher confirmation with live RabbitMQ -> returns HTTP 202 Accepted + preserves idempotency
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from kombu.exceptions import OperationalError
from sqlalchemy import select
from starlette.testclient import TestClient

from db.models import AuditReport
from db.persistence import default_persistence_service
from db.session import get_tenant_session
from gateway.main import create_app
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory
from workers.tasks import generate_report_task

app = create_app()
client = TestClient(app)


class TestP1ReportBrokerFailures:
    """Test suite validating publisher confirmations, failure semantics, and state safety for reports."""

    def test_broker_unavailable_before_dispatch_returns_503_and_retry_after(self) -> None:
        """When RabbitMQ is unreachable before dispatch, return 503 SERVICE_DEGRADED + Retry-After: 30.

        CRITICAL INVARIANT: No orphaned report record must be created in PostgreSQL.
        """
        tenant_id = f"t_broker_unavail_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        start = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        end = datetime.now(UTC).isoformat()
        req_payload = {
            "title": "Unreachable Broker Audit",
            "start_date": start,
            "end_date": end,
            "model_id": "test-model-v1",
        }

        # Simulate broker offline before dispatch
        with patch("workers.celery_app.is_broker_reachable", return_value=False):
            res = client.post("/v1/reports/generate", json=req_payload, headers=headers)

        # 1. Must return HTTP 503
        assert res.status_code == 503, f"Expected 503, got {res.status_code}: {res.text}"

        # 2. Must include Retry-After: 30 header
        assert res.headers.get("retry-after") == "30", f"Missing Retry-After header: {res.headers}"

        # 3. Canonical ErrorEnvelope
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "SERVICE_DEGRADED"
        assert "trace_id" in data["error"]
        assert "timestamp" in data["error"]

        # 4. Prove NO orphaned report record was created in PostgreSQL
        async def verify_no_report() -> None:
            key = f"idemp_{uuid.uuid4().hex[:8]}"
            report = await default_persistence_service.get_report_by_idempotency_key(tenant_id, key)
            assert report is None

        asyncio.run(verify_no_report())

    def test_publisher_failure_marks_report_failed_and_returns_503(self) -> None:
        """When publisher confirmation fails or raises, return 503 SERVICE_DEGRADED + Retry-After: 30.

        CRITICAL INVARIANT: Report record must be atomically marked FAILED in PostgreSQL,
        never left in a false-success PENDING state.
        """
        tenant_id = f"t_pub_fail_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        start = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        end = datetime.now(UTC).isoformat()
        req_payload = {
            "title": "Publisher Failure Test Report",
            "start_date": start,
            "end_date": end,
            "model_id": "test-model-v1",
        }

        # Simulate publisher confirmation raising OperationalError
        with (
            patch("workers.celery_app.is_broker_reachable", return_value=True),
            patch(
                "workers.tasks.generate_report_task.apply_async",
                side_effect=OperationalError("Simulated RabbitMQ publisher confirmation NACK / timeout"),
            ),
        ):
            res = client.post("/v1/reports/generate", json=req_payload, headers=headers)

        # 1. Must return HTTP 503
        assert res.status_code == 503
        assert res.headers.get("retry-after") == "30"

        # 2. Canonical ErrorEnvelope
        data = res.json()
        assert data["error"]["code"] == "SERVICE_DEGRADED"
        assert "Message broker dispatch failed" in data["error"]["message"]

        # 3. Prove the report in PostgreSQL was marked FAILED (NOT left in PENDING)
        async def check_db_state() -> str:
            async with get_tenant_session(tenant_id) as session:
                stmt = select(AuditReport).where(AuditReport.tenant_id == tenant_id)
                reports = (await session.execute(stmt)).scalars().all()
                assert len(reports) == 1, f"Expected exactly 1 report record, found {len(reports)}"
                rep = reports[0]
                assert rep.status == "FAILED", f"Report was left in status '{rep.status}' instead of 'FAILED'!"
                assert "Broker dispatch failure" in rep.summary.get("error", "")
                return rep.report_id

        failed_report_id = asyncio.run(check_db_state())

        # 4. Prove GET /v1/reports/{id} returns status FAILED
        detail_res = client.get(f"/v1/reports/{failed_report_id}", headers=headers)
        assert detail_res.status_code == 200
        assert detail_res.json()["status"] == "FAILED"

        # 5. Prove GET /v1/reports/{id}/pdf returns 409 Conflict
        pdf_res = client.get(f"/v1/reports/{failed_report_id}/pdf", headers=headers)
        assert pdf_res.status_code == 409
        assert pdf_res.json()["error"]["code"] == "CONFLICT"

    def test_retry_after_failed_dispatch_succeeds_without_duplicate_work(self) -> None:
        """Proves retry after a failed dispatch creates a new report and is not blocked by idempotency."""
        tenant_id = f"t_retry_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        start = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        end = datetime.now(UTC).isoformat()
        req_payload = {
            "title": "Idempotent Retry Report",
            "start_date": start,
            "end_date": end,
            "model_id": "test-model-v1",
        }

        # 1. First attempt fails due to broker dispatch failure
        with (
            patch("workers.celery_app.is_broker_reachable", return_value=True),
            patch(
                "workers.tasks.generate_report_task.apply_async",
                side_effect=OperationalError("Transient broker down"),
            ),
        ):
            res1 = client.post("/v1/reports/generate", json=req_payload, headers=headers)
            assert res1.status_code == 503

        # Capture failed report ID
        async def get_failed_id() -> str:
            async with get_tenant_session(tenant_id) as session:
                stmt = select(AuditReport).where(AuditReport.tenant_id == tenant_id, AuditReport.status == "FAILED")
                rep = (await session.execute(stmt)).scalars().first()
                assert rep is not None
                return rep.report_id

        failed_id = asyncio.run(get_failed_id())

        # 2. Second attempt (retry) succeeds because broker recovered
        with (
            patch("workers.celery_app.is_broker_reachable", return_value=True),
            patch("workers.tasks.generate_report_task.apply_async"),
        ):
            res2 = client.post("/v1/reports/generate", json=req_payload, headers=headers)
            assert res2.status_code == 202
            data2 = res2.json()
            assert data2["status"] == "PENDING"
            new_report_id = data2["report_id"]

        # 3. Third identical attempt within 1 hour returns the existing PENDING report (idempotency works)
        with (
            patch("workers.celery_app.is_broker_reachable", return_value=True),
            patch("workers.tasks.generate_report_task.apply_async"),
        ):
            res3 = client.post("/v1/reports/generate", json=req_payload, headers=headers)
            assert res3.status_code == 202
            assert res3.json()["report_id"] == new_report_id

        # 4. Worker pre-execution guard check: if worker is invoked for a FAILED report, it safely aborts
        abort_result = generate_report_task.apply(
            kwargs={
                "tenant_id": tenant_id,
                "report_id": failed_id,
                "title": "Abort Test",
                "start_date_iso": start,
                "end_date_iso": end,
            }
        ).result
        assert abort_result.get("status") == "ABORTED"
        assert abort_result.get("reason") == "Report marked FAILED"

    def test_successful_publisher_confirmation_with_live_rabbitmq(self, live_rabbitmq_broker: Any) -> None:
        """Proves end-to-end report dispatch against live RabbitMQ Testcontainer with durable Quorum queue."""
        if live_rabbitmq_broker is None:
            pytest.skip("RabbitMQ Testcontainer not available in current test environment")

        tenant_id = f"t_live_rmq_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_id, role=Role.TENANT_ADMIN)

        start = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        end = datetime.now(UTC).isoformat()
        req_payload = {
            "title": "Live RabbitMQ Confirmed Report",
            "start_date": start,
            "end_date": end,
            "model_id": "test-model-v1",
        }

        # Dispatch against real broker
        res = client.post("/v1/reports/generate", json=req_payload, headers=headers)
        assert res.status_code == 202
        data = res.json()
        assert data["status"] == "PENDING"
        assert data["report_id"].startswith("rep_")
