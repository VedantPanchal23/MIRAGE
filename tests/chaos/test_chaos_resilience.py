"""Chaos & Fault Tolerance Tests: Dependency failure simulation and graceful degradation.

Implements Testing Strategy §9 & Technical Architecture §9:
- Circuit breaker failure tripping (fail_max threshold)
- Fallback activation under dependency outages (Qdrant down, LLaVA down, Redis down)
- Circuit recovery and half-open reset timeout handling
- Health check status transition to 'degraded' when a circuit breaker trips open
"""

import time

from starlette.testclient import TestClient

from gateway.main import create_app
from gateway.middleware.circuit_breaker import (
    llava_circuit,
    qdrant_circuit,
    redis_circuit,
)
from shared.schemas import Claim, ClaimCriticality, ClaimType
from tests.auth_factory import AuthTestFactory
from workers.visual.worker import VisualGroundingWorker

app = create_app()
client = TestClient(app)


class TestChaosResilience:
    """Simulates external dependency faults and verifies graceful degradation."""

    def setup_method(self) -> None:
        """Reset circuit breakers before each test."""
        for c in [qdrant_circuit, llava_circuit, redis_circuit]:
            c.close()

    def test_qdrant_circuit_breaker_tripping_and_rav_fallback(self) -> None:
        """Verify Qdrant failure trips circuit breaker and activates RAV fallback."""
        assert qdrant_circuit.current_state == "closed"

        def _failing_call() -> None:
            raise ConnectionError("Qdrant socket connection refused: 6333")

        # Trip breaker with fail_max=3 failures
        for _ in range(3):
            try:
                qdrant_circuit.call(_failing_call)
            except Exception:
                pass

        assert qdrant_circuit.current_state == "open"

        # Verify pipeline still functions in degraded RAV-less mode
        payload = {
            "prompt": "What is the capital of Mars?",
            "response": "Mars does not have an official capital city.",
            "tenant_id": "tenant_chaos_01",
        }
        headers = AuthTestFactory.auth_headers(tenant_id="tenant_chaos_01")
        res = client.post("/v1/verify", json=payload, headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert "hrs_result" in data
        assert 0.0 <= data["hrs_result"]["hrs"] <= 1.0

        # Health endpoint should reflect degraded state
        health_res = client.get("/v1/health")
        assert health_res.status_code == 200
        assert health_res.json()["status"] == "degraded"
        assert health_res.json()["circuits"]["qdrant"]["state"] == "open"

    def test_llava_circuit_breaker_graceful_degradation(self) -> None:
        """Verify visual worker gracefully handles LLaVA model server outage."""
        assert llava_circuit.current_state == "closed"

        def _failing_llava() -> None:
            raise TimeoutError("TGI inference timed out after 5000ms")

        # Trip llava circuit
        for _ in range(3):
            try:
                llava_circuit.call(_failing_llava)
            except Exception:
                pass

        assert llava_circuit.current_state == "open"

        # Verify visual worker returns circuit open degraded verdict
        import asyncio

        worker = VisualGroundingWorker()
        claim = Claim(
            claim_id="c_img_01",
            text="There is a red truck parked outside the building.",
            claim_type=ClaimType.IMAGE_GROUNDED,
            criticality=ClaimCriticality.HIGH,
        )
        vgs_score, verdict, meta = asyncio.run(
            worker.verify_claim(
                claim=claim,
                images=[
                    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
                ],
            )
        )
        assert verdict.value == "CIRCUIT_OPEN_DEGRADED"
        assert vgs_score == 0.50
        assert meta.get("circuit_breaker") == "open"

    def test_circuit_breaker_half_open_recovery(self) -> None:
        """Verify circuit breaker transitions from open to half-open after reset timeout."""
        # Trip breaker
        for _ in range(3):
            try:
                qdrant_circuit.call(lambda: (_ for _ in ()).throw(ValueError("Qdrant timeout")))
            except Exception:
                pass

        assert qdrant_circuit.current_state == "open"

        # Set reset timeout to 0 for instant recovery test
        orig_timeout = qdrant_circuit.reset_timeout
        try:
            qdrant_circuit.reset_timeout = 0.01
            time.sleep(0.02)

            # Successful call should close the circuit
            def _healthy_call() -> str:
                return "qdrant_ok"

            result = qdrant_circuit.call(_healthy_call)
            assert result == "qdrant_ok"
            assert qdrant_circuit.current_state == "closed"
        finally:
            qdrant_circuit.reset_timeout = orig_timeout
