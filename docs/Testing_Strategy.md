# MIRAGE 3.0 — Testing Strategy

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05

## 1. Introduction

This document outlines the complete testing pyramid and evaluation methodology for MIRAGE 3.0. Testing must ensure that the AI Execution Assurance Platform is resilient, accurate, secure, and performant.

MIRAGE 3.0 preserves and references the excellent MIRAGE 2.x testing heritage, including:
- 8-tier testing pyramid
- Chaos testing framework with toxiproxy
- Adversarial robustness suite (ATK-01 through ATK-04)
- Model behavioral bounds testing
- Fail-open vs fail-closed boundary testing
- Mathematical invariant enforcement

## 2. The 8-Tier Testing Pyramid

### 2.1 Unit Tests
- **Scope:** Individual component logic, utility functions, gate validators. Key modules include risk scoring algorithms and parsing utilities.
- **Acceptance Criteria:** >90% line coverage. All tests must complete within 2 minutes. No external network calls (all mocked).

### 2.2 Component Tests
- **Scope:** Subsystem behavior (e.g., Risk Engine, Policy Engine, Context Builder).
- **Acceptance Criteria:** Must test 100% of state transitions for each component. Mocked external dependencies are permitted.

### 2.3 Contract Tests
- **Scope:** API contract compliance.
- **Tooling:** Schemathesis against OpenAPI 3.0 specifications.
- **Acceptance Criteria:** 0 contract violations. All documented API boundaries must strictly validate payloads.

### 2.4 Integration Tests
- **Scope:** Cross-service interactions over real network protocols (e.g., Gateway to Intent Classifier to Policy Engine).
- **Tooling:** `testcontainers-python` for ephemeral databases and brokers.
- **Acceptance Criteria:** Must verify successful data flow and error propagation.

### 2.5 Security Tests
- **Scope:** Auth, RBAC/ABAC, capability model, tenant isolation, injection.
- **Acceptance Criteria:** All tenant boundary crossings must be blocked. Capability enforcement must successfully deny unauthorized actions without exception.

### 2.6 Adversarial Tests
- **Scope:** Prompt injection (direct/indirect), tool poisoning, memory poisoning, MCP poisoning, model supply-chain attacks.
- **Acceptance Criteria:** Preservation of MIRAGE 2.x adversarial suite (ATK-01 to ATK-04). System must successfully neutralize >99.9% of indirect prompt injections.

### 2.7 Property-Based Tests
- **Scope:** Protocol invariants, mathematical properties of risk scoring and cost attribution.
- **Tooling:** Hypothesis (Python) / Quickcheck-style tools.
- **Acceptance Criteria:** No unhandled exceptions or state corruptions when components are subjected to dynamically generated edge-case inputs.

### 2.8 Performance Tests
- **Scope:** Latency and throughput.
- **Acceptance Criteria:** p95 latency for inline control plane evaluations per gate (Policy, Risk) must be < 15ms. System must support 10k RPS baseline throughput.

## 3. Specialized Testing & Reliability

### 3.1 Load Tests
- **Scope:** Sustained high-volume traffic.
- **Tooling:** k6 or Locust.
- **Acceptance Criteria:** Must sustain 3x average load for 4 hours with zero memory leaks and stable latencies.

### 3.2 Stress Tests
- **Scope:** Beyond capacity behavior.
- **Acceptance Criteria:** System must demonstrate graceful degradation (circuit breakers trip, `429 Too Many Requests` returned) without crashing.

### 3.3 Chaos Tests
- **Scope:** Dependency failure, network partition.
- **Tooling:** MIRAGE 2.x Chaos Framework (using toxiproxy).
- **Acceptance Criteria:** Simulating Redis or DB failure must result in strictly defined fail-closed or fail-open behavior.

### 3.4 Resilience Tests
- **Scope:** Recovery, failover, leader election.
- **Acceptance Criteria:** Recovery Time Objective (RTO) < 30 seconds for stateful service failover.

### 3.5 Multi-Tenant Isolation Tests
- **Scope:** Cross-tenant data leakage verification across all stores (PostgreSQL, Qdrant, MongoDB).
- **Acceptance Criteria:** Automated suite must continuously attempt and fail to read Tenant B data using Tenant A credentials.

## 4. Evaluation Testing

### 4.1 Model Evaluation
- **Scope:** Verification Engine accuracy, calibration, conformal coverage.
- **Acceptance Criteria:** Expected Calibration Error (ECE) < 0.05.

### 4.2 Routing Evaluation
- **Scope:** Model selection quality.
- **Acceptance Criteria:** Router selects the lowest-cost model meeting capability and risk requirements in 100% of tested scenarios.

### 4.3 Cost Evaluation
- **Scope:** Budget enforcement, cost attribution.
- **Acceptance Criteria:** Hard budgets must never be exceeded by more than the cost of a single atomic transaction.

### 4.4 Policy Evaluation
- **Scope:** Policy decision correctness, conflict resolution.
- **Acceptance Criteria:** Expected policy outcomes must match deterministic ground truth.

### 4.5 Memory Poisoning Tests
- **Scope:** Detection and prevention of context injection.
- **Acceptance Criteria:** Contradictory or malicious memory injections flagged in Gate 2 (Context Assurance).

### 4.6 Tool Poisoning Tests
- **Scope:** Malicious tool output handling.
- **Acceptance Criteria:** Tool outputs containing imperative execution commands or scripts must not bypass Gate 1 or Gate 3 checks.

### 4.7 Prompt Injection Tests
- **Scope:** Resistance measurement.
- **Acceptance Criteria:** High resistance against sophisticated jailbreak prompts (measured against dynamic red-team datasets).

### 4.8 Outcome Verification Tests
- **Scope:** Reality verification accuracy.
- **Acceptance Criteria:** Gate 5 accurately flags partial failures and discrepancies between expected and actual state.

### 4.9 End-to-End Tests
- **Scope:** Full transaction lifecycle (Input → Identity → Intent → Risk → Policy → Routing → Context → Plan → Action → Tool/MCP/API → Real World → Outcome → Output → Assurance).
- **Acceptance Criteria:** Successful navigation of all assurance gates resulting in accurate output and audit trace.

## 5. CI/CD Test Gating

- **Pull Request (PR):** Unit Tests, Component Tests, Contract Tests, static analysis.
- **Staging / Pre-Merge:** Integration Tests, Security Tests, Property-Based Tests, Performance Baseline, Multi-Tenant Isolation.
- **Nightly / Production-Readiness:** E2E Tests, Chaos Tests, Adversarial Tests, Load & Stress Tests, Model Evaluations.

## 6. Coverage Targets
- **Core Verification Engine:** 95%
- **Policy Engine:** 100% (logic branches)
- **API/Gateway:** 90%
- **Tool Integrations:** 85%

## 7. Test Data Management
- **Fixtures:** Used strictly for Unit and Component tests. Kept in source control.
- **Live Data:** Used carefully in staging. Must be fully anonymized.
- **Dataset Governance:** Adversarial datasets are versioned and stored securely to prevent test-set leakage into model training/prompt contexts.

## 8. Benchmark Limitations
No benchmark numbers or benchmark figures shall be fabricated. Performance guarantees are defined as minimum targets based on architecture design. Exact system benchmarks are determined per deployment environment.
