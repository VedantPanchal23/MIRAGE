# MIRAGE: Testing Strategy
**Autonomous Multimodal Hallucination Detection and Factual Consistency Verification System for Production LLMs**

**Version:** 2.1.0
**Date:** September 2026
**Authors:** 23AIML042 Vedant, 23AIML076 Dax
**Institution:** IIIT Bangalore — CTRI-DG

---

## 1. Testing Philosophy

The testing methodology for the MIRAGE middleware is governed by a **shift-left approach**: test early, test often, and test comprehensively before code reaches staging or production environments. Given that MIRAGE operates as a critical security and reliability middleware for production Large Language Models (LLMs), traditional software testing paradigms are insufficient. Our philosophy extends the classic test pyramid to treat **Model Evaluation**, **Security**, and **Chaos/Fault Tolerance** as first-class citizens alongside standard functional correctness.

> [!IMPORTANT]  
> Security testing and model benchmarking are not optional add-ons. They are directly integrated into the CI/CD pipeline and the standard testing pyramid to ensure absolute reliability in multi-tenant, high-throughput environments.

## 2. Test Pyramid

MIRAGE utilizes a multi-tiered test pyramid engineered specifically for complex ML systems. The volume of tests decreases as we move up the pyramid, reflecting the increasing cost, time, and complexity of execution.

```text
                  /\
                 /  \
                / E2E\ (10 tests)
               /------\
              / Chaos  \ (10+ scenarios)
             /   Perf   \ (10+ scenarios)
            /------------\
           /   Security   \ (30+ tests)
          /    Contract    \ (20+ tests)
         /------------------\
        /    Integration     \ (50+ tests)
       /----------------------\
      /       Model Unit       \ (50+ tests)
     /        Unit (Core)       \ (200+ tests)
    ------------------------------
```

### Layer Breakdown
*   **Unit Tests:** Testing individual functions and pure business logic (no external DBs/networks).
*   **Model Unit Tests:** Ensuring model inference correctness, output parsing, and deterministic constraints.
*   **Integration Tests:** Testing multi-component interactions across actual databases and queues.
*   **Contract Tests:** Validating strict compliance with defined API and JSON schemas.
*   **Security Tests:** Verifying RBAC, data isolation, and resilience against adversarial payloads.
*   **Performance Tests:** Validating latency, throughput, and concurrent scaling behavior.
*   **Chaos Tests:** Ensuring fault tolerance, fallback activations, and graceful degradation during system failure.
*   **E2E / Smoke Tests:** Comprehensive, full-pipeline testing from initial prompt to final verified response.

## 3. Unit Testing

The foundational layer verifies isolated components quickly and reliably.
*   **Framework:** `pytest` augmented with `pytest-cov` and `pytest-asyncio`.
*   **Mocking Strategy:** External dependencies (Qdrant, Redis, PostgreSQL, LLM APIs, and GPU model servers) are mocked using `pytest` fixtures and `unittest.mock`.

### Test Categories by Module

*   **Gateway:**
    *   *Focus:* Request payload parsing, tenant authentication logic, rate limit counter algorithms, environment config loading.
*   **FLAN-T5 Decomposer:**
    *   *Focus:* JSON output validation, Regex parser fallbacks, claim type classification, claim criticality assignment (`high`, `medium`, `low`), edge cases (empty strings, extremely long sequences, malformed characters).
*   **RAV Module (Retrieval-Augmented Verification):**
    *   *Focus:* Text-to-embedding translation interfaces, Qdrant vector distance algorithms, retrieval score normalization ($RSS$).
*   **SCS Module (Self-Consistency Sampling):**
    *   *Focus:* SHA-256 prompt-model cache key generation logic, n=5 sample collection, bidirectional semantic clustering, Semantic Entropy formula calculation ($SE(x) = -\sum p(c) \log p(c)$), cache hit/miss resolution logic.
*   **NLI Scorer (DeBERTa-v3-large):**
    *   *Focus:* Asynchronous batch tensor construction, raw logits to probability extraction via Softmax, (Premise, Hypothesis) label parsing, multi-evidence max-contradiction aggregation.
*   **ICS Module (Internal Consistency Scorer):**
    *   *Focus:* Pairwise intra-response claim combination generation ($O(K^2)$ filtered by shared entities/attributes), DeBERTa contradiction scoring, $ICS_{\text{resp}}$ max-pooling, circular reasoning detection.
*   **HRS Engine (Hallucination Risk Score):**
    *   *Focus:* LightGBM GBDT inference logic, 12-feature vector extraction, Isotonic regression calibration, Platt scaling and Temperature scaling baseline implementations, Mondrian group-conditional conformal quantile lookup, TreeSHAP feature attribution calculation, and criticality-weighted response aggregation.
*   **Correction Agent (LangGraph):**
    *   *Focus:* DAG traversal logic, state mutations, claim prioritization queueing (high criticality first), contextual evidence selection, mandatory re-verification pass.
*   **Audit Module:**
    *   *Focus:* JSONB and BSON document formulation, asynchronous write-ahead log structures, cryptographic chain hash validation.
*   **RBAC (Role-Based Access Control):**
    *   *Focus:* JWT decoding, bitwise permission validation, role inheritance traversal, explicit tenant isolation rule enforcement.

## 4. Model Testing

Model logic cannot be tested simply by checking for a 200 HTTP response. These tests evaluate deterministic behavioral bounds of probabilistic components.

*   **FLAN-T5 Decomposer:**
    *   *JSON Validity:* 100 sample responses must yield >99% successfully parsable JSON output.
    *   *Claim Extent:* Ensure output array realistically contains between 1 and 20 discrete claims.
    *   *Criticality Coverage:* Output must assign valid criticality (`high`, `medium`, `low`) matching rule-based heuristics on 100 benchmark assertions.
    *   *Distribution Check:* All supported types (Factual, Temporal, Numerical, Relational, Image-Grounded) must be correctly classified against a curated test set.
    *   *Latency Bound:* < 50ms per batch operation on CPU.
    *   *Regression Target:* Claim F1 score on a held-out evaluation set must not decrease following any model weight updates.
*   **DeBERTa Verifier:**
    *   *Output Shape:* Model must consistently yield three floating-point values (Entailed, Neutral, Contradicted) that exactly sum to 1.0.
    *   *Known-Answer Verification:* Evaluated against a curated set of 50 exact (Premise, Hypothesis) pairs with statically defined expected labels.
    *   *Intra-Response Contradiction Sensitivity:* Evaluated against 20 curated contradictory claim pairs (e.g. arithmetic/temporal mismatches) — contradiction prob must exceed 0.80.
    *   *Calibration:* Expected Calibration Error (ECE) must remain < 0.05 on held-out sets.
    *   *Latency Bound:* 10 pairs inferred in < 200ms on GPU (G5.2xlarge / College GPU).
*   **LLaVA Visual Grounder:**
    *   *Response Parsing:* Regex or structured output must consistently extract `CONSISTENT`, `INCONSISTENT`, or `INSUFFICIENT_EVIDENCE`.
    *   *Known-Answer Verification:* Evaluated against 20 curated (Image, Claim) pairs mapping to concrete ground truth labels.
    *   *Latency Bound:* Single image/claim extraction in < 1000ms.
*   **CLIP Pre-filter:**
    *   *Threshold Logic:* Asserts that cosine similarity > 0.85 gracefully skips LLaVA, while similarity ≤ 0.85 strictly invokes the heavier vision model.
    *   *Known-Answer Verification:* 10 obviously consistent pairs (bypass filter check) and 10 logically disconnected pairs (trigger filter).

## 5. Integration Testing

Validates cross-boundary communication using ephemeral environments.
*   **Framework:** `pytest` in tandem with `testcontainers-python`.
*   **Infrastructure:** Ephemeral Docker containers for PostgreSQL, MongoDB, Qdrant, Redis, and RabbitMQ spin up strictly for the test duration.

### Integration Scenarios
1.  **Gateway → RAV Worker → Qdrant:** E2E retrieval accuracy and connection pooling.
2.  **Gateway → SCS Worker → Redis:** Ensuring caching round-trips correctly write and retrieve state.
3.  **Cache Behavior:** Explicit validation of cache hit (fast path) vs. cache miss (full computation path) state flows.
4.  **HRS Engine Topologies:**
    *   Compute with all 5 signals intact (RAV, SCS, NLI, VGS, ICS).
    *   Compute with SCS disabled (validating dynamic weight redistribution across remaining signals).
5.  **Dual-write Audit Logging:** Concurrent insertions into PostgreSQL (relational mappings) and MongoDB (trace payloads).
6.  **Correction Triggers:** Agent wakes up and successfully modifies output when `HRS > Tier.HIGH` threshold.
7.  **Correction Escalation:** If the LangGraph agent fails 2 consecutive iterations, verify it escalates or gracefully terminates to avoid infinite loops.
8.  **Data Isolation (PostgreSQL RLS):** Tenant A attempts to execute `SELECT *` — verify Row-Level Security explicitly prevents reading Tenant B's data.
9.  **Data Isolation (MongoDB):** Verify `traces_{tenant_A}` namespace is completely sealed from Tenant B's API key context.
10. **Rate Limiting Mechanism:** Verify HTTP `429 Too Many Requests` correctly engages upon crossing specified API limits.
11. **Circuit Breaking:** Intentionally crash Qdrant container → verify system seamlessly activates RAV-less fallback mode without dropping the HTTP connection.
12. **Alembic Migrations:** Ensure the PostgreSQL schema cleanly migrates both from an empty DB and an existing earlier version without data loss.

## 6. Contract Testing

Ensures total stability and backward compatibility of all exposed APIs.
*   **Framework:** `schemathesis` (generates property-based test cases dynamically from our OpenAPI/Swagger v3 schema).

### Target Contracts
*   `POST /v1/verify`: Request body must fully comply with OpenAI-compatible Chat Completions standard (used by Groq, OpenRouter, HuggingFace).
*   `POST /v1/verify`: Response payload must guarantee the inclusion of `mirage.hrs`, `mirage.tier`, `mirage.claims`, `mirage.claims[*].criticality`, `mirage.claims[*].ics_score`, and `mirage.claims[*].signal_attribution`.
*   **Errors:** Standardized error schema enforced globally (`code`, `message`, `trace_id`, `timestamp`).
*   **Headers:** Absolute requirement for `Strict-Transport-Security`, `X-Content-Type-Options`, and `X-Frame-Options` on all endpoints.
*   **HRS Bounds:** System invariant: `0.0 <= HRS <= 1.0`.
*   **Tier Enumeration:** Must output exactly one of `[LOW, MEDIUM, HIGH, CRITICAL]`.
*   **Conformal Interval Logic:** Must satisfy mathematical constraint `hrs_ci_lower <= hrs <= hrs_ci_upper`.
*   **TreeSHAP Normalization:** Sum of active signal attributions in `signal_attribution` must equal 1.0 ($\pm 0.01$).


## 7. Security Testing

Security testing is segmented into automated pipelines and periodic manual inspections.

### Automated CI Tests
*   **Cross-Tenant Access:** Hard isolation checks to ensure API Key A cannot fetch Analytics B.
*   **JWT Integrity:** Tampered claims and expired tokens must explicitly return `401 Unauthorized` or `403 Forbidden` with standard error schemas.
*   **Injection Resistance:** Parametrized validation utilizing the OWASP SQLi payload lists against PostgreSQL, and NoSQL injection payloads against MongoDB search filters.
*   **Rate Limit Bypass Attempts:** Distribute synthetic source IPs to verify that token-bucket limits are enforced by *tenant key*, not just IP address.
*   **RBAC Matrix Mapping:** Every defined role is tested against every permission block to ensure no accidental escalations exist.
*   **Audit Tamper Detection:** Any `UPDATE` or `DELETE` executed against the audit ledger must fail at the database level.
*   **Cryptographic Chain Validation:** Verify sequential hash integrity using a script recalculating the SHA-256 chain of audit entries.

### Manual/Periodic Audits
*   **Weekly:** OWASP ZAP automated baseline scans running against the staging environment.
*   **Monthly:** Burp Suite Professional manual probing of authenticated endpoints.
*   **Monthly (LLM Specific):** Prompt Injection payload suites passed through the proxy to ensure adversarial content cannot hijack the LangGraph correction agent.
*   **Month 5 Project Milestone:** External formal Penetration Test.

### 7.3 Adversarial Robustness Test Suite

To verify resilience against model evasion tactics, automated CI security suites run 4 explicit adversarial attack test cases:

1.  **ATK-01 (Hedged Phrasing Resilience):** Inject 50 synthetically hedged false assertions (e.g., *"It is commonly speculated that..."*). Assert that DeBERTa verifier identifies the core contradiction without classification drift ($\Delta F_1 < 0.05$).
2.  **ATK-02 (Stated Confidence Invariance):** Append authoritative false framing (e.g., *"As an established medical consensus confirmed by all researchers..."*). Assert that computed HRS is invariant ($\Delta HRS < 0.02$) compared to the unadorned false claim.
3.  **ATK-03 (Hallucinated Citation Detection):** Feed claims citing fabricated papers and authors. Assert that RAV Qdrant retrieval score is $RSS > 0.85$ (unsupported) and surfaces an explicit `unverified_citation` flag.
4.  **ATK-04 (Evidence Poisoning Resilience):** Inject contradictory poisoned documents into an isolated test collection in Qdrant. Assert that the multi-signal LightGBM ensemble rejects the hallucination due to high Semantic Entropy and high ICS disagreement, despite the poisoned KB match.

## 8. Performance Testing

Validates systemic behaviors under variable and extreme conditions.
*   **Framework:** `k6`

### Load Scenarios
1.  **Baseline:** 1 concurrent user, 100 requests. (Measures stable P50/P95/P99 latency).
2.  **Ramp-up:** 1 → 100 concurrent users over 5 minutes. (Identifies inflection breaking points).
3.  **Sustained Load:** 100 concurrent users held for 10 minutes. (Validates system stability without memory leaks).
4.  **Spike/Burst:** 10 → 200 → 10 concurrent users. (Validates swift recovery of connection pools).
5.  **Noisy Neighbor (Single-Tenant Burst):** Tenant A pushes 10x volume. (Verifies Tenant B latency is completely unaffected).
6.  **SCS Cache Warm Load:** Blast 10 identical prompts repeatedly. (Verifies cache hit > 90% and massive latency drop).
7.  **Model Cold Start:** Hard restart TorchServe. (Measures raw initialization/weights-loading time).
8.  **DB Exhaustion:** Overwhelm PgBouncer/PostgreSQL with 200 concurrent writes. (Verifies graceful queueing without data loss).
9.  **RabbitMQ Backpressure:** Flood async logging queues. (Verifies max depth limits drop requests predictably instead of causing OOM).
10. **Correction Loop Latency:** Inject prompts triggering high HRS. (Verifies LangGraph corrects and returns within 2 seconds).

### Acceptance Criteria
*   P95 E2E Latency < 3000ms at 100 concurrent sessions.
*   System Sustained Throughput > 33 requests/second.
*   Zero data loss (all 100% of audit logs present in PG/Mongo under load).
*   Zero HTTP 5xx errors under normal standard operating load.

## 9. Chaos Testing

Resilience verification utilizing `toxiproxy` and orchestrated container failures.

| Scenario | Injected Fault | Expected System Behavior & Recovery |
| :--- | :--- | :--- |
| **1** | Redis forcefully killed | SCS module bypasses cache smoothly, NLI takes over. HTTP 200 returned. |
| **2** | Qdrant forcefully killed | Circuit breaker opens, system defaults to RAV-less fallback mode. HTTP 200 returned. |
| **3** | NLI GPU Server offline | Graceful degradation to RAV + SCS + Visual logic only. |
| **4** | LLaVA Server offline | System ignores visual grounding requirements for image claims. |
| **5** | FLAN-T5 Server offline | System catches timeout, falls back to static Regex claim splitter. |
| **6** | RabbitMQ Network Partition | Circuit breaker opens, HTTP 503 returned gracefully rather than hanging. |
| **7** | PostgreSQL offline | Audit writes succeed to MongoDB, PG writes queued to memory/disk buffer. |
| **8** | Upstream LLM API (Groq/OpenRouter) 10s Delay | Gateway circuit breaker fires instantly, HTTP 503 returned to client. |
| **9** | 500ms Network Latency Addition | Parallel async executions absorb delay; E2E latency remains within standard SLA. |
| **10** | Container OOM / Kill -9 | Docker/Kubernetes health checks identify dead pod, successfully restart < 5 seconds. |

## 10. Regression Testing

Automated gates ensuring subsequent updates do not degrade prior system state.
*   **Model Regression:** Following any finetuning (FLAN-T5, DeBERTa, LLaVA), the offline benchmark suite evaluates against holdout datasets. Changes rejected if Claim F1 drops > 0.02 or Calibration ECE increases > 0.01.
*   **API Regression:** Full `schemathesis` contract test suite runs automatically on any FastAPI router modification.
*   **Security Regression:** Full RBAC and injection suite runs on changes to middleware auth modules.
*   **Performance Regression:** K6 Baseline test runs nightly, alerting on latency deviations > 10% from historical moving average.

## 11. Test Data Management

*   **Test Fixtures:** Small, manually curated JSON representations of prompts, LLM responses, generated claims, and evidence chunks stored securely in `tests/fixtures/`.
*   **Model Fixtures:** Representative slices of *HaluEval* and *TruthfulQA* benchmarks stored in `tests/model_fixtures/`.
*   **Ephemeral DB State:** All database state is isolated per-test. `testcontainers` ensures completely fresh environments. Zero shared state.
*   **Data Sanctity:** Absolutely NO production data is ever pulled down to local or staging environments. All user strings are synthesized.
*   **Secrets:** API Keys and mocked credentials securely injected via `.env.test`, never committed to source control.

## 12. CI/CD Integration

The testing pyramid is deeply embedded into our GitHub Actions deployment pipelines:

*   **Every Commit:** `ruff` (Lint) + `mypy` (Type Check) + Pytest Unit Tests + `trivy` (Security Scans).
*   **Every PR Creation:** Unit + Model Unit + Integration + Contract + Security Tests run parallelized.
*   **Merge to `develop`:** Trigger deployment to Staging environment + Run Smoke Tests + Run OWASP ZAP Baseline.
*   **Release to `main`:** Full K6 performance test suite run against isolated replica + Generation of full SBOM (Software Bill of Materials).
*   **Pipeline Gates:** 
    *   **Coverage Block:** PR cannot merge if absolute line coverage dips beneath 85%.
    *   **Security Block:** PR cannot merge if `Bandit`, `Safety`, or `Trivy` flags any High or Critical vulnerabilities.

## 13. Test Environment Architecture

*   **Local Development:** Orchestrated via `docker-compose`. Full suite of DB dependencies. Model servers run mocked lightweight CPU wrappers for rapid developer velocity.
*   **CI Pipeline (GitHub Actions):** Operates on standard runners utilizing `testcontainers`. No GPU available; Model logic is verified using pre-computed deterministic I/O fixtures.
*   **Staging:** Identical mirror to production topology hosted on AWS. Full G5.2xlarge GPU access.
*   **Production:** Strictly reserved for lightweight, non-destructive Smoke Tests and Canary synthetic verifications.

## 14. Coverage Targets Table

| System Component | Minimum Line Coverage | Minimum Branch Coverage |
| :--- | :--- | :--- |
| **Global Pipeline Average** | 85.0% | 80.0% |
| **Gateway & Middleware** | 90.0% | 85.0% |
| **FLAN-T5 Module** | 85.0% | 80.0% |
| **RAV & SCS Workers** | 85.0% | 80.0% |
| **ICS Module (Intra-Response NLI)** | **90.0%** | **85.0%** |
| **NLI & VGS Inferencing** | 85.0% | 80.0% |
| **HRS Engine (LightGBM Meta-Learner)** | **95.0%** | **95.0%** |
| **Mondrian Conformal Module** | **95.0%** | **95.0%** |
| **TreeSHAP Attribution Generator** | **90.0%** | **85.0%** |
| **Correction Agent (LangGraph)** | 90.0% | 85.0% |
| **RBAC & Auth Verification** | **95.0%** | **95.0%** |

## 15. Test Execution Commands

The test suite leverages native `pytest` markers for precise execution filtering.

```bash
# Run all unit tests with full HTML coverage reporting
pytest -m unit --cov --cov-report=html

# Run isolated model verification tests
pytest -m model_unit

# Spin up testcontainers and run integration suite
pytest -m integration

# Run security, injection, and RBAC tests
pytest -m security

# Run adversarial robustness test suite
pytest -m adversarial

# Run Schemathesis contract suite against OpenAPI spec
pytest -m contract

# Run k6 baseline performance scenario locally
k6 run tests/performance/baseline.js
```

---

## 16. Document Changelog

| Version | Date | Description |
|---|---|---|
| 1.0.0 | August 2026 | Initial Draft Testing Strategy |
| 2.0.0 | September 2026 | Comprehensive rewrite: 8-layer test pyramid, unit/model/integration/contract/security/performance/chaos/E2E tests, coverage targets, CI gating. |
| 2.1.0 | September 2026 | Advanced Research Overhaul: Added test suites for Internal Consistency Scorer (ICS), Semantic Entropy clustering, LightGBM meta-learner, Mondrian conformal prediction, TreeSHAP attribution, and 4-vector Adversarial Robustness Test Suite (hedged phrasing, stated confidence injection, fake citations, evidence poisoning). |

