"""Circuit breaker specifications and listeners using pybreaker."""

from datetime import UTC, datetime, timedelta
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


class AsyncCircuitBreaker:
    """Async-compatible wrapper around pybreaker.CircuitBreaker.

    Solves pybreaker's synchronous limitation where call() treats an unawaited coroutine
    as success and call_async() crashes due to deprecated Tornado dependency.
    """

    def __init__(self, breaker: pybreaker.CircuitBreaker) -> None:
        self.breaker = breaker

    @property
    def current_state(self) -> str:
        return self.breaker.current_state

    @property
    def fail_counter(self) -> int:
        return self.breaker.fail_counter

    @property
    def name(self) -> str | None:
        return self.breaker.name

    def close(self) -> None:
        self.breaker.close()

    async def call(self, coro_fn: Any, *args: Any, **kwargs: Any) -> Any:
        with self.breaker._lock:
            state = self.breaker.state
            if state.name == pybreaker.STATE_OPEN:
                timeout = timedelta(seconds=self.breaker.reset_timeout)
                opened_at = self.breaker._state_storage.opened_at
                if opened_at and datetime.now(UTC) < opened_at + timeout:
                    raise pybreaker.CircuitBreakerError("Timeout not elapsed yet, circuit breaker still open")
                self.breaker.half_open()
                state = self.breaker.state

            for listener in self.breaker.listeners:
                listener.before_call(self.breaker, coro_fn, *args, **kwargs)

        try:
            res = await coro_fn(*args, **kwargs)
        except BaseException as exc:
            with self.breaker._lock:
                state._handle_error(exc)
            raise
        else:
            with self.breaker._lock:
                state._handle_success()
            return res


async def call_async_with_circuit(breaker: pybreaker.CircuitBreaker, coro_fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Convenience helper to invoke an async coroutine under pybreaker protection."""
    return await AsyncCircuitBreaker(breaker).call(coro_fn, *args, **kwargs)


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

# Multimodal Vision Model Server (LLaVA-1.6 / Vision API)
llava_circuit = pybreaker.CircuitBreaker(
    fail_max=3,
    reset_timeout=30,
    name="llava_model",
    listeners=[listener],
)


def get_all_circuit_statuses() -> dict[str, dict[str, Any]]:
    """Return dictionary of current circuit states and fail counters."""
    circuits = [
        llm_circuit,
        qdrant_circuit,
        nli_circuit,
        flan_t5_circuit,
        redis_circuit,
        rabbitmq_circuit,
        llava_circuit,
    ]
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
    circuits = [
        llm_circuit,
        qdrant_circuit,
        nli_circuit,
        flan_t5_circuit,
        redis_circuit,
        rabbitmq_circuit,
        llava_circuit,
    ]
    for cb in circuits:
        cb.close()
