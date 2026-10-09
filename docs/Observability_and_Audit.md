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

## 10. Audit Chain

MIRAGE preserves the cryptographic audit chain from MIRAGE 2.x for tamper-evident compliance.

### 10.1 Mechanism
- Every transaction produces a final canonical JSON summary.
- The summary is hashed using SHA-256.
- Each hash includes the hash of the preceding transaction within the tenant, forming a continuous chain.
- The chain is stored in PostgreSQL and asynchronously archived.

## 11. Audit Queries

The observability system MUST be capable of answering the following questions for any given transaction:
1. **Why was this action allowed?** (Resolved via Policy Decision and Risk Decision logs)
2. **What did the AI know?** (Resolved via Context logs and Provenance tracking)
3. **Where did that information come from?** (Resolved via Provenance attributes)
4. **Which model made the decision?** (Resolved via Model Decision logs)
5. **Which tools were called?** (Resolved via Tool Call logs)
6. **Which policies applied?** (Resolved via Policy Decision logs)
7. **What risk was calculated?** (Resolved via Risk Decision logs)
8. **What did MIRAGE verify?** (Resolved via Gate 1-4 logs)
9. **What actually happened?** (Resolved via Gate 5 Outcome logs)
10. **What did the transaction cost?** (Resolved via Cost logs)

## 12. Retention Policies

- **Metrics:** 13 months (downsampled after 30 days).
- **Logs:** 30 days hot storage, 7 years cold archive (depending on tenant compliance needs).
- **Traces (Detailed):** 7 days hot storage.
- **Audit Ledger (Cryptographic):** Permanent retention (never deleted).

## 13. Export Formats

- **JSONL:** Bulk export format for logs and events, partitioned by tenant and date.
- **Compliance PDFs:** Generated reports summarizing transaction assurance and policy violations over a time period, digitally signed.

## 14. Dashboard Integration

The React/JSX frontend consumes the observability data to display:
- Live transaction flows.
- Assurance gate funnel metrics (e.g., % of requests blocked at Gate 1).
- Cost attribution per agent/model.
- Risk heatmaps.
