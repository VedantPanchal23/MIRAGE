# MIRAGE 3.0 — Intelligent Model Routing

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document specifies the Model Routing architecture for MIRAGE 3.0.
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md).

---

## 1. Introduction

No single AI model is optimal for all tasks. Using a frontier model for simple text parsing is a waste of budget; using a fast, small model for complex reasoning over sensitive data introduces unacceptable risk.

MIRAGE 3.0 implements Intelligent Model Routing — a dynamic system that selects the optimal model(s) for a given transaction based on task requirements, risk assessment, cost constraints, and tenant policy.

### 1.1 Scope Boundary: Assurance-Constrained Routing vs. Commodity Gateway
MIRAGE is NOT a general-purpose token proxy, commodity load balancer, or commercial model arbitrage router. Those functions belong to commoditized infrastructure tools (such as LiteLLM, Portkey, or Cloudflare AI Gateway).

Model Routing in MIRAGE exists **strictly to enforce execution assurance and policy invariants**:
1. **Security & Privacy Boundary:** Ensuring that confidential data (PII/PHI, internal IP) routes exclusively to self-hosted, private VPC, or zero-retention compliance endpoints (e.g., Azure OpenAI with enterprise BAA).
2. **Risk-Proportional Reliability:** Enforcing that high-risk intents (L3/L4 actions) are processed exclusively by models with verified reliability indices and low conformal error rates.
3. **Assurance Overhead Minimization:** Routing low-risk tasks to lightweight models whose outputs require only Tier 1/2 deterministic checks, avoiding unnecessary verification compute.

Low-level provider connection multiplexing is delegated to standard OpenAI-compatible client libraries.

---

## 2. Routing Dimensions

The Model Router evaluates requests across multiple dimensions before selecting a model:

- **Task Complexity:** Does the task require deep reasoning, mathematical logic, or simple extraction?
- **Risk Level:** Higher risk transactions (L3/L4) require highly reliable, verifiable models.
- **Latency Requirements:** Synchronous UI interactions require fast time-to-first-token (TTFT); background async jobs can tolerate higher latency.
- **Cost Constraints:** Strict transaction or tenant budgets enforce maximum cost-per-token limits.
- **Privacy / Data Sensitivity:** Highly sensitive data (e.g., PHI) may require routing strictly to self-hosted models or zero-retention commercial endpoints.
- **Context Length:** Large documents require models with expansive context windows (e.g., 128k+).
- **Tool/Function-Calling:** Does the plan require precise JSON structured output and tool invocation capabilities?
- **Modality:** Does the input or required output involve vision, audio, or just text?
- **Reliability Requirements:** Tasks requiring high factual consistency favor models that score well on MIRAGE's internal calibration metrics.
- **Tenant Policy / Data Residency:** Geofencing requirements (e.g., "EU models only").

---

## 3. Model Capability Profiles

Every model available to MIRAGE is registered in the Model Registry with a dynamic Capability Profile.

Profiles include:
- **Class/Tier:** Frontier (e.g., GPT-4o, Claude 3.5 Sonnet), Capable (e.g., GPT-4o-mini, Claude 3 Haiku), Specialized (e.g., specialized coding models, fast extractors).
- **Cost Metrics:** Current cost per 1k input/output tokens.
- **Performance Metrics:** Expected latency, TTFT, and context window size.
- **Feature Flags:** `supports_tools`, `supports_vision`, `supports_system_prompt`, `is_zero_retention`.
- **Reliability Index:** Historical accuracy and calibration scores maintained continuously by MIRAGE's Verification Engine.

---

## 4. Routing Algorithm

The routing process occurs dynamically during the Transaction lifecycle:

1. **Constraint Collection:** The Router gathers constraints from the Policy Engine (e.g., data residency), Risk Engine (required reliability), and Context Assembler (context size).
2. **Filtering:** Models that do not meet hard constraints (e.g., missing tool support, insufficient context window, violating privacy policy) are immediately eliminated.
3. **Scoring:** The remaining models are scored based on an optimization function weighting Cost, Latency, and Reliability. The weights are determined by the Intent classification (e.g., an intent of "real-time chat" weights latency higher; "batch financial analysis" weights reliability higher).
4. **Selection:** The highest-scoring model is selected.

---

## 5. Cost-Aware and Risk-Aware Routing

**Cost-Aware Routing:**
MIRAGE tracks token and cost budgets in real-time. If a transaction approaches its budget limit, the Router will automatically downgrade to a cheaper model for subsequent planning steps, provided the cheaper model meets the minimum capability constraints. If no model fits the budget, the transaction fails safely.

**Risk-Aware Routing:**
The Risk Engine computes an initial risk score at Gate 1. 
- Low-risk tasks (e.g., summarizing public text) are routed to Tier 2/3 models.
- High-risk tasks (e.g., generating database queries, sending external emails) are exclusively routed to Frontier models (Tier 1) with proven high reliability indices.

---

## 6. Multi-Model Strategies

MIRAGE frequently utilizes multiple models within a single transaction to optimize cost and quality:

- **Draft-and-Verify:** A fast, cheap model generates an initial plan or output. A stronger, frontier model (or the Verification Engine) reviews and critiques it.
- **Decomposition:** A frontier model breaks a complex task into sub-tasks; cheaper models execute the simple sub-tasks; a frontier model synthesizes the final result.
- **Classification:** Ultra-fast models (or specialized local models) are used at Gate 1 for intent and injection classification, saving frontier models for the actual reasoning task.

---

## 7. Model Fallback and Health Monitoring

**Health Monitoring:**
The Model Registry continuously monitors model endpoints for latency spikes, error rates (5xx HTTP errors), and rate limit exhaustion (429 HTTP errors).

**Graceful Fallback:**
If the primary selected model fails or times out, the Router utilizes a fallback chain.
1. Retry with exponential backoff (for transient errors).
2. Failover to an equivalent model in the same tier (e.g., GPT-4o fails -> fallback to Claude 3.5 Sonnet).
3. If no equivalent model is available, assess whether a lower-tier model is safe to use given the risk level.
4. If no safe fallback exists, trigger a Circuit Breaker and return a governed failure to the user.

---

## 8. Model-Specific Verification

Not all models require the same level of verification overhead at Gate 4 (Output Assurance).
- Highly calibrated frontier models may require only lightweight consistency checks for low-risk tasks.
- Lower-tier models, or models prone to hallucination, require rigorous, full-stack verification (RAV, NLI, SCS) before their outputs are trusted.
- The Assurance Budget dictates how much verification compute is expended on a given model's output.

---

## 9. Routing Transparency

Routing decisions are not opaque. Every model selection is logged in the Transaction Trace, including:
- Which models were considered.
- Why models were filtered out (e.g., "Exceeded cost budget", "Policy: No public models for PII").
- The exact optimization scores for the final selection.
- Any fallback events that occurred during execution.

This ensures complete auditability of the AI Execution Plane, allowing organizations to understand precisely why a specific model was used for a specific action.
