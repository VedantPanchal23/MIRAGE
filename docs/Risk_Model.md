# MIRAGE 3.0 — Risk Framework Specification

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document defines the MIRAGE 3.0 Risk Framework, which quantifies the potential for harm and maps it to required autonomy levels and controls.
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md) and [MIRAGE_3.0_Specification.md](MIRAGE_3.0_Specification.md).

---

## 1. Introduction

The Risk Framework is the engine that allows MIRAGE to be adaptive. By quantifying the risk of a transaction, intent, or action, MIRAGE determines whether to allow execution, require human approval, or deploy expensive verification models.

---

## 2. Risk Dimensions

Risk in MIRAGE is not a single number; it is a composite computed from multiple dimensions.

1. **Action Sensitivity:** How inherently dangerous is the tool being called? (e.g., `read_file` vs `drop_table`).
2. **Data Sensitivity:** Does the context or output contain PII, PHI, or secrets?
3. **Target Criticality:** How important is the resource being acted upon? (e.g., dev database vs production database).
4. **Blast Radius:** How many users or systems are affected by this action?
5. **Reversibility:** Can this action be easily undone? (e.g., deleting a record vs sending a public tweet).
6. **Confidence:** How certain is the model in its output?
7. **Model Reliability:** Historical performance and trustworthiness of the specific model being used.
8. **Tool Trust:** Is the MCP server internal and audited, or external and unverified?
9. **Evidence Quality:** Provenance and trustworthiness of the RAG context.
10. **Policy Sensitivity:** Does this touch heavily regulated workflows?
11. **Financial Impact:** Monetary cost of the action if it fails or succeeds.
12. **Privacy Impact:** Risk of data exfiltration.
13. **Security Impact:** Risk of privilege escalation or system compromise.
14. **Operational Impact:** Risk of system downtime.
15. **Uncertainty:** A meta-dimension representing lack of information about the other factors.

---

## 3. Risk Computation

The composite risk score is a value from 0 to 100.
While the exact mathematical weights are configurable per tenant, the canonical formula structure is:

`Composite Risk = Base Risk + Max(Severity Multipliers) + Uncertainty Penalty`

Where:
- **Base Risk:** Weighted sum of Evidence, Model, and Tool trust.
- **Severity Multipliers:** Exponential scalars based on Reversibility, Target Criticality, and Data Sensitivity. (A non-reversible action on a critical target forces the score > 80 regardless of base risk).
- **Uncertainty Penalty:** Adds artificial risk when provenance is missing.

---

## 4. Autonomy Levels (L0 - L5)

Risk scores map directly to Autonomy Levels. Agents operate under an assigned maximum autonomy level.

- **L0 — Observe Only:** 
  - *Criteria:* Read-only access. Cannot propose actions.
  - *Risk Mapping:* N/A.
- **L1 — Recommend:** 
  - *Criteria:* Can formulate plans, but cannot execute any tools. Human must take the action.
  - *Risk Mapping:* Score 0-100 (Safe because execution is manual).
- **L2 — Auto-Execute Low-Risk:** 
  - *Criteria:* Action is fully reversible, low blast radius, low financial impact.
  - *Risk Mapping:* Score 0 - 39.
- **L3 — Execute with Controls:** 
  - *Criteria:* Medium risk. Requires heavy logging, outcome verification (Gate 5), and active monitoring.
  - *Risk Mapping:* Score 40 - 69.
- **L4 — Execute with Approval:** 
  - *Criteria:* High risk, irreversible, or touches critical data. Requires explicit human or policy approval before Gate 3 execution.
  - *Risk Mapping:* Score 70 - 94.
- **L5 — Prohibited:** 
  - *Criteria:* Extreme risk, violating fundamental safety policies. Blocked entirely.
  - *Risk Mapping:* Score 95 - 100.

---

## 5. Autonomy Mapping and Escalation

When an agent attempts an action:
1. The Risk Engine computes the Action Risk Score.
2. The score is mapped to an Autonomy Level requirement (e.g., L4).
3. If the Agent's granted capability is < L4, the system triggers an **Escalation**.
4. Escalation pauses the transaction and requests human approval or triggers a higher-tier verification model to buy down the uncertainty.

---

## 6. Risk Budgets and Aggregate Blast Radius (Salami-Attack Defense)

### 6.1 The Salami-Slicing Attack Vector
An attacker or malfunctioning agent can attempt an L4 high-risk operation (e.g., transferring $10,000 or exfiltrating 5,000 records) by decomposing it into hundreds of individually low-risk L2 micro-actions (e.g., transferring $10 or deleting 1 record at a time). Because each individual action is reversible and has low blast radius, evaluating risk strictly per action would allow the aggregate attack to bypass human oversight.

### 6.2 Sliding-Window Aggregate Blast Radius Quotas
To structurally prevent salami-slicing evasion, the Risk Engine tracks cumulative metrics across rolling sliding windows (e.g., 10 minutes, 1 hour, 24 hours):
- `cumulative_records_mutated`
- `cumulative_financial_delta`
- `cumulative_external_egress_bytes`
- `cumulative_actions_count`

**Dynamic Authorization Rule:**
When authorizing any action at Gate 3, the Risk Engine evaluates:
$$\text{Effective Risk} = \max\left(\text{Instantaneous Action Risk}, \text{Cumulative Window Risk}\right)$$

Where:
$$\text{Cumulative Window Risk} = f\left(\frac{\text{Current Cumulative Usage}}{\text{Tenant Aggregate Window Quota}}\right) \times 100$$

If cumulative usage across the window exceeds the tenant's L2 ceiling (e.g., more than 50 total records modified in 1 hour), all subsequent actions—even trivial, reversible micro-actions—are **automatically escalated to L4 (Mandatory Human Approval)**!

#### 6.2.1 Defensive Parameter Extraction (Phase 3.5 Hardening)
Attackers may attempt to hide financial or record deltas by declaring `estimated_dollar_cost = 0.0` while passing large financial figures inside nested or differently named payload parameters (e.g. `{"amount": 5000}`, `{"spend": 2500}`, `{"cost": 1000}`).
The Action Governor defensively extracts financial figures directly from parameters if `estimated_dollar_cost <= 0`:
- Inspects common financial keys (`amount`, `dollar_amount`, `cost`, `spend`, `price`, `funds`) and assigns `effective_cost = max(declared_cost, extracted_parameter_amount)`.
- If the effective cost exceeds single-action limits (e.g., \$1,000) or cumulative window budgets (\$5,000/hr), the action is escalated directly to L4 human approval regardless of the agent's nominal autonomy level.


### 6.3 Hierarchical Risk Budget Scopes
Risk and blast radius quotas are enforced across an explicit 6-tier hierarchy:
1. **Per-Transaction Budget:** Caps cumulative risk points and action counts within a single end-to-end task.
2. **Per-Actor (Identity) Quota:** Limits autonomous actions triggered by a specific human or service identity across all agents within a time window.
3. **Per-Agent Quota:** Caps the autonomous activity of a specific agent identity (e.g., Customer Support Bot vs. DevOps Agent).
4. **Per-Capability Quota:** Restricts high-impact capabilities independently (e.g., `db:mutate` capped at 100 ops/hour, while `db:read` is unbounded).
5. **Per-Resource Quota:** Restricts aggregate mutations on sensitive target resources (e.g., `prod_database.users` has a strict daily mutation ceiling).
6. **Per-Tenant Aggregate Burst Cap:** Organization-wide ceiling preventing runaway systemic cost or operational disruption.

### 6.4 Concurrency and Atomic Quota Synchronization
In multi-agent or parallel tool-calling scenarios:
- Evaluating quotas sequentially in asynchronous threads would introduce race conditions where parallel calls slip under the threshold simultaneously.
- All sliding-window consumption counters are maintained in Redis sorted sets and incremented atomically via Redis Lua scripts.
- If a parallel action batch causes the projected quota to cross the threshold, the entire batch is atomically halted or escalated to L4.

---

## 7. Dynamic Risk Adjustment

Risk is not static. It updates dynamically:
- **Context Updates:** If new evidence is retrieved that contradicts earlier evidence, Uncertainty increases, driving up Risk.
- **Outcome Feedback:** If an action fails (detected in Gate 5), the risk of subsequent actions in the same plan is multiplied.
- **History:** If an agent successfully completes a specific workflow 100 times, the Model Reliability score improves, slightly lowering the base risk for future identical transactions.

---

## 8. Risk Inheritance

In multi-agent systems:
- A child agent inherits the baseline risk constraints of the parent transaction.
- If a highly trusted agent delegates to an untrusted tool, the transaction risk adopts the "high water mark" of the untrusted component.
- Risk cannot be laundered by passing data between agents.

---

## 9. Examples

### Scenario A: Drafting an Email
- **Tool:** `draft_email` (Reversible: Yes, Target: Drafts folder)
- **Data:** Public PR release notes.
- **Risk Calculation:** Low sensitivity, fully reversible. Score = 15.
- **Autonomy Required:** L2. Agent executes immediately.

### Scenario B: Dropping a Database Table
- **Tool:** `execute_sql` with `DROP TABLE users`
- **Data:** User PII schema.
- **Risk Calculation:** Critical Target, Irreversible. Severity Multiplier maxes out. Score = 92.
- **Autonomy Required:** L4. Transaction paused; approval request sent to Admin.

### Scenario C: Unverified API Call
- **Tool:** `external_weather_api`
- **Context:** Unknown provider.
- **Risk Calculation:** Uncertainty Penalty applied due to lack of provenance. Score = 45.
- **Autonomy Required:** L3. Executes with controls; Outcome Assurance heavily scrutinizes the API response before passing it to Output.
