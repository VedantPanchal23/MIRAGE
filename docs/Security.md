# MIRAGE 3.0 — Security and Threat Model

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document specifies the threat model and security architecture for MIRAGE 3.0. It supersedes the `Security_Access.md` file from MIRAGE 2.x.
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md).

---

## 1. Introduction

MIRAGE 3.0 operates as an AI Execution Assurance Platform, mediating between untrusted inputs, probabilistic AI models, and deterministic real-world actions. In this position, MIRAGE inherits all traditional software security vulnerabilities while introducing entirely new classes of AI-specific risks.

This document defines the comprehensive threat model MIRAGE mitigates and specifies the Zero Trust security architecture required to enforce the Five Assurance Gates safely.

---

## 2. Threat Model

The MIRAGE 3.0 threat model assumes that inputs are malicious, context is poisoned, models can be manipulated, tools can be compromised, and agent plans can be destructive. 

### 2.1 Prompt Injection (Direct and Indirect)
- **Attack:** An attacker crafts an input (direct) or embeds instructions in retrieved context/documents (indirect) that subverts the model's instructions, forcing it to execute malicious actions, leak data, or bypass policies.
- **Impact:** Complete subversion of agent behavior, unauthorized actions, data exfiltration.
- **MIRAGE Mitigation:** Gate 1 (Input Assurance) scans for known injection patterns. Gate 2 (Context Assurance) creates explicit boundaries between instructions and data (e.g., using chat ML formats and system-level isolation). Gate 3 (Action Assurance) ensures that even if an injection succeeds in generating a malicious plan, the action lacks the capability authorization or requires human approval (L4 Autonomy).

### 2.2 Tool Poisoning and MCP Poisoning
- **Attack:** An external tool or Model Context Protocol (MCP) server returns malicious output designed to exploit the agent parsing the response.
- **Impact:** Code execution, confused deputy attacks, privilege escalation, or forcing the agent into an infinite loop.
- **MIRAGE Mitigation:** Gate 2 treats all tool outputs as untrusted context. Tool outputs are parsed via strict schemas, sanitized, and never executed as raw instructions. The Tool Proxy enforces capability limits on what an MCP server can request or return.

### 2.3 Malicious Extensions, Compromised Tools, Compromised Models
- **Attack:** A legitimate tool, extension, or model is compromised upstream (supply-chain attack) or replaced with a malicious variant.
- **Impact:** System-wide compromise, stealthy data exfiltration, backdoored outputs.
- **MIRAGE Mitigation:** Cryptographic verification of tool/model identity and integrity. The Zero Trust model ensures that even compromised tools are strictly bounded by least privilege capabilities (ABAC + Capabilities). Output from compromised models is caught by Gate 4 (Output Assurance).

### 2.4 Model Supply-Chain Attacks
- **Attack:** An attacker modifies model weights, fine-tuning data, or system prompts at the source or during transit.
- **Impact:** The model exhibits targeted failures, biases, or backdoors (e.g., sleeper agents).
- **MIRAGE Mitigation:** The Model Registry enforces checksum verification for loaded models. Gate 4 (Output Assurance) acts as a second independent verification layer, ensuring that even if a model generates a backdoored response, it fails factual consistency, safety, or policy checks.

### 2.5 Memory Poisoning and RAG Poisoning
- **Attack:** An attacker injects false information, malicious instructions, or biased data into long-term memory or RAG knowledge bases.
- **Impact:** The agent relies on poisoned context for future decisions, spreading the compromise temporally across sessions.
- **MIRAGE Mitigation:** Every memory and context item requires explicit Provenance tracking. Gate 2 (Context Assurance) evaluates the trust score and freshness of retrieved information. Memory mutation requires authorization and is recorded in the cryptographically chained Audit log.

### 2.6 Data Exfiltration, Credential Theft, Secret Leakage
- **Attack:** An agent is manipulated into appending sensitive data (PII, credentials, secrets) to external tool calls, URLs, or generated output.
- **Impact:** Loss of confidential information, compliance violations.
- **MIRAGE Mitigation:** Gate 4 (Output Assurance) includes active sensitive data detection (PII/secrets scanning) before any response is delivered or external tool is invoked. Action Governor inspects tool parameters for unauthorized data transfer. Secrets are managed securely and never exposed to the agent's context window in plaintext.

### 2.7 Cross-Tenant Access, Confused Deputy, Privilege Escalation
- **Attack:** An attacker exploits an agent or vulnerability to access data belonging to another tenant or escalates their own privileges by tricking a privileged agent (confused deputy).
- **Impact:** Catastrophic data breach, multi-tenant compromise.
- **MIRAGE Mitigation:** Strict Tenant Isolation using PostgreSQL Row-Level Security (RLS) and per-tenant collections in MongoDB/Qdrant. Every AI Transaction has an explicit identity context that is propagated to all components. The Capability model prevents ambient authority, mitigating confused deputy attacks.

### 2.8 Agent Identity Spoofing and Tool Impersonation
- **Attack:** An attacker or malicious component assumes the identity of a trusted agent, user, or tool to bypass authorization checks.
- **Impact:** Unauthorized actions performed under the guise of a trusted entity.
- **MIRAGE Mitigation:** Cryptographically verifiable identities (mTLS, JWTs) for all agents, tools, and services. Anonymous or unattributable actions are blocked at Gate 1.

### 2.9 Malicious Outputs and Malicious Tool Outputs
- **Attack:** The model naturally hallucinates or intentionally generates harmful, toxic, or policy-violating outputs.
- **Impact:** Reputational damage, compliance failure, delivery of unsafe content.
- **MIRAGE Mitigation:** Gate 4 (Output Assurance) runs the Verification Engine (inherited from MIRAGE 2.x) including semantic consistency, NLI, and holistic reliability scoring to block or redact malicious outputs.

### 2.10 SSRF, Unsafe Code Execution, Data Poisoning
- **Attack:** An agent generates and executes arbitrary code or performs Server-Side Request Forgery (SSRF) via web browsing tools.
- **Impact:** Internal network compromise, lateral movement, database corruption.
- **MIRAGE Mitigation:** Code execution occurs in strict, ephemeral Sandboxes (e.g., restricted containers, gVisor) with no network access unless explicitly authorized via capability. The Tool Proxy blocks private IP ranges to prevent SSRF. 

### 2.11 Denial of Service, Cost Attacks, Agent Loops, Runaway Tool Calls
- **Attack:** An attacker intentionally triggers expensive model routing, infinite agent loops, or excessive tool usage to drain budgets or cause resource exhaustion.
- **Impact:** Financial loss, system downtime.
- **MIRAGE Mitigation:** Explicit Budget management per transaction, session, and tenant. The Execution Plane enforces token, latency, and tool-call limits. Circuit breakers prevent cascading failures.

### 2.12 Excessive Autonomy, Lateral Movement, Destructive Actions
- **Attack:** An agent decides to take destructive actions (e.g., dropping a database) or moves laterally across systems due to unbounded autonomy.
- **Impact:** Irreversible state changes, infrastructure destruction.
- **MIRAGE Mitigation:** Autonomy Levels (L0-L5) and the Risk Engine. High-risk, destructive actions are assessed as L4 or L5. Gate 3 (Action Assurance) requires explicit approval for L4 actions and strictly blocks L5 actions. Gate 5 (Outcome Assurance) verifies postconditions.

---

## 3. Security Architecture

MIRAGE 3.0 adopts a strictly enforced, defense-in-depth architecture.

### 3.1 Zero Trust Model
No entity, whether internal or external, is trusted by default. Every transaction, tool call, and internal service request requires authentication, authorization, and policy evaluation. Trust is explicitly calculated for inputs, context, and models, and it dynamically influences the required verification budget.

### 3.2 Identity Architecture
Identity is the foundation of MIRAGE governance. 
- **Users:** Authenticated via OIDC/SAML. Represent the human initiating or approving a transaction.
- **Agents:** Possess unique identities bound to cryptographic keys. Agent identity determines base autonomy levels and policy application.
- **Tools / MCP Servers:** Registered with unique identifiers and verified via mTLS.
- **Services:** Internal MIRAGE microservices authenticate via mutual TLS (mTLS) and JWTs.

### 3.3 Authentication
- **External API:** API keys with prefix-based checksums for fast invalidation, or OAuth2/OIDC for user-facing applications.
- **Service-to-Service:** mTLS ensures encrypted, authenticated communication between the Gateway, Control Plane, and Execution Plane.
- **Token Exchange:** Ephemeral JWTs define the exact scope, tenant, and transaction ID for internal requests.

### 3.4 Authorization: ABAC + Capability Model
MIRAGE 2.x relied on a 4-role RBAC model. MIRAGE 3.0 extends this significantly:
- **Attribute-Based Access Control (ABAC):** Policies evaluate attributes of the subject (user/agent), object (resource/tool), and environment (risk level, time).
- **Capability Security:** Agents do not possess ambient authority. Instead, they are granted specific, scoped, time-bounded Capabilities for a given transaction. A capability is an unforgeable token granting the right to execute a specific action (e.g., `github:issue:create(repo="mirage")`).

### 3.5 Least Privilege Enforcement
Capabilities are issued strictly on a per-transaction or per-session basis. If an agent does not explicitly require a tool to fulfill an intent, the capability is not granted. Gate 3 enforces this before any action execution.

### 3.6 Tenant Isolation
Isolation is enforced across all data planes:
- **PostgreSQL:** Row-Level Security (RLS) guarantees that control plane data and metadata cannot cross tenant boundaries.
- **MongoDB:** Execution traces are stored in strictly separated, per-tenant collections.
- **Redis:** Key prefixes and logical database separation per tenant for state and rate limits.
- **Qdrant:** Tenant-isolated collections/namespaces for embeddings to prevent cross-tenant RAG poisoning.

### 3.7 Secrets Management
Secrets (API keys, database credentials) are never stored in plaintext or `.env` files in production.
- Integration with HashiCorp Vault, AWS Secrets Manager, or Azure Key Vault.
- Secrets are injected at runtime into the Tool Proxy.
- **Crucially:** Secrets are NEVER provided to the AI model's context window. They are resolved by the Tool Proxy during execution.

### 3.8 Encryption
- **At Rest:** AES-256 encryption for all databases (PostgreSQL, MongoDB, Qdrant).
- **In Transit:** TLS 1.3 mandatory for all external and internal communications.
- **Field-Level Encryption:** Highly sensitive fields (e.g., user PII in memory) use application-level field encryption before database insertion.

### 3.9 Audit and Hash Chaining
Preserving the enterprise-grade auditability of MIRAGE 2.x, all transaction records, policy decisions, and approvals are stored in an append-only Audit Ledger in PostgreSQL.
- Each record includes a SHA-256 cryptographic hash of its contents and the hash of the previous record, creating a tamper-evident hash chain.
- Ensures non-repudiation of agent actions and human approvals.

### 3.10 Retention Policies
- Transitory data (working memory, ephemeral context) is purged immediately upon transaction completion or session expiry.
- Audit logs and execution traces follow configurable tenant retention policies (e.g., 30, 90, 365 days) enforced via TTLs in MongoDB and automated jobs in PostgreSQL.

### 3.11 Incident Response Framework
- **Fail-Safe Behavior:** Security-critical evaluations — identity (Gate 1), authorization, capability enforcement (Gate 3), cost/budget enforcement, and data privacy — always **fail closed**. If these components fail to compute, the transaction is explicitly blocked. Statistical and content verification evaluations — Context Assurance (Gate 2) and Output Factual Consistency (Gate 4) — **default to fail-open with degraded assurance** (the transaction proceeds with a logged warning and reduced assurance score), unless the tenant configures strict fail-closed behavior. See [Policy_Engine.md](Policy_Engine.md) §6.2 for the complete fail-safe matrix.
- **Circuit Breakers:** Prevent cascading failures if external tools or model providers degrade.
- **Automated Revocation:** Agents exhibiting anomalous behavior (e.g., failing Gate 4 repeatedly) have their capabilities automatically revoked.

### 3.12 Threat Detection Patterns
MIRAGE actively detects:
- **Velocity anomalies:** Rapid, repeated identical actions.
- **Policy violation spikes:** Sudden increase in Gate 1 or Gate 4 rejections.
- **Cost spikes:** Unexpected consumption of inference budgets.
- **Unrecognized capabilities:** Attempts to use tools not explicitly granted.

### 3.13 Sandboxing for Code Execution
If an agent requires arbitrary code execution (e.g., Python data analysis), it occurs in isolated, ephemeral sandboxes (e.g., gVisor, Firecracker microVMs).
- No external network access unless explicitly allowed.
- Strictly limited CPU, memory, and execution time budgets.
- Destroyed immediately after execution.

---

---

## 4. Specific Security Boundaries & Information Flow Control (IFC)

### 4.1 Information Flow Control (IFC) & Resolving the Dangerous Triad
The most catastrophic vulnerability in enterprise AI agents occurs when three conditions coincide:
$$\text{Private Data} + \text{Untrusted Content} + \text{External Communication}$$

Heuristic output scanning (e.g., regex PII redaction) is fundamentally inadequate against adversarial LLM exfiltration because an attacker can instruct a compromised model to rephrase, steganographically encode, chunk, or leak data across token timing, DNS queries, image prompts, or innocuous-looking tool parameters (e.g., `web_search(query=base64(secret))`).

#### 4.1.1 Taint Labels and Lifecycle
Every context fragment assembled by the Context Assembler carries immutable provenance taint metadata:
- `TAINT_UNTRUSTED`: User inputs from public endpoints, scraped web pages, third-party emails, untrusted MCP tool results.
- `TAINT_CONFIDENTIAL`: Internal databases, user credentials, proprietary long-term memory, customer PII/PHI.

#### 4.1.2 Propagation Rules Through LLM Inference
1. **High-Water Mark Inheritance:** An LLM is a probabilistic black box. Any generation produced by a model whose prompt context contained `TAINT_CONFIDENTIAL` **automatically inherits `TAINT_CONFIDENTIAL`** in its entirety.
2. **Tool Parameter Inheritance:** All tool call parameters proposed by an agent whose prompt was tainted inherit the active taints of the context.
3. **No Self-Declassification:** An LLM can NEVER declassify its own output. A model claiming "I have redacted the private keys" remains fully tainted.
4. **Declassification Authority:** Declassification requires either:
   - Explicit human sign-off via an L4 approval gate, OR
   - A deterministic, cryptographic transform pipeline (e.g., certified hashing, format-preserving encryption) with proven non-invertibility.

#### 4.1.3 Dynamic Capability Interlocking
If a transaction's active context window concurrently contains **both** `TAINT_UNTRUSTED` and `TAINT_CONFIDENTIAL`:
- The transaction enters `TAINT_CONCURRENT_RESTRICTION` status.
- All tools registered with the `EGRESS_EXTERNAL` attribute (including web search, HTTP requests, webhooks, email dispatch, external ticketing, DNS lookups, and cloud storage egress) are **dynamically revoked or demoted to L4 (Mandatory Human Approval)**!
- Tool execution sandboxes have ambient network interfaces and raw socket access disabled; DNS queries from sandboxed processes are routed strictly through the Tool Proxy with egress domain filtering.

#### 4.1.4 The Realistic Security Boundary
> **Honest Architectural Boundary:** MIRAGE does NOT claim that taint tracking prevents an LLM from "thinking" about private data or restructuring text internally. MIRAGE enforces security by **structurally eliminating the exfiltration path**: even if an LLM is 100% hijacked by an indirect prompt injection, it physically cannot transmit the stolen data out of the system because all external communication channels are locked down at Gate 3.

### 4.2 Dual-Mode Identity Architecture
To prevent enterprise identity over-specification from creating fatal developer adoption friction:
1. **Developer Mode (Zero-Friction Ingress):**
   - Direct authentication via tenant API keys (`mrg_live_...`).
   - Agent identity passed via headers (`X-Mirage-Agent-ID`).
   - Internal service-to-service communication secured over private VPC networks with TLS termination at the Gateway.
2. **Zero-Trust Enterprise Mode (High-Assurance):**
   - Mutual TLS (mTLS) with short-lived SPIFFE/SPIRE workload identities.
   - Cryptographically signed JWT assertion exchanges for each cross-service and tool invocation.
   - Mandatory for regulated, multi-tenant banking and defense deployments.

---
*This document defines the security boundaries of MIRAGE 3.0. In the event of a conflict between security requirements and feature functionality, security takes precedence.*

