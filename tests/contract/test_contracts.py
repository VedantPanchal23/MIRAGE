"""Contract Tests: Validates API contract schemas, error formats, and security headers.

Implements Testing Strategy §6:
- OpenAPI specification completeness and schema conformity
- Response structure guarantees across core endpoints
- Standardized error response contract
- Mandatory enterprise security headers
- Health check dependency contract
"""

from starlette.testclient import TestClient

from gateway.main import create_app

app = create_app()
client = TestClient(app)


class TestAPIContracts:
    """Contract test suite validating API schemas and security boundaries."""

    def test_openapi_spec_contains_all_core_routes(self) -> None:
        """Verify openapi.json contains all required endpoints per technical architecture."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        spec = response.json()
        assert "paths" in spec
        paths = spec["paths"]

        required_paths = [
            "/v1/verify",
            "/v1/chat/completions",
            "/v1/health",
            "/v1/drift",
            "/v1/dashboard/stats",
            "/v1/dashboard/sessions",
            "/v1/knowledge-base/upload",
            "/v1/knowledge-base/documents",
            "/v1/audit/verify-chain",
            "/v1/audit/report/{session_id}",
            "/v1/audit/export",
            "/v1/audit/query",
        ]

        for p in required_paths:
            assert p in paths, f"Missing required API path: {p}"

    def test_verification_response_contract_schema(self) -> None:
        """Verify /v1/verify response contract strictly conforms to schema specification."""
        payload = {
            "prompt": "What is the chemical formula for water?",
            "response": "Water is represented by the chemical formula H2O.",
            "tenant_id": "tenant_contract_01",
        }
        response = client.post("/v1/verify", json=payload)
        assert response.status_code == 200
        data = response.json()

        # Required root fields
        assert isinstance(data["request_id"], str)
        assert isinstance(data["verified_response"], str)
        assert isinstance(data["original_response"], str)
        assert isinstance(data["hrs_result"], dict)
        assert isinstance(data["claims"], list)
        assert isinstance(data["metadata"], dict)

        # HRS Result Contract
        hrs = data["hrs_result"]
        assert 0.0 <= hrs["hrs"] <= 1.0
        assert hrs["tier"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert isinstance(hrs["conformal_interval"], dict)
        assert hrs["conformal_interval"]["lower"] <= hrs["conformal_interval"]["upper"]

        # Metadata Contract
        meta = data["metadata"]
        assert isinstance(meta["trace_id"], str)
        assert isinstance(meta["execution_time_ms"], float)
        assert isinstance(meta["pipeline_signals_used"], list)

    def test_error_response_contract_schema(self) -> None:
        """Verify validation failure returns standardized error schema."""
        # Empty prompt should trigger validation error
        response = client.post("/v1/verify", json={"prompt": "", "response": ""})
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_security_headers_contract_on_all_endpoints(self) -> None:
        """Verify enterprise security headers are enforced across endpoints."""
        test_endpoints = [
            ("/v1/health", "GET"),
            ("/v1/dashboard/stats", "GET"),
            ("/v1/drift", "GET"),
        ]

        for path, method in test_endpoints:
            res = client.get(path) if method == "GET" else client.post(path)
            assert res.headers.get("X-Content-Type-Options") == "nosniff", f"Failed on {path}"
            assert res.headers.get("X-Frame-Options") == "DENY", f"Failed on {path}"
            assert res.headers.get("X-XSS-Protection") == "1; mode=block", f"Failed on {path}"
            assert "Strict-Transport-Security" in res.headers, f"Failed on {path}"
            assert "Content-Security-Policy" in res.headers, f"Failed on {path}"
            assert "X-Trace-ID" in res.headers, f"Failed on {path}"

    def test_health_check_contract_schema(self) -> None:
        """Verify health check endpoint schema and dependency circuit coverage."""
        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()

        assert data["status"] in {"healthy", "degraded"}
        assert data["version"] == "2.1.0"
        assert "circuits" in data

        circuits = data["circuits"]
        required_circuits = [
            "llm_api",
            "qdrant",
            "nli_verifier",
            "flan_t5_decomposer",
            "redis_cache",
            "rabbitmq_broker",
            "llava_model",
        ]
        for c in required_circuits:
            assert c in circuits, f"Circuit breaker '{c}' missing from health check"
            assert circuits[c]["state"] in {"closed", "open", "half-open"}
