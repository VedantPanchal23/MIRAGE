# MIRAGE 3.0 — Benchmarking and Evaluation

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05

## 1. Introduction

This document defines the methodology for benchmarking and evaluating MIRAGE 3.0. Evaluating an AI Execution Assurance Platform requires rigorous distinction between engineering performance, security resilience, model accuracy, and real-world outcome verification. 

**Strict Rule:** No fabricated benchmark numbers or fixture data masquerading as scientific evidence are permitted. All dataset references must be reproducible, strictly versioned, and cryptographically verified.

---

## 2. Evaluation Methodology and Provenance

MIRAGE preserves and extends the `BenchmarkCertificationGuard` concept from 2.x. 
Every benchmark result must cryptographically sign its methodology, dataset hash, model version, and exact prompt protocol used.

### 2.1 Tier 1 vs. Tier 2 Distinctions
- **Tier 1 (Curated, N=30):** Certified, immutable benchmarks using public datasets with full provenance and statistical validity. Used for official releases and compliance reporting.
- **Tier 2 (Academic/Internal, N≥1000):** Internal, unverified, or dynamically generated benchmarks used for CI/CD, directional feedback, and broad generalization testing across massive datasets.

### 2.2 BenchmarkCertificationGuard (7 Gates)
All Tier 1 benchmark runs must pass the 7 machine-checkable gates before results are accepted:
1. Dataset SHA-256 checksum verification.
2. Model weight hash/API version verification.
3. Prompt template exact match verification.
4. Zero-contamination check (training data isolation).
5. Statistical significance threshold met.
6. Execution environment parity verified.
7. Cryptographic signature of the final report.

### 2.3 Statistical Protocols
- **Bonferroni Correction:** Applied when evaluating multiple hypotheses across model routing strategies to prevent false positives.
- **Paired Bootstrap Resampling:** Used for comparing latency distributions and verification accuracy between MIRAGE 2.x and 3.0.
- **McNemar's Test:** Deployed for evaluating changes in the error rates of the Output Assurance engine before and after tuning.

---

## 3. Preserved MIRAGE 2.x Benchmark Heritage

MIRAGE 3.0 retains the core datasets and evaluation methodologies that established its authority in hallucination detection.

### 3.1 Datasets
- **HaluEval:** Broad-domain hallucination detection.
- **TruthfulQA:** Factuality and adversarial truthfulness.
- **FActScore:** Atomic fact decomposition and verification.
- **MMHAL-Bench:** Multimodal hallucination detection.

### 3.2 Evaluation Designs
- **12-Configuration Ablation Study:** Evaluates the contribution of individual verification components (RAV, SCS, NLI, ICS) by systematically disabling them.
- **3-Way Calibration Comparison:** Compares uncalibrated model confidence, Isotonic Regression calibration, and Conformal Prediction bounded intervals.
- **Cross-Model Generalization Testing:** Verifies that the holistic reliability scoring remains accurate across different foundation models (e.g., Llama, GPT-4, Claude).
- **Adversarial Robustness Suite (ATK-01 to ATK-04):** Evaluates resilience against prompt injection, context poisoning, claim obfuscation, and evidence contradiction.

---

## 4. Expanded MIRAGE 3.0 Benchmark Categories

With the expansion into a full AI Execution Assurance Platform, new benchmarks are required to evaluate the Five Assurance Gates and the Control Plane.

### 4.1 Gate Effectiveness Benchmarks (Per Gate)
* **Focus:** Individual gate performance in isolating and blocking specific failure modes.
* **Metrics:** True Positive Rate (blocking bad actions), False Positive Rate (blocking benign actions), processing latency per gate.
* **Acceptance Criteria:** FPR < 1% for Gate 1; TPR > 99% for known injection attacks.
* **Measurement Methodology:** Shadow traffic replay and synthetic failure injection.
* **Required Infrastructure:** Dedicated benchmark clusters with deterministic network emulation.
* **Reporting Format:** ROC curves and latency distribution histograms per gate.

### 4.2 Policy Engine Correctness Benchmarks
* **Focus:** Accuracy and conflict resolution of the declarative policy engine.
* **Metrics:** Policy evaluation accuracy (match against expected decisions), resolution time for deeply nested policy hierarchies.
* **Acceptance Criteria:** 100% correctness on the foundational policy test suite; P99 evaluation latency < 5ms.
* **Measurement Methodology:** Property-based testing generating complex overlapping policy sets and evaluating deterministic outcomes.

### 4.3 Risk Engine Calibration Benchmarks
* **Focus:** Accuracy of the multi-dimensional risk scoring.
* **Metrics:** Brier score for risk probability estimation; rank correlation between computed risk and actual blast radius.
* **Acceptance Criteria:** Brier score < 0.1 for known vulnerability vectors.
* **Measurement Methodology:** Evaluating risk scores against a curated dataset of historical AI incidents and near-misses.

### 4.4 Action Authorization Accuracy
* **Focus:** The capability model and ABAC enforcement.
* **Metrics:** Capability over-granting detection rate; unauthorized access block rate.
* **Acceptance Criteria:** Zero unauthorized tool invocations permitted under any context.
* **Measurement Methodology:** Adversarial agent simulations attempting privilege escalation within the Tool Proxy.

### 4.5 Reality Verification Accuracy
* **Focus:** Gate 5's ability to detect actual outcomes vs. model claims.
* **Metrics:** Discrepancy detection rate (detecting when an action failed but the model claimed success).
* **Acceptance Criteria:** > 99.5% accuracy in state comparison tasks.
* **Measurement Methodology:** Interacting with mock databases and APIs that deliberately fail or silently drop requests after the model initiates them.

### 4.6 Cost Optimization Benchmarks
* **Focus:** Budget management and adaptive verification escalation.
* **Metrics:** Reduction in verification cost per transaction compared to naive maximum-verification; budget enforcement strictness.
* **Acceptance Criteria:** Budget overruns blocked 100% of the time; cost reduced by 40% for low-risk transactions.
* **Measurement Methodology:** Replaying varied risk traffic and analyzing the verification escalation paths.

### 4.7 Model Routing Quality Benchmarks
* **Focus:** Intelligent selection of models based on intent, risk, and cost.
* **Metrics:** Task success rate vs. cost efficiency; fallback latency during simulated provider outages.
* **Acceptance Criteria:** 95% optimal routing decisions based on Pareto frontiers of cost/accuracy.
* **Measurement Methodology:** Simulating dynamic loads and varying API health statuses.

### 4.8 Memory Governance Benchmarks
* **Focus:** Provenance tracking and poisoning resistance in persistent memory.
* **Metrics:** Time-to-detect memory poisoning; access control enforcement latency.
* **Acceptance Criteria:** 100% block rate for cross-tenant memory access; sub-10ms memory retrieval overhead.
* **Measurement Methodology:** Vector database injection attacks and simulated multi-agent memory sharing.

### 4.9 Tool Poisoning Resistance
* **Focus:** Resilience against malicious MCP servers and tool outputs.
* **Metrics:** Interception rate of payload injections disguised as tool outputs.
* **Acceptance Criteria:** All malicious tool outputs neutralized before context assembly (Gate 2).
* **Measurement Methodology:** Using the Adversarial Robustness Suite (ATK-02) adapted for tool output streams.

### 4.10 Multi-Tenant Isolation Verification
* **Focus:** Absolute data and execution isolation across tenants.
* **Metrics:** Cross-tenant data leakage rate.
* **Acceptance Criteria:** STRICTLY 0.0%. Any failure here is a critical blocker.
* **Measurement Methodology:** Automated red-teaming scripts attempting to query PostgreSQL RLS barriers and Qdrant tenant collections using leaked or forged identities.

---

## 5. Provenance and Integrity Requirements

For every dataset used in these benchmarks, strict provenance must be maintained:
1. **Origin:** The source of the data must be explicitly documented and legally cleared for use.
2. **Immutability:** Datasets must be stored in read-only object storage, addressable by their SHA-256 hash.
3. **Contamination:** Before evaluating any foundation model, the dataset must be run through a contamination check to ensure the model did not train on the test set.
4. **Reporting:** Every benchmark report must include the `BenchmarkCertificationGuard` cryptographic signature, allowing independent verification of the results.

*Fabricating benchmark results, obfuscating test conditions, or using fixture data to simulate performance is explicitly prohibited by MIRAGE engineering policy and will result in rejected commits.*
