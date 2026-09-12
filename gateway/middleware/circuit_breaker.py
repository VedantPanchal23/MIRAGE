"""Circuit breaker specifications and listeners using pybreaker."""

from typing import Any

import pybreaker

from shared.logging import get_logger

logger = get_logger("circuit_breaker")


class CircuitBreakerLogger(pybreaker.CircuitBreakerListener):
    """Monitors and logs circuit state transitions."""

    def state_change(self, cb: pybreaker.CircuitBreaker, old_state: Any, new_state: Any) -> None:
        logger.warning(
            "Circuit breaker state changed",
            circuit=cb.name,
            old_state=str(old_state),
            new_state=str(new_state),
        )

    def failure(self, cb: pybreaker.CircuitBreaker, exc: BaseException) -> None:
        logger.warning(
            "Circuit breaker recorded failure",
            circuit=cb.name,
            error=str(exc),
            fail_counter=cb.fail_counter,
        )


listener = CircuitBreakerLogger()

# ------------------------------------------------------------------------------
# Per-dependency Circuit Breakers
# ------------------------------------------------------------------------------

# Primary LLM API (Groq / OpenRouter / OpenAI)
llm_circuit = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=60,
    name="llm_api",
    listeners=[listener],
)

# Vector Database (Qdrant)
qdrant_circuit = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=30,
    name="qdrant",
    listeners=[listener],
)

# NLI Model Server (DeBERTa)
nli_circuit = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=30,
    name="nli_verifier",
    listeners=[listener],
)

# Atomic Claim Decomposer (FLAN-T5)
flan_t5_circuit = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=15,
    name="flan_t5_decomposer",
    listeners=[listener],
)

# In-Memory Cache (Redis)
redis_circuit = pybreaker.CircuitBreaker(
    fail_max=5,
    reset_timeout=10,
    name="redis_cache",
    listeners=[listener],
)

# Message Broker (RabbitMQ)
rabbitmq_circuit = pybreaker.CircuitBreaker(
    fail_max=2,
    reset_timeout=120,
    name="rabbitmq_broker",
    listeners=[listener],
)


def get_all_circuit_statuses() -> dict[str, dict[str, Any]]:
    """Return dictionary of current circuit states and fail counters."""
    circuits = [llm_circuit, qdrant_circuit, nli_circuit, flan_t5_circuit, redis_circuit, rabbitmq_circuit]
    return {
        (cb.name or "unknown"): {
            "state": cb.current_state,
            "fail_counter": cb.fail_counter,
            "fail_max": cb.fail_max,
            "reset_timeout": cb.reset_timeout,
        }
        for cb in circuits
    }


def reset_all_circuits() -> None:
    """Reset all circuit breakers to closed state and clear failure counters."""
    circuits = [llm_circuit, qdrant_circuit, nli_circuit, flan_t5_circuit, redis_circuit, rabbitmq_circuit]
    for cb in circuits:
        cb.close()
