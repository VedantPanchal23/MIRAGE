# MIRAGE 3.0 — Reality Verification Subsystem

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document defines the Reality Verifier subsystem, which implements Gate 5 (Outcome Assurance).
> Terminology is governed by [GLOSSARY.md](GLOSSARY.md).

---

## 1. Introduction

A fundamental flaw in early AI agent frameworks is treating tool execution responses as absolute truth. "The model said it sent the email" or "The API returned 200 OK" is fundamentally different from "The email was actually delivered." 

The Reality Verification subsystem (Gate 5) is responsible for confirming actual state changes in real systems, detecting discrepancies, and managing the fallout of partial failures.

## 2. Why Outcome Verification is Distinct from Output Verification

- **Output Verification (Gate 4)** asks: *Did the model generate factually consistent text?* (Hallucination detection).
- **Outcome Verification (Gate 5)** asks: *Did the real world actually change as intended?* (State verification).

An AI can perfectly generate a syntactically correct SQL `UPDATE` statement that doesn't hallucinate (passing Gate 4), but the statement might affect 0 rows because of a WHERE clause mismatch (failing Gate 5).

## 3. Architecture of the Reality Verifier

The Reality Verifier sits between the Tool Proxy (which executed the action) and the Verification Engine (which will generate the final output).

1. **Precondition Capture:** Before action execution, the verifier captures necessary baseline state.
2. **Predicted State:** The system calculates the expected post-execution state (the Action Contract).
3. **Execution Wait:** The system waits for the action to complete (handling synchronous and async patterns).
4. **Actual State Measurement:** The verifier actively queries the target system to observe the new state.
5. **Reconciliation:** Predicted state is compared to Actual state.

## 4. The Epistemic Observability Model

In real enterprise systems, state cannot always be immediately or directly measured. MIRAGE classifies target resources into four **Epistemic Observability Classes**:

1. **`OBS_DIRECT` (Synchronously Observable):**
   - The resource exposes an immediate, consistent read API (e.g., SQL `SELECT` in an ACID database, REST `GET` on a master entity).
   - *Verification Mechanism:* Direct read immediately following tool execution.
2. **`OBS_EVENTUAL` (Asynchronously Observable):**
   - The target system exhibits eventual consistency or queue propagation delay (e.g., AWS S3 object creation, Kafka consumer lag, Elasticsearch indexing, Kubernetes pod scheduling).
   - *Verification Mechanism:* Non-blocking polling with exponential backoff or background webhook callback. Outcome state transitions to `PENDING_ASYNC` until confirmed.
3. **`OBS_INFERRED` (Transport-Acknowledged Only):**
   - The sink provides an acknowledgment of message receipt, but does not provide access to recipient state (e.g., Stripe payment intent created, Jira webhook delivered, GitHub event emitted).
   - *Verification Mechanism:* Cryptographic proof of receipt / HTTP 200 payload hash.
4. **`OBS_BLIND` (Write-Only Sinks):**
   - The target system has no read API or feedback channel (e.g., fire-and-forget UDP syslog, external SMTP dispatch, unmonitored pub/sub).
   - *Verification Mechanism:* None possible at sink. Transport completion is logged; epistemic confidence is set to zero.

## 5. Preconditions, Expected State, and Actual State

Every high-risk action must be defined with an **Action Contract**:
- **Preconditions:** What must be true before execution? (e.g., User exists).
- **Predicted State:** What should be true after? (e.g., User status is 'Suspended').
- **Postconditions:** What invariants must be maintained? (e.g., Admin count > 1).

The Reality Verifier measures the **Actual State** against the predicted state and postconditions, respecting the target's Observability Class.

## 6. Discrepancy Detection and Outcome Qualification

Rather than a naive binary pass/fail, Outcome Assurance outputs an **Outcome Tuple**:
$$\text{Outcome} = \left(\text{OutcomeStatus}, \text{EpistemicConfidence}\right)$$

### 6.1 Canonical Outcome Statuses
Every outcome evaluation returns an immutable tuple `(OutcomeStatus, EpistemicConfidence)` using the following 7 canonical statuses:

1. **`SUCCESS_CONFIRMED`:**
   - Postconditions directly verified in the target state via synchronous read API or SQL query (`OBS_DIRECT`).
   - Epistemic Confidence: High ($0.95 - 1.00$).
2. **`SUCCESS_EVENTUALLY_OBSERVED`:**
   - State transition confirmed after background polling or webhook callback (`OBS_EVENTUAL`).
   - Epistemic Confidence: High ($0.90 - 1.00$).
3. **`ACKNOWLEDGED_UNVERIFIED`:**
   - Transport acknowledged success (HTTP 200/202, queue ACK, payment intent created), but postconditions cannot be directly inspected by MIRAGE at the sink (`OBS_INFERRED`).
   - Epistemic Confidence: Moderate ($0.40 - 0.60$).
4. **`FAILED`:**
   - Tool returned an error, or verified target state confirms the requested state mutation was rejected or aborted.
   - Epistemic Confidence: High ($0.90 - 1.00$).
5. **`PARTIAL`:**
   - In a multi-step action or batch, some sub-operations succeeded while others failed (e.g., database record created, but notification dispatch failed).
   - Epistemic Confidence: High ($0.90 - 1.00$).
6. **`UNKNOWN`:**
   - Network timeout, ambiguous error, or transient verification probe failure during reconciliation.
   - Epistemic Confidence: Zero ($0.00$). Triggers circuit breaker or human reconciliation.
7. **`UNOBSERVABLE`:**
   - Action targeted a write-only sink (`OBS_BLIND`) where no feedback loop or read API exists (e.g., fire-and-forget UDP syslog, unmonitored external email).
   - Epistemic Confidence: Zero ($0.00$).

### 6.2 The Fundamental Epistemic Invariant
> **NON-NEGOTIABLE RULE:** MIRAGE must NEVER represent an unobservable (`UNOBSERVABLE`), ambiguous (`UNKNOWN`), or merely transport-acknowledged (`ACKNOWLEDGED_UNVERIFIED`) action as confirmed real-world success (`SUCCESS_CONFIRMED` or `SUCCESS_EVENTUALLY_OBSERVED`).

Any attempt by a model to claim "The record has been updated and verified" when the outcome status is `ACKNOWLEDGED_UNVERIFIED` or `UNOBSERVABLE` is treated as a factual contradiction in Gate 5 (Output Assurance) and rewritten or flagged.

## 7. Rollback and Compensation Strategies

If an outcome is classified as a failure or partial success, MIRAGE must remediate:
- **Transactional Rollback:** For systems supporting ACID transactions, issue a `ROLLBACK`.
- **Compensating Actions:** For distributed systems, issue a logical undo (e.g., if `CREATE` succeeded but setup failed, issue `DELETE`).
- **Human Escalation:** If rollback is impossible or fails, pause the AI Transaction, alert an administrator, and wait for human resolution.

## 8. Retry Semantics

Retries are managed by the Reality Verifier, not the LLM. 
- Retries are only attempted if the Action Contract defines the action as **Idempotent**.
- Non-idempotent actions are never automatically retried upon timeout or partial failure without confirming state first.

## 9. Integration with the AI Transaction Model

The result of the Reality Verifier is appended to the AI Transaction trace.
- If Gate 5 detects a failure, the Assurance Score is updated.
- The Failure Context is passed to Gate 4 (Output Assurance).
## 10. Implementation & Runtime Architecture (Phase 5)

Phase 5 delivers the production runtime implementation of the Reality Verification subsystem:

### 10.1 Pluggable Verifier Adapters
The subsystem implements a modular, pluggable architecture via `BaseOutcomeAdapter`:
- **`DatabaseStateAdapter` (`OutcomeVerifierType.DATABASE`):** Performs deterministic, read-only SQL queries (`SELECT`) against target relational/ACID data stores. Verifies row presence, expected column values, and affected row counts under strict read-only guarantees.
- **`HttpResourceAdapter` (`OutcomeVerifierType.HTTP_RESOURCE`):** Inspects REST APIs, webhooks, and cloud control planes. Features deep SSRF defenses: DNS resolution inspection, blocking private/loopback/link-local IPv4 & IPv6, decimal/hex IP obfuscation, cloud metadata IP addresses (`169.254.169.254`), and local hostname resolution rejection (`localhost`, `*.internal`, `*.local`).
- **`AsyncEventAdapter` (`OutcomeVerifierType.ASYNC_EVENT`):** Verifies eventually consistent distributed states (`OBS_EVENTUAL`). Implements exponential backoff polling (jittered) with configurable poll counts, timeout limits, and state matching against message queues or log streams.
- **`SimulatedTestAdapter` (`OutcomeVerifierType.SIMULATED`):** Deterministic mock adapter for testbeds and CI/CD pipelines. Explicitly flagged as `is_simulated=True` with mandatory provenance disclosures to prevent mock tests from masquerading as physical verification evidence.

### 10.2 Cryptographic Verification Hash & Audit Ledger
Every completed verification contract computes an immutable SHA-256 fingerprint:
$$\text{hash} = \text{SHA-256}\left(\text{tenant\_id} \mathbin{\Vert} \text{transaction\_id} \mathbin{\Vert} \text{action\_id} \mathbin{\Vert} \text{status} \mathbin{\Vert} \text{confidence} \mathbin{\Vert} \text{observed\_bytes}\right)$$
This hash is appended to the tenant's cryptographic `AuditLogRecord` hash chain, guaranteeing tamper-evident auditability across regulatory audits (EU AI Act, SOC2, HIPAA).

### 10.3 Output ↔ Outcome Consistency Reconciliation
The reconciler (`reconcile_output_with_outcome`) bridges Gate 4 Output Assurance with Gate 5 Outcome Assurance:
- Flags any AI agent output that claims physical state mutation success when the underlying action is merely transport-acknowledged (`ACKNOWLEDGED_UNVERIFIED`), unobservable (`UNOBSERVABLE`), or timed out (`UNKNOWN`).
- Dispositions non-compliant outputs to `REWRITE_WITH_CAVEAT` or `BLOCK`, neutralizing epistemic overconfidence before final release.

### 10.4 REST Endpoints & Multi-Tenant Storage
- `POST /v1/outcomes/verify`: Submits an action for postcondition reality verification.
- `GET /v1/outcomes/{outcome_id}`: Retrieves outcome verification contract by ID under tenant isolation.
- `GET /v1/outcomes/transaction/{transaction_id}`: Fetches all outcome contracts for a transaction.
- `POST /v1/outcomes/reconcile`: Epistemic consistency reconciliation between model text and outcome state.
- **PostgreSQL RLS:** Managed by Alembic migration `009_gate5_outcome_assurance.py`, isolating records per `tenant_id`.

## 11. Reality Verification Red-Team & Integrity Hardening (Phase 5.5)

Phase 5.5 executes a comprehensive adversarial red-team audit and integrity hardening across all reality verification execution paths:

### 11.1 Monotonic Outcome State Machine
State transitions for an `OutcomeVerificationRecord` are governed by `VALID_OUTCOME_TRANSITIONS`. Terminal states cannot be silently overwritten or downgraded:
- `SUCCESS_CONFIRMED` can only transition to `SUCCESS_CONFIRMED`.
- `FAILED` can only transition to `FAILED`.
- `ACKNOWLEDGED_UNVERIFIED` can transition to `SUCCESS_CONFIRMED`, `FAILED`, or `PARTIAL` when deeper evidence is obtained, but never to `UNKNOWN`.
- `UNKNOWN` can transition to terminal outcomes as eventual probes resolve.
Any invalid transition raises an HTTP 409 Conflict error.

### 11.2 Canonical Cryptographic Serialization & Chaining
To eliminate JSON serialization ambiguities and delimiter collision attacks, outcome hashes use canonical sorted JSON:
```json
{
  "schema_version": "mirage.outcome.v1",
  "tenant_id": "<tenant>",
  "transaction_id": "<txn>",
  "action_id": "<act>",
  "outcome_status": "<status>",
  "epistemic_confidence": 1.0,
  "observability_class": "OBS_DIRECT",
  "verifier_adapter": "DatabaseStateAdapter",
  "observed_state_hash": "<sha256>",
  "verified_at": "<iso_timestamp>",
  "contract_binding_hash": "<sha256>"
}
```
This payload is hashed with SHA-256 and chained into the tenant's `AuditLogRecord` ledger with previous hash chaining.

### 11.3 Action Contract Execution State Invariant
Verification probes may only be dispatched for `ActionContract` entities in `COMPLETED`, `EXECUTING`, or `EXECUTED` states. Attempting to verify unexecuted actions (`PROPOSED`, `AWAITING_APPROVAL`, `BLOCKED`) is strictly rejected with HTTP 409 Conflict.

### 11.4 Target Resource & Environment Binding
Every verification probe is mathematically bound to the authorized `ActionContract.target_resource` and `blast_radius.target_environment`:
- Database table names must match the authorized table identifier parsed from the target URI or normalized parameters.
- HTTP target hosts must match the authorized host in `ActionContract.target_resource`.
- Probes requesting non-matching environments are rejected with HTTP 400 Bad Request.
- `SimulatedTestAdapter` is prohibited for production environments (`PROD`).

### 11.5 Advanced Adapter Defenses
- **Anti-SSRF & Redirect Protection:** In `HttpResourceAdapter`, redirect responses (`301`/`302`/`307`/`308`) are inspected with `follow_redirects=False`. The redirect target host undergoes full DNS resolution inspection and is validated against private/loopback/link-local IPv4/IPv6, cloud metadata (`169.254.169.254`), and local domains.
- **SQL Injection Defense:** In `DatabaseStateAdapter`, table identifiers are validated against strict regex (`^[a-zA-Z_][a-zA-Z0-9_]*$`). Queries execute under `SET TRANSACTION READ ONLY` with parameterized bindings for record keys.
- **Bounded Eventual Consistency:** In `AsyncEventAdapter`, polling iterations and timeouts are bounded (max 30 attempts, 60s max timeout). Unresolved polling strictly yields `UNKNOWN` with confidence 0.0.

### 11.6 Compensating Action Governance
Gate 5 is strictly a verification and reconciliation boundary. Calling `propose_compensating_action` on the reality verifier raises `NotImplementedError` directing all remediation and rollback actions strictly through Gate 3 (`ActionGovernorService`).

### 11.7 Dedicated Adversarial Hardening Suite
A dedicated 30-vector adversarial test suite (`tests/security/test_phase5_5_hardening.py`) verifies all 30 attack vectors with 100% pass rate. Full repository regression suite achieves 511/511 passing tests.

---
*End of Document*

