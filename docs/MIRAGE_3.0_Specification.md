# MIRAGE 3.0 — Canonical Specification

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document is the highest-level conceptual source of truth for MIRAGE 3.0.
> All other specification documents derive their authority from this document.
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md).

---

## 1. Mission

MIRAGE exists to make AI systems trustworthy enough for consequential real-world use.

MIRAGE provides the control, verification, and assurance infrastructure that allows organizations to deploy AI agents, copilots, and automated workflows with confidence — knowing that every input is validated, every action is authorized, every output is verified, and every outcome is confirmed.

---

## 2. Product Statement

> **MIRAGE sits between AI systems and the real world, inspecting inputs, context, actions, outputs, and outcomes to enforce identity, security, policy, reliability, and cost controls — using adaptive verification and intelligent model routing to achieve the required level of assurance at the lowest practical cost.**

---

## 3. Product Promise

> **Control AI before it acts. Verify AI after it acts.**

---

## 4. Problem

Industrial AI systems face a compounding set of challenges that no single existing tool category addresses:

### 4.1 LLM Applications
- LLMs generate plausible but incorrect outputs (hallucination rates of 3–27% in enterprise deployments).
- Outputs may contain sensitive data, bias, toxicity, or policy violations.
- Confidence in model outputs cannot be derived from the outputs themselves.

### 4.2 RAG Systems
- Retrieved context may be stale, poisoned, irrelevant, or conflicting.
- Evidence provenance is rarely tracked end-to-end.
- Instruction-data boundary violations allow retrieved content to hijack model behavior.

### 4.3 Autonomous Agents
- Agents compose multi-step plans with compounding error probability.
- Agent actions may be irreversible, expensive, or dangerous.
- "The model said it worked" is not the same as "it actually worked."
- Agent loops, runaway tool calls, and excessive autonomy create unbounded risk.

### 4.4 Tool Use and MCP
- Tools receive parameters from untrusted AI model outputs.
- Tool outputs are treated as trusted data by default — but they should not be.
- MCP servers may be compromised, poorly implemented, or malicious.
- No standard mechanism exists to authorize, audit, or govern tool invocations.

### 4.5 Enterprise Workflows
- Multiple AI systems interact with shared resources under different policies.
- Regulatory, compliance, and governance requirements demand auditability.
- Cost attribution across AI workloads is typically absent or inaccurate.

### 4.6 Multi-Agent Systems
- Agent-to-agent communication creates trust propagation risks.
- One compromised agent can influence the behavior of others.
- Transaction boundaries, identity, and accountability become ambiguous.

### 4.7 Model Routing
- Using a single model for all tasks wastes resources or accepts unnecessary risk.
- No standardized way to match task requirements to model capabilities.
- Model failures, rate limits, and degradation require graceful fallback.

### 4.8 Memory
- AI systems accumulate information across sessions without governance.
- Memory can be poisoned, become stale, or contain contradictory information.
- No standard mechanism exists for memory provenance, expiration, or access control.

### 4.9 Sensitive Data
- AI systems process, generate, and store sensitive information without classification or controls.
- Data exfiltration through model outputs, tool calls, or memory is a systemic risk.
- PII, secrets, credentials, and proprietary information require active detection and governance.

### 4.10 External Actions
- AI systems perform actions in real systems (databases, APIs, infrastructure, payments) without verification that the action succeeded, failed, or produced unintended side effects.
- "The model said it sent the email" is fundamentally different from "the email was actually sent."

### 4.11 Cost
- AI systems consume expensive resources (model inference, tool calls, API calls) without budgeting, attribution, or optimization.
- Adding verification and assurance layers increases cost unless deliberately optimized.
- Organizations cannot answer: "What did this AI transaction cost?"

### 4.12 Reliability
- AI system failures are often silent — wrong answers delivered with high confidence.
- Cascading failures across dependent AI systems are difficult to detect and contain.
- Recovery from AI-initiated errors in real systems requires compensation, rollback, or human intervention.

### 4.13 Security
- AI systems are vulnerable to prompt injection, data poisoning, identity spoofing, privilege escalation, and supply-chain attacks targeting models, tools, and context.
- Traditional security models do not account for AI-specific threat vectors.

### 4.14 Compliance
- Regulated industries require explainable, auditable, and reproducible AI decision-making.
- Current AI systems cannot reliably answer: "Why was this decision made?" or "What information led to this output?"

---

## 5. Product Category

MIRAGE is an **AI Execution Assurance Platform** — also described as an **AI Control & Assurance Fabric**.

### 5.1 What MIRAGE Is

MIRAGE is the control, verification, and governance layer between AI systems and the real world. It provides:

1. **Pre-execution control:** Identity, authorization, policy enforcement, risk assessment, and action approval before AI systems act.
2. **Execution governance:** Model routing, capability enforcement, budget management, and tool invocation control during AI system operation.
3. **Post-execution verification:** Output verification, outcome confirmation, reality checks, and assurance scoring after AI systems produce results.
4. **Continuous accountability:** Transaction tracing, provenance tracking, audit logging, cost attribution, and compliance reporting across the full AI lifecycle.

### 5.2 What MIRAGE Is Not

| Category | How MIRAGE Differs |
|---|---|
| **AI Gateway / Proxy** | Gateways route traffic and apply rate limits. MIRAGE understands intent, assesses risk, enforces policy, verifies outputs, and confirms outcomes. |
| **Model Router** | Routers select models based on cost and latency. MIRAGE routes based on risk, policy, data sensitivity, required assurance level, and capability requirements — and then verifies results. |
| **Guardrails Library** | Guardrails apply input/output filters. MIRAGE provides five assurance gates spanning the full lifecycle from input through outcome, with adaptive verification proportional to risk. |
| **AI Security Platform** | Security platforms detect threats. MIRAGE combines threat detection with identity, authorization, capability enforcement, policy evaluation, and action governance. |
| **Observability Platform** | Observability platforms collect metrics and traces. MIRAGE traces the full AI decision chain with provenance, risk scores, policy decisions, and causal attribution — enabling "why" questions, not just "what" questions. |
| **Agent Framework** | Agent frameworks build agents. MIRAGE governs agents regardless of which framework built them. |
| **Hallucination Detector** | Hallucination detectors check output accuracy. MIRAGE includes output verification as one component (Gate 4) within a comprehensive five-gate assurance system. |
| **RAG Platform** | RAG platforms retrieve and generate. MIRAGE verifies that retrieval is trustworthy (Gate 2) and that generation is accurate (Gate 4), while also governing the actions taken based on that generation (Gate 3). |

---

## 6. Core Principles

These principles are non-negotiable architectural constraints. Every MIRAGE component must satisfy them.

1. **Input is untrusted.** All inputs — user prompts, API requests, system messages — may contain injection attacks, malicious instructions, sensitive data, or policy violations. Inputs must be validated before processing.

2. **Context is untrusted.** Retrieved documents, memory, tool results, conversation history, and environmental data may be stale, poisoned, conflicting, or manipulated. Context must be evaluated for provenance, integrity, and relevance.

3. **Tool output is untrusted.** Results from tools, MCP servers, APIs, and external systems may be incorrect, manipulated, or compromised. Tool outputs must never be automatically interpreted as instructions.

4. **Model output is untrusted.** LLM outputs — including reasoning, claims, plans, and proposed actions — may be hallucinated, biased, unsafe, or policy-violating. Model outputs require verification proportional to the risk of acting on them.

5. **Actions require authorization.** No action that changes real-world state may proceed without explicit capability authorization and policy evaluation. An agent must not receive unrestricted tool access simply because a tool exists.

6. **Memory requires provenance.** Every item stored in memory must have tracked origin, owner, timestamp, sensitivity classification, integrity verification, and expiration. Memory without provenance is untrusted.

7. **High-risk actions require stronger assurance.** The level of verification, oversight, and approval must increase with the risk, irreversibility, and blast radius of the action. Low-risk actions may proceed with lightweight checks; high-risk actions require comprehensive verification and explicit approval.

8. **Verification should be adaptive.** MIRAGE must not apply the same verification overhead to every transaction. Cheap deterministic checks should run first; expensive verification should escalate only when justified by risk, complexity, or policy requirements.

9. **Expensive verification must justify its cost.** Every verification step that adds latency or cost must have a measurable contribution to assurance. Verification that does not improve confidence should be eliminated.

10. **Outcome verification is distinct from output verification.** Verifying that a model's output is factually consistent (output verification) is fundamentally different from confirming that a real-world action actually succeeded (outcome verification). Both are necessary.

11. **Identity must be explicit.** Every entity in a MIRAGE transaction — user, agent, model, tool, service — must have a verifiable identity. Anonymous or unattributable actions are prohibited for consequential operations.

12. **Least privilege is mandatory.** Every agent, tool, user, and service operates with the minimum capabilities required for its current task. Capabilities are scoped, time-bounded, and revocable.

13. **Tenant isolation is mandatory.** Data, policies, memory, evidence, audit logs, model configurations, and agent behaviors must not leak across tenant boundaries. Isolation must be enforced at both the application level and the storage level.

14. **Fail-safe behavior must be explicit.** Every component must define whether it fails open (permits the action with degraded assurance) or fails closed (blocks the action until the component recovers). Critical security decisions must fail closed.

15. **Every consequential AI action must be attributable.** It must be possible to reconstruct, for any transaction: who initiated it, which agent processed it, which model generated the output, which tools were called, which policies applied, what risk was assessed, what evidence was used, and what outcome occurred.

16. **Taint tracking and information flow control are mandatory.** When a transaction processes both untrusted external content and confidential internal data, external network capabilities must be dynamically restricted to prevent covert data exfiltration. Heuristic output filtering alone is insufficient.

17. **Reality verification must respect epistemic bounds.** Outcome assurance must report the observable limits of the target system (`OBS_DIRECT`, `OBS_EVENTUAL`, `OBS_INFERRED`, `OBS_BLIND`). The system must never assert that an unobservable, write-only, or pending asynchronous action is verified.

---

## 7. Canonical Lifecycle (Governed Turn-Loop Model)

Every AI Transaction processed by MIRAGE follows an overarching transaction envelope containing an iterative, governed **Turn Loop** for agentic reasoning and action execution.

```
TRANSACTION INITIALIZATION
INPUT           Receive and parse the request
    ↓
IDENTITY        Authenticate actor; resolve tenant, user, agent identity
    ↓
INTENT          Classify purpose and scope of request
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ GATE 1: INPUT ASSURANCE                                         │
│ Validate identity, scan injection, check tenant policy,         │
│ evaluate initial risk, assign baseline taint tags               │
│ Decisions: ALLOW / TRANSFORM / SANITIZE / ROUTE / BLOCK         │
└─────────────────────────────────────────────────────────────────┘
    ↓
ROUTING & INIT  Select primary reasoning model; initialize budget envelope
    ↓
CONTEXT ASSEMBLY Retrieve initial evidence (RAG) & memory
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ GATE 2: CONTEXT ASSURANCE                                       │
│ Verify provenance & trust; enforce Instruction/Data separation; │
│ apply Taint Tracking (TAINT_UNTRUSTED, TAINT_CONFIDENTIAL)      │
└─────────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────────┐
│ 🔄 THE GOVERNED TURN LOOP (Bounded by max_turns & turn_budget)  │
│                                                                 │
│   PLAN / REASON: Agent generates reasoning and intended tool intent│
│       ↓                                                         │
│   GATE 3: ACTION ASSURANCE                                      │
│   Authorize capabilities; validate parameters; evaluate         │
│   instantaneous & sliding-window aggregate blast radius;        │
│   enforce IFC taint rules; require human approval (L4) if risk  │
│   exceeds autonomy.                                             │
│       ↓                                                         │
│   TOOL PROXY: Securely invoke external API / MCP server         │
│       ↓                                                         │
│   GATE 4: OUTCOME ASSURANCE (Reality Verification)              │
│   Evaluate postconditions against epistemic observability class │
│   (OBS_DIRECT, OBS_EVENTUAL, OBS_INFERRED, OBS_BLIND);          │
│   emit (OutcomeStatus, EpistemicConfidence); trigger compensation│
│   if partial failure.                                           │
│       ↓                                                         │
│   DYNAMIC CONTEXT UPDATE: Sanitize tool output; update taint;    │
│   feed verified outcome into next turn (or break if finished).  │
└─────────────────────────────────────────────────────────────────┘
    ↓ (Loop Terminates: Agent emits final output response)
┌─────────────────────────────────────────────────────────────────┐
│ GATE 5: OUTPUT ASSURANCE                                        │
│ Verify factual consistency (Verification Engine: RAV, NLI, SCS, │
│ ICS, VGS, HRS); scan secrets; enforce schema; apply speculative │
│ assurance buffering if streaming.                               │
└─────────────────────────────────────────────────────────────────┘
    ↓
ASSURANCE FINALIZATION & AUDIT
Compute composite assurance score; commit cryptographic hash to Audit Ledger
    ↓
DELIVERY
Deliver assured, verifiable response to user or caller
```

### Lifecycle Notes

1. **Governed Turn-Loop model:** Modern agents do not follow a single linear pass. Intermediate tool executions cycle through Action Assurance and Outcome Assurance, updating dynamic context and taint states before the next reasoning turn.
2. **Epistemic outcome verification:** Outcome Assurance explicitly records whether the state was directly measured, eventually confirmed, or acknowledged by transport, avoiding false certainty.
3. **Speculative streaming assurance:** In interactive streaming sessions, tokens are streamed with speculative assurance, while heavy statistical verification runs asynchronously out-of-band with retractability protocols.
4. **Information Flow Control (IFC):** If Gate 2 or dynamic turn updates tag the transaction context as concurrently containing `TAINT_UNTRUSTED` and `TAINT_CONFIDENTIAL`, Action Assurance dynamically revokes external network communication capabilities.

---

## 8. Core Primitives — Canonical Semantics

The following primitives are the conceptual building blocks of MIRAGE 3.0. Their canonical definitions are maintained in [GLOSSARY.md](GLOSSARY.md). This section defines how they relate to each other.

### Primitive Relationships

```
TENANT
  └── contains → USER(s), AGENT(s), POLICY(ies), MEMORY, RESOURCE(s)

USER / AGENT
  └── has → IDENTITY
  └── holds → CAPABILITY(ies)
  └── initiates → TRANSACTION(s)

TRANSACTION
  └── has → INTENT, CONTEXT, PLAN
  └── uses → MODEL (via ROUTING)
  └── evaluates → RISK, POLICY
  └── requires → APPROVAL (when risk exceeds autonomy)
  └── contains → ACTION(s)
  └── consumes → BUDGET
  └── produces → OUTPUT, OUTCOME
  └── records → PROVENANCE, AUDIT

ACTION
  └── invokes → TOOL / MCP / API
  └── targets → RESOURCE
  └── requires → CAPABILITY, AUTHORIZATION
  └── assessed by → RISK ENGINE
  └── governed by → POLICY ENGINE

CONTEXT
  └── includes → EVIDENCE, MEMORY, TOOL RESULTS
  └── evaluated by → CONTEXT ASSURANCE (Gate 2)

OUTPUT
  └── verified by → VERIFICATION ENGINE (Gate 4)
  └── may contain → sensitive data, policy violations, hallucinations

OUTCOME
  └── verified by → REALITY VERIFICATION (Gate 5)
  └── may reveal → partial failure, discrepancy, side effects
```

### Primitive Invariants

1. Every Transaction belongs to exactly one Tenant.
2. Every Transaction has exactly one initiating Identity.
3. Every Action within a Transaction requires at least one Capability.
4. Every Policy evaluation produces a deterministic result for the same inputs.
5. Every Evidence item has Provenance.
6. Every Memory item has an owner, tenant, and expiration.
7. Every Budget has a measurable remaining balance at any point.
8. Every Outcome is independently verifiable from the corresponding Output.

---

## 9. Architectural Overview

MIRAGE 3.0 is organized into two primary planes:

### 9.1 Control Plane

Responsible for configuration, policy, identity, and administration.

| Component | Responsibility |
|---|---|
| **Identity Service** | User, agent, tool, and service identity management; authentication; credential lifecycle |
| **Policy Service** | Policy definition, versioning, hierarchy, and conflict resolution |
| **Model Registry** | Model capability profiles, health status, cost, routing rules |
| **Capability Manager** | Capability definitions, grants, revocation, and scope enforcement |
| **Tenant Manager** | Tenant configuration, isolation enforcement, resource limits |
| **Budget Manager** | Budget definitions, tracking, enforcement, and cost attribution |
| **Admin API** | Configuration, monitoring, and operational management |

### 9.2 Execution Plane

Responsible for real-time AI transaction processing.

| Component | Responsibility |
|---|---|
| **Gateway** | Request ingestion, identity resolution, rate limiting, initial validation |
| **Intent Classifier** | Purpose and scope classification for incoming requests |
| **Risk Engine** | Multi-dimensional risk scoring for intents, actions, and transactions |
| **Policy Engine** | Runtime policy evaluation against transaction context |
| **Model Router** | Dynamic model selection based on requirements, risk, cost, and policy |
| **Context Assembler** | Evidence retrieval, memory loading, tool state gathering |
| **Action Governor** | Capability enforcement, parameter validation, approval workflow |
| **Tool Proxy** | Secure, governed invocation of tools, MCP servers, and external APIs |
| **Verification Engine** | Output factual consistency, reliability, and safety verification (MIRAGE 2.x core) |
| **Reality Verifier** | Outcome confirmation, postcondition checking, discrepancy detection |
| **Assurance Scorer** | Overall transaction assurance computation and disposition |
| **Transaction Manager** | Transaction lifecycle, state management, correlation, and audit recording |

### 9.3 Data Plane

| Store | Purpose | Rationale |
|---|---|---|
| **PostgreSQL** | Control plane data: tenants, users, agents, policies, capabilities, sessions, audit ledger | ACID transactions, RLS for tenant isolation, relational integrity |
| **MongoDB** | Execution traces: full transaction records, tool invocations, verification details | Flexible schema for evolving trace structures, append-heavy workload |
| **Redis** | Runtime state: rate limiting, caching, session state, circuit breaker state | Low-latency reads/writes, TTL-based expiration |
| **Qdrant** | Evidence embeddings: knowledge base vectors for retrieval-augmented verification | Purpose-built vector similarity search, HNSW indexing |
| **Event Stream** | Transaction events: policy decisions, risk assessments, action outcomes | Ordered, durable event log for audit, replay, and downstream consumption |

### 9.4 Observability Plane

| Component | Purpose |
|---|---|
| **OpenTelemetry** | Distributed tracing across all transaction stages |
| **Prometheus** | Metrics collection for latency, throughput, error rates, cost |
| **Structured Logging** | JSON-formatted event logs with correlation IDs |
| **Audit Service** | Cryptographically chained, tamper-evident audit records |
| **Provenance Tracker** | End-to-end information lineage tracking |

---

## 10. MIRAGE 2.x Migration Boundary

MIRAGE 3.0 preserves the proven engineering assets of MIRAGE 2.x while repositioning them within a broader architecture.

### 10.1 Preserved

| MIRAGE 2.x Component | MIRAGE 3.0 Position | Rationale |
|---|---|---|
| RAV (Retrieval-Augmented Verification) | Verification Engine → Output Assurance (Gate 4) | Proven claim-evidence verification with dense retrieval |
| SCS (Self-Consistency Sampling) | Verification Engine → Output Assurance (Gate 4) | Semantic entropy provides valuable consistency signals |
| NLI (Natural Language Inference) | Verification Engine → Output Assurance (Gate 4) | DeBERTa entailment scoring is production-proven |
| ICS (Internal Consistency Scoring) | Verification Engine → Output Assurance (Gate 4) | Intra-response contradiction detection remains valuable |
| VGS (Visual Grounding Service) | Verification Engine → Output Assurance (Gate 4) | Multimodal verification is a differentiator |
| HRS (Holistic Reliability Scoring) | Verification Engine → Output Assurance (Gate 4) | LightGBM meta-learner with calibration and conformal prediction is strong |
| Conformal Prediction (Mondrian CP) | Verification Engine → Output Assurance (Gate 4) | Statistically rigorous uncertainty quantification |
| Calibration (Isotonic Regression) | Verification Engine → Output Assurance (Gate 4) | Well-calibrated probabilities are essential |
| TreeSHAP Explainability | Verification Engine → Output Assurance (Gate 4) | Attribution transparency is a competitive advantage |
| PostgreSQL with RLS | Data Plane → Control + Execution | Proven multi-tenant isolation with ACID guarantees |
| MongoDB Trace Storage | Data Plane → Execution Traces | Flexible trace schema with TTL management |
| Redis Caching/Rate Limiting | Data Plane → Runtime State | Battle-tested for low-latency state management |
| Qdrant Vector Storage | Data Plane → Evidence Embeddings | Purpose-built for dense retrieval |
| SHA-256 Audit Chain | Observability → Audit Service | Cryptographic tamper evidence is enterprise-grade |
| Circuit Breaker Pattern (pybreaker) | Execution Plane → Resilience | Proven graceful degradation |
| LangGraph Correction Agent | Execution Plane → Output Remediation (optional) | Valuable auto-correction capability |

### 10.2 Refactored

| MIRAGE 2.x Component | Change | Rationale |
|---|---|---|
| Gateway (FastAPI) | Extend with Identity, Intent, and Gate 1 | Gateway must become the entry point for full lifecycle, not just verification |
| RBAC (4 roles) | Extend to ABAC + Capability model | Role-based access is insufficient for agent governance |
| Rate Limiting (Token Bucket) | Extend with per-tenant, per-agent, cost-aware budgets | Rate limiting alone does not govern AI resource consumption |
| Celery/RabbitMQ Workers | Evaluate: retain for batch/async, add synchronous path for real-time gates | Real-time gate evaluation cannot tolerate queue latency for inline checks |
| FLAN-T5 Claim Decomposition | Retain within Verification Engine; consider model-agnostic decomposition | The decomposer is tightly coupled to a specific model |

### 10.3 New in MIRAGE 3.0

| Component | Description |
|---|---|
| Five Assurance Gates | Comprehensive lifecycle governance beyond output verification |
| AI Transaction Model | End-to-end traceable unit of work with full lifecycle |
| Policy Engine | Declarative policy evaluation with hierarchy and precedence |
| Risk Engine | Multi-dimensional risk scoring with autonomy levels |
| Action Governor | Capability-based action authorization and approval workflow |
| Reality Verifier | Outcome confirmation against actual system state |
| Model Router | Intelligent model selection based on risk, cost, and policy |
| Memory Governance | Provenance-tracked, access-controlled, poisoning-resistant memory |
| Identity Model | Comprehensive identity for users, agents, tools, and services |
| Cost Optimization | Budget management with adaptive verification escalation |
| Intent Classifier | Request purpose classification for risk and routing |
| Tool Proxy | Governed, audited tool invocation with output validation |

### 10.4 Deprecated

| MIRAGE 2.x Component | Disposition | Rationale |
|---|---|---|
| Streamlit Dashboard | Replace with React 18/JSX dashboard | Streamlit is insufficient for production interactive dashboards |
| In-memory SlidingWindowRateLimiter | Already replaced in 2.x | Non-distributed rate limiting was eliminated |
| `mongo_use_per_tenant_collections` toggle | Already eliminated in ADR 0001 | Per-tenant collections are unconditionally enforced |

---

## 11. Documentation Hierarchy

This specification is supported by the following documents, each elaborating a specific aspect of MIRAGE 3.0:

| Document | Scope |
|---|---|
| [PRD.md](PRD.md) | Product requirements, use cases, user journeys, success metrics |
| [Technical_Architecture.md](Technical_Architecture.md) | Detailed system architecture, component design, data flows |
| [Security.md](Security.md) | Threat model, identity, authorization, encryption, incident response |
| [Memory.md](Memory.md) | Memory governance, provenance, access control, poisoning protection |
| [AI_Transaction.md](AI_Transaction.md) | Transaction model, lifecycle, idempotency, streaming, multi-agent |
| [AI_Action_Contract.md](AI_Action_Contract.md) | Action contracts, preconditions, postconditions, rollback |
| [Policy_Engine.md](Policy_Engine.md) | Policy model, language, hierarchy, evaluation semantics |
| [Risk_Model.md](Risk_Model.md) | Risk framework, dimensions, autonomy levels, budgets |
| [Cost_Optimization.md](Cost_Optimization.md) | Verification budgets, escalation, cost attribution |
| [Model_Routing.md](Model_Routing.md) | Routing strategy, model profiles, fallback, health |
| [MCP_Tools_Agents.md](MCP_Tools_Agents.md) | Agent governance, tool management, MCP integration |
| [Input_Output_Assurance.md](Input_Output_Assurance.md) | Five Assurance Gates specification |
| [Reality_Verification.md](Reality_Verification.md) | Outcome verification, state comparison, remediation |
| [Data_Model.md](Data_Model.md) | Canonical entities, relationships, storage decisions |
| [API_Specification.md](API_Specification.md) | External API design, authentication, endpoints |
| [SDK_and_Integration.md](SDK_and_Integration.md) | Developer integration patterns, SDKs, frameworks |
| [Observability_and_Audit.md](Observability_and_Audit.md) | Tracing, metrics, audit, provenance |
| [Testing_Strategy.md](Testing_Strategy.md) | Testing pyramid, acceptance criteria, adversarial testing |
| [Benchmarking_Evaluation.md](Benchmarking_Evaluation.md) | Evaluation methodology, datasets, statistical protocols |
| [Deployment_and_Operations.md](Deployment_and_Operations.md) | Deployment models, scaling, HA, DR |
| [Development_Workflow.md](Development_Workflow.md) | Development standards, CI/CD, agent instructions |
| [Compatibility_and_Migration.md](Compatibility_and_Migration.md) | MIRAGE 2.x component migration map |
| [GLOSSARY.md](GLOSSARY.md) | Canonical term definitions |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [ADRs/README.md](ADRs/README.md) | Architecture Decision Record framework |

---

## 12. Documentation Status

### 12.1 Documents Created
All documents listed in Section 11 are created as part of this specification release.

### 12.2 Major Architectural Decisions
1. MIRAGE is repositioned from a hallucination detection platform to an AI Execution Assurance Platform.
2. The MIRAGE 2.x verification stack becomes the Verification Engine subsystem within Output Assurance (Gate 4).
3. Five Assurance Gates provide comprehensive lifecycle governance.
4. AI Transactions are the canonical unit of traceable work.
5. Capability-based security replaces simple RBAC for agent governance.
6. Adaptive verification escalation optimizes cost while maintaining assurance.
7. Reality Verification (Gate 5) is introduced as a first-class concept distinct from output verification.
8. Memory is governed with provenance, access control, and poisoning protection.

### 12.3 Unresolved Decisions
These require human/product decisions before implementation:

1. **Policy Language:** Whether to adopt an existing policy language (OPA/Rego, Cedar) or design a MIRAGE-specific DSL. See [Policy_Engine.md](Policy_Engine.md).
2. **Event Stream Technology:** Whether to use Kafka, NATS, Redis Streams, or RabbitMQ Streams for the transaction event log.
3. **A2A Protocol Support:** Whether to support Google's Agent-to-Agent protocol, adopt an alternative, or define MIRAGE-specific agent communication.
4. **Model Provider Strategy:** Which model providers to support initially and how to abstract provider-specific APIs.
5. **Commercial Licensing Model:** Open-source core with commercial extensions, or fully open-source.
6. **Deployment Target Priority:** Whether to optimize first for Docker Compose (developer), Kubernetes (cloud), or managed service.
7. **Frontend Scope:** Whether the React/JSX dashboard should be a full management console or remain an operational dashboard.

### 12.4 Deprecated MIRAGE 2.x Concepts
- Product identity as "hallucination detection platform" — superseded by AI Execution Assurance Platform
- Streamlit dashboard — superseded by React 18/JSX frontend
- RBAC-only authorization — extended to ABAC + capability model
- Verification-only transaction model — replaced by full AI Transaction lifecycle
- MCP as exposure-only (MIRAGE as MCP tool) — extended to MCP governance (MIRAGE governing MCP tools)

### 12.5 Preserved MIRAGE 2.x Capabilities
- Complete verification engine (RAV, SCS, NLI, ICS, VGS, HRS) with calibration, conformal prediction, and SHAP
- Multi-tenant PostgreSQL with RLS and cryptographic audit chain
- Per-tenant MongoDB trace collections
- Qdrant evidence embeddings
- Redis caching and rate limiting with atomic token bucket
- Quorum queue broker durability
- Circuit breaker resilience pattern
- LangGraph correction agent
- Container hardening and network segmentation

### 12.6 Next Implementation Phase
Implementation should proceed in this order:
1. **Phase 1:** Core Control Plane — Identity, Policy, Tenant, Capability services; extended Gateway with Gate 1
2. **Phase 2:** Transaction Model — AI Transaction lifecycle, state management, correlation
3. **Phase 3:** Risk + Action Governance — Risk Engine, Action Governor, Gate 3, approval workflow
4. **Phase 4:** Context + Output Assurance — Context Assembler with Gate 2; Verification Engine integration with Gate 4
5. **Phase 5:** Model Routing + Cost — Model Router, Budget Manager, cost attribution
6. **Phase 6:** Outcome Assurance — Reality Verifier, Gate 5, postcondition checking
7. **Phase 7:** Memory Governance — Governed memory system with provenance and access control
8. **Phase 8:** Tool Governance — Tool Proxy, MCP governance, tool identity
9. **Phase 9:** Observability + Audit — Enhanced tracing, provenance tracking, audit reporting
10. **Phase 10:** Dashboard + SDK — React 18/JSX management console, Python SDK, documentation

---

*This document is the canonical source of truth for MIRAGE 3.0. All other specification documents derive their authority from this document and the [GLOSSARY.md](GLOSSARY.md). In the event of conflict between documents, this specification governs.*
