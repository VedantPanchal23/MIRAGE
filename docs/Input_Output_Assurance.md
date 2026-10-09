# MIRAGE 3.0 — The Five Assurance Gates

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document defines the Five Assurance Gates that form the core of the MIRAGE 3.0 Execution Assurance Platform.
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md).

---

## 1. Introduction

The Five Assurance Gates provide comprehensive lifecycle governance for AI systems. They ensure that every interaction—from the moment an input is received until the real-world outcome is confirmed—is subjected to inspection, validation, and policy enforcement proportional to its risk.

The canonical AI Transaction lifecycle routes through these Five Assurance Gates:
1. **Input Assurance** (`input_assurance`): Pre-execution boundary (Identity, Injection, Intent, Taint Seeding)
2. **Context Assurance** (`context_assurance`): Retrieval & Assembly boundary (Provenance, Freshness, Taint Tracking)
3. **Action Assurance** (`action_assurance`): Pre-action boundary within the Turn Loop (Capabilities, Parameter Schemas, Aggregate Blast Radius, IFC Interlocking)
4. **Outcome Assurance** (`outcome_assurance`): Post-action Reality Verification within the Turn Loop (Epistemic Observability, State Reconciliation)
5. **Output Assurance** (`output_assurance`): Post-execution response boundary (Verification Engine: RAV, NLI, SCS, ICS, VGS, HRS)

*Note: In the agentic Turn Loop, Action Assurance and Outcome Assurance cycle iteratively for each intermediate tool invocation before Output Assurance evaluates the final response.*

---

## 2. Gate 1 — Input Assurance

### 2.1 Purpose
Input Assurance inspects the initial request before any model inference occurs. It establishes identity, determines intent, and prevents malicious or non-compliant inputs from engaging the AI system.

### 2.2 Inputs Evaluated
- User or system prompts
- API request payloads
- System messages
- Extracted metadata (IP, authentication tokens)

### 2.3 Checks Performed
- **Identity & Authentication:** Verifies the cryptographic identity of the requester.
- **Authorization & Tenant Boundary:** Ensures the actor is authorized within the specified tenant.
- **Intent Classification:** Infers the purpose and scope of the request.
- **Prompt Injection & Malicious Instructions:** Scans for jailbreaks, prompt injection, and adversarial patterns.
- **Sensitive Data Detection:** Scans for PII, PHI, credentials, and secrets.
- **Policy Violations & Abuse:** Checks against predefined acceptable use policies.
- **Cost Implications & Risk:** Calculates initial risk score and verifies token/cost budgets.

### 2.4 Decision Space
Gate 1 can produce the following deterministic outcomes:
- `ALLOW`: Input is safe and compliant; proceed to Gate 2.
- `TRANSFORM`: Input is structurally modified to comply (e.g., standardizing format).
- `SANITIZE`: Sensitive data or malicious payloads are redacted/removed.
- `ROUTE`: Input intent dictates routing to a specific model or workflow.
- `REQUIRE_APPROVAL`: Input touches high-risk topics requiring human clearance.
- `BLOCK`: Input violates policy or poses unacceptable risk. Transaction terminates.

### 2.5 Failure Modes & Bypass Conditions
- **Failure Mode:** A novel jailbreak evades detection; sensitive data is misclassified.
- **Bypass:** Emergency break-glass access by a tenant administrator (logged heavily).
- **Relationship:** Gate 1 establishes the baseline Intent and Identity used by Gates 2 and 3.

---

## 3. Gate 2 — Context Assurance

### 3.1 Purpose
Context Assurance evaluates the information assembled for the model. It ensures that memory, retrieved evidence, and tool states are trustworthy, fresh, and free from poisoning.

### 3.2 Context Sources Evaluated
- RAG (Retrieval-Augmented Generation) evidence
- Governed Memory
- Tool and MCP server results
- Environmental state

### 3.3 Checks Performed
- **Provenance & Freshness:** Verifies the origin and age of each context item.
- **Trust Scoring:** Assesses the credibility of the context source.
- **Poisoning Detection:** Scans for context manipulation or injected adversarial payloads.
- **Instruction/Data Separation:** Ensures retrieved context cannot be interpreted as a system instruction (mitigating indirect prompt injection).
- **Tenant Boundaries:** Re-verifies that all context belongs to the authorized tenant.
- **Sensitive Information:** Redacts secrets or PII that shouldn't be exposed to the model.
- **Conflicting Evidence:** Detects contradictions across retrieved documents or memory items.

### 3.4 Evaluation and Scoring
Each context item is assigned a **Context Trust Score**. Items below the threshold are discarded or flagged. The combined context is constrained by the model's context window and the transaction's verification budget.

### 3.5 Failure Modes
- **Failure Mode:** Stale memory overrides factual retrieval; subtle indirect prompt injection succeeds.
- **Relationship:** Provides the verified grounding material for the plan (Gate 3) and output generation (Gate 4).

---

## 4. Gate 3 — Action Assurance

### 4.1 Purpose
Action Assurance governs the AI's intent to interact with the real world. It authorizes plans and tool invocations before execution, enforcing least privilege and capability bounds.

### 4.2 Inputs Evaluated
- Agent-proposed plan
- Requested tool or MCP invocation
- Parameters and payload
- Target resources

### 4.3 Checks Performed
- **Capability Authorization:** Verifies the agent holds the specific capability to invoke the tool on the target resource.
- **Actor Identity:** Confirms the agent's identity and autonomy level.
- **Parameter Validation:** Ensures tool arguments match schema and policy constraints.
- **Blast Radius & Risk:** Quantifies the potential impact if the action fails or acts maliciously.
- **Cost & Budgeting:** Verifies sufficient budget for the external invocation.
- **Preconditions:** Checks if required system states are met before execution.

### 4.4 Authorization and Approval Workflow
1. **Autonomy Check:** Does the action's risk exceed the agent's assigned Autonomy Level (L0-L5)?
2. **Policy Evaluation:** The Policy Engine evaluates declarative rules.
3. **Escalation:** If risk > autonomy, the state becomes `REQUIRE_APPROVAL`.
4. **Approval Workflow:** A request is routed to a human or delegated policy authority. The transaction pauses until explicitly approved or rejected.

### 4.5 Failure Modes
- **Failure Mode:** Confused deputy attack where an agent misuses its capability; approval fatigue leading to rubber-stamping.
- **Relationship:** Gate 3 ensures nothing harmful happens. If Gate 3 passes, Gate 5 will verify the result.

---

## 5. Gate 4 — Output Assurance

### 5.1 Purpose
Output Assurance evaluates AI-generated output after model and tool execution, but strictly before the output is accepted as trustworthy or released to the user or downstream systems. It evaluates the epistemic, safety, policy, evidence, consistency, and integrity properties of the output itself. It complements—and does NOT replace—Gate 3 Action Assurance or Gate 5 Reality Verification.

### 5.2 Inputs Evaluated
- Generated model completion (text, code, structured payload)
- Parent `AITransaction` context, turn state, and DIFC taint flags (`taint_flags`)
- Associated `ActionContract` states and parameters (Gate 3 execution history)
- Retrieved RAG evidence chunks and knowledge base active document generations
- Verification budget parameters (`max_latency_ms`, `max_tokens`, `max_cost_usd`, `max_tier`)

### 5.3 Adaptive Verification Escalation Ladder
Output Assurance operates on a cost-optimized, latency-bounded escalation ladder:
1. **Tier 1 — Cheap Deterministic Scanner (0 ms latency, $0.00 cost):**
   - **Unicode Normalization & Anti-Obfuscation:** Applies NFKC normalization and strips zero-width spaces/joiners (`\u200b`, `\u200c`, `\u200d`, `\ufeff`) and control bytes to defeat token-splitting evasions before regex scanning.
   - **Comprehensive DLP Secret Scanning:** High-speed regex scanning detecting AWS access keys (`AKIA/ASIA/AROA`), GitHub personal access tokens (`ghp_`), Slack bot/user tokens (`xoxb-/xoxp-`), Bearer tokens, database credentials, passwords, cryptographic private keys (`-----BEGIN PRIVATE KEY-----`), and PII (SSN, email, phone, IP). Provides deterministic redaction (`[REDACTED_SECRET]`, `[REDACTED_PII]`) and hard-blocks raw secrets.
   - **Prompt Injection & Jailbreak Control Tokens:** Detects and blocks raw prompt injection delimiters and jailbreak tokens (`<|im_start|>`, `<|endoftext|>`, `[INST]`, `[SYSTEM]`, `DAN mode`).
2. **Tier 2 — Lightweight Classifier (<20 ms latency, <$0.0001 cost):** Fast intent and proposition categorization (differentiates factual claims from opinions/greetings).
3. **Tier 3 — Retrieval-Augmented NLI & Meta-Learner (<150 ms latency, ~$0.0015 cost):**
   - **Atomic Claim Decomposition:** Flan-T5 extracts discrete propositions with span tracking and taxonomy typing (`FACTUAL`, `TEMPORAL`, `CAUSAL`, `COMPARATIVE`, `OPINION`).
   - **Stale Evidence Defense:** Validates retrieved evidence against active knowledge base generations (`generation < active_generation` rejected).
   - **Indirect Instruction Neutralization:** Escapes `<trusted_instructions>` in retrieved evidence to prevent passive RAG payloads from overriding policy.
   - **Multi-Signal Synthesis:** Gathers Retrieval-Augmented Verification (`s_rav`), Self-Consistency Entropy (`s_scs`), Natural Language Inference (`s_nli`), and Internal Consistency (`s_ics`).
   - **HRS Meta-Learner:** LightGBM synthesizes signals into the calibrated Holistic Reliability Score (`HRS`).
4. **Tier 4 — Frontier Multimodal Judge (On-Demand):** Evaluates visual grounding (VGS) for multimodal inputs.
5. **Tier 5 — Human-in-the-Loop Review:** Triggered for critical risk, unresolvable contradictions, or sensitive policy overrides. Outputs requiring human review are categorized as `PARTIALLY_VERIFIED`.

### 5.4 Uncertainty Calibration & Conformal Prediction
- **Isotonic Regression:** Calibrates raw scores ensuring empirical probabilities align with true error rates (Expected Calibration Error $\text{ECE} < 0.05$).
- **Mondrian Conformal Prediction:** Computes non-parametric, finite-sample valid 95% coverage prediction intervals $[\text{lower}, \text{upper}]$ for every claim and composite score.
- **Conformal Uncertainty Escalation:** If the conformal interval upper bound indicates elevated risk ($\text{upper} \ge 0.85$), Gate 4 escalates the decision to `REQUIRE_HUMAN_REVIEW` with status `PARTIALLY_VERIFIED`, preventing high-uncertainty outputs from being released as fully trusted.
- **Explainability:** TreeSHAP computes Shapley attribution across individual verifier signals.
- **Scientific Integrity & Empirical Certification Disclosure:** Analytical conformal intervals derived under exchangeability are explicitly marked with `is_certified=False` and `certification_status="NOT_SCIENTIFICALLY_CERTIFIED"` until empirical coverage is certified on held-out benchmark splits (e.g., HaluEval, FActScore).

### 5.5 Postcondition Honesty & DIFC Dangerous Triad
- **Postcondition Honesty Check:** Rejects responses asserting real-world action execution (in active or passive voice, e.g., "sent", "transferred", "deleted", "paid", "updated") if associated `ActionContract` instances remain in `PROPOSED`, `AWAITING_APPROVAL`, or `BLOCKED` states, or if zero action contracts exist for the transaction. Violations trigger an immediate hard `BLOCK`. Output assurance never claims real-world state changes without Gate 5 confirmation.
- **Dangerous Triad Interlock:** Blocks confidential disclosures when `TAINT_UNTRUSTED` and `TAINT_CONFIDENTIAL` co-exist in transaction context.
- **Transaction State Machine Invariant:** An `AITransaction` cannot transition to `COMPLETED` unless a verified Gate 4 `OutputAssuranceRecord` exists (when required by policy). If Gate 4 output assurance is missing, or if the latest assurance decision was `BLOCK` or `REQUIRE_HUMAN_REVIEW`, transition is rejected with HTTP 409 Conflict.

### 5.6 Verification Budgets & Graceful Degradation
- If latency, token, or financial budgets are exhausted, Gate 4 gracefully emits status `DEGRADED` with decision `ALLOW_WITH_UNCERTAINTY` (with elevated conformal uncertainty intervals) rather than fabricating false certainty.

### 5.7 Autonomous LangGraph Self-Correction Loop
- Claims flagged as `CONTRADICTED` trigger the bounded LangGraph StateGraph self-correction loop (maximum $K=2$ retries).
- Rewritten propositions must pass re-verification before release.

### 5.8 Authoritative Persistence & Audit Chaining
- Verified outputs persist to `OutputAssuranceRecord` under PostgreSQL Row-Level Security (RLS).
- SHA-256 output fingerprints cryptographically chain into the immutable `AuditLogRecord` ledger.

### 5.9 Runtime Egress Hardening (Proxy & Streaming)
- **OpenAI-Compatible Proxy (`/v1/chat/completions`):** Enforces Tier 1 DLP scanning on model responses, redacts detected secrets, and injects honest verification headers (`X-Mirage-Verified: true` only when $\text{HRS} < 0.20$, zero contradictions, and DLP clean) and safety headers (`X-Mirage-Safety-Safe`).
- **WebSocket Streaming (`/v1/stream/transactions`):** Runs DLP scanning on final chunks and includes honest `verification_status` and `safety` results in the `verification_complete` terminal stream event.

---

## 6. Gate 5 — Outcome Assurance (Reality Verification)

### 6.1 Purpose
Outcome Assurance verifies that an action authorized in Action Assurance actually produced the intended state change in the real world. It explicitly distinguishes between "The model said it succeeded" and "The real system confirms it succeeded."

### 6.2 Inputs Evaluated
- The authorized action and parameters (from Action Assurance)
- The expected postconditions and target Observability Class (`OBS_DIRECT`, `OBS_EVENTUAL`, `OBS_INFERRED`, `OBS_BLIND`)
- Actual system state measured after execution

### 6.3 Checks Performed
- **Epistemic State Verification:** Did the requested change occur within observable limits?
- **Postconditions:** Are the required constraints and domain invariants satisfied?
- **Side Effect Detection:** Did unauthorized mutations occur beyond the declared blast radius?
- **Outcome Qualification:** Emits an outcome tuple `(OutcomeStatus, EpistemicConfidence)`:
  - `CONFIRMED_SUCCESS` (directly verified via read back)
  - `UNVERIFIABLE_ACKNOWLEDGED` (acknowledged by sink without read API)
  - `PENDING_ASYNC` (asynchronous propagation underway)
  - `DISCREPANCY_DETECTED` (silent failure: model claimed success, system contradicts)
  - `CONFIRMED_FAILURE` (loud failure: tool error)
- **Rollback / Compensation:** Triggers compensatory actions if the outcome is a partial failure.

### 6.4 Failure Modes & Invariants
- **Failure Mode:** Eventual consistency lag incorrectly flagged as a discrepancy; target system lacks read permissions.
- **Invariant:** MIRAGE will never emit `CONFIRMED_SUCCESS` for write-only (`OBS_BLIND`) endpoints.
- **Relationship:** Feeds directly into the dynamic context for the next agent turn or the final Output Assurance gate. If Outcome Assurance detects a discrepancy, the agent is forced to report the actual state.

---
*End of Document*
