# MIRAGE 3.0 — Canonical Glossary

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Supersedes:** All prior informal term usage
>
> Every MIRAGE document, implementation, and agent instruction MUST use these definitions.
> No other document may redefine these terms differently.

---

## Core Primitives

### Action
A discrete operation that may change state in a real system. Actions are the unit of authorization, risk assessment, and outcome verification. An action is not merely an LLM token generation — it is something that can affect the real world (e.g., creating a ticket, sending an email, executing code, modifying a database record, making a payment).

### Agent
An autonomous or semi-autonomous AI system that can perceive, reason, plan, and act. An agent operates under an explicit identity, is bound by policies and capabilities, and executes within the context of an AI Transaction. Agents include LLM-based assistants, coding agents, research agents, multi-agent workflows, and any software entity that uses AI models to make decisions or take actions.

### AI Transaction
An end-to-end traceable unit of AI work. A transaction encapsulates the complete lifecycle from input reception through identity verification, intent classification, risk assessment, policy evaluation, model routing, context assembly, planning, action execution, tool invocation, outcome verification, output generation, and assurance determination. Every consequential AI interaction is recorded as a transaction. See [AI_Transaction.md](AI_Transaction.md).

### Approval
Explicit authorization from a human, a policy, or a delegated authority for a specific action. Approvals are required when risk exceeds the autonomy level granted to an agent. Approvals are logged, time-bounded, scoped to specific actions, and non-transferable.

### Assurance
The verified confidence that an AI system's behavior, output, or outcome meets the required level of correctness, safety, security, and policy compliance. Assurance is achieved through the Five Assurance Gates: Input, Context, Action, Output, and Outcome. Assurance is not binary — it exists on a spectrum from deterministic checks to statistical verification to human confirmation.

### Assurance Level
A quantified measure of the confidence MIRAGE has in the correctness, safety, and policy compliance of a transaction or action. Assurance levels determine whether additional verification, escalation, or approval is required.

### Autonomy Level
The degree of independent action permitted to an agent for a given context. Defined as:
- **L0 — Observe:** Agent can observe and report, but cannot recommend or act.
- **L1 — Recommend:** Agent can suggest actions; human decides and executes.
- **L2 — Auto-Execute Low-Risk:** Agent can execute reversible, bounded, low-risk actions without approval.
- **L3 — Execute with Controls:** Agent can execute medium-risk actions with monitoring, logging, and automated controls.
- **L4 — Execute with Approval:** Agent can execute high-risk actions only after explicit human or policy approval.
- **L5 — Prohibited:** Action is blocked regardless of approval or context.

### Blast Radius
The scope of potential impact if an action fails, produces incorrect results, or causes unintended side effects. Measured across dimensions: number of affected systems, data sensitivity, reversibility, user impact, financial impact, and operational impact.

### Aggregate Blast Radius
The cumulative blast radius accumulated across multiple discrete actions within a sliding time window or transaction. Used by the Risk Engine to prevent "salami-slicing" attacks where high-risk intents are disguised as many micro-actions.

### Budget
An explicit, enforceable limit on resources consumed during a transaction, session, or time period. Budget types include: token budget (input/output tokens), inference budget (model calls), tool-call budget (external invocations), latency budget (wall-clock time), cost budget (monetary), and verification budget (assurance overhead allowed).

### Capability
A specific, bounded permission to perform an action on a resource. Capabilities are granted to agents, scoped to specific tools and resource sets, and enforced by the Policy Engine. A capability is not the same as a tool — a tool is a mechanism; a capability is the authorization to use that mechanism in a specific way.

### Context
All information available to an AI system during processing of a transaction. Context includes: user input, conversation history, retrieved evidence (RAG), memory, tool results, system prompts, agent instructions, and environmental state. Context is classified by provenance, trust level, freshness, and sensitivity.

### Evidence
Verifiable information used to support or contradict claims, decisions, or outputs. Evidence has provenance (origin), confidence (reliability), freshness (age), and trust level (source credibility). Evidence may come from retrieval (RAG), tools, databases, APIs, human attestation, or prior verified transactions.

### Identity
A cryptographically verifiable assertion of who or what is making a request, executing an action, or producing an output. Identity applies to: human users, AI agents, tools, MCP servers, services, and tenants. Identity is the foundation of authorization, audit, and accountability.

### Intent
The declared or inferred purpose of a request or action. Intent classification determines risk assessment, policy selection, model routing, and capability requirements. Intent may be explicitly stated by the user or inferred by MIRAGE from the input, context, and conversation history.

### Memory
Governed, persistent information accessible across interactions and sessions. Memory is not merely a vector database — it is a governed system with provenance tracking, access controls, expiration, integrity verification, and poisoning protection. See [Memory.md](Memory.md).

### Model
An AI/ML model used for inference, generation, verification, or routing. Models are characterized by capabilities, cost, latency, reliability, context window, modality support, and trust level. MIRAGE treats model outputs as untrusted data requiring verification proportional to risk.

### Outcome
The actual real-world state change resulting from an action. Outcome is fundamentally distinct from Output: an output is what the AI system says happened; an outcome is what actually happened in the real system. Outcome verification confirms that postconditions are satisfied and the intended state change occurred.

### Output
The response generated by an AI system. Output includes text, structured data, code, media, or control signals. Output is subject to Output Assurance checks including factual consistency, safety, sensitive data detection, schema validation, and policy compliance.

### Plan
An ordered sequence of intended actions that an agent proposes to execute. Plans are subject to risk assessment, policy evaluation, and approval before execution begins. Plans may be modified during execution based on intermediate outcomes.

### Policy
A declarative rule that constrains behavior within MIRAGE. Policies are evaluated deterministically wherever possible. Policies have explicit precedence, scope (tenant, organization, agent, capability, data, model, cost, risk), and fail-safe behavior. See [Policy_Engine.md](Policy_Engine.md).

### Provenance
The complete, verifiable history of an information item — where it came from, how it was produced, who produced it, when it was created or modified, and what transformations it underwent. Provenance is mandatory for evidence, memory, context, and audit records.

### Reality Verification
The process of confirming that an action's intended state change actually occurred in the real system. Reality verification compares predicted state with actual state, detects discrepancies, and triggers remediation for partial or failed outcomes. See [Reality_Verification.md](Reality_Verification.md).

### Resource
Any system, data store, API, service, or entity that an action may affect. Resources are classified by sensitivity, criticality, and ownership. Access to resources is governed by capabilities and policies.

### Risk
Quantified potential for harm from an action, decision, or AI system behavior. Risk is a function of: action sensitivity, data sensitivity, target criticality, blast radius, reversibility, confidence, model reliability, tool trust, evidence quality, financial impact, privacy impact, security impact, and operational impact. See [Risk_Model.md](Risk_Model.md).

### Tenant
An isolated organizational boundary for data, policy, access control, and resource allocation. Tenant isolation is mandatory — data, policies, memory, evidence, audit logs, and configuration MUST NOT leak across tenant boundaries. All data has a tenant owner.

### Tool
An executable function, API, service, or MCP server that an agent can invoke to interact with external systems. Tool outputs are treated as untrusted data. Tools have identity, provenance, capability scope, parameter constraints, and output validation requirements.

### Transaction
See **AI Transaction**.

### Turn Loop
The governed execution cycle within an AI Transaction in which an agent iteratively formulates an intermediate plan, submits action intents through Action Assurance, executes tools via the Tool Proxy, observes verified real-world outcomes via Outcome Assurance, and updates context before proceeding to the next turn. Bounded by max turn quotas.

### Verification Engine
The subsystem of MIRAGE responsible for evaluating the factual consistency, reliability, and trustworthiness of AI outputs. In MIRAGE 3.0, the existing MIRAGE 2.x verification stack (RAV, SCS, ICS, NLI, VGS, HRS) becomes one subsystem within the broader Assurance framework, specifically serving Output Assurance (Gate 4). It is no longer the entirety of the product.

---

## Architectural Terms

### Assurance Gate
One of five defined checkpoints in the MIRAGE lifecycle where inspection, validation, and policy enforcement occur. The Five Assurance Gates are: (1) Input Assurance, (2) Context Assurance, (3) Action Assurance, (4) Output Assurance, (5) Outcome Assurance. **Execution order note:** Gate numbers are stable identifiers, not execution sequence numbers. In the canonical lifecycle, Outcome Assurance (Gate 5) executes *before* Output Assurance (Gate 4), so that real-world state confirmation informs the final response. The execution order is: Gate 1 → Gate 2 → Gate 3 → Gate 5 → Gate 4. See [MIRAGE_3.0_Specification.md](MIRAGE_3.0_Specification.md) §7 for the full lifecycle.

### Control Plane
The architectural layer responsible for policy management, identity management, tenant configuration, routing rules, model registry, capability definitions, budget management, and administrative operations. The Control Plane does not process AI transactions directly.

### Execution Plane
The architectural layer responsible for processing AI transactions: receiving inputs, evaluating gates, routing to models, executing actions, invoking tools, verifying outcomes, and producing assured outputs. The Execution Plane enforces Control Plane policies at runtime.

### Verification Engine
The MIRAGE subsystem that performs factual consistency and reliability verification of AI outputs. Comprises claim decomposition, retrieval-augmented verification (RAV), semantic consistency scoring (SCS), natural language inference (NLI), internal consistency scoring (ICS), visual grounding (VGS), and holistic reliability scoring (HRS). In MIRAGE 3.0, this is repositioned as the Output Assurance engine within Gate 4.

### Policy Engine
The subsystem that evaluates declarative policies against transaction context to produce deterministic allow/deny/transform/escalate decisions. See [Policy_Engine.md](Policy_Engine.md).

### Risk Engine
The subsystem that computes risk scores for actions, transactions, and agent behaviors based on multi-dimensional risk factors. See [Risk_Model.md](Risk_Model.md).

### Model Router
The subsystem that selects optimal models for tasks based on complexity, risk, latency, cost, privacy, context requirements, and policy constraints. See [Model_Routing.md](Model_Routing.md).

### Epistemic Observability
The classification of real-world target systems according to whether and how their post-action state can be verified: `OBS_DIRECT` (synchronously readable), `OBS_EVENTUAL` (asynchronously observable with propagation delay), `OBS_INFERRED` (acknowledged by transport, unobservable at sink), and `OBS_BLIND` (write-only, zero feedback). Outcome Assurance evaluates these classes to avoid overclaiming certainty.

### Outcome Status (Epistemic)
The standardized 7-state classification returned by Outcome Assurance (Gate 4): `SUCCESS_CONFIRMED` (directly observed), `SUCCESS_EVENTUALLY_OBSERVED` (async observed), `ACKNOWLEDGED_UNVERIFIED` (transport ACK only), `FAILED` (state rejected), `PARTIAL` (batch partial success), `UNKNOWN` (ambiguous/timeout), and `UNOBSERVABLE` (write-only sink). Prevents false assertions of real-world state success.

### Speculative Assurance
An execution pattern for low-latency interactive streaming where generated tokens are delivered to the user tagged with speculative confidence, while heavy statistical verification (SCS/NLI) runs asynchronously out-of-band, issuing retraction events only if severe discrepancies are discovered.

---

## Security Terms

### Capability Security
An authorization model where access is granted through explicit, bounded, revocable capabilities rather than ambient authority. An agent can only perform actions for which it holds a valid capability.

### Confused Deputy
A security vulnerability where a trusted component is tricked into misusing its authority on behalf of an untrusted entity. MIRAGE mitigates confused deputy attacks through explicit identity propagation, capability scoping, and tool output isolation.

### Information Flow Control (IFC) / Taint Tracking
A deterministic security mechanism that tags transaction context and data with provenance labels (e.g., `TAINT_UNTRUSTED`, `TAINT_CONFIDENTIAL`). Rules enforce that contexts bearing both untrusted inputs and confidential records cannot execute external network communication actions without explicit human approval (L4), structurally dismantling the dangerous triad exfiltration vector.

### Least Privilege
The principle that every agent, tool, user, and service should operate with the minimum set of capabilities necessary to perform its function. Capabilities are granted per-transaction or per-session, not permanently.

### Zero Trust
The security model where no component, agent, tool, or data source is trusted by default, regardless of network location or prior behavior. Every request is authenticated, authorized, and validated independently.

---

## MIRAGE 2.x Legacy Terms

> These terms refer to MIRAGE 2.x components. In MIRAGE 3.0, they are repositioned as subsystems of the Verification Engine within Output Assurance (Gate 4).

### HRS (Holistic Reliability Score)
The calibrated composite risk score produced by the MIRAGE 2.x meta-learner (LightGBM), representing the probability that an LLM response contains hallucinated or unreliable content. In MIRAGE 3.0, HRS becomes one signal within Output Assurance.

### ICS (Internal Consistency Scoring)
Pairwise NLI-based detection of contradictions within a single LLM response.

### NLI (Natural Language Inference)
Cross-encoder entailment scoring of claim-evidence pairs using DeBERTa.

### RAV (Retrieval-Augmented Verification)
Dense vector retrieval of evidence from a knowledge base (Qdrant) to support or contradict individual claims.

### SCS (Self-Consistency Sampling)
Multi-sample generation from an LLM with semantic entropy analysis to measure consistency.

### VGS (Visual Grounding Service)
CLIP and LLaVA-based verification of vision-language model outputs against source images.

---

## Abbreviations

| Abbreviation | Expansion |
|---|---|
| ABAC | Attribute-Based Access Control |
| ADR | Architecture Decision Record |
| A2A | Agent-to-Agent (protocol) |
| CP | Conformal Prediction |
| DLX | Dead-Letter Exchange |
| ECE | Expected Calibration Error |
| HRS | Holistic Reliability Score |
| ICS | Internal Consistency Scoring |
| MCP | Model Context Protocol |
| NLI | Natural Language Inference |
| OTel | OpenTelemetry |
| PII | Personally Identifiable Information |
| RAG | Retrieval-Augmented Generation |
| RAV | Retrieval-Augmented Verification |
| RBAC | Role-Based Access Control |
| RLS | Row-Level Security |
| SCS | Self-Consistency Sampling |
| SHAP | SHapley Additive exPlanations |
| VGS | Visual Grounding Service |

---

*This glossary is the canonical source of truth for MIRAGE terminology. All documents in the MIRAGE 3.0 specification hierarchy cross-reference this glossary. When a term appears to conflict between documents, this glossary governs.*
