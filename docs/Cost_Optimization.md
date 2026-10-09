# MIRAGE 3.0 — Cost Optimization Specification

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document defines how MIRAGE 3.0 manages resource consumption, budgets, and adaptive verification to ensure assurance does not become prohibitively expensive.
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md) and [MIRAGE_3.0_Specification.md](MIRAGE_3.0_Specification.md).

---

## 1. Core Principle

**MIRAGE must NOT become a system that blindly adds expensive model calls everywhere.** 

Adding assurance inherently adds overhead. If MIRAGE doubles the cost and latency of every AI transaction, it will fail in production. Therefore, every expensive verification step must have a measurable reason for executing, justified by risk or policy. 

**Optimization Objective:** Minimize cost and latency subject to strict reliability, security, policy, and assurance constraints.

---

## 2. Budgets

MIRAGE uses strict budgets to constrain resource consumption. A transaction fails if it exceeds its allocated budgets.

### 2.1 Verification Budget
The maximum allowed cost/latency specifically allocated to MIRAGE's internal assurance gates (Gates 1-5). It prevents the system from spending $2 to verify a $0.05 LLM call.

### 2.2 Inference Budget
Limits the number of discrete LLM calls allowed within a single transaction (preventing infinite agent loops).

### 2.3 Latency Budget
Wall-clock time limits for a transaction. Important for synchronous user-facing applications. If the latency budget is tight, MIRAGE skips statistical verification and falls back to deterministic checks.

### 2.4 Token Budget
Limits on total input and output tokens consumed across the primary models and verification models.

### 2.5 Tool-Call Budget
Limits the number of external invocations an agent can make.

### 2.6 Transaction Budget
The absolute monetary limit (e.g., "$0.50 per transaction") encompassing all models, retrievals, and tool calls.

---

## 3. Verification Escalation Ladder

To optimize cost, the Verification Engine (Gate 4) and Input Assurance (Gate 1) utilize an escalation ladder. Evaluation starts at the cheapest tier and only escalates if uncertainty or risk demands it.

1. **Tier 1: Cheap Deterministic Checks (Cost: $0.00)**
   - Regex, schema validation, allow/deny lists, exact keyword matches.
   - Example: Block request if it contains forbidden blocklist terms.
2. **Tier 2: Small Model Classification (Cost: Very Low)**
   - Fast, cheap, specialized small models (e.g., 8B parameter or BERT-based classifiers).
   - Example: Fast PII detection or toxicity classification.
3. **Tier 3: Retrieval + NLI + Statistical (Cost: Medium)**
   - The core MIRAGE 2.x stack. Qdrant retrieval + DeBERTa entailment scoring + semantic consistency sampling.
   - Triggered when output requires factual grounding.
4. **Tier 4: Larger Model Verification (Cost: High)**
   - Using a highly capable model (e.g., GPT-4o, Claude 3.5 Sonnet) as a judge.
   - Triggered only for complex reasoning verification where Tier 3 confidence is low.
5. **Tier 5: Human Approval (Cost: Extreme / High Latency)**
   - Escalate to a human.
   - Triggered for L4 Risk Autonomy or strict policy requirements.

*Rule:* Only escalate when justified. If a Tier 1 regex catches an injection attack, Gate 1 halts the transaction immediately—saving the cost of all subsequent tiers.

### 3.1 Asynchronous Speculative Assurance Pattern (Latency & Cost Defense)
Running Tier 3 verification (SCS with 5 LLM samples + DeBERTa NLI cross-encoder) synchronously adds 800ms–2,500ms of latency and increases token costs by up to 500%. Blocking user chat streams on Tier 3 is economically and operationally non-viable.

**The Speculative Streaming Protocol:**
1. **Low-Latency Release:** For interactive user sessions, generated tokens release immediately through Tier 1 (regex PII/secret scanners) with a transient header `X-Assurance-Status: SPECULATIVE`.
2. **Out-of-Band Background Verification:** Tier 3 verification jobs (RAV, NLI, SCS) are enqueued asynchronously in Celery / background workers.
3. **Out-of-Band Retraction / Remediation:** If the background verification detects severe factual contradictions or policy breaches (HRS score > 0.60):
   - MIRAGE emits an out-of-band SSE/WebSocket correction event to the client UI.
   - An incident record is written to the audit log.
   - The agent's session memory is marked with a contradiction penalty.
4. **Absolute Prohibition of Speculative Real-World Actions:** Speculative assurance applies **strictly and exclusively to user-visible informational text output**. Real-world external actions (Gate 3 $\to$ Tool Proxy $\to$ Gate 4) CAN NEVER EXECUTE SPECULATIVELY. Any action that mutates external state, initiates network egress, transfers funds, deletes records, or alters permissions MUST complete synchronous capability validation, precondition checks, and required human approvals BEFORE the tool is dispatched. Once an external side-effect occurs in a physical or external software system, it cannot be undone by an out-of-band retraction event.

---

## 4. Cost-Aware Model Routing

The Model Router dynamically selects models not just on capability, but on cost-efficiency.

- **Risk-Based Routing:** Low-risk, internal summary tasks are routed to cheap, fast models (e.g., Llama 3 8B, Haiku). High-risk, complex reasoning tasks are routed to frontier models.
- **Fallback Routing:** If a primary model experiences rate limits, the router fails over to a secondary model within the same cost tier before escalating to a more expensive tier.
- **Context Caching Awareness:** The router prioritizes endpoints that support prompt caching if the transaction uses heavy, repetitive context (like a massive system prompt or document).

---

## 5. Cost Attribution and Reporting

To provide enterprise accountability, MIRAGE meticulously tracks costs.

### 5.1 Attribution Model
Every fraction of a cent is attributed via tracing IDs to:
- **Tenant:** Who pays for this?
- **Agent:** Which AI system generated the cost?
- **Transaction:** Which specific task consumed the resources?
- **Phase:** Was the cost incurred doing the work (Agent Model) or checking the work (Verification Engine)?

### 5.2 Key Cost Metrics
Dashboards expose the following metrics:
- **Cost per Successful Transaction:** Total cost of end-to-end execution.
- **Cost per Verified Transaction:** The specific overhead added by MIRAGE gates.
- **Cost per Prevented Failure:** (Total Assurance Cost) / (Number of Critical Blocks/Remediations). This proves the ROI of MIRAGE.
- **Assurance Overhead Ratio:** (Assurance Cost) / (Primary Inference Cost). Target ratio is configurable, typically < 30%.
