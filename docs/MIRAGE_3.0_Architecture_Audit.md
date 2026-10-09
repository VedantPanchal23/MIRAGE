# MIRAGE 3.0 — Pre-Implementation Red-Team Architecture Audit

> **Document:** `docs/MIRAGE_3.0_Architecture_Audit.md`  
> **Status:** Ratified Audit Report  
> **Date:** 2026-10-06  
> **Auditor:** DeepMind / Antigravity Autonomous Architecture Audit  
> **Scope:** Full MIRAGE 3.0 Specification Suite (`docs/`), Architectural Contracts, Security Threat Models, Data Architecture, and Economic Viability  

---

## 1. Executive Verdict

### **APPROVE WITH REQUIRED CHANGES**

The conceptual foundation of MIRAGE 3.0 is fundamentally sound, highly differentiated, and strategically vital: evolving from a point-solution hallucination detector into an **AI Execution Assurance Platform** that controls AI before it acts and verifies AI after it acts addresses the most pressing problem in enterprise autonomous AI.

However, the current specification suite suffers from **four critical architectural defects (P0)**, **five high-priority engineering friction points (P1)**, and several unresolved structural assumptions that would lead to failure, unbounded latency, or security bypasses if implemented without correction.

**Implementation of Phase 1 is BLOCKED until the required changes documented herein are incorporated into the canonical specification and governing documents.**

---

## 2. Summary of Strengths

What is genuinely robust, valuable, and preserved from MIRAGE 2.x and established in 3.0:

1. **Repositioning of the Verification Engine:** Moving RAV, SCS, NLI, ICS, VGS, and HRS from the "entire product" to the Gate 4 (Output Assurance) subsystem is an exemplary architectural evolution that preserves valuable statistical assets without constraining the platform.
2. **Mathematical Rigor in Uncertainty Quantification:** Retaining Mondrian Conformal Prediction and Isotonic Regression calibration provides mathematically verifiable guarantees that competitors (who rely on arbitrary LLM-as-a-judge scores) cannot match.
3. **Capability Security Model:** Rejecting ambient authority and moving beyond basic role-based access control (RBAC) to Attribute-Based Access Control (ABAC) with explicit, bounded, revocable Capability Tokens (`subject:action:resource`) provides a true zero-trust foundation.
4. **Dual SQL/NoSQL Persistence Boundary:** Cleanly separating relational authoritative control plane entities (PostgreSQL 16 with RLS) from append-heavy execution traces (MongoDB 7 with per-tenant namespaces) provides architectural sanity for high-write telemetry workloads.
5. **Cryptographic Audit Hash-Chaining:** Retaining the SHA-256 tamper-evident hash chain for audit logs satisfies enterprise non-repudiation and compliance mandates (SOC 2, ISO 27001, DPDP Act).
6. **Deterministic Policy Philosophy:** Mandating that policy evaluation is deterministic, non-probabilistic, and does not depend on recursive LLM calls prevents hallucinations within the governance fabric itself.

---

## 3. Critical Findings (P0 — Must Fix Before Any Code is Written)

### [P0-1] The Dangerous Triad Vulnerability: Lack of Deterministic Information Flow Control (IFC)
* **Location:** `docs/Security.md`, `docs/Input_Output_Assurance.md`, `docs/MCP_Tools_Agents.md`
* **The Vulnerability:** The threat model discusses Prompt Injection, Data Exfiltration, and Confused Deputy attacks, but fails to structurally mitigate the **Dangerous Triad**:
  $$\text{Private Data} + \text{Untrusted Content} + \text{External Communication}$$
  If an agent reads sensitive internal records (Private Data), ingests an external email or document with indirect prompt injection (Untrusted Content), and holds a valid capability to make network requests (External Communication), heuristic scanning in Gate 4 (PII regex / NLP detectors) is mathematically insufficient. An attacker can instruct the LLM to exfiltrate secrets via steganography, URL encoding, base64 fragments, or token timing channels.
* **Architectural Fix:** MIRAGE must implement **Dynamic Taint Tracking / Information Flow Control (IFC)** at the transaction level.
  - Context sources must be tagged with taint flags: `TAINT_UNTRUSTED` (external inputs, web scraping) and `TAINT_CONFIDENTIAL` (internal DBs, private memories, secrets).
  - **Invariant Control Rule:** If a transaction context is concurrently marked with `TAINT_UNTRUSTED` and `TAINT_CONFIDENTIAL`, all external communication capabilities (`network:egress`, `webhook:send`, `email:send`) are **dynamically revoked or demoted to L4 (Mandatory Human Approval)**, regardless of the agent's baseline autonomy grant!

### [P0-2] The Linear Transaction Fallacy vs. Cyclic Agentic Reality (ReAct Loop)
* **Location:** `docs/AI_Transaction.md`, `docs/MIRAGE_3.0_Specification.md`, `docs/Technical_Architecture.md`
* **The Flaw:** The canonical lifecycle is currently specified as a rigid linear pipeline:
  $$\text{INPUT} \to \text{GATE 1} \to \text{GATE 2} \to \text{PLAN} \to \text{GATE 3} \to \text{EXECUTE} \to \text{GATE 5} \to \text{GATE 4} \to \text{OUTPUT}$$
  Modern industrial AI agents (LangGraph, CrewAI, AutoGen, Claude Computer Use) operate in **iterative reasoning-action loops (ReAct)**. An agent formulates a plan, executes tool 1, receives the tool result, updates context, plans step 2, executes tool 2, encounters a failure, re-plans, and only emits a final output after $K$ iterations.
  Treating an AI Transaction as a single pass through the gates either forces developers to open a new top-level transaction for every sub-step (destroying transaction atomicity and correlation) or bypasses Gate 3 and Gate 5 for intermediate turns.
* **Architectural Fix:** The AI Transaction must be formally defined as a **Directed Execution Graph with a Governed Turn Loop**:
  - A Transaction encapsulates an overarching intent and budget.
  - Within a transaction, the execution loop alternates:
    $$\text{Plan Turn} \to \text{Gate 3 (Action)} \to \text{Tool Proxy} \to \text{Gate 5 (Outcome)} \to \text{Context Update (Taint & Evidence)} \to \text{Next Turn}$$
  - The loop is bounded by explicit `max_turns` and `turn_budget` constraints.
  - Gate 4 (Output Assurance) evaluates the synthesized response upon loop termination, while intermediate tool outputs are governed dynamically.

### [P0-3] The Epistemic Fallacy of Reality Verification (Gate 5 Overclaiming)
* **Location:** `docs/Reality_Verification.md`, `docs/Input_Output_Assurance.md`
* **The Flaw:** `docs/Reality_Verification.md` claims MIRAGE "confirms actual state changes in real systems: databases, APIs, cloud infrastructure, payments, tickets, deployments, documents." It then provides a binary classification (Full Success, Partial Success, Silent Failure, Loud Failure).
  This is technically and epistemically impossible for three major classes of enterprise actions:
  1. **Eventual Consistency:** Cloud infrastructure (AWS), distributed databases (Cassandra), and search clusters (Elasticsearch) exhibit propagation lag. Querying immediately after an action yields a false discrepancy.
  2. **Write-Only / External Sinks:** Sending an email, emitting an un-acknowledged webhook, or triggering third-party SMS has no read-back verification API.
  3. **Asymmetric Authorization:** The agent may hold write permissions to a queue or table, but the MIRAGE verifier may not have read permissions to inspect the target system state.
  Claiming an outcome is "Verified" when MIRAGE only received an HTTP 200 from a write-only endpoint introduces dangerous false confidence.
* **Architectural Fix:** Reality Verification must incorporate an **Epistemic Observability Model**:
  - Every action target must declare its Observability Class:
    - `OBS_DIRECT` (immediately readable via read API / SQL `SELECT`)
    - `OBS_EVENTUAL` (observable after duration $\Delta t$ with exponential backoff)
    - `OBS_INFERRED` (acknowledged by transport, unobservable at sink)
    - `OBS_BLIND` (write-only, zero feedback loop)
  - Outcome Assurance (Gate 5) must output a tuple: `(OutcomeStatus, EpistemicConfidence)`:
    - Statuses: `CONFIRMED_SUCCESS`, `UNVERIFIABLE_ACKNOWLEDGED`, `PENDING_ASYNC`, `DISCREPANCY_DETECTED`, `CONFIRMED_FAILURE`.
  - MIRAGE must never claim an action is `CONFIRMED_SUCCESS` if the observability class is `OBS_INFERRED` or `OBS_BLIND`.

### [P0-4] The Salami-Slicing Aggregate Risk Vulnerability
* **Location:** `docs/Risk_Model.md`, `docs/AI_Action_Contract.md`
* **The Vulnerability:** Risk is evaluated per individual action. A malicious or confused agent attempting an L4 high-risk action (e.g., deleting 1,000 customer records or transferring $10,000) can trivially decompose the operation into 1,000 discrete L2 micro-actions (e.g., deleting 1 record or transferring $10 at a time).
  Because each individual action is low-risk and reversible, each scores $<40$ (L2 Auto-Execute), completely bypassing the human approval gate (L4)!
* **Architectural Fix:** Enforce **Sliding-Window Aggregate Blast Radius Quotas** in the Risk Engine:
  - Define cumulative blast radius dimensions: `cumulative_records_mutated`, `cumulative_financial_delta`, `cumulative_external_calls`.
  - Action authorization (Gate 3) must evaluate:
    $$\text{Effective Risk} = \max\left(\text{Instantaneous Action Risk}, \text{Cumulative Window Risk}\right)$$
  - When cumulative consumption crosses the tenant-configured tier ceiling within a sliding window (e.g., 1 hour), subsequent L2 actions are automatically escalated to L4 (Mandatory Human Approval).

---

## 4. High-Priority Findings (P1 — Serious Operational/Engineering Flaws)

### [P1-1] The Economic & Latency Catastrophe of Synchronous Verification
* **Location:** `docs/Cost_Optimization.md`, `docs/Technical_Architecture.md`
* **The Problem:** The verification stack inherited from MIRAGE 2.x (SCS with $n=5$ LLM samples + DeBERTa NLI + Qdrant RAV) costs between 800ms and 2,500ms and increases inference costs by 300% to 600%. If Gate 4 runs Tier 3 statistical verification synchronously on every user chat completion, MIRAGE will destroy application performance and blow up API bills.
* **Architectural Fix:** Formalize the **Asynchronous Speculative Assurance Pattern**:
  - For interactive streaming chat, the response is delivered to the user with a transient header `X-Assurance: SPECULATIVE`.
  - Heavy statistical verification (SCS and DeBERTa) executes asynchronously in the background.
  - If a critical hallucination or contradiction is discovered post-delivery, MIRAGE emits an out-of-band retraction event (via WebSocket/SSE) and logs an operator alert.
  - Synchronous blocking verification is strictly reserved for **Action Preconditions (Gate 3)** and **High-Risk Non-Streaming Transactions (L3/L4)**.

### [P1-2] Identity Over-Specification vs. Adoption Friction
* **Location:** `docs/Security.md`, `docs/Technical_Architecture.md`, `docs/API_Specification.md`
* **The Problem:** The specification mandates mutual TLS (mTLS), asymmetric cryptographic keys, and signed JWTs for every agent, tool, and client. Requiring an enterprise developer building a Python LangChain script to manage an internal CA and issue mTLS certificates for local tools creates extreme adoption friction.
* **Architectural Fix:** Establish a **Dual-Mode Identity Model**:
  - **Developer Mode (Zero-Friction):** Standard Bearer API keys (`mrg_live_...`) with tenant and agent ID headers; internal services communicate over private VPC networks with TLS termination at the ingress gateway.
  - **Zero-Trust Enterprise Mode (High-Assurance):** mTLS with short-lived SPIFFE/SPIRE workload identities and token exchange for defense/banking deployments.

### [P1-3] Distributed Saga Rollback Without Durable Workflow Orchestration
* **Location:** `docs/AI_Action_Contract.md`, `docs/Reality_Verification.md`
* **The Problem:** `docs/AI_Action_Contract.md` specifies that when a multi-action transaction enters a `PARTIAL` failure state, MIRAGE "walks backward through the execution log, invoking defined rollback or compensation actions." However, the architecture relies on Celery with RabbitMQ. If a worker crashes mid-rollback, Celery does not provide durable event-sourced state machines; transactions can be left in corrupt, half-compensated states.
* **Architectural Fix:** 
  - Restrict automated compensation in Phase 1 to **Single-Action Atomic Compensations**.
  - Multi-step distributed Sagas must be explicitly recorded in an append-only **Action Compensation Journal** in PostgreSQL. If a compensation fails or the process dies, a dedicated idempotency reconciliation worker resumes compensation from the journal or escalates to `ESCALATION_HUMAN_INTERVENTION`.

### [P1-4] Gate Semantic Naming & Sequence Clarity
* **Location:** `docs/Input_Output_Assurance.md`, `docs/GLOSSARY.md`
* **The Problem:** Numbering the gates as 1, 2, 3, 4, 5 while executing them in sequence 1 → 2 → 3 → 5 → 4 creates permanent cognitive friction and developer confusion.
* **Architectural Fix:** Deprecate numerical gate designations as primary code identifiers. Standardize across all APIs, schemas, and documentation on **Semantic Gate Designations**:
  - `Gate 1` $\to$ **Input Assurance** (`input_assurance`)
  - `Gate 2` $\to$ **Context Assurance** (`context_assurance`)
  - `Gate 3` $\to$ **Action Assurance** (`action_assurance`)
  - `Gate 4` $\to$ **Outcome Assurance** (`outcome_assurance` — real-world state check)
  - `Gate 5` $\to$ **Output Assurance** (`output_assurance` — generated response check)
  *(This aligns execution order: Input $\to$ Context $\to$ Action $\to$ Outcome $\to$ Output).*

### [P1-5] Memory Poisoning via Unverifiable Personal Facts
* **Location:** `docs/Memory.md`
* **The Problem:** `docs/Memory.md` states that memory is verified for factual consistency via Gate 4 before being written. However, episodic memories and user preferences (e.g., "User prefers dark mode", "Meeting scheduled with Dr. Smith tomorrow at 3pm") cannot be verified against an organizational knowledge base using NLI because the knowledge base does not contain private future facts!
* **Architectural Fix:** Separate memory into **Two Distinct Epistemological Classes**:
  - **Attested Knowledge:** Claims extracted from verified documents or explicitly signed by a human user. Held as high-trust, eligible for RAG evidence.
  - **Observational / Heuristic Memory:** Model-inferred preferences and intermediate notes. Stored with an explicit `ADVISORY` flag. **Advisory memory can never be used as authoritative evidence to satisfy Gate 3 Action preconditions!**

---

## 5. Medium & Low Findings (P2 / P3)

### [P2-1] Model Routing Scope Creep (Commodity vs. Assurance)
* **Location:** `docs/Model_Routing.md`
* **Analysis:** Building a full-blown cost/latency router duplicates LiteLLM, RouteLLM, and Portkey. MIRAGE should not maintain latency benchmarks for 100 commercial models.
* **Resolution:** Re-scope Model Routing to **Policy-Constrained Assurance Routing**: MIRAGE enforces data residency, privacy boundaries (no PII to public APIs), and minimum reliability tiers, while delegating low-level provider multiplexing to an OpenAI-compatible proxy interface.

### [P2-2] Polyglot Persistence Operational Overhead
* **Location:** `docs/Data_Model.md`, `docs/Technical_Architecture.md`
* **Analysis:** Requiring PostgreSQL + MongoDB + Redis + Qdrant + RabbitMQ creates an 8-service operational burden for local developers.
* **Resolution:** Define a **Lightweight Embedded Profile** for local testing: PostgreSQL (with pgvector), Redis, and RabbitMQ, making MongoDB and Qdrant optional enterprise deployment profiles.

### [P3-1] Unclear Stream Verification Buffering Semantics
* **Location:** `docs/AI_Transaction.md`, `docs/API_Specification.md`
* **Resolution:** Define exact token buffer windowing for streaming responses: buffer sentences using regex sentence boundary detectors, execute PII/regex checks on sentence release, stream assured chunks, and finalize full claim verification upon stream completion.

---

## 6. Comprehensive Failure Semantics Matrix

To ensure absolute system stability, every critical subsystem must have explicit failure semantics:

| Subsystem | Failure Trigger | Default Mode | Fallback / Compensating Behavior | Emitted Telemetry / Audit |
|---|---|---|---|---|
| **Identity Service** | Token invalid, DB down, spoofing detected | **FAIL-CLOSED** | Block request immediately; return HTTP 401/403. | Security Alert; audit log with client IP/headers. |
| **Input Assurance** | Scanner timeout or unparseable payload | **FAIL-CLOSED** | Block request; return HTTP 422 Invalid Input. | Event `input_assurance_failed`. |
| **Policy Engine** | Syntax error, DB timeout, evaluation crash | **FAIL-CLOSED** | Deny action; default-deny principle applies. | Critical Error `policy_eval_failure`; alert admin. |
| **Risk Engine** | Missing dimension data or calculation error | **FAIL-CLOSED** | Assume maximum risk score (100 / L5); require admin override. | Event `risk_calculation_fallback`. |
| **Context Assembler / RAG** | Vector DB (Qdrant) down or timeout | **FAIL-OPEN (Degraded)** | Proceed without external context; flag transaction `UNGROUNDED_CONTEXT`; drop Output Assurance score floor. | Warning `qdrant_unreachable`; circuit breaker trips. |
| **Memory Store** | Memory retrieval timeout | **FAIL-OPEN (Degraded)** | Proceed with empty episodic memory; log degraded session. | Event `memory_retrieval_timeout`. |
| **Model Provider** | LLM 5xx error, rate limit (429), timeout | **FAILOVER** | Retry once with backoff; failover to secondary model in same tier; if exhausted, return HTTP 504. | Metric `model_failover_count`. |
| **Action Governor (Gate 3)** | Precondition check fails or auth error | **FAIL-CLOSED** | Block tool execution; return action error to agent loop. | Audit entry `action_blocked`. |
| **Tool / MCP Server** | External tool crash, 500, socket disconnect | **RECORD & RECOVER** | Treat tool output as error string; do not crash transaction; feed error to agent for re-planning. | Metric `tool_invocation_error`. |
| **Reality Verifier (Gate 4)** | Target system read API down or unobservable | **DEGRADE TO UNVERIFIED** | Set outcome status to `UNVERIFIABLE_ACKNOWLEDGED`; do NOT fail transaction; tag Output Assurance. | Warning `outcome_verification_unobservable`. |
| **Verification Engine** | DeBERTa GPU worker down or timeout | **FAIL-OPEN (Degraded)** | Skip NLI entailment; fall back to heuristic ICS/regex; reduce final assurance score by 40%. | Metric `verification_engine_degraded`. |
| **PostgreSQL (Ledger)** | DB connection lost or commit failure | **FAIL-CLOSED** | Abort transaction; return HTTP 503 Service Unavailable; memory buffering prohibited. | Critical Alert `ledger_commit_failure`. |
| **MongoDB (Traces)** | Trace write timeout | **FAIL-OPEN (Buffered)** | Buffer trace asynchronously in Redis queue; retry background flush. | Warning `trace_buffer_enqueued`. |
| **Event Stream / Broker** | RabbitMQ broker disconnect | **FAIL-CLOSED (Local Queue)** | Pause background task dispatch; hold HTTP connection up to timeout; reject new async jobs. | Critical Alert `broker_unreachable`. |

---

## 7. Resolution of the Seven Open Architectural Decisions

We formally resolve the seven open decisions identified in prior reviews:

1. **Policy Engine Language Standard:**
   - **Resolution:** **Native Typed Python/JSON Schema Engine (Phase 1) with Open Policy Agent (Rego) Transpiler (Enterprise Phase).**
   - **Rationale:** A native JSON schema evaluated via deterministic Python functions requires zero external C-dependencies or external daemons, ensuring instant unit testing and zero latency overhead.
2. **Event Stream Infrastructure:**
   - **Resolution:** **RabbitMQ Streams & AMQP Quorum Queues.**
   - **Rationale:** RabbitMQ 3.13 is already deployed in MIRAGE 2.x with Quorum queues and Raft consensus. Introducing Kafka or NATS adds needless operational complexity.
3. **Agent-to-Agent (A2A) Governance Protocol:**
   - **Resolution:** **Standardized Transaction Context Injection over HTTP/MCP.**
   - **Rationale:** Rather than inventing a new binary wire protocol, parent agents pass a cryptographically signed `Mirage-Transaction-Context` HTTP header or MCP metadata block containing the parent transaction ID, bounded capability token, and remaining budget.
4. **Primary Model Provider Abstraction:**
   - **Resolution:** **OpenAI-Compatible Wire Standard + Lightweight Adapter Layer.**
   - **Rationale:** Standardizing internally on the OpenAI request/response format allows direct proxying to OpenAI, Azure, Groq, vLLM, and Ollama, with small adapter functions for Anthropic Claude and Google Gemini.
5. **Commercial Licensing & Open-Core Boundary:**
   - **Resolution:** **Open-Core Architecture.**
   - **Rationale:** 
     - *Apache 2.0 (Open-Source):* Execution Plane, Five Assurance Gates, Verification Engine (RAV/NLI/SCS/HRS), Local Docker Topology, Python SDK.
     - *Commercial / Enterprise License:* Multi-Tenant SAML/SSO, Role Delegation, Automated Compliance PDF Audit Generator, Longitudinal Drift Console, Distributed OTel Tracing.
6. **Deployment Target Priority:**
   - **Resolution:** **Developer-First Hardened Docker Compose (Tier 1) followed by Production Kubernetes Helm Charts (Tier 2).**
   - **Rationale:** Adoption begins on local developer laptops. If developers cannot run `docker compose up` in 60 seconds, enterprise adoption never materializes.
7. **Frontend Console Scope:**
   - **Resolution:** **Phase 1: Operational Drift & Transaction Viewer; Phase 3: Administrative Control Plane.**
   - **Rationale:** The frontend must remain strictly **React 18 / JSX (No TypeScript)**. In Phase 1, it provides visibility into transaction traces and risk scores. Management of policies and tenants occurs via REST API until Phase 3.

---

## 8. Required Specification Updates (Batch Actions)

To maintain absolute documentation synchronization, the following specification files are updated in this commit batch:

1. **`docs/MIRAGE_3.0_Specification.md`**: Update lifecycle to reflect the ReAct turn loop and incorporate the Epistemic Observability Model and Information Flow Control rules.
2. **`docs/Security.md`**: Add Dynamic Taint Tracking (IFC) to resolve the Dangerous Triad.
3. **`docs/AI_Transaction.md`**: Refactor the transaction lifecycle from a rigid linear sequence to a bounded turn-loop state machine.
4. **`docs/Reality_Verification.md`**: Replace binary verification with the Epistemic Observability Model (`OBS_DIRECT`, `OBS_EVENTUAL`, `OBS_INFERRED`, `OBS_BLIND`).
5. **`docs/Risk_Model.md`**: Add Sliding-Window Aggregate Blast Radius Quotas to prevent salami-slicing attacks.
6. **`docs/Cost_Optimization.md`**: Add Asynchronous Speculative Assurance pattern for interactive streaming.
7. **`docs/GLOSSARY.md`**: Add new canonical definitions: *Epistemic Observability*, *Taint Tracking*, *Speculative Assurance*, *Turn Loop*, and *Aggregate Blast Radius*.
8. **`docs/ADRs/0008-react-turn-loop-and-epistemic-verification.md`**: Ratify the architectural corrections established in this audit.

---

## 9. Final Specification Audit Status

```text
================================================================================
MIRAGE 3.0 SPECIFICATION STATUS:
APPROVED WITH REQUIRED CHANGES (REMEDIATION APPLIED IN CURRENT BATCH)

IMPLEMENTATION:
STOPPED / NOT STARTED — SPECIFICATION HARDENED AND RATIFIED FOR PHASE 1
================================================================================
```
