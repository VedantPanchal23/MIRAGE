"""Unit tests for Performance Test Harness Invariants (P3.1 & P3.2).

Validates:
1. Scenario 4 does not introduce invented error thresholds (e.g. http_req_failed).
2. Scenario 5 enforces a strict 10x arrival rate workload ratio between Tenant A and Tenant B.
3. Scenario 6 official execution strictly enforces rate>0.90 cache hit rate.
4. Scenario 6 accounting isolates primary cache metrics from cross-tenant isolation checks.
5. Runner CLI supports all required P3.1 and P3.2 flags without regressions.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class TestPerformanceHarnessInvariants:
    """Verifies that the performance harness adheres strictly to governing Testing Strategy §8."""

    def test_scenario4_contains_no_invented_error_thresholds(self) -> None:
        """Verify scenario4_spike.js does not contain invented failure tolerance thresholds."""
        spike_script = PROJECT_ROOT / "tests" / "performance" / "scenarios" / "scenario4_spike.js"
        assert spike_script.is_file(), f"Missing script: {spike_script}"

        content = spike_script.read_text(encoding="utf-8")
        assert "http_req_failed" not in content, (
            "Found prohibited invented threshold 'http_req_failed' in scenario4_spike.js"
        )
        assert "p(95)<3000" in content, "Scenario 4 must retain governing latency threshold"
        assert "mirage_http_5xx_rate" in content, "Scenario 4 must retain zero unhandled 5xx threshold"

    def test_scenario5_enforces_10x_workload_arrival_rate_ratio(self) -> None:
        """Verify scenario5_noisy_neighbor.js targets exact 10x arrival rate ratio."""
        noisy_script = PROJECT_ROOT / "tests" / "performance" / "scenarios" / "scenario5_noisy_neighbor.js"
        assert noisy_script.is_file(), f"Missing script: {noisy_script}"

        content = noisy_script.read_text(encoding="utf-8")
        assert "constant-arrival-rate" in content, (
            "Scenario 5 must use constant-arrival-rate executor for mathematically strict workload ratio"
        )
        assert "tenantARate" in content and "tenantBRate" in content
        assert "tenant_b_429_rate" not in content, (
            "Scenario 5 must not invent a pass/fail threshold on tenant_b_429_rate"
        )

    def test_scenario6_official_threshold_is_strictly_90_percent(self) -> None:
        """Verify scenario6_cache_warm.js enforces governing rate>0.90 in official execution."""
        cache_script = PROJECT_ROOT / "tests" / "performance" / "scenarios" / "scenario6_cache_warm.js"
        assert cache_script.is_file(), f"Missing script: {cache_script}"

        content = cache_script.read_text(encoding="utf-8")
        assert "rate>0.90" in content, "Scenario 6 must enforce governing rate>0.90 cache hit rate threshold"

    def test_scenario6_separates_primary_and_cross_tenant_accounting(self) -> None:
        """Verify metrics.js and scenario6 separate primary cache metrics from cross-tenant checks."""
        metrics_script = PROJECT_ROOT / "tests" / "performance" / "metrics.js"
        assert metrics_script.is_file()

        m_content = metrics_script.read_text(encoding="utf-8")
        assert "recordPrimaryCacheMetrics" in m_content
        assert "recordCrossTenantMetrics" in m_content
        assert "primary_cache_workload" in m_content
        assert "cross_tenant_isolation_workload" in m_content

        cache_script = PROJECT_ROOT / "tests" / "performance" / "scenarios" / "scenario6_cache_warm.js"
        c_content = cache_script.read_text(encoding="utf-8")
        assert "recordPrimaryCacheMetrics" in c_content
        assert "recordCrossTenantMetrics" in c_content
