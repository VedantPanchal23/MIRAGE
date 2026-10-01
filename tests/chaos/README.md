# MIRAGE Chaos Resilience & Network Fault-Injection Infrastructure (P3.3)

This directory provides the centralized, safe, and reversible network fault-injection harness for the MIRAGE multi-signal hallucination verification middleware. It implements the infrastructure foundations for the chaos engineering scenarios specified in `Testing_Strategy.md §9`.

> [!IMPORTANT]
> **Phase 3.3 Scope Boundary**: This harness establishes the network fault-injection primitives and lifecycle management only. Specific Chaos Scenarios 1–10 (Redis kill, Qdrant kill, GPU offline, PostgreSQL offline, upstream timeouts, etc.) will be implemented and evaluated in Phases 3.4 and 3.5.

---

## 1. How the Chaos Environment is Started

Toxiproxy is isolated to the test and chaos environments and is never exposed in production.

### Starting Toxiproxy via Docker Compose
To start the pinned Toxiproxy container alongside the MIRAGE stack:
```bash
docker compose -f docker-compose.yml -f docker-compose.chaos.yml up -d toxiproxy
```

### Inspecting Toxiproxy Health
```bash
curl -s http://127.0.0.1:8474/version
```
Expected output:
```
2.11.0
```

### Container Specifications
- **Image**: `ghcr.io/shopify/toxiproxy:2.11.0` (pinned release; no floating `latest`).
- **Network**: Attached strictly to `backend_net`.
- **Host Binding**: Bound strictly to `127.0.0.1` (`8474` management API and proxy ports `25000–28999`). Never exposed on `0.0.0.0` or publicly routable interfaces.
- **Initial Configuration**: Mounted read-only from [`docker/toxiproxy.json`](file:///c:/Users/vedan/Desktop/MIRAGE/docker/toxiproxy.json).

---

## 2. Dependency & Proxy Topology Mapping

The harness models all 8 authoritative dependencies in the MIRAGE microservices architecture without inventing non-existent services:

| Dependency Enum | Registered Proxy Name | Toxiproxy Listen Address | Upstream Target | Purpose in MIRAGE Pipeline |
| :--- | :--- | :--- | :--- | :--- |
| `DependencyName.REDIS` | `mirage_redis` | `0.0.0.0:26379` | `redis:6379` | Token bucket rate limiting (fail-closed) & SCS cache (fail-open) |
| `DependencyName.QDRANT` | `mirage_qdrant` | `0.0.0.0:26333` | `qdrant:6333` | Vector store for Knowledge Base chunks & RAV retrieval |
| `DependencyName.POSTGRES` | `mirage_postgres` | `0.0.0.0:25432` | `postgres:5432` | Authoritative persistence & audit log chain |
| `DependencyName.RABBITMQ` | `mirage_rabbitmq` | `0.0.0.0:25672` | `rabbitmq:5672` | Celery broker for async pipeline signal distribution |
| `DependencyName.NLI` | `mirage_nli` | `0.0.0.0:28085` | `torchserve:8085` | TorchServe / DeBERTa-v3-large NLI entailment verifier |
| `DependencyName.LLAVA` | `mirage_llava` | `0.0.0.0:28086` | `tgi:8086` | TGI / LLaVA-1.6 multimodal vision grounding model |
| `DependencyName.FLAN_T5` | `mirage_flan_t5` | `0.0.0.0:28087` | `flan-t5:8087` | Atomic claim decomposer service |
| `DependencyName.UPSTREAM_LLM` | `mirage_upstream_llm` | `0.0.0.0:28088` | `api.groq.com:443` | Upstream generator LLM (Groq / OpenRouter API) |

---

## 3. Supported Fault Types

The harness supports six standard Toxiproxy toxic types:

1. **Connection Cut / Outage (`cut_connection`)**:
   - Disables the proxy completely, causing connection refused (`ECONNREFUSED` / `BrokenPipeError`).
   - Used for simulating process crashes, kills, and network blackholes.
2. **Injected Latency (`inject_latency`)**:
   - Adds symmetric or asymmetric millisecond delay (`latency`) with optional `jitter`.
   - Used for testing parallel latency absorption (Scenario 9) and SLA compliance.
3. **Connection Timeout (`inject_timeout`)**:
   - Keeps connections open for a specified duration before terminating them without sending data.
   - Used for testing client-side socket and gateway request timeouts (Scenario 8).
4. **Peer Connection Reset (`inject_connection_reset`)**:
   - Injects TCP `RST` packets immediately upon connection (`reset_peer`).
   - Used for testing transport-level socket error handling and retry circuits.
5. **Bandwidth Throttling (`inject_bandwidth_limit`)**:
   - Limits data transmission rates (`rate` in KB/s).
   - Used for testing slow networks and large payload streaming resilience.
6. **Temporary Partition (`temporary_partition`)**:
   - Cuts network traffic for a strictly bounded time window before automatically restoring it.
   - Used for testing transient broker partitions (Scenario 6) and recovery.

---

## 4. How to Inject and Remove Faults

Every fault is managed through a reversible Python context manager with guaranteed cleanup:

### Example 1: Simulating Redis Outage
```python
from tests.chaos import ChaosController, DependencyName

controller = ChaosController()

# Connection to Redis is completely cut inside this block
with controller.cut_connection(DependencyName.REDIS):
    # Execute verification request
    # Rate limiter fails closed with 503; SCS cache bypasses smoothly
    response = client.post("/v1/verify", json=payload, headers=headers)
    assert response.status_code == 503

# Exiting the block automatically re-enables the proxy
assert controller.check_health().is_healthy is True
```

### Example 2: Injected Latency on Qdrant
```python
with controller.inject_latency(DependencyName.QDRANT, latency_ms=500, jitter_ms=50):
    # Qdrant requests experience 500ms delay
    # Parallel pipeline absorbs delay or circuit breaker trips if timeout exceeded
    response = client.post("/v1/verify", json=payload, headers=headers)

# Latency toxic is automatically removed upon block exit
```

### Example 3: Global State Restoration
```python
controller = ChaosController()
# Clears all toxics, enables all proxies, and validates zero residual faults
health_status = controller.restore_all()
assert health_status.is_healthy is True
```

---

## 5. Safety Guards & Enforcement

The chaos harness includes five active safety protections:

1. **Explicit Enablement Guard (`MIRAGE_CHAOS_ENABLED=true`)**:
   - Fault injection raises `ChaosSafetyViolation` if `MIRAGE_CHAOS_ENABLED` is false or absent.
2. **Environment Protection**:
   - Rejects execution if `ENVIRONMENT=production` in application settings or if `CHAOS_ENVIRONMENT` is set to `prod`, `production`, or `staging`.
3. **Safe Host Allowlist Validation**:
   - Validates that target hosts match the safe allowlist (`localhost`, `127.0.0.1`, `backend_net` container names).
   - Explicitly blocks cloud RDS instances, production DNS names (`.prod`, `.internal`), or public IPs.
4. **Secret Sanitization & Redaction**:
   - The [`redact_secrets()`](file:///c:/Users/vedan/Desktop/MIRAGE/tests/chaos/config.py) function scrubs database passwords, JWT tokens, and API keys from all error logs and exception messages.
5. **Bounded Fault Durations**:
   - Prevents orphaned partitions by capping temporary fault durations (`CHAOS_MAX_FAULT_DURATION_SEC`, default 30s).

---

## 6. Cleanup Guarantees

- **Context Manager `finally` Blocks**: All fault primitives wrap their toxic deletion in `try ... finally`, ensuring cleanup executes even if test assertions fail or unhandled exceptions are raised.
- **Pytest Fixture Teardown**: The [`clean_chaos_environment`](file:///c:/Users/vedan/Desktop/MIRAGE/tests/chaos/fixtures.py) fixture calls `controller.restore_all()` both before each test and during post-test fixture teardown.
- **Pre- and Post-Fault Health Verification**: `controller.check_health()` inspects all proxies and toxics, asserting that zero disabled proxies or active toxics remain after test completion.

---

## 7. How P3.4 and P3.5 Will Consume the Harness

When implementing the full chaos scenarios in P3.4 and P3.5:
- **Scenario 1 (Redis Outage)**: Will call `with controller.cut_connection(DependencyName.REDIS):` to verify SCS bypass and rate limiter 503 fail-closed semantics.
- **Scenario 2 (Qdrant Outage)**: Will call `with controller.cut_connection(DependencyName.QDRANT):` to verify `qdrant_circuit` opening and RAV-less fallback mode.
- **Scenario 3 (NLI GPU Offline)**: Will call `with controller.cut_connection(DependencyName.NLI):` to verify degradation to RAV + SCS + Visual.
- **Scenario 4 (LLaVA Offline)**: Will call `with controller.cut_connection(DependencyName.LLAVA):` to verify visual grounding graceful bypass.
- **Scenario 5 (FLAN-T5 Offline)**: Will call `with controller.cut_connection(DependencyName.FLAN_T5):` to verify regex fallback claim splitting.
- **Scenario 6 (RabbitMQ Partition)**: Will call `with controller.cut_connection(DependencyName.RABBITMQ):` to verify circuit breaker trip and HTTP 503 return.
- **Scenario 7 (PostgreSQL Offline)**: Will call `with controller.cut_connection(DependencyName.POSTGRES):` to verify MongoDB trace persistence and authoritative PostgreSQL persistence contract (HTTP 503).
- **Scenario 8 (Upstream LLM 10s Delay)**: Will call `with controller.inject_timeout(DependencyName.UPSTREAM_LLM, timeout_ms=10000):` to verify gateway circuit breaker tripping.
- **Scenario 9 (500ms Network Latency Addition)**: Will call `with controller.inject_latency(DependencyName.QDRANT, latency_ms=500):` across services to verify parallel execution latency bounds.
- **Scenario 10 (Container OOM / Kill -9)**: Orchestrated container kill testing.
