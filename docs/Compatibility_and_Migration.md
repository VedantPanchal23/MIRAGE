# MIRAGE 3.0 — Compatibility and Migration Map

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05

This document maps MIRAGE 2.x components to the MIRAGE 3.0 architecture and provides the comprehensive migration strategy, rationale, and timelines. As MIRAGE transitions from a hallucination detection platform to an AI Execution Assurance Platform, our engineering assets must be strategically repositioned, preserved, refactored, or deprecated.

---

## 1. Core Verification Components (MIRAGE 2.x Heritage)

### RAV (Retrieval-Augmented Verification)
* **Current 2.x Role:** Primary mechanism for claim-evidence verification using dense retrieval against a knowledge base.
* **Classification:** REPOSITION
* **Migration Path:** RAV will be integrated into the Verification Engine subsystem, specifically operating under Gate 4 (Output Assurance). The core dense retrieval logic remains unchanged.
* **Rationale:** Claim-evidence verification is critical for ensuring factual consistency in model outputs. It transitions from a standalone feature to an automated check within the broader assurance lifecycle.

### SCS (Semantic Consistency Scoring)
* **Current 2.x Role:** Evaluates semantic entropy across multiple LLM generation samples to detect instability.
* **Classification:** REPOSITION
* **Migration Path:** Moves to the Verification Engine within Gate 4. We will optimize the sampling strategy to respect dynamic verification budgets.
* **Rationale:** Entropy is a strong signal for hallucination, but multi-sample generation is expensive. It will only be triggered for high-risk intents.

### NLI (Natural Language Inference)
* **Current 2.x Role:** Cross-encoder entailment scoring of claim-evidence pairs.
* **Classification:** REPOSITION
* **Migration Path:** Subsumed into the Verification Engine (Gate 4) pipeline.
* **Rationale:** Provides the necessary logical entailment verification for RAV outputs.

### VGS (Visual Grounding Service)
* **Current 2.x Role:** Verification of vision-language model outputs against source images using CLIP and LLaVA.
* **Classification:** REPOSITION
* **Migration Path:** Integrated into Gate 4 as a specialized multimodal verifier.
* **Rationale:** Multimodal verification is increasingly important; maintaining this capability ensures MIRAGE can support vision-based agent actions.

### ICS (Internal Consistency Scoring)
* **Current 2.x Role:** Pairwise NLI-based detection of contradictions within a single LLM response.
* **Classification:** REPOSITION
* **Migration Path:** Becomes an optional, lower-latency check within the Verification Engine (Gate 4).
* **Rationale:** Intra-response contradiction is a cheap heuristic that can short-circuit more expensive verification steps.

### HRS (Holistic Reliability Scoring)
* **Current 2.x Role:** The calibrated composite risk score produced by the MIRAGE 2.x meta-learner.
* **Classification:** REPOSITION
* **Migration Path:** HRS becomes one specific metric used by the Assurance Scorer, contributing to the overall Output Assurance (Gate 4) assessment.
* **Rationale:** While HRS is a robust indicator of hallucination, MIRAGE 3.0 requires a broader assurance score that encompasses input, context, action, and outcome assurance.

---

## 2. Statistical & Machine Learning Primitives

### Calibration (Isotonic Regression)
* **Current 2.x Role:** Calibrates raw model probabilities to reflect true likelihoods.
* **Classification:** PRESERVE
* **Migration Path:** Preserved exactly as implemented, operating within the Verification Engine.
* **Rationale:** Well-calibrated probabilities are essential for the Risk Engine to make automated approval decisions.

### Conformal Prediction (Mondrian CP)
* **Current 2.x Role:** Statistically rigorous uncertainty quantification.
* **Classification:** PRESERVE
* **Migration Path:** Preserved within the Verification Engine to provide bounded confidence intervals.
* **Rationale:** Necessary for strict compliance and safety guarantees in high-risk autonomous actions.

### SHAP Explainability
* **Current 2.x Role:** Provides feature attribution and explainability for HRS scores.
* **Classification:** PRESERVE
* **Migration Path:** Preserved within the Observability Plane and Verification Engine.
* **Rationale:** Attribution transparency is a key competitive advantage and a regulatory requirement in many enterprise deployments.

### FLAN-T5 Claim Decomposer
* **Current 2.x Role:** Decomposes complex model outputs into atomic claims.
* **Classification:** REFACTOR
* **Migration Path:** Retained initially within the Verification Engine, but will be refactored to a model-agnostic or pluggable decomposition interface.
* **Rationale:** The decomposer is tightly coupled to a specific model. Abstracting it allows for more capable decomposition models as they emerge.

### DeBERTa-v3 NLI Verifier
* **Current 2.x Role:** Primary model for natural language inference.
* **Classification:** PRESERVE
* **Migration Path:** Preserved within the Verification Engine.
* **Rationale:** DeBERTa-v3 remains a highly efficient and accurate model for entailment tasks.

### LightGBM Meta-Learner
* **Current 2.x Role:** Combines signals to produce the final HRS.
* **Classification:** REFACTOR
* **Migration Path:** The model itself is preserved, but its outputs will feed into a new Assurance Combiner that aggregates signals across all five gates.
* **Rationale:** The meta-learner is tuned for hallucination; it must be re-trained or refactored to account for broader assurance signals.

---

## 3. Infrastructure and Data Plane

### PostgreSQL (with RLS, audit chain)
* **Current 2.x Role:** Multi-tenant database for relational configuration and audit ledgers.
* **Classification:** PRESERVE and EXTEND
* **Migration Path:** Will be heavily extended to store Control Plane data: Tenants, Users, Agents, Policies, Capabilities, and Budgets. Row-Level Security (RLS) remains mandatory.
* **Rationale:** PostgreSQL provides the necessary ACID guarantees and tenant isolation required for the Control Plane.

### MongoDB (per-tenant collections, traces)
* **Current 2.x Role:** Stores unstructured execution traces and verification details.
* **Classification:** PRESERVE
* **Migration Path:** Continues to store AI Transaction traces, with updated schemas to accommodate the Five Assurance Gates.
* **Rationale:** A flexible schema is vital for evolving trace structures and handling diverse tool output payloads.

### Redis (token bucket, ACLs, caching)
* **Current 2.x Role:** Low-latency caching, rate limiting, and session state.
* **Classification:** PRESERVE and EXTEND
* **Migration Path:** Extended to support per-tenant and per-agent cost-aware budgets, alongside existing rate limiting.
* **Rationale:** Battle-tested for low-latency state management; essential for inline gate evaluations.

### RabbitMQ/Celery (quorum queues, DLX, idempotency)
* **Current 2.x Role:** Asynchronous task queue for batch processing and heavy verification tasks.
* **Classification:** REFACTOR
* **Migration Path:** Retained for async background tasks (e.g., Gate 5 Reality Verification polling, log aggregation). However, Gate 1-4 inline checks must use a synchronous execution path to avoid queue latency.
* **Rationale:** Real-time AI assurance requires low-latency inline evaluation. Message queues introduce unacceptable overhead for synchronous user-facing requests.

### Qdrant (HNSW, evidence embeddings)
* **Current 2.x Role:** Vector database for evidence retrieval.
* **Classification:** PRESERVE and EXTEND
* **Migration Path:** Retained for evidence embeddings and extended to support the new Governed Memory system (provenance-tracked, access-controlled vector storage).
* **Rationale:** Qdrant is purpose-built for dense retrieval and supports the required filtering capabilities for memory governance.

---

## 4. Application and Execution Plane

### FastAPI Gateway
* **Current 2.x Role:** API entry point for verification requests.
* **Classification:** REFACTOR
* **Migration Path:** The Gateway will be heavily refactored. It must now handle the full AI Transaction lifecycle, identity resolution, Intent Classification, and inline Gate 1 (Input Assurance) evaluation before routing.
* **Rationale:** The Gateway must become the entry point for end-to-end lifecycle governance, not just post-hoc verification.

### RBAC (4 roles)
* **Current 2.x Role:** Simple role-based access control for dashboard and API access.
* **Classification:** REFACTOR
* **Migration Path:** Transitioning to a full Attribute-Based Access Control (ABAC) system coupled with an explicit Capability model.
* **Rationale:** Role-based access is grossly insufficient for granular agent governance, tool authorization, and complex policy enforcement.

### Audit Chain (SHA-256 hash chaining)
* **Current 2.x Role:** Cryptographically links verification records for tamper evidence.
* **Classification:** PRESERVE
* **Migration Path:** Preserved and expanded into the Observability Plane as the Audit Service, chaining full AI Transaction lifecycles.
* **Rationale:** Cryptographic tamper evidence is an enterprise-grade requirement for compliance and legal non-repudiation.

### MCP Server
* **Current 2.x Role:** Exposes MIRAGE as a tool to external agents.
* **Classification:** REPOSITION and EXTEND
* **Migration Path:** Shifts from merely exposing MIRAGE to actively governing other MCP tools within the Tool Proxy.
* **Rationale:** MIRAGE must govern tool invocations, not just be a tool. The Tool Proxy will validate MCP interactions securely.

### LangGraph Correction Loop
* **Current 2.x Role:** Automated agent loop for correcting hallucinated outputs.
* **Classification:** PRESERVE
* **Migration Path:** Preserved as an optional output remediation mechanism within Gate 4.
* **Rationale:** Auto-correction adds significant value but must be strictly controlled to prevent infinite loops and unbounded costs.

---

## 5. Resilience and Quality

### Circuit Breakers (pybreaker)
* **Current 2.x Role:** Prevents cascading failures when dependencies are unavailable.
* **Classification:** PRESERVE
* **Migration Path:** Retained across all external dependency boundaries (LLM APIs, external tools, databases).
* **Rationale:** Graceful degradation is a core design principle of the Execution Plane.

### Container Hardening
* **Current 2.x Role:** Security benchmarks and minimal base images.
* **Classification:** PRESERVE
* **Migration Path:** Retained and applied to all new services in the expanded topology.
* **Rationale:** Foundational security practice.

### Chaos Testing Framework
* **Current 2.x Role:** Induces faults to verify resilience.
* **Classification:** PRESERVE and EXTEND
* **Migration Path:** Extended to test complex fail-safe behaviors of the Policy Engine and Risk Engine under dependency loss.
* **Rationale:** Essential for ensuring high availability and correct failure modes (fail-closed for security policies).

---

## 6. Deprecated Components

### Dashboard (Streamlit)
* **Current 2.x Role:** Legacy operational dashboard.
* **Classification:** DEPRECATE and DELETE
* **Migration Path:** To be entirely replaced by the React 18/JSX frontend.
* **Rationale:** Streamlit is insufficient for the interactive complexity, state management, and scalability required by the MIRAGE 3.0 Control Plane UI.

### Dashboard (React 18/JSX)
* **Current 2.x Role:** The Phase 10 dashboard from 2.x.
* **Classification:** PRESERVE and EXPAND
* **Migration Path:** Becomes the primary frontend, expanding into a full management console for policies, identity, routing, and audit viewing.
* **Rationale:** React provides the necessary component ecosystem and performance for a production-grade enterprise console.

---

## 7. Migration Timeline (Aligned with 10-Phase Plan)

1. **Phase 1 (Core Control Plane):** Deploy new PostgreSQL schemas; refactor FastAPI Gateway; implement new Identity and Policy services.
2. **Phase 2 (Transaction Model):** Implement MongoDB trace schema updates; roll out the core AI Transaction state machine.
3. **Phase 3 (Risk + Action Governance):** Deploy the Risk Engine and Action Governor; replace simple RBAC with the Capability model.
4. **Phase 4 (Context + Output Assurance):** Reposition RAV, SCS, NLI, VGS, ICS, and HRS into the new Verification Engine under Gate 4.
5. **Phase 5 (Model Routing + Cost):** Extend Redis logic for Budget management; deploy the Model Router.
6. **Phase 6 (Outcome Assurance):** Implement the Reality Verifier and Gate 5 logic using the synchronous/asynchronous hybrid model.
7. **Phase 7 (Memory Governance):** Extend Qdrant schemas; deploy provenance-tracked memory APIs.
8. **Phase 8 (Tool Governance):** Deploy the Tool Proxy; reposition the MCP Server logic.
9. **Phase 9 (Observability + Audit):** Expand the SHA-256 Audit Chain to cover full transactions; deploy OpenTelemetry collectors.
10. **Phase 10 (Dashboard + SDK):** Delete the Streamlit dashboard; fully deploy the React 18/JSX management console.

---

## 8. Backward Compatibility Commitments

To ensure a smooth transition for existing customers, the following backward compatibility commitments are guaranteed during the migration period:

1. **API Compatibility:** The existing `/v1/verify` API endpoints will remain functional. Requests will be internally mapped to a simplified AI Transaction that bypasses Gates 1-3 and executes Gate 4 (Output Assurance).
2. **Data Formats:** Existing verification trace schemas in MongoDB will not be mutated. The new AI Transaction schema will be written alongside legacy traces.
3. **Policy Evaluation:** Existing rate limits and tenant constraints will be automatically migrated to equivalent declarative policies in the new Policy Engine.
4. **Audit Chains:** Cryptographic verification of historical audit chains generated in 2.x will remain supported via a dedicated verification utility.
