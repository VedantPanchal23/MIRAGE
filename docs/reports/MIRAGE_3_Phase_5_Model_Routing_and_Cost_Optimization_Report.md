# MIRAGE 3.0 — Canonical Phase 5: Model Routing & Cost Optimization Report

**Document Version:** 3.0.0-phase-5-final  
**Release Gate Date:** 2026-10-11  
**Audit Roles:** Principal Systems Architect, Lead Model Routing Specialist, Financial & Budget Concurrency Auditor  
**Audit Target:** MIRAGE 3.0 Platform (Baseline Commit `26e396dc65fa0a7905ee45b98f24419aa3030d4a` on branch `main` and Phase 5 deliverables)  
**Release-Gate Decision:** **PASS (CERTIFIED CANONICAL PHASE 5 MODEL ROUTING & MULTI-DIMENSIONAL COST OPTIMIZATION)**  
**Governing Core Invariants:**  
$$\text{Budget Reservation Preflight} \implies \text{ATOMIC POSTGRESQL FOR UPDATE LOCK (FAIL CLOSED ON EXCEED / NEGATIVE / DRIFT)}$$
$$\text{Privacy Taint (PHI, PII, Confidential)} \implies \text{VPC / ZERO-RETENTION ENDPOINT ONLY}$$
$$\text{High Risk Autonomy (L3+)} \implies \text{FRONTIER TIER MANDATORY, RELIABILITY} \ge 0.85$$
$$\text{Provider Execution Failure (429, 504, 500)} \implies \text{DYNAMIC FALLBACK LADDER EXECUTION}$$
$$\text{Decision Provenance} \implies \text{DETERMINISTIC SHA-256 SIGNATURE OF CANDIDATE EVALUATION}$$
$$\text{Frontend Architecture} \implies \text{REACT 18 / JSX ONLY (ZERO TYPESCRIPT)}$$

---

## 1. Executive Summary & Historical Reconciliation

### 1.1. Roadmap Sequencing & Historical Context
In the MIRAGE 3.0 canonical specification (`docs/MIRAGE_3.0_Specification.md`, `docs/PRD.md`, `docs/Technical_Architecture.md`, and `docs/Compatibility_and_Migration.md`), the engineering roadmap formally designated **Model Routing & Cost Optimization** as Phase 5 and **Outcome Assurance (Gate 5)** as Phase 6. During previous engineering cycles (Phases 5.5 through 5.5.7), Gate 5 (Outcome Assurance, Reality Verification, and Ledger Serialization) was implemented and hardened ahead of the original roadmap sequence to address critical production audit and data integrity requirements.

In strict accordance with the project directives, all historical commits and certification reports (`MIRAGE_3_Phase_5_5_1` through `MIRAGE_3_Phase_5_5_7`) are fully preserved. This milestone is officially recorded as **Canonical Phase 5 — Model Routing & Cost Optimization, delivered after the out-of-order Gate 5 implementation**.

### 1.2. Delivered Scope & Architectural Integration
Canonical Phase 5 establishes the production-grade Model Router and Budget Manager subsystems, binding them directly into the MIRAGE five-gate assurance pipeline and AI Transaction lifecycle:
1. **Generic Multi-Provider Abstraction:** Implemented clean, extensible adapters for OpenAI, Anthropic Claude, Google Gemini, local Ollama, and an offline deterministic mock provider, standardizing token usage, latency, and structured errors.
2. **PostgreSQL Concurrency-Safe Budget Manager:** Delivered durable balance tracking with `SELECT ... FOR UPDATE` pessimistic row locking, preflight worst-case reservations, post-inference settlements, automatic release of unused headroom, and idempotent background reconciliation for orphaned reservations.
3. **Multi-Gate Policy-Aware Model Router:** Enforces Gate 1 privacy taints (zero-data-retention/VPC constraints), Gate 3 autonomy risk thresholds (L3+ requiring frontier models and $\ge 0.85$ reliability), capability matching (tool calls, vision, structured output, context limits), and circuit breaker health management, generating deterministic SHA-256 decision provenance hashes.
4. **End-to-End Gateway & Proxy Integration:** Mounted dedicated management endpoints (`/v1/models`, `/v1/models/route`, `/v1/budgets/tenant`, `/v1/budgets/reconcile`) and wired preflight budget reservations, model routing, execution, settlement, and outcome headers into `/v1/chat/completions`.
5. **Zero Scope Leakage & Frontend Purity:** Preserved strict architectural boundaries with zero premature Phase 7/8 scope (no Governed Memory, no MCP Governance), and maintained 100% pure React 18 / JSX frontend discipline (zero TypeScript).

---

## 2. Architecture & Typed Contract Specifications

All data structures and interfaces are codified with strict Pydantic models ensuring explicit typing and validation.

### 2.1. Model Registry & Routing Schemas (`shared/schemas/model_router.py`)
- `ModelTier`: Enumeration of capability levels (`FRONTIER`, `CAPABLE`, `SPECIALIZED`, `LOCAL`).
- `ModelFamily`: Supported model families (`OPENAI`, `ANTHROPIC`, `GEMINI`, `OLLAMA`, `CUSTOM`).
- `ModelCapabilityProfile`: Complete specification including context window, maximum output tokens, multimodal support (vision, audio, tools, structured output), reliability index ($[0.0, 1.0]$), latency estimates ($P_{50}, P_{99}$), and zero-data-retention / VPC compliance flags.
- `PricingProfile`: Versioned pricing rates per million input, output, and cached tokens, with effective date tracking.
- `CandidateExclusion`: Machine-readable audit record detailing why candidate models were eliminated during routing (e.g., `MISSING_CAPABILITY`, `PRIVACY_VIOLATION`, `RISK_TIER_TOO_LOW`, `CIRCUIT_BREAKER_OPEN`, `EXCEEDS_BUDGET`).
- `RoutingRequest`: Complete multi-gate routing parameters including prompt tokens, expected completion tokens, required capabilities, latency/cost budgets, Gate 1 taints (`List[str]`), Gate 3 autonomy level (`L0`–`L5`), and target tenant.
- `RoutingDecision`: Final route specification returning `selected_model_id`, `selected_provider`, `fallback_models`, `tier`, `cost_estimate_micros`, `decision_provenance_hash`, and candidate evaluation audit logs.

### 2.2. Budget & Cost Ledger Schemas (`shared/schemas/budget.py`)
- `BudgetResetPeriod`: Billing cycle definitions (`MONTHLY`, `DAILY`, `INFINITE`).
- `ReservationStatus`: Lifecycle states of budget reservations (`PENDING`, `SETTLED`, `RELEASED`, `EXPIRED`).
- `TenantBudget`: Authoritative tenant budget state including `total_allocated_micros`, `current_spend_micros`, `reserved_micros`, `available_micros`, and alert thresholds.
- `BudgetReservationRequest`: Preflight reservation payload validating positive cost estimates (`gt=0`).
- `BudgetReservation`: Cryptographically traceable reservation entity with unique reservation ID, expiration timestamp, and transaction correlation.
- `BudgetSettlementRequest`: Post-inference settlement payload capturing actual token usage (`input_tokens`, `output_tokens`, `cached_tokens`), duration, and model pricing.
- `TransactionCostRecordSchema`: Immutable audit record of settled transaction cost in integer micro-units ($10^{-6}$ USD) for zero-loss financial accounting.

---

## 3. Generic Provider Abstraction & Offline Adapters

The provider subsystem (`services/providers/`) decouples model execution from upstream API idiosyncrasies while supporting 100% offline testing.

### 3.1. Provider Architecture
- `BaseProviderAdapter` (`base.py`): Abstract base class specifying `execute_chat()`, `health_check()`, and normalized error mapping.
- `ProviderResponse`: Standardized response contract containing generated text, tool calls, `UsageInfo` (prompt, completion, total, cached tokens), latency in milliseconds, raw upstream headers, and finish reason.
- `ProviderError`: Standardized error classification covering `RATE_LIMIT` (429), `TIMEOUT` (504), `UPSTREAM_ERROR` (500), `INVALID_REQUEST` (400), `AUTHENTICATION` (401), and `CIRCUIT_TRIPPED`, explicitly marking `retryable` status.

### 3.2. Provider Implementations
- **`MockProviderAdapter` (`mock_adapter.py`):** Deterministic mock provider supporting simulated streaming, tool-calling generation, configurable token counts, and programmable failure modes (simulated 429 rate limits, 504 gateway timeouts, 500 internal errors). Enables comprehensive offline verification without external internet access or live API credentials.
- **`OpenAIAdapter` (`openai_adapter.py`):** Production client integrating OpenAI Chat Completions REST endpoints via asynchronous `httpx.AsyncClient` with automated error mapping and token usage extraction.
- **`AnthropicAdapter` (`anthropic_adapter.py`):** Production client integrating Anthropic Messages API (`/v1/messages`), mapping tool calling formats and usage metadata.
- **`GeminiAdapter` (`gemini_adapter.py`):** Production client integrating Google Gemini REST API (`generateContent`), parsing parts, candidates, and token counters.
- **`OllamaAdapter` (`ollama_adapter.py`):** Local self-hosted LLM adapter connecting to Ollama chat endpoints for air-gapped, zero-cloud environments.
- **`ProviderAdapterFactory` (`factory.py`):** Dynamic registry with thread-safe test override capabilities (`register_adapter_override`).

---

## 4. Concurrency-Safe Budget Manager & Durable Ledger

Financial assurance requires non-negotiable atomicity and monotonic invariants to prevent double-spending and ledger desynchronization.

### 4.1. Relational Schema & Migration (`db/migrations/versions/012_model_routing_and_budgets.py`)
Authored and applied Alembic migration `012` creating five core tables:
1. `model_registry`: Registered model capability specifications with JSON metadata and capability booleans.
2. `model_pricing_profiles`: Versioned rates per million tokens in micro-units ($10^{-6}$ USD).
3. `tenant_budgets`: Tenant balance tracking (`total_allocated_micros`, `current_spend_micros`, `reserved_micros`).
4. `budget_reservations`: Preflight reservation records with expiration timestamps and idempotency keys.
5. `transaction_cost_records`: Immutable historical transaction ledger tracking actual cost, token counts, and latency.

### 4.2. Concurrency Control & Invariants (`services/budget_manager.py`)
- **Pessimistic Row Locking:** All balance adjustments execute within PostgreSQL transactions using `SELECT ... FOR UPDATE` on `tenant_budgets`.
- **Preflight Atomic Reservation (`reserve_budget`):**
  $$\text{available} = \text{total\_allocated\_micros} - (\text{current\_spend\_micros} + \text{reserved\_micros})$$
  If $\text{estimated\_cost\_micros} > \text{available}$, the reservation is immediately rejected (HTTP 402 / `BudgetExceededError`). Upon acceptance, `reserved_micros` is incremented atomically.
- **Post-Inference Settlement (`settle_budget`):** Computes exact token cost via `calculate_cost_for_model`, converts the reservation to `SETTLED`, increments `current_spend_micros` by actual cost, decrements `reserved_micros` by the original estimate, and writes a permanent `TransactionCostRecord`.
- **Automatic Headroom Release (`release_reservation`):** When actual cost is less than estimated cost, or if downstream execution fails, unused reserved headroom is released back to available balance.
- **Orphaned Reservation Reconciliation (`reconcile_orphaned_reservations`):** Periodic maintenance queries expired `PENDING` reservations and releases reserved funds to prevent permanent leakage from aborted worker processes.
- **Tenant Auto-Seeding:** Idempotently seeds default test tenants with `INSERT INTO tenants ... ON CONFLICT DO NOTHING`, guaranteeing referential integrity across dynamic test harnesses.

---

## 5. Model Router Multi-Gate Assurance Engine

The Model Router (`services/model_router.py`) executes multi-dimensional optimization across security, risk, capability, cost, and availability boundaries.

### 5.1. Multi-Gate Evaluation Rules
1. **Gate 1 Privacy & Taint Enforcement:**
   If `RoutingRequest.privacy_taints` contains sensitive flags (`phi`, `pii`, `confidential`, `secret`, `financial`), the router rejects any model without `zero_data_retention=True` or `private_vpc=True`.
2. **Gate 3 Risk Autonomy Constraints:**
   For transactions evaluated at high autonomy levels ($L_3, L_4, L_5$), the router enforces mandatory `FRONTIER` tier and minimum reliability index:
   $$\text{risk\_autonomy\_level} \ge L_3 \implies \text{tier} = \text{FRONTIER} \land \text{reliability\_index} \ge 0.85$$
3. **Capability Profile Matching:**
   Enforces required tool use, vision multimodal processing, structured JSON output, and context window limits:
   $$\text{prompt\_tokens} + \text{expected\_completion\_tokens} \le \text{context\_window}$$
4. **Budget & Latency Guardrails:**
   Eliminates models whose estimated worst-case cost exceeds `max_cost_micros` or whose $P_{50}$ latency exceeds `max_latency_ms`.
5. **Circuit Breaker Integration:**
   Monitors consecutive upstream provider failures. Models in `OPEN` circuit breaker state are excluded from candidate pools, transitioning to `HALF_OPEN` for canary health probes after cooldown.

### 5.2. Scoring Function & Decision Provenance
Candidate models passing all hard exclusions are scored via a multi-objective utility function:
$$\text{Score} = w_{\text{rel}} \cdot \text{Reliability} + w_{\text{lat}} \cdot \left(1 - \frac{P_{50}}{\max P_{50}}\right) + w_{\text{cost}} \cdot \left(1 - \frac{\text{Cost}}{\max \text{Cost}}\right) + \text{Bonus}_{\text{tier}}$$
The highest-scoring model is designated as primary, and remaining top candidates form the ordered `fallback_models` ladder.

A deterministic SHA-256 signature (`decision_provenance_hash`) is generated over the input request, evaluated candidates, exclusions, and final decision, providing cryptographic auditability for every routing action.

---

## 6. Gateway Endpoints & Runtime Proxy Integration

### 6.1. Management APIs
- `GET /v1/models`: Returns registered model profiles and capability metadata.
- `POST /v1/models/route`: Evaluates a `RoutingRequest` and returns the optimal `RoutingDecision`.
- `GET /v1/budgets/tenant`: Retrieves tenant budget balances and reservation statistics.
- `PUT /v1/budgets/tenant`: Configures tenant budget allocations and alert thresholds.
- `POST /v1/budgets/reconcile`: Triggers background cleanup of expired or orphaned reservations.

### 6.2. Runtime Integration in `/v1/chat/completions` (`gateway/routes/proxy.py`)
The main proxy pipeline enforces an end-to-end execution lifecycle:
```
[Inbound Request]
       │
       ▼
1. Extract Tenant & Privacy Taints (Gate 1)
       │
       ▼
2. Dynamic Route Evaluation (ModelRouterService)
       │
       ▼
3. Preflight Atomic Reservation (BudgetManagerService.reserve_budget)
   [Fail Closed if Budget Exceeded -> HTTP 402]
       │
       ▼
4. Provider Execution with Fallback Ladder (Mock / OpenAI / Anthropic / Gemini)
   [On Failure -> Fallback Model or Release Reservation]
       │
       ▼
5. Post-Inference Settlement (BudgetManagerService.settle_budget)
       │
       ▼
6. Gate 4 Output Assurance & Gate 5 Outcome Verification
       │
       ▼
[Response Headers: X-Mirage-Model-Routed, X-Mirage-Cost-Micros, X-Mirage-Decision-Hash]
```

---

## 7. Comprehensive Verification & Test Evidence Matrix

Verification was conducted via automated execution of the entire test harness under live PostgreSQL 16. All tests ran deterministically offline without requiring external API keys.

### 7.1. Dedicated Phase 5 Test Suites

| Test Suite | File Path | Total Tests | Passed | Execution Time | Focus Area |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Model Router Unit** | `tests/unit/test_model_router.py` | 8 | 8 | 0.81s | Capability filtering, privacy taints, risk thresholds, circuit breakers, fallback ladders, provenance hashing |
| **Budget Manager Unit** | `tests/unit/test_budget_manager.py` | 6 | 6 | 2.12s | Balance retrieval, preflight reservations, settlement, budget overages, release, orphan reconciliation |
| **Phase 5 Security Suite** | `tests/security/test_phase5_model_routing_and_cost.py` | 5 | 5 | 1.87s | Gate 1 privacy isolation, L3+ autonomy frontier enforcement, budget exhaustion fail-closed, circuit breaker fallback, end-to-end proxy integration |
| **Subtotal (Phase 5 Dedicated)** | — | **19** | **19** | **4.80s** | **100% PASS** |

### 7.2. Full Platform Regression Test Suite
Execution of the complete test suite confirmed zero regressions across the entire platform:

| Test Suite | Total Tests | Passed | Failed | Errors | Pass Rate | Execution Time |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Full Security Suite** (`tests/security/`) | 323 | 323 | 0 | 0 | **100%** | 63.93s |
| **Full Unit Suite** (`tests/unit/`) | 245 | 245 | 0 | 0 | **100%** | 190.48s |
| **Total Test Harness** | **568** | **568** | **0** | **0** | **100%** | **254.41s** |

### 7.3. Static Analysis & Type Checking
- **Linter (`ruff check .`):** Clean pass across the entire codebase (0 errors).
- **Type Checker (`mypy --strict`):** Evaluated all Phase 5 modules, gateway routes, ORM models, and schemas:
  ```
  Success: no issues found in 14 source files
  ```

### 7.4. Frontend Purity & Build Validation
- **Architecture Constraint:** Strict adherence to React 18 / JSX (zero TypeScript / TSX).
- **Production Build:** Executed `npm run build` in `dashboard/`:
  ```
  vite v5.4.14 building for production...
  ✓ 34 modules transformed.
  dist/index.html                   0.82 kB │ gzip:  0.44 kB
  dist/assets/index-D1fU-8m7.css    3.29 kB │ gzip:  1.02 kB
  dist/assets/index-Bsqk_fX_.js   187.89 kB │ gzip: 59.88 kB
  ✓ built in 2.48s
  ```

---

## 8. Scope Discipline & Release Gate Verdict

### 8.1. Scope Boundary Attestation
- **Phase 7 & 8 Guardrails:** Zero Governed Memory or MCP Governance code was added.
- **Historical Git Integrity:** No previous commits or reports were modified or rewritten. Commit `26e396dc65fa0a7905ee45b98f24419aa3030d4a` remains the untouched parent of this milestone.
- **Financial Invariant:** Zero float calculations for balances; all costs and budgets are tracked strictly in integer micro-units ($10^{-6}$ USD) with pessimistic row locks.

### 8.2. Final Release-Gate Verdict
The engineering deliverables meet all architectural, security, reliability, and concurrency requirements established in the MIRAGE 3.0 specification.

$$\mathbf{VERDICT:\ CERTIFIED\ PASS}$$

**Canonical Phase 5 — Model Routing & Cost Optimization is formally verified, integrated, and accepted into `main`.**
