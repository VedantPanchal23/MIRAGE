# MIRAGE 3.0 — Canonical Specification: AI Action Contract

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
> 
> This document defines the AI Action Contract, the governing mechanism for how AI agents interact with the real world in MIRAGE 3.0.
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md) and relates to [MIRAGE_3.0_Specification.md](MIRAGE_3.0_Specification.md).

## 1. Introduction

In MIRAGE 3.0, an AI model generating text that says "I have updated the database" is fundamentally untrusted. To actually update a database, the AI system must execute an **Action**. 

An Action is a discrete, state-changing operation in a real-world system. Because actions carry risk (Blast Radius), they cannot be invoked arbitrarily. The **AI Action Contract** is the canonical framework that defines how an action is requested, authorized, executed, and verified.

## 2. The Action Lifecycle

Every Action executes through a strict lifecycle governed by the Execution Plane, specifically Gate 3 (Action Assurance) and Gate 5 (Outcome Assurance).

`INTENT → PRECONDITIONS → AUTHORIZATION → EXECUTION → POSTCONDITIONS → OUTCOME`

1. **INTENT**: The agent proposes an action as part of its plan, providing the required parameters.
2. **PRECONDITIONS**: MIRAGE evaluates the current state of the world to ensure the action is safe and valid to attempt.
3. **AUTHORIZATION**: MIRAGE checks capabilities, evaluates policies, and requests human approval if the risk exceeds the agent's autonomy level.
4. **EXECUTION**: The tool, API, or MCP server is invoked securely via the Tool Proxy.
5. **POSTCONDITIONS**: MIRAGE observes the resulting state of the world to see what changed.
6. **OUTCOME**: MIRAGE compares the postconditions to the expected state to determine if the action succeeded, failed, or partially completed.

## 3. The Action Contract Schema

The Action Contract defines the parameters, constraints, and verification logic for a specific type of action.

### Core Identification
- `action_id`: Unique identifier for this execution instance.
- `transaction_id`: The parent AI Transaction this action belongs to.
- `tool`: The specific executable function, MCP server, or API endpoint being invoked.
- `target_resource`: The specific system or data entity being affected (e.g., `github_repo:MIRAGE/core`).

### Scope & Constraints
- `capability`: The explicit permission required (e.g., `repo:write`).
- `parameters`: The validated input arguments for the tool, sanitized against schema definitions.
- `allowed_resources`: Explicit allowlist of resource URIs this action may touch.
- `prohibited_resources`: Explicit denylist of resource URIs this action must NEVER touch.

### State Verification (The Core Contract)
- `preconditions`: Assertions that MUST evaluate to true before execution (e.g., "PR is open", "User exists").
- `expected_state_transition`: Declarative description of what should change (e.g., "PR status becomes closed").
- `postconditions`: Assertions that MUST evaluate to true after execution to consider the action a success.

### Governance
- `authorization`: Record of capability checks and policy engine evaluations.
- `approval`: If required by the Risk Engine, the audit record of who/what approved the action, and when.

### Resilience & Recovery
- `timeout`: Maximum allowed execution wall-clock time.
- `retry_policy`: Rules for retrying (e.g., max attempts, backoff) if the action is idempotent.
- `idempotency_key`: Token ensuring safe retries.
- `rollback_strategy`: Defined method to revert the action if subsequent steps fail.
- `compensation_action`: A specific alternative action to run if rollback is impossible.

### Audit
- `evidence`: Cryptographic links to the context that justified taking this action.
- `audit_record`: Immutable log of the entire contract lifecycle.

## 4. Why Tools Exist Does Not Mean Tools Execute

A core tenet of MIRAGE 3.0 is **Zero Trust for Agent Tooling**. 

Historically, AI frameworks provide an agent with a list of available tools, and if the agent decides to use one, it is executed. In MIRAGE, *an agent must not receive unrestricted tool access simply because a tool exists.*

Knowing how to format a tool call is a **skill**. Being allowed to execute it is a **capability**. The Action Contract ensures that generation of the tool call payload does not automatically result in execution. Gate 3 intercepts the payload and enforces the contract.

## 5. How Capabilities Scope the Agent

Capabilities implement the principle of Least Privilege.
- A capability binds an identity (the agent), a tool (the mechanism), and a scope (the resource).
- Instead of giving an agent the `github_tool`, MIRAGE grants the `github:issue:read` capability for `repo=MIRAGE/core`.
- If the agent attempts to use the tool to write code or access a different repository, the Action Contract authorization phase fails, blocking the action before it reaches the external system.

## 6. Preconditions: Preventing Unsafe Execution

Preconditions are executable checks that run *before* the tool is invoked.
They serve as a final sanity check against hallucinations or stale context.
- Example: Before executing `delete_user(id=123)`, a precondition checks `user_exists(123) == true` and `is_admin(123) == false`.
- If the agent hallucinates a user ID, or attempts to delete an admin, the precondition fails, saving the system from a dangerous operation and saving the budget from a wasted tool call.

## 7. Postconditions: Enabling Outcome Verification

Postconditions solve the "The model said it worked" problem.
- After `execute_payment()`, the agent might confidently generate text saying "Payment successful."
- MIRAGE ignores the agent's text. Instead, it executes the postconditions (Gate 5 - Outcome Assurance).
- Example Postcondition: `check_payment_status(txn_id) == 'SETTLED'`.
- Only if the postcondition passes does the Action Contract record a SUCCESS. This verified outcome is then fed back to the agent to inform its final Output.

## 8. Rollback and Compensation Patterns

AI plans often involve multiple interdependent actions. If Action 3 fails, the state changes from Actions 1 and 2 might need to be undone.
- **Rollback**: If an action is reversible (e.g., a database transaction, creating a draft document), the Action Contract defines the rollback command (e.g., `delete_document(id)`).
- **Compensation**: If an action is irreversible (e.g., sending an email), the contract defines a compensation action (e.g., sending a follow-up correction email).
- When an AI Transaction enters the `PARTIAL` failure state, MIRAGE automatically walks backward through the execution log, invoking the defined rollback or compensation for each completed Action Contract.

## 9. Relationship with the Risk Model

The Action Contract interfaces directly with the MIRAGE Risk Engine.
- Before execution, the Action Contract submits its `intent`, `target_resource`, and `parameters` to the Risk Engine.
- The Risk Engine calculates the **Blast Radius** (e.g., modifying production DB vs. reading a dev wiki).
- Based on the Risk Score and the Agent's **Autonomy Level**, the system determines if `approval` is required.
- A low-risk action (L2 Autonomy) executes immediately if preconditions pass.
- A high-risk action (L4 Autonomy) pauses the contract, persisting state, until a human explicitly signs off.

## 10. Cryptographic Binding and Tamper Defense (Phase 3.5 Hardening)

To prevent post-authorization parameter tampering, confused-deputy redirection, or state manipulation between Gate 3 evaluation and physical dispatch:
1. **Cryptographic Binding Hash (`contract_binding_hash`):**
   - Computed as a deterministic SHA-256 over:
     `tenant_id | transaction_id | action_id | tool_name | action_type | target_resource | parameters_hash | required_capability | estimated_dollar_cost | sorted(taint_flags)`
   - Stored on both the `ActionContract` and the `ActionApproval` record upon authorization/approval creation.
   - Verified with constant-time comparison prior to physical tool dispatch. Any tampering with target resource, action type, parameters, or capability triggers immediate termination with `ContractTamperError` (HTTP 409).
2. **Defensive Parameter Normalization:**
   - All parameters undergo Unicode NFKC normalization and recursive sanitization.
   - Path traversal defenses reject relative sequences (`..`), URL-encoded variants (`%2e%2e`, `%252e%252e`), null-byte poisonings (`\x00`, `%00`), Windows absolute drives (`C:\`), and UNC paths (`\\`).
   - URL parameter normalization canonicalizes hostnames to lowercase, strips embedded user credentials (`user:pass@`), and prevents SSRF across loopback (`127.0.0.1`), decimal representations (`2130706433`), hexadecimal representations (`0x7f000001`), octal representations (`0177.0.0.1`), IPv4-mapped IPv6 (`::ffff:127.0.0.1`), cloud metadata services (`169.254.169.254`, `metadata.google.internal`), and unapproved schemes (`file://`, `gopher://`, `dict://`).

## 11. Governed Tool Proxy & Approval Replay Defense (Phase 3.5 Hardening)

1. **Governed Tool Proxy Boundary (`GovernedToolProxy`):**
   - Direct execution or invocation bypassing MIRAGE is structurally forbidden. All external and internal tools can only be invoked through `GovernedToolProxy`.
   - The proxy strictly enforces that `contract.state == ActionState.EXECUTING`. Any invocation attempted outside this state raises `ToolProxyBypassError` (HTTP 403).
2. **Single-Use Approval & Replay Protection:**
   - Approvals transition to `ApprovalStatus.CONSUMED` upon execution. Reusing an existing approval raises `ApprovalReplayError` (HTTP 409).
   - Approval records are strictly bound to `tenant_id`, `transaction_id`, and `action_id`. Replaying an approval across transactions or actions is rejected.
   - Row-level database locks (`select(...).with_for_update()`) serialize concurrent execution attempts and prevent race conditions.
3. **Agent Self-Approval Prevention:**
   - AI agents or API client identities (`Role.API_CLIENT`) are forbidden from granting approvals.
   - An approver cannot approve an action requested by their own identity (`approval.requested_by == auth.identity_id`).
4. **Runtime Capability and Tool Revocation:**
   - Actor capabilities and tool registry active statuses are re-checked at physical execution time to defeat TOCTOU (Time-Of-Check to Time-Of-Use) vulnerabilities where permissions are revoked after authorization.

