# MIRAGE 3.0 — Product Requirements Document (PRD)

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document supersedes the MIRAGE 2.x PRD and serves as the product requirements for MIRAGE 3.0. Terminology is strictly governed by the canonical MIRAGE 3.0 `GLOSSARY.md`.
> **Product Promise:** Control AI before it acts. Verify AI after it acts.

---

## 1. Executive Summary

As AI moves from read-only chat to autonomous action, organizations are encountering the fundamental problem of trust. "The model said it worked" is not the same as "it actually worked." LLMs generate plausible but incorrect outputs, RAG systems retrieve poisoned context, and agents composed of multiple steps compound error probabilities. 

MIRAGE 3.0 solves this by acting as an **AI Execution Assurance Platform** — an AI Control & Assurance Fabric that sits between AI systems and the real world. MIRAGE inspects inputs, context, actions, outputs, and outcomes to enforce identity, security, policy, reliability, and cost controls while using adaptive verification and intelligent model routing to achieve the required level of assurance at the lowest practical cost.

This Product Requirements Document details the capabilities, features, constraints, and success metrics for MIRAGE 3.0, mapping its evolution from a verification tool (2.x) into a comprehensive lifecycle governance platform.

---

## 2. Vision and Mission

**Vision:** To make AI systems completely trustworthy enough for consequential real-world use across all industries.

**Mission:** MIRAGE provides the control, verification, and assurance infrastructure that allows organizations to deploy AI agents, copilots, and automated workflows with confidence — knowing that every input is validated, every action is authorized, every output is verified, and every outcome is confirmed.

---

## 3. Problem Statement

Industrial AI systems face a compounding set of challenges that no single existing tool category addresses. Referencing the canonical specification, the 14 key problem areas are:

1. **LLM Applications:** Models generate plausible but incorrect outputs (hallucinations), toxic content, or policy violations. Confidence cannot be derived from outputs alone.
2. **RAG Systems:** Retrieved context may be stale, poisoned, or irrelevant. Evidence provenance is rarely tracked end-to-end.
3. **Autonomous Agents:** Agents execute plans with compounding error probabilities. Actions may be irreversible or dangerous, creating unbounded risk.
4. **Tool Use and MCP:** Tools receive parameters from untrusted AI models. Tool outputs are incorrectly treated as trusted data by default.
5. **Enterprise Workflows:** Multiple AI systems interact with shared resources under varying policies. Auditability and cost attribution are lacking.
6. **Multi-Agent Systems:** Agent-to-agent communication propagates trust risks, blurring accountability and transaction boundaries.
7. **Model Routing:** Static routing wastes resources or ignores risk. Model failures need graceful fallback based on task and capability requirements.
8. **Memory:** AI systems accumulate session data without governance, provenance, or expiration, leading to poisoning or stale context.
9. **Sensitive Data:** PII, credentials, and proprietary information flow through models without active detection, risking exfiltration.
10. **External Actions:** Models execute actions without verification that the action actually succeeded in the target system.
11. **Cost:** Unbounded model and tool calls lack budgeting and attribution. Naïve verification linearly increases cost.
12. **Reliability:** AI system failures are often silent. Cascading failures require manual rollback or human intervention.
13. **Security:** Prompt injection, data poisoning, and identity spoofing exploit AI-specific threat vectors.
14. **Compliance:** Regulated industries require auditable and explainable decision-making that current AI systems cannot provide.

---

## 4. Target Customers

- **Enterprise IT & Operations:** Large organizations deploying internal AI tools that require governance, auditability, and safety controls.
- **AI-Native Product Companies:** Startups and SaaS vendors building autonomous agents and needing out-of-the-box trust infrastructure.
- **Regulated Industries (Finance, Healthcare-adjacent):** Organizations facing strict compliance requirements for data privacy, traceability, and explainable decision-making. (Note: Subject to strict boundaries regarding actual healthcare/medical diagnosis).
- **Platform Builders:** Teams constructing internal developer platforms (IDPs) that offer secure AI capabilities to their engineering teams.

---

## 5. Target Users

- **AI / ML Engineers:** Integrating MIRAGE into agents, evaluating model routing, and tuning verification thresholds.
- **Platform Engineers:** Deploying MIRAGE within Kubernetes, configuring Gateway proxies, and managing infrastructure.
- **Security Engineers:** Defining identity policies, risk models, and capability boundaries to prevent exfiltration and injection.
- **Compliance Officers:** Reviewing audit logs, tracing transaction provenance, and validating policy adherence.
- **Product Managers:** Defining acceptable risk levels, budgets, and autonomy tiers for AI features.
- **DevOps / SRE:** Monitoring system health, latency budgets, cost optimization, and incident response.

---

## 6. Industrial Use Cases

MIRAGE 3.0 supports the following families of use cases:

1. **Enterprise Copilots:** Internal assistants querying internal knowledge bases, governed by data access policies (Context Assurance, Gate 2).
2. **Customer Support Agents:** Public-facing bots executing refunds or resolving tickets, governed by strict action budgets (Action Assurance, Gate 3) and output safety (Gate 4).
3. **Coding Agents:** Agents writing and executing code in sandboxes. MIRAGE ensures blast radius is contained and actions are reversible.
4. **Research Agents:** Long-running agents summarizing massive datasets. MIRAGE provides memory governance and evidence provenance.
5. **Financial Workflows:** Automated expense approval or invoice generation. Requires L4 autonomy (Execute with Approval) and cryptographically verifiable audit trails.
6. **Healthcare-adjacent Workflows (Strict Boundaries):** Administrative tasks like scheduling and billing automation. *Legal Boundary: MIRAGE is explicitly NOT certified for clinical diagnosis, patient treatment decisions, or autonomous medical dispensing.*
7. **Enterprise Automation:** ERP and CRM data entry agents, relying on Reality Verifier (Gate 5) to confirm data was actually written.
8. **Procurement Agents:** Automated vendor evaluation and contract drafting, governed by strict spending limits and budget tracking.
9. **Sales Operations:** Automated lead enrichment and outreach. MIRAGE checks outputs for brand safety and policy compliance.
10. **Infrastructure/DevOps Agents:** Automated incident response or scaling agents. MIRAGE ensures fail-safe behavior and enforces capabilities on infrastructure APIs.
11. **Security Operations Agents:** Log analysis and threat hunting. MIRAGE ensures agent memory is not poisoned by attacker-controlled logs.
12. **Data Analysis Agents:** Agents querying data warehouses. MIRAGE prevents prompt injection from executing destructive SQL via tools.
13. **Multi-Agent Workflows:** Supply chain coordination across distinct agents. MIRAGE tracks transaction boundaries and enforces inter-agent trust boundaries.
14. **MCP-based Applications:** Agents interacting with standardized Model Context Protocol servers. MIRAGE provides tool governance and capability enforcement.

---

## 7. User Journeys

### Journey 1: Security Engineer Securing an Enterprise Copilot
*Goal: Prevent sensitive PII data exfiltration via internal copilot.*
1. Security Engineer logs into the MIRAGE Dashboard.
2. Navigates to **Policy Engine** and creates a Tenant Policy blocking PII in Gate 4 (Output Assurance).
3. Configures **Input Assurance (Gate 1)** to detect prompt injection attempts.
4. Observes real-time transactions in the **Observability** tab, viewing requests that were blocked at Gate 1 or sanitized at Gate 4.

### Journey 2: Platform Engineer Managing AI Cost and Routing
*Goal: Optimize model inference costs without sacrificing reliability.*
1. Platform Engineer defines **Budget** limits for the internal Coding Agent team.
2. Configures the **Model Router** to use a fast, cheap model for initial intent classification, but routes to a heavyweight model for high-risk execution plans.
3. Sets up an **Adaptive Verification** threshold: cheap heuristic checks first, escalating to the full Verification Engine only if risk > 0.4.
4. Views cost attribution charts to confirm the Budget Manager is enforcing limits.

### Journey 3: ML Engineer Deploying a High-Risk Support Agent
*Goal: Ensure support agent cannot issue refunds over $50 without approval.*
1. ML Engineer defines a **Capability** for the `refund_api` tool.
2. In the **Risk Engine**, assigns L4 (Execute with Approval) autonomy for any transaction where financial impact > $50.
3. During execution, when the agent attempts a $100 refund, **Gate 3 (Action Assurance)** suspends execution and triggers a webhook.
4. A human manager approves the action; MIRAGE resumes the transaction and executes the tool.

### Journey 4: Compliance Officer Auditing an Automated Workflow
*Goal: Prove to regulators why a specific financial decision was made.*
1. Compliance Officer searches the **Transaction Manager** ledger using a correlation ID.
2. Views the complete **AI Transaction** trace: Identity, Intent, retrieved Context, Risk Assessment, and executed Plan.
3. Inspects the **Provenance** of the evidence used by the model to justify the decision.
4. Exports a tamper-evident, SHA-256 chained audit report for the regulator.

---

## 8. Jobs-to-Be-Done (JTBD)

1. **Govern Action Risk:** As a PM, I want to restrict what tools an agent can use so that it doesn't accidentally cause catastrophic damage to production systems.
2. **Verify Outcomes:** As an SRE, I want to know if the agent's attempt to restart a server actually succeeded, rather than just trusting the model's textual claim.
3. **Control Costs:** As an engineering leader, I want to enforce strict budgets on LLM token usage and tool calls per tenant to prevent runaway billing.
4. **Enforce Policy:** As a security engineer, I want to write declarative rules that universally block data exfiltration, regardless of which agent framework my teams use.
5. **Route Intelligently:** As a platform architect, I want incoming requests to be routed to the cheapest capable model automatically, based on the task's complexity and risk.
6. **Protect Memory:** As a security researcher, I want to ensure that attacker-controlled inputs do not poison the long-term memory of our analysis agents.
7. **Trace Decisions:** As a compliance officer, I want to trace exactly which documents were retrieved and used to generate a specific output.
8. **Detect Hallucinations:** As an ML engineer, I want to automatically flag or reject outputs that contain factual contradictions before they reach the user.

---

## 9. Product Principles

Derived directly from the canonical specification (Section 6):
1. **Input is untrusted.**
2. **Context is untrusted.**
3. **Tool output is untrusted.**
4. **Model output is untrusted.**
5. **Actions require authorization.**
6. **Memory requires provenance.**
7. **High-risk actions require stronger assurance.**
8. **Verification should be adaptive.**
9. **Expensive verification must justify its cost.**
10. **Outcome verification is distinct from output verification.**
11. **Identity must be explicit.**
12. **Least privilege is mandatory.**
13. **Tenant isolation is mandatory.**
14. **Fail-safe behavior must be explicit.**
15. **Every consequential AI action must be attributable.**

---

## 10. Functional Requirements

### 10.1 Gateway
- **Ingestion:** Must accept HTTP/REST and gRPC traffic, intercepting standard LLM API formats (e.g., OpenAI compatible endpoints) and agent webhooks.
- **Rate Limiting:** Must enforce rate limits per identity, tenant, and token budget using Redis token buckets.
- **Gate 1 (Input Assurance):** Must detect prompt injection, classify intent, check initial policy, and evaluate data sensitivity before forwarding.

### 10.2 Identity Service
- **Authentication:** Must support API keys, OIDC, and mTLS for identifying users, agents, tools, and services.
- **Tenant Management:** Must enforce strict logical isolation of data and configuration per tenant.

### 10.3 Policy Engine
- **Declarative Policies:** Must support a structured policy language (e.g., OPA/Rego or a custom MIRAGE DSL) for defining rules across Gates.
- **Hierarchical Precedence:** Global policies override tenant policies, which override agent policies.

### 10.4 Risk Engine
- **Scoring:** Must compute risk dynamically (0.0 to 1.0) based on blast radius, data sensitivity, and intent.
- **Autonomy Levels:** Must map risk scores to Autonomy Levels (L0 to L5) and enforce human-in-the-loop approvals for L4 actions.

### 10.5 Model Router
- **Dynamic Selection:** Must select target models dynamically based on real-time health, cost constraints, and intent classification.
- **Fallback:** Must implement circuit breakers (via `pybreaker` or similar) to fallback gracefully when a primary model provider fails.

### 10.6 Action Governor (Gate 3)
- **Capability Enforcement:** Must evaluate requested tool calls against the agent's granted capabilities.
- **Parameter Validation:** Must validate tool arguments against defined schemas and semantic policies.
- **Approval Workflow:** Must suspend execution and emit events for manual/policy approval when required by Autonomy Level.

### 10.7 Verification Engine (Gate 4)
*Incorporates MIRAGE 2.x core.*
- **Factual Consistency:** Must perform claim decomposition and RAV (Retrieval-Augmented Verification) using Qdrant.
- **Reliability Scoring:** Must compute HRS (Holistic Reliability Score) using conformal prediction and calibration.
- **Safety Checks:** Must execute NLI and SCS to identify contradictions and hallucinations.
- **Explainability:** Must provide TreeSHAP attributions for verification decisions.

### 10.8 Reality Verifier (Gate 5)
- **State Confirmation:** Must query target systems or secondary oracles to confirm if an executed action achieved its postconditions.
- **Discrepancy Detection:** Must flag instances where the action's intent diverges from the confirmed real-world state.

### 10.9 Memory Governance
- **Provenance Tracking:** Must tag all stored context with origin, author, and timestamp.
- **Poisoning Protection:** Must isolate memories by tenant and session to prevent cross-contamination.
- **Lifecycle:** Must enforce TTL/expiration policies on stored memory.

### 10.10 Observability
- **Distributed Tracing:** Must implement OpenTelemetry tracing across all gates and components.
- **Ledger Storage:** Must store complete AI Transaction traces in MongoDB.
- **Cryptographic Audit:** Must generate SHA-256 chains for tamper-evident compliance logging.

### 10.11 Dashboard (Frontend)
- **Technology:** Must be built in React 18/JSX (TypeScript/TSX is explicitly prohibited per engineering directives).
- **Views:** Must provide views for Policy Management, Transaction Tracing, Risk Configuration, Budget Monitoring, and System Health.

---

## 11. Non-Functional Requirements

### 11.1 Latency
- **Gate 1 (Input):** < 50ms overhead (p95).
- **Gate 3 (Action):** < 100ms overhead (p95) for deterministic checks.
- **Gate 4 (Verification):** Adaptive; fast heuristic checks < 200ms; full RAV/SCS verification bounded by Model/LLM latency but targeted < 2000ms.
- **Throughput:** System must scale horizontally to handle 10,000+ concurrent transactions per standard enterprise cluster.

### 11.2 Availability & Scalability
- **Uptime:** Control Plane 99.99%; Execution Plane 99.99%.
- **Stateless Execution:** Gateway and Execution Plane components must be stateless to allow horizontal pod autoscaling.
- **State Stores:** PostgreSQL (ACID), Redis (Cache), and MongoDB (Traces) must be deployed in highly available topologies.

---

## 12. Trust/Security Requirements

- **Tenant Isolation:** Row-Level Security (RLS) in PostgreSQL; per-tenant database logical separation in MongoDB.
- **Data Encryption:** TLS 1.3 in transit. AES-256 for data at rest.
- **Zero Trust:** Every internal component must mutually authenticate via mTLS.
- **Least Privilege:** Internal microservices run with minimum required IAM roles.

---

## 13. Cost Requirements

- **Verification Budget:** The system must support adaptive verification logic to ensure the cost of Verification Engine operations does not exceed configurable percentages (e.g., 10%) of the total transaction value or budget.
- **Cost Attribution:** Every API call, model inference, and tool execution must be logged with estimated cost and attributed to a specific Tenant and AI Transaction.

---

## 14. Reliability Requirements

- **Fail-Safe Defaults:** If the Risk Engine or Policy Engine is unreachable, the system must fail closed (block action).
- **Circuit Breakers:** All external calls (to LLMs, MCP servers, target APIs) must be wrapped in circuit breakers to prevent cascading failures.
- **Graceful Degradation:** If heavy verification models fail, the system should fall back to fast heuristic checks, logging the degraded assurance level.

---

## 15. Developer Experience Requirements

- **SDKs:** Official Python SDK mirroring the API functionality, focusing on intuitive agent framework integration.
- **OpenAPI:** All APIs must be documented with OpenAPI 3.1 specifications.
- **Local Dev:** Must provide a `docker-compose` environment that brings up a complete, functional MIRAGE 3.0 instance locally in under 3 minutes.
- **ADR Process:** All architectural deviations must be documented in the `ADRs/` directory.

---

## 16. Enterprise Requirements

- **SSO / SAML:** Support for enterprise identity providers (Okta, Entra ID) for Dashboard and API access.
- **Audit Logging:** Exportable, tamper-evident logs compliant with standard SIEM formats (CEF, Syslog).
- **Compliance Alignment:** Architecture must support deployment in SOC2, ISO27001, and HIPAA compliant environments (though MIRAGE itself does not provide automatic certification).

---

## 17. Deployment Models

1. **SaaS (Managed):** Fully hosted multi-tenant cloud service.
2. **On-Premise / VPC:** Helm charts for deployment into customer-controlled Kubernetes clusters.
3. **Air-Gapped:** Support for completely disconnected environments using localized OSS LLMs (Llama 3, Mistral) instead of cloud APIs.

---

## 18. Integrations

- **LLM Providers:** Native routing support for OpenAI, Anthropic, Google Gemini, Cohere, and local inference via vLLM/Ollama.
- **Agent Frameworks:** Drop-in integration for LangChain/LangGraph, AutoGen, CrewAI, and LlamaIndex.
- **MCP Integration:** Native support for the Model Context Protocol, capable of governing access to standardized MCP servers.
- **Observability:** Export integrations to Datadog, Splunk, and standard OTLP endpoints.

---

## 19. APIs and SDKs

- **Control Plane APIs:** RESTful endpoints for managing Policies, Identities, Capabilities, Budgets, and Tenants.
- **Execution Plane APIs:** Streaming endpoints for AI Transactions, Proxy endpoints for model routing, and Webhooks for approval workflows.
- **SDK:** `mirage-python` package providing decorators, middleware, and clients for rapid integration.

---

## 20. Observability and Governance

- **Provenance Tracking:** End-to-end data lineage connecting output claims back to retrieved source documents and memory nodes.
- **Assurance Scoring:** Every transaction receives an overall Assurance Score, visible in the dashboard and attached to output metadata.
- **Event Stream:** System must publish structured events for every policy decision, risk assessment, and gate evaluation for asynchronous consumption.

---

## 21. Success Metrics

1. **Adoption:** Number of Active Tenants, Number of AI Transactions Processed (Target: >10M/month in first 6 months).
2. **Efficacy:** False Positive / False Negative rates for Gate 1 (Injection) and Gate 4 (Hallucination) < 5%.
3. **Performance:** Median overhead per transaction < 150ms for low-risk paths.
4. **Cost Optimization:** Average verification cost reduction of 40% when using adaptive routing vs. static heavyweight verification.
5. **Resilience:** 100% block rate for L4+ actions lacking explicit approval.

---

## 22. Failure Scenarios

- **Model Provider Outage:** Router automatically falls back to secondary provider; if all fail, Gate returns controlled error without crashing the transaction state.
- **Database Unavailability:** PostgreSQL outage causes Gate 1 to fail closed; System halts new transaction processing while preserving in-flight states in Redis.
- **Verification Timeout:** If Gate 4 takes too long, system triggers configured timeout policy (either fail closed or pass with warning flag depending on risk).
- **Partial Action Failure:** Gate 5 detects a tool failure; Action Governor logs the discrepancy, triggers rollback/compensation workflow, and updates Assurance Score.

---

## 23. Non-Goals

1. **Building Foundational LLMs:** MIRAGE evaluates and routes models; it does not train or host foundational base models.
2. **Replacing CI/CD:** MIRAGE is for runtime execution assurance, not static code analysis or deployment pipelines.
3. **General Purpose API Gateway:** MIRAGE focuses exclusively on AI workload governance, not general web traffic routing (use Kong or Envoy for that).
4. **Clinical / Medical Diagnosis:** MIRAGE will not be certified for, nor provide features explicitly supporting, autonomous medical decisions.

---

## 24. Anti-Features

These are explicitly prohibited and will not be built:
1. **Unbounded Auto-Execution:** The system will never allow configuration that completely bypasses Gate 3 for L4/L5 high-risk actions.
2. **TypeScript/TSX Frontend:** By engineering mandate, the frontend will strictly utilize React 18 with standard JSX/JavaScript. No TypeScript.
3. **Black Box Policies:** The Policy Engine will never use opaque ML models to make allow/deny decisions. Policy evaluation must remain deterministic and explainable.
4. **Permanent Ambient Authority:** Agents will never be granted permanent, unbound capabilities. All capabilities must be scoped and temporary.

---

## 25. Roadmap (Aligned with Canonical Spec Section 12.6)

- **Phase 1: Core Control Plane** - Identity, Policy, Tenant, Capability services; extended Gateway with Gate 1.
- **Phase 2: Transaction Model** - AI Transaction lifecycle, state management, correlation.
- **Phase 3: Risk + Action Governance** - Risk Engine, Action Governor, Gate 3, approval workflow.
- **Phase 4: Context + Output Assurance** - Context Assembler with Gate 2; Verification Engine integration with Gate 4.
- **Phase 5: Model Routing + Cost** - Model Router, Budget Manager, cost attribution.
- **Phase 6: Outcome Assurance** - Reality Verifier, Gate 5, postcondition checking.
- **Phase 7: Memory Governance** - Governed memory system with provenance and access control.
- **Phase 8: Tool Governance** - Tool Proxy, MCP governance, tool identity.
- **Phase 9: Observability + Audit** - Enhanced tracing, provenance tracking, audit reporting.
- **Phase 10: Dashboard + SDK** - React 18/JSX management console, Python SDK, comprehensive documentation.

---

*End of Document. MIRAGE 3.0 PRD.*
