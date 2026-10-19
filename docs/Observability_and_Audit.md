# MIRAGE 3.0 — Observability and Audit

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05

## 1. Introduction

MIRAGE 3.0 observability and audit systems ensure that every AI transaction is transparent, measurable, and cryptographically verifiable. As an AI Execution Assurance Platform, MIRAGE must prove why decisions were made, what data was used, and what outcomes occurred.

This document details the telemetry, logging, metrics, tracing, and audit components of MIRAGE 3.0.

## 2. Distributed Tracing

MIRAGE uses OpenTelemetry (OTel) for end-to-end distributed tracing.

### 2.1 Trace Structure
Every transaction begins with a root span generated at the Gateway.
- **Root Span:** AI Transaction
- **Child Spans:** Gate 1 (Input), Gate 2 (Context), Gate 3 (Action), Gate 4 (Output), Gate 5 (Outcome)
- **Sub-spans:** Risk Engine evaluation, Policy Engine evaluation, Model Router selection, Tool Execution, Verification Engine steps.

### 2.2 Trace Context Propagation
MIRAGE strictly adheres to the **W3C Trace Context** specification (`traceparent` and `tracestate` headers) to propagate correlation IDs across internal microservices, external models, and external MCP servers.

## 3. Provenance Tracking

Information lineage is tracked across all sources. Every piece of data entering the AI Transaction context must carry a provenance record.

### 3.1 Provenance Attributes
- `source_id`: Unique identifier of the origin (e.g., specific document ID, tool ID, memory node).
- `tenant_id`: Owner of the data.
- `timestamp`: Time of creation/retrieval.
- `trust_level`: Computed trust score of the source.
- `transformations`: Array of operations applied to the data before reaching context.

## 4. Structured Events

Every decision point within MIRAGE emits a structured JSON event to the Event Stream (Data Plane).

### 4.1 Event Schema Requirements
- `event_id`: UUIDv7
- `transaction_id`: UUID
- `tenant_id`: UUID
- `timestamp`: ISO-8601 UTC
- `gate_id`: Identifier of the assurance gate.
- `event_type`: Type of decision or state change.
- `payload`: Event-specific data.

## 5. Metrics

MIRAGE exposes metrics in Prometheus format via `/metrics` endpoints on all Execution Plane and Control Plane components.

### 5.1 Core Metrics Categories
- **Latency:** Histograms of transaction duration, gate duration, model inference duration, and tool execution latency.
- **Throughput:** Requests per second (RPS) per tenant, per agent, and per model.
- **Error Rates:** HTTP 4xx/5xx rates, verification failure rates, outcome failure rates.
- **Cost:** Accumulated cost per tenant, per transaction, per model (using counters and gauges).
- **Risk Scores:** Distribution of calculated risk levels (L0-L5) across intents.
- **Assurance Levels:** Distributions of overall transaction assurance scores.

## 6. Structured Logging

All logs are written as JSON objects to stdout/stderr. No unstructured text logging is permitted in production.

### 6.1 Required Log Fields
Every log entry MUST contain:
- `timestamp`: ISO-8601 UTC
- `level`: INFO, WARN, ERROR, FATAL
- `transaction_id`: W3C trace ID (if within a transaction context)
- `span_id`: W3C span ID
- `tenant_id`: Tenant ID
- `component`: Source component name (e.g., `policy_engine`, `gateway`)

## 7. Decision Logging

MIRAGE makes automated governance decisions. Every decision must be explicitly logged.

### 7.1 Policy Decision Logging
For every policy evaluation:
- **Inputs:** Agent identity, intent, capability requested, resource target, context attributes.
- **Outputs:** ALLOW, DENY, TRANSFORM, ESCALATE.
- **Rationale:** The specific policy ID and rule ID that triggered the decision.

### 7.2 Risk Decision Logging
For every risk assessment:
- **Inputs:** Action sensitivity, blast radius, trust levels.
- **Outputs:** Calculated risk score, Autonomy Level (L0-L5).
- **Dimensions:** Individual sub-scores for security, privacy, and operational risk.

### 7.3 Model Decision Logging
For every routing decision:
- **Inputs:** Required capabilities, current budget, risk level, task complexity.
- **Outputs:** Selected model provider and model version.
- **Rationale:** Why the model was chosen (e.g., "cost_optimized", "privacy_required").

## 8. Action and Outcome Logging

### 8.1 Tool Call Logging
Every external invocation must log:
- **Parameters:** Sanitized inputs passed to the tool.
- **Latency:** Wall-clock duration of the call.
- **Results:** Raw outputs (truncated/sanitized if sensitive).
- **Errors:** Stack traces or fault codes from external systems.

### 8.2 Outcome Logging
Gate 5 (Outcome Assurance) must log:
- **Preconditions:** Expected state prior to action.
- **Postconditions:** Expected state after action.
- **Actual Outcome:** Result of the reality verification check.
- **Discrepancy:** Any detected difference between expected and actual state.

## 9. Transaction Profiling

### 9.1 Cost Logging
Every transaction calculates its total cost:
- Model inference cost (input/output tokens)
- Tool invocation costs
- Verification Engine compute costs
- Total monetary cost attached to the `transaction_id`.

### 9.2 Assurance Level Logging
Each gate outputs an independent assurance score. The final transaction log records the overall assurance score and the disposition (Allowed, Blocked, Escalated, Remediated).

## 10. Audit Chain and External Cryptographic Anchoring

MIRAGE enforces an immutable, tamper-evident audit ledger across all five assurance gates.

### 10.1 Deterministic Hash Chain Construction
- Every audit record computes a canonical SHA-256 chain hash linking directly to the authoritative predecessor (`prev_hash`).
- The canonical representation sorts and serializes all fields (`entry_id`, `sequence_number`, `tenant_id`, `event_type`, `session_id`, `trace_id`, `transaction_id`, `actor_identity_id`, `decision`, `prompt_hash`, `response_hash`, `hrs_score`, `payload_digest`, `timestamp`) into compact JSON without whitespace before hashing.
- Sequence numbers are strictly monotonic integers (1, 2, 3...) scoped per tenant.
- Appends in PostgreSQL serialize under an explicit row lock (`SELECT ... FOR UPDATE` on `tenant_audit_ledgers`), preventing sequence gaps, concurrency forks, or race conditions.

### 10.2 External Notary Anchoring (`AuditAnchorBackend`)
To prevent retroactive revision even by privileged database administrators with superuser permissions, MIRAGE commits signed checkpoints outside mutable PostgreSQL rows:
- **Pluggable Architecture:** `AuditAnchorBackend` provides an abstract interface for persisting signed checkpoints.
- **Append-Only File Backend (`FileAuditAnchorBackend`):** Persists HMAC-SHA256 signed checkpoints with fsync durability on isolated filesystem storage outside database tables.
- **Truncation Detection:** If database rows are truncated or rolled back (e.g., records deleted by an intruder), the database head sequence will be less than the externally anchored sequence. MIRAGE immediately detects this discrepancy and flags `INTEGRITY_FAILURE (TRUNCATION_DETECTED)`.

### 10.3 Verification Status Hierarchy
The audit integrity endpoint evaluates both the database hash chain and external anchor synchronization:
- `ANCHORED`: Database hash chain is unbroken and matches the latest external anchor at the head sequence.
- `ANCHOR_STALE`: Database hash chain is unbroken and valid, but new events have been appended since the last committed anchor.
- `CHAIN_VALID`: Database hash chain is unbroken, but no external anchor proof has been registered yet.
- `ANCHOR_UNAVAILABLE`: External anchor backend is temporarily unreachable; verification cannot assert remote anchoring.
- `INTEGRITY_FAILURE`: Tampering detected (hash mismatch, broken prev_hash link, sequence gap, reordering, or database truncation).

## 11. Audit Queries & Export

The observability system exposes tenant-isolated endpoints:
1. `GET /v1/audit/events`: Paginated, filterable audit event queries with monotonic ordering.
2. `GET /v1/audit/integrity`: Evaluates database hash chain integrity and cross-references external anchor proof.
3. `POST /v1/audit/export-bundle`: Generates a self-contained, cryptographically signed compliance bundle with a SHA-256 bundle digest for regulatory archival.
4. `POST /v1/audit/anchor`: Administrative endpoint committing current ledger head to external anchor storage.

## 12. Five-Gate Telemetry Metrics

Prometheus metrics are collected across the five assurance gates with strictly bounded cardinality:
- `mirage_gate_decisions_total{gate, decision}`: Counter tracking gate evaluations.
- `mirage_gate_latency_seconds{gate}`: Histogram measuring execution latency per gate.
- `mirage_action_lifecycle_total{action_type, state}`: Transitions in Gate 3 and Action Governor.
- `mirage_tool_dispatch_failures_total{transport, failure_category}`: Failures in tool and MCP execution.
- `mirage_outcome_verification_total{observability_class, outcome_status}`: Gate 5 independent reality verifications.
- `mirage_audit_integrity_checks_total{status}`: Cryptographic hash chain verification outcomes.
- `mirage_security_denials_total{reason}`: Auth, API key, and tenant boundary rejections.
- `mirage_audit_anchor_status{status}`: Gauge reflecting external anchor synchronization state.

## 13. Retention Policies

- **Metrics:** 13 months (downsampled after 30 days).
- **Logs:** 30 days hot storage, 7 years cold archive.
- **Traces (Detailed):** 7 days hot storage.
- **Audit Ledger (Cryptographic):** Permanent retention (never deleted).

## 14. Export Formats

- **JSONL:** Bulk export format for logs and events, partitioned by tenant and date.
- **Compliance PDFs:** Generated reports summarizing transaction assurance and policy violations over a time period, digitally signed.
- **Sealed Compliance Evidence Bundles:** JSON-structured evidence bundles containing events, chain verification proofs, anchor signatures, and canonical SHA-256 bundle digests.

## 15. Dashboard Integration

The React 18 / JSX frontend (`AuditIntegrityView.jsx`) provides operators with:
- Live status badges reflecting audit chain integrity (`ANCHORED`, `ANCHOR_STALE`, `CHAIN_VALID`, `INTEGRITY_FAILURE`).
- Comprehensive defect lists on tamper or truncation detection.
- Interactive external anchor commitment and sealed evidence bundle exports.
- Paginated, filterable event browsers with sequence numbers, actor attribution, decisions, and SHA-256 hashes.
