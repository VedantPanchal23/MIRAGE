# MIRAGE 3.0 — Policy Engine Specification

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document governs the Policy Engine in MIRAGE 3.0, the core subsystem that evaluates declarative policies against transaction context to produce deterministic allow/deny/transform/escalate decisions.
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md) and [MIRAGE_3.0_Specification.md](MIRAGE_3.0_Specification.md).

---

## 1. Introduction

The Policy Engine is a critical component of the MIRAGE 3.0 Control Plane and Execution Plane. It provides a declarative mechanism to constrain behavior across all Five Assurance Gates. Policies dictate what an agent can do, what data it can access, what models it can use, and when human approval is required.

---

## 2. Policy Model

### 2.1 What is a Policy?
A Policy in MIRAGE is a declarative rule or set of rules that constrains AI system behavior based on context. Policies are not hardcoded logic; they are dynamically evaluated data structures that enforce governance at runtime. 

### 2.2 Policy Structure
Every policy contains the following canonical elements:
- **Metadata:** ID, name, description, author, version, timestamps.
- **Scope:** The entities the policy applies to (e.g., global, tenant-specific, agent-specific).
- **Conditions:** Boolean expressions evaluated against transaction context, risk scores, budget state, identity, and environmental variables.
- **Actions:** The enforcement result when conditions are met. Allowed actions are: `ALLOW`, `DENY`, `TRANSFORM` (modify the payload/request), `ESCALATE` (require higher assurance or human approval).
- **Fail-Safe Mode:** `FAIL_OPEN` or `FAIL_CLOSED`. Defines behavior if the policy engine crashes or fails to evaluate.

---

## 3. Policy Types

MIRAGE 3.0 supports the following specialized policy types:

### 3.1 Tenant Policy
Applies to all transactions within a specific tenant boundary. Enforces broad organizational rules (e.g., "All tenant data must remain in EU regions").

### 3.2 Organization Policy
Applies across multiple tenants within a single enterprise deployment. Useful for global compliance mandates.

### 3.3 Agent Policy
Scoped to a specific AI Agent. Restricts what that agent is permitted to do, independent of the user invoking it.

### 3.4 Capability Policy
Defines the preconditions and constraints for invoking a specific tool or resource. (e.g., "The `drop_database` capability requires L4 Autonomy").

### 3.5 Data Policy
Governs access to and generation of specific data classifications (e.g., "Mask PII in all Output Assurance gates").

### 3.6 Model Policy
Restricts which models can be used for which tasks (e.g., "Do not route PHI to external public models").

### 3.7 Cost Policy
Defines budget enforcement rules (e.g., "If transaction cost > $1.00, require approval").

### 3.8 Risk Policy
Maps Risk Engine scores to necessary controls (e.g., "If Action Risk > 80, Escalate to human").

### 3.9 Geographic Policy
Enforces data sovereignty by restricting where models run or data is stored.

### 3.10 Approval Policy
Defines the workflow and quorum required for L4 actions.

### 3.11 Emergency Controls
Kill switches and immediate suspension policies that bypass standard hierarchy for instant threat mitigation.

---

## 4. Policy Hierarchy and Precedence

Policies often overlap. MIRAGE resolves conflicts using a strict hierarchy.

### 4.1 Evaluation Hierarchy
1. **System (Global)** - Immutable baseline policies.
2. **Organization** - Cross-tenant governance.
3. **Tenant** - Tenant-wide rules.
4. **Agent** - Agent-specific rules.
5. **Session/Transaction** - Ephemeral constraints.

### 4.2 Conflict Resolution
When policies conflict:
- **For Security/Risk/Access:** The *most restrictive* policy wins. An explicit DENY at any level overrides an ALLOW at all other levels.
- **For Capabilities:** The *most permissive* policy with explicit override authority wins.
- **Default Stance:** Default-deny. Every consequential action must be explicitly permitted by a capability policy.

---

## 5. Deny/Allow Semantics

MIRAGE follows a **Default-Deny with Explicit Allow** paradigm.
- An action is blocked unless a capability or policy explicitly permits it.
- A `DENY` decision short-circuits evaluation.
- An `ESCALATE` decision overrides an `ALLOW` but is overridden by a `DENY`.

---

## 6. Policy Evaluation

### 6.1 Determinism
Policy evaluation in MIRAGE MUST be deterministic. Given the exact same context (identity, intent, risk score, budgets, time), the Policy Engine must return the same result. The Policy Engine does *not* call LLMs; it relies on structured data provided by earlier pipeline stages (e.g., intent classifier).

### 6.2 Fail-Open vs Fail-Closed
Every critical decision class must explicitly define its fail-safe behavior:
- **Authentication/Identity:** Fail-closed.
- **Capability/Authorization (Gate 3):** Fail-closed.
- **Cost/Budget:** Fail-closed (with grace period options).
- **Data Privacy (PII Masking):** Fail-closed.
- **Context Assurance (Gate 2):** Fail-open (warn user but proceed), unless strictly configured otherwise.
- **Output Factual Consistency (Gate 4):** Fail-open (flag as low confidence), unless strictly configured otherwise.

---

## 7. Emergency Controls

The Policy Engine includes emergency override mechanisms:
- **Kill Switches:** Global or tenant-level flags that immediately halt all active agents and transactions.
- **Tenant Suspension:** Instantly blocks all ingress for a specific tenant without deleting their configuration.
- **Global Throttle:** Imposes immediate, drastic rate limits across the platform during severe resource contention or active attacks.

---

## 8. Policy Versioning and Testing

### 8.1 Versioning
Policies are immutable once published. Updates create a new semantic version (e.g., v1.1.0). Transactions capture the exact policy version hash used in their evaluation for perfect auditability.
Rollbacks are executed by updating the active pointer to a previous version.

### 8.2 Testing
Policies must be validated before deployment. The Policy Engine provides a "dry-run" mode where proposed policies are evaluated against historical transaction traces to assess impact without affecting live traffic (Shadow Mode).

---

## 9. Policy Language (Open Decision)

> **Architectural Decision Pending:** The syntax of the Policy Engine is currently under review. 

Potential candidates:
1. **OPA/Rego:** Industry standard, highly expressive, steep learning curve.
2. **Cedar (AWS):** Purpose-built for RBAC/ABAC, highly performant, simpler syntax than Rego.
3. **Custom DSL:** JSON/YAML based, natively integrated with MIRAGE primitives.

Regardless of the final syntax chosen, the semantics defined in this document (hierarchy, determinism, fail-closed defaults) must be supported.

---

## 10. Examples

### 10.1 PII Masking Policy (Data Policy)
```json
{
  "id": "pol_data_mask_pii",
  "type": "DATA_POLICY",
  "scope": "tenant:acme_corp",
  "conditions": {
    "intent.contains_pii": true
  },
  "action": "TRANSFORM",
  "transformation": "mask_entities",
  "fail_safe": "FAIL_CLOSED"
}
```

### 10.2 High-Risk Action Escalation (Risk Policy)
```json
{
  "id": "pol_risk_escalate_l4",
  "type": "RISK_POLICY",
  "scope": "global",
  "conditions": {
    "transaction.risk_score": { ">=": 80 },
    "action.is_reversible": false
  },
  "action": "ESCALATE",
  "escalation_target": "role:admin",
  "fail_safe": "FAIL_CLOSED"
}
```
