"""Comprehensive test suite for Phase 7 Observability, Distributed Tracing, Drift & Dashboard."""

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from analytics.drift import (
    DriftStatus,
    LongitudinalDriftTracker,
    calculate_ks_test,
    calculate_psi,
    check_rolling_spikes,
    evaluate_distribution_drift,
)
from gateway.main import app
from mcp_server.server import MirageMCPServer
from shared.telemetry import (
    CIRCUIT_BREAKER_STATE,
    HALLUCINATION_TIER_TOTAL,
    REQUESTS_TOTAL,
    export_metrics,
    record_circuit_breaker_state,
    record_request_metric,
    record_verification_metrics,
    time_module,
)
from shared.tracing import (
    extract_w3c_context,
    get_current_span_id,
    get_current_trace_id,
    inject_w3c_context,
    sanitize_trace_attributes,
    trace_span,
)


class TestPrometheusMetrics:
    """Validate Prometheus metrics collectors, exposition formatting, and /metrics endpoint."""

    def test_record_request_metric(self) -> None:
        """Verify HTTP request counter increments correctly."""
        before = REQUESTS_TOTAL.labels(tenant_id="t_test", status_code="200", endpoint="/v1/verify")._value.get()
        record_request_metric(tenant_id="t_test", status_code=200, endpoint="/v1/verify")
        after = REQUESTS_TOTAL.labels(tenant_id="t_test", status_code="200", endpoint="/v1/verify")._value.get()
        assert after == before + 1

    def test_record_verification_metrics(self) -> None:
        """Verify verification telemetry records HRS distribution and tier counts."""
        before_tier = HALLUCINATION_TIER_TOTAL.labels(tenant_id="t_obs", tier="HIGH")._value.get()
        record_verification_metrics(
            tenant_id="t_obs",
            model_id="gpt-4o",
            hrs=0.72,
            tier="HIGH",
            ci_width=0.12,
            latency_seconds=0.45,
            cached_scs_hit=True,
            correction_applied=True,
            correction_success=True,
        )
        after_tier = HALLUCINATION_TIER_TOTAL.labels(tenant_id="t_obs", tier="HIGH")._value.get()
        assert after_tier == before_tier + 1

    def test_record_circuit_breaker_state(self) -> None:
        """Verify circuit breaker gauge accurately reflects open/closed state."""
        record_circuit_breaker_state("qdrant", is_open=True)
        assert CIRCUIT_BREAKER_STATE.labels(dependency="qdrant")._value.get() == 1.0

        record_circuit_breaker_state("qdrant", is_open=False)
        assert CIRCUIT_BREAKER_STATE.labels(dependency="qdrant")._value.get() == 0.0

    def test_time_module_context_manager(self) -> None:
        """Verify time_module records non-zero execution duration."""
        with time_module("flan_t5"):
            total = sum(range(1000))
            assert total > 0

    def test_export_metrics_text_format(self) -> None:
        """Verify exported metrics contain required Prometheus metric names."""
        data, content_type = export_metrics()
        text = data.decode("utf-8")
        assert "mirage_requests_total" in text
        assert "mirage_verification_latency_seconds" in text
        assert "mirage_hrs_distribution" in text
        assert "text/plain" in content_type

    def test_metrics_endpoint_http(self) -> None:
        """Verify GET /metrics scrape endpoint returns 200 OK with Prometheus exposition format."""
        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "mirage_requests_total" in response.text


class TestOpenTelemetryTracing:
    """Validate OpenTelemetry spans, W3C trace propagation, and security sanitization."""

    def test_sanitize_trace_attributes_strips_sensitive_content(self) -> None:
        """Verify compliance with Section 10.6: prompts and responses are replaced by SHA-256 hashes."""
        raw_attrs = {
            "tenant_id": "tenant_123",
            "prompt": "Confidential patient medical record summary...",
            "response": "Patient diagnosed with hypertension...",
            "claims_count": 5,
        }
        clean = sanitize_trace_attributes(raw_attrs)

        # Raw content must NOT be present
        assert "prompt" not in clean
        assert "response" not in clean

        # Hashes must be present
        assert "prompt_sha256" in clean
        assert "response_sha256" in clean
        assert len(clean["prompt_sha256"]) == 64
        assert len(clean["response_sha256"]) == 64
        assert clean["tenant_id"] == "tenant_123"
        assert clean["claims_count"] == 5

    def test_trace_span_context_manager(self) -> None:
        """Verify trace_span yields an active span and records attributes."""
        with trace_span("test.operation", {"tenant_id": "t_101", "model_id": "llama-3"}) as span:
            assert span is not None

    def test_w3c_context_injection_and_extraction(self) -> None:
        """Verify W3C Trace Context propagation headers."""
        carrier: dict[str, str] = {}
        injected = inject_w3c_context(carrier)
        assert isinstance(injected, dict)

        # Extract should not fail
        extract_w3c_context(injected)

    def test_trace_and_span_id_helpers(self) -> None:
        """Verify trace ID and span ID are non-empty hex strings."""
        trace_id = get_current_trace_id()
        span_id = get_current_span_id()
        assert isinstance(trace_id, str) and len(trace_id) == 32
        assert isinstance(span_id, str) and len(span_id) == 16


class TestDriftDetectionEngine:
    """Validate Population Stability Index (PSI), KS test, and longitudinal drift tracking."""

    def test_psi_identical_distributions(self) -> None:
        """Verify identical distributions produce near-zero PSI (< 0.02)."""
        rng = np.random.default_rng(42)
        samples = rng.uniform(0.1, 0.4, 500).tolist()
        psi, _, _ = calculate_psi(samples, samples, num_bins=10)
        assert psi < 0.02

    def test_psi_moderate_drift(self) -> None:
        """Verify mild distribution shift yields moderate drift classification (0.10 <= PSI < 0.20)."""
        rng = np.random.default_rng(42)
        base = rng.normal(0.20, 0.05, 500).tolist()
        target = rng.normal(0.27, 0.07, 500).tolist()
        report = evaluate_distribution_drift(base, target)
        assert report.status in (DriftStatus.MODERATE_DRIFT, DriftStatus.SIGNIFICANT_DRIFT)

    def test_psi_significant_drift(self) -> None:
        """Verify substantial distribution shift triggers SIGNIFICANT_DRIFT status and alert."""
        rng = np.random.default_rng(42)
        base = rng.uniform(0.05, 0.25, 500).tolist()
        target = rng.uniform(0.65, 0.95, 500).tolist()
        report = evaluate_distribution_drift(base, target)
        assert report.status == DriftStatus.SIGNIFICANT_DRIFT
        assert report.psi >= 0.20
        assert report.alert_triggered is True

    def test_ks_test_significance(self) -> None:
        """Verify Kolmogorov-Smirnov test detects statistically significant shifts."""
        rng = np.random.default_rng(42)
        s1 = rng.uniform(0.1, 0.3, 100).tolist()
        s2 = rng.uniform(0.6, 0.8, 100).tolist()
        ks_stat, p_val = calculate_ks_test(s1, s2)
        assert ks_stat > 0.80
        assert p_val < 1e-5

    def test_rolling_spike_detection_critical_rate(self) -> None:
        """Verify alert triggers when critical hallucination rate exceeds 5%."""
        samples = [0.1] * 90 + [0.95] * 10  # 10% critical rate > 5%
        alert, reason, _ = check_rolling_spikes(prior_7d_samples=[0.1] * 100, current_7d_samples=samples)
        assert alert is True
        assert reason is not None and "Critical tier rate" in reason

    def test_rolling_spike_detection_mean_increase(self) -> None:
        """Verify alert triggers when 7-day average increases by > 0.15."""
        prior = [0.10] * 50
        current = [0.30] * 50  # delta = +0.20 > 0.15
        alert, reason, delta = check_rolling_spikes(prior_7d_samples=prior, current_7d_samples=current)
        assert alert is True
        assert delta >= 0.20
        assert reason is not None and "7-day average HRS increased" in reason

    def test_longitudinal_drift_tracker(self) -> None:
        """Verify LongitudinalDriftTracker records samples and returns valid drift reports."""
        tracker = LongitudinalDriftTracker(baseline_size=10)
        for val in [0.12, 0.15, 0.18, 0.22, 0.14]:
            tracker.record_score("tenant_corp", val)

        report = tracker.get_drift_report("tenant_corp")
        assert report.status in (DriftStatus.STABLE, DriftStatus.MODERATE_DRIFT, DriftStatus.SIGNIFICANT_DRIFT)
        assert isinstance(report.psi, float)


class TestDashboardAPI:
    """Validate dashboard stats, paginated session queries, and longitudinal drift time-series."""

    @pytest.fixture(autouse=True)
    def setup_test_sessions(self) -> None:
        """Seed sample sessions in session store."""
        from analytics.store import default_session_store

        default_session_store.sessions.clear()
        default_session_store.record_session(
            session_id="sess_001",
            tenant_id="tenant_dash",
            trace_id="trace_001",
            model_id="gpt-4o",
            prompt="Capital of France?",
            response="Paris is the capital.",
            hrs_score=0.12,
            risk_tier="LOW",
            ci_lower=0.08,
            ci_upper=0.16,
            correction_applied=False,
            claims_count=1,
            contradicted_count=0,
        )
        default_session_store.record_session(
            session_id="sess_002",
            tenant_id="tenant_dash",
            trace_id="trace_002",
            model_id="gpt-4o",
            prompt="Who invented penicillin?",
            response="Alexander Fleming in 1928.",
            hrs_score=0.88,
            risk_tier="CRITICAL",
            ci_lower=0.80,
            ci_upper=0.95,
            correction_applied=True,
            claims_count=2,
            contradicted_count=1,
        )

    def test_get_dashboard_stats(self) -> None:
        """Verify GET /v1/dashboard/stats returns aggregate metrics and tier breakdown."""
        client = TestClient(app)
        response = client.get(
            "/v1/dashboard/stats",
            headers={"X-API-Key": "dev_key_default", "X-Tenant-ID": "tenant_dash"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_requests"] == 2
        assert "LOW" in data["tier_counts"]
        assert "CRITICAL" in data["tier_counts"]
        assert data["tier_counts"]["LOW"] == 1
        assert data["tier_counts"]["CRITICAL"] == 1
        assert data["correction_rate"] == 0.5
        assert "drift_report" in data

    def test_get_dashboard_sessions_pagination_and_filter(self) -> None:
        """Verify GET /v1/dashboard/sessions pagination and risk_tier filtering."""
        client = TestClient(app)
        response = client.get(
            "/v1/dashboard/sessions?risk_tier=CRITICAL",
            headers={"X-API-Key": "dev_key_default", "X-Tenant-ID": "tenant_dash"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["risk_tier"] == "CRITICAL"

    def test_get_drift_report_and_timeseries(self) -> None:
        """Verify GET /v1/drift returns PSI drift metrics and daily time-series."""
        client = TestClient(app)
        response = client.get(
            "/v1/drift?days=7",
            headers={"X-API-Key": "dev_key_default", "X-Tenant-ID": "tenant_dash"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "drift_report" in data
        assert "time_series" in data
        assert len(data["time_series"]) >= 1


class TestMCPServer:
    """Validate Model Context Protocol (MCP) server tool declarations and execution."""

    @pytest.mark.asyncio
    async def test_mcp_tools_list(self) -> None:
        """Verify MCP server advertises verify_factual_consistency and check_hallucination tools."""
        server = MirageMCPServer()
        rpc_req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        res = await server.handle_rpc_request(rpc_req)
        assert res["id"] == 1
        tools = res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "verify_factual_consistency" in tool_names
        assert "check_hallucination" in tool_names

    @pytest.mark.asyncio
    async def test_mcp_check_hallucination_tool_call(self) -> None:
        """Verify check_hallucination MCP tool call via JSON-RPC."""
        server = MirageMCPServer()
        rpc_req = {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {
                "name": "check_hallucination",
                "arguments": {
                    "text": "The Eiffel Tower is in Paris, France.",
                    "prompt": "Tell me about the Eiffel Tower.",
                },
            },
        }
        res = await server.handle_rpc_request(rpc_req)
        assert res["id"] == 42
        content = res["result"]["content"][0]["text"]
        payload = json.loads(content)
        assert "is_hallucination" in payload
        assert "hrs_score" in payload
        assert "risk_tier" in payload

    @pytest.mark.asyncio
    async def test_mcp_verify_factual_consistency_tool_call(self) -> None:
        """Verify verify_factual_consistency tool returns complete breakdown."""
        server = MirageMCPServer()
        rpc_req = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": "verify_factual_consistency",
                "arguments": {
                    "text": "Quantum computing uses qubits.",
                    "prompt": "Explain quantum computing in one sentence.",
                },
            },
        }
        res = await server.handle_rpc_request(rpc_req)
        assert res["id"] == 100
        content = res["result"]["content"][0]["text"]
        payload = json.loads(content)
        assert "hrs_score" in payload
        assert "conformal_interval" in payload
        assert "signal_attribution" in payload
        assert "claims" in payload

    @pytest.mark.asyncio
    async def test_mcp_unknown_tool_error(self) -> None:
        """Verify unknown tool call returns JSON-RPC -32601 error."""
        server = MirageMCPServer()
        rpc_req = {
            "jsonrpc": "2.0",
            "id": 999,
            "method": "tools/call",
            "params": {"name": "non_existent_tool", "arguments": {}},
        }
        res = await server.handle_rpc_request(rpc_req)
        assert res["id"] == 999
        assert res["error"]["code"] == -32601
