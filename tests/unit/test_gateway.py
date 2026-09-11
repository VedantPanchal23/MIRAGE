"""Unit and contract tests for the FastAPI Gateway layer."""

import pytest
from fastapi.testclient import TestClient

from gateway.main import app
from gateway.middleware.circuit_breaker import get_all_circuit_statuses
from gateway.middleware.rate_limiter import SlidingWindowRateLimiter


@pytest.fixture
def client() -> TestClient:
    """Provide a TestClient instance for the FastAPI application."""
    return TestClient(app)


@pytest.mark.unit
class TestHealthEndpoint:
    def test_health_check_success(self, client: TestClient) -> None:
        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in {"healthy", "degraded"}
        assert data["version"] == "2.1.0"
        assert "uptime_seconds" in data
        assert "circuit_breakers" in data
        assert "gateway" in data["components"]

    def test_security_headers_injected(self, client: TestClient) -> None:
        response = client.get("/v1/health")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert "x-trace-id" in response.headers


@pytest.mark.unit
class TestVerifyEndpoint:
    def test_direct_verify_success(self, client: TestClient) -> None:
        payload = {
            "prompt": "What is the capital of France?",
            "response": "The capital of France is Paris. It was founded in the 3rd century BC.",
            "tenant_id": "test_tenant",
        }
        response = client.post("/v1/verify", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "request_id" in data
        assert data["verified_response"] == payload["response"]
        assert "hrs_result" in data
        assert 0.0 <= data["hrs_result"]["hrs"] <= 1.0
        assert data["hrs_result"]["tier"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert len(data["claims"]) >= 1
        assert "metadata" in data
        assert "trace_id" in data["metadata"]

    def test_verify_empty_prompt_rejected(self, client: TestClient) -> None:
        payload = {
            "prompt": "",
            "response": "Valid response",
        }
        response = client.post("/v1/verify", json=payload)
        assert response.status_code == 422


@pytest.mark.unit
class TestOpenAIProxyEndpoint:
    def test_chat_completions_proxy_success(self, client: TestClient) -> None:
        payload = {
            "model": "llama-3.1-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Tell me about antibiotics."},
            ],
            "temperature": 0.7,
        }
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 200
        data = response.json()

        # Strict OpenAI format compliance
        assert data["object"] == "chat.completion"
        assert data["model"] == "llama-3.1-70b-versatile"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert len(data["choices"][0]["message"]["content"]) > 0
        assert "usage" in data

        # MIRAGE verification metadata
        assert "mirage" in data
        assert "hrs" in data["mirage"]
        assert "tier" in data["mirage"]
        assert response.headers["x-mirage-tier"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        assert "x-mirage-hrs" in response.headers

    def test_chat_completions_empty_messages_error(self, client: TestClient) -> None:
        payload = {"messages": []}
        response = client.post("/v1/chat/completions", json=payload)
        assert response.status_code == 400


@pytest.mark.unit
class TestRateLimiterAndCircuits:
    def test_rate_limiter_exceeded(self) -> None:
        limiter = SlidingWindowRateLimiter(limit_per_minute=2)
        tenant = "burst_tenant"
        limiter.check_rate_limit(tenant)
        limiter.check_rate_limit(tenant)
        with pytest.raises(Exception) as exc_info:
            limiter.check_rate_limit(tenant)
        assert "Rate limit exceeded" in str(exc_info.value)

    def test_all_circuits_initialized(self) -> None:
        circuits = get_all_circuit_statuses()
        expected = {"llm_api", "qdrant", "nli_verifier", "flan_t5_decomposer", "redis_cache", "rabbitmq_broker"}
        assert set(circuits.keys()) == expected
        for _name, info in circuits.items():
            assert info["state"] == "closed"
            assert info["fail_counter"] == 0
