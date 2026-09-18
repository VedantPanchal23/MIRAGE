"""Security and tenant boundary tests for SessionStore and dashboard read-side analytics.

Adheres to:
- Security_Access.md §1.3 (Threats T-05a, T-05b), §9.1, §10
- Technical_Architecture.md §7.1, §8.8
- Testing_Strategy.md §5, §7
"""

import uuid

import pytest
from starlette.testclient import TestClient

from analytics.store import SessionStore
from gateway.main import create_app
from shared.schemas.auth import Role
from tests.auth_factory import AuthTestFactory


@pytest.mark.security
class TestSessionStoreSecurity:
    """Validate tenant isolation, bounded memory guarantees, and authoritative store precedence."""

    def test_cross_tenant_dashboard_stats_forbidden(self) -> None:
        """Verify Tenant A cannot access Tenant B's dashboard stats via query param."""
        app = create_app()
        client = TestClient(app)

        tenant_a = f"tenant_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_a, role=Role.API_CLIENT)

        response = client.get(f"/v1/dashboard/stats?tenant_id={tenant_b}", headers=headers)
        assert response.status_code == 403
        data = response.json()
        assert "Access denied" in data["detail"]
        assert tenant_a in data["detail"]
        assert tenant_b in data["detail"]

    def test_cross_tenant_dashboard_sessions_forbidden(self) -> None:
        """Verify Tenant A cannot query Tenant B's session list via query param."""
        app = create_app()
        client = TestClient(app)

        tenant_a = f"tenant_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_a, role=Role.OPERATOR)

        response = client.get(f"/v1/dashboard/sessions?tenant_id={tenant_b}", headers=headers)
        assert response.status_code == 403
        data = response.json()
        assert "Access denied" in data["detail"]

    def test_cross_tenant_drift_report_forbidden(self) -> None:
        """Verify Tenant A cannot query Tenant B's drift analysis via query param."""
        app = create_app()
        client = TestClient(app)

        tenant_a = f"tenant_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"tenant_b_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=tenant_a, role=Role.OPERATOR)

        response = client.get(f"/v1/drift?tenant_id={tenant_b}", headers=headers)
        assert response.status_code == 403
        data = response.json()
        assert "Access denied" in data["detail"]

    def test_super_admin_can_access_cross_tenant_dashboard(self) -> None:
        """Verify SUPER_ADMIN role has legitimate cross-tenant operational visibility."""
        app = create_app()
        client = TestClient(app)

        admin_tenant = "mirage_admin_tenant"
        target_tenant = f"tenant_target_{uuid.uuid4().hex[:8]}"
        headers = AuthTestFactory.auth_headers(tenant_id=admin_tenant, role=Role.SUPER_ADMIN)

        response = client.get(f"/v1/dashboard/stats?tenant_id={target_tenant}", headers=headers)
        # Super admin is permitted through the tenant isolation check (200 OK)
        assert response.status_code == 200

    def test_session_store_in_memory_tenant_partitioning(self) -> None:
        """Verify process-local SessionStore queries strictly partition records by tenant_id."""
        store = SessionStore()
        tenant_a = f"tenant_part_a_{uuid.uuid4().hex[:8]}"
        tenant_b = f"tenant_part_b_{uuid.uuid4().hex[:8]}"

        # Record sessions for Tenant A
        store.record_session(
            session_id="sess_a1",
            tenant_id=tenant_a,
            trace_id="tr_a1",
            model_id="gpt-4o",
            prompt="Prompt A",
            response="Resp A",
            hrs_score=0.10,
            risk_tier="LOW",
            ci_lower=0.05,
            ci_upper=0.15,
            correction_applied=False,
            claims_count=1,
            contradicted_count=0,
        )

        # Record sessions for Tenant B
        store.record_session(
            session_id="sess_b1",
            tenant_id=tenant_b,
            trace_id="tr_b1",
            model_id="gpt-4o",
            prompt="Prompt B",
            response="Resp B",
            hrs_score=0.90,
            risk_tier="CRITICAL",
            ci_lower=0.85,
            ci_upper=0.95,
            correction_applied=True,
            claims_count=2,
            contradicted_count=1,
        )

        # Query Tenant A
        total_a, items_a = store.list_sessions(tenant_id=tenant_a)
        assert total_a == 1
        assert items_a[0]["session_id"] == "sess_a1"
        assert items_a[0]["tenant_id"] == tenant_a

        # Query Tenant B
        total_b, items_b = store.list_sessions(tenant_id=tenant_b)
        assert total_b == 1
        assert items_b[0]["session_id"] == "sess_b1"
        assert items_b[0]["tenant_id"] == tenant_b

        # Verify stats do not cross-pollinate
        stats_a = store.get_stats(tenant_id=tenant_a)
        assert stats_a["total_requests"] == 1
        assert stats_a["tier_counts"]["LOW"] == 1
        assert stats_a["tier_counts"]["CRITICAL"] == 0

        stats_b = store.get_stats(tenant_id=tenant_b)
        assert stats_b["total_requests"] == 1
        assert stats_b["tier_counts"]["LOW"] == 0
        assert stats_b["tier_counts"]["CRITICAL"] == 1

    def test_session_store_bounded_memory_ring_buffer(self) -> None:
        """Verify SessionStore bounds in-memory records to MAX_LOCAL_SESSIONS (prevents production OOM)."""
        store = SessionStore()
        assert store.MAX_LOCAL_SESSIONS == 1000

        # Insert 1050 records
        for i in range(1050):
            store.record_session(
                session_id=f"sess_{i:04d}",
                tenant_id="tenant_bound",
                trace_id=f"tr_{i:04d}",
                model_id="gpt-4o",
                prompt=f"Prompt {i}",
                response=f"Resp {i}",
                hrs_score=0.20,
                risk_tier="LOW",
                ci_lower=0.10,
                ci_upper=0.30,
                correction_applied=False,
                claims_count=1,
                contradicted_count=0,
            )

        # Buffer must be strictly capped at 1000
        assert len(store.sessions) == 1000
        # Oldest records 0..49 must have been discarded
        assert store.sessions[0].session_id == "sess_0050"
        assert store.sessions[-1].session_id == "sess_1049"
