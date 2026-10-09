# MIRAGE 3.0 — Technical Architecture

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05

This document defines the core architecture for the MIRAGE 3.0 AI Execution Assurance Platform. All system components, data flows, and infrastructure designs are bounded by these architectural definitions.

---

## 1. Architecture Overview

MIRAGE 3.0 is designed as a distributed, high-assurance system divided into four planes:

1. **Control Plane:** Configuration, policy, identity, and administrative management.
2. **Execution Plane:** Real-time AI transaction processing and governance.
3. **Data Plane:** State persistence, embeddings, tracing, and event streams.
4. **Observability Plane:** Tracing, metrics, audit logging, and provenance tracking.

The system enforces five Assurance Gates across the AI Transaction lifecycle: Input, Context, Action, Output, and Outcome.

---

## 2. Control Plane Components

The Control Plane is responsible for managing the rules, identities, and metadata that govern the Execution Plane. It primarily interacts with the Data Plane (PostgreSQL) and exposes administrative APIs.

### 2.1 Identity Service
- **Responsibility:** Manages identities for human users, AI agents, tools, MCP servers, and internal services. Handles authentication and credential lifecycle.
- **Implementation:** Issues cryptographically signed short-lived tokens (e.g., JWT). 

### 2.2 Policy Service
- **Responsibility:** Manages declarative policies governing tenant, organizational, and agent behaviors. Handles versioning, hierarchy, and conflict resolution.
- **Implementation:** Policies are stored in PostgreSQL and cached in Redis.

### 2.3 Model Registry
- **Responsibility:** Stores model capability profiles, health statuses, costs, and routing rules.
- **Implementation:** Tracks real-time model health and rate limits.

### 2.4 Capability Manager
- **Responsibility:** Defines capabilities (bounded permissions), manages grants, revocations, and enforces scope across agents and tools.

### 2.5 Tenant Manager
- **Responsibility:** Manages tenant configuration, ensures strict tenant isolation (using PostgreSQL RLS), and enforces resource limits.

### 2.6 Budget Manager
- **Responsibility:** Tracks and enforces token budgets, cost limits, latency budgets, and tool-call budgets.

### 2.7 Admin API
- **Responsibility:** Provides the interface (FastAPI) for configuring the Control Plane. Consumed by the React 18/JSX dashboard.

---

## 3. Execution Plane Components

The Execution Plane is the real-time engine processing AI Transactions. It enforces Control Plane policies at runtime.

### 3.1 Gateway
- **Responsibility:** Ingests requests, resolves identities, applies token-bucket rate limiting, and performs initial payload validation. It evaluates **Gate 1 (Input Assurance)**.

### 3.2 Intent Classifier
- **Responsibility:** Classifies the purpose and scope of requests to determine risk assessment and model routing.

### 3.3 Risk Engine
- **Responsibility:** Computes multi-dimensional risk scores (e.g., data sensitivity, target criticality, blast radius).

### 3.4 Policy Engine
- **Responsibility:** Evaluates runtime policies against the transaction context.

### 3.5 Model Router
- **Responsibility:** Dynamically selects the optimal model(s) based on task complexity, risk, latency, cost, and policy constraints.

### 3.6 Context Assembler
- **Responsibility:** Gathers evidence (RAG), loads memory, and assembles tool states. Evaluates **Gate 2 (Context Assurance)** for provenance and poisoning.

### 3.7 Action Governor
- **Responsibility:** Enforces capabilities, validates parameters, and manages approval workflows for high-risk actions. Evaluates **Gate 3 (Action Assurance)**.

### 3.8 Tool Proxy
- **Responsibility:** Securely invokes tools, MCP servers, and external APIs. Governs interactions with external systems.

### 3.9 Verification Engine
- **Responsibility:** Verifies model output factual consistency, safety, and reliability. This subsystem encapsulates the MIRAGE 2.x core (RAV, SCS, NLI, ICS, VGS, HRS). Evaluates **Gate 4 (Output Assurance)**.

### 3.10 Reality Verifier
- **Responsibility:** Confirms that real-world outcomes match the intended actions. Evaluates **Gate 5 (Outcome Assurance)**.

### 3.11 Assurance Scorer
- **Responsibility:** Computes the overall transaction assurance score based on the outputs of the Five Gates.

### 3.12 Transaction Manager
- **Responsibility:** Manages the AI Transaction lifecycle, state, correlation, and audit recording.

---

## 4. Data Plane

The Data Plane persists all state, configuration, and event data.

- **PostgreSQL:** Stores Control Plane data (tenants, users, agents, policies, capabilities, audit ledger). Enforces tenant isolation via Row-Level Security (RLS).
- **MongoDB:** Stores full AI Transaction execution traces, tool invocations, and verification details in a flexible, append-heavy schema with TTL management.
- **Redis:** Manages runtime state, rate limiting (atomic token bucket), caching, session state, and circuit breaker state.
- **Qdrant:** Stores evidence embeddings for retrieval-augmented verification.
- **Event Stream:** (e.g., RabbitMQ Streams or Kafka) Handles ordered, durable transaction events for audit and downstream consumption.

---

## 5. Observability Plane

The Observability Plane ensures full accountability and traceability.

- **OpenTelemetry (OTel):** Provides distributed tracing across all components and AI Transaction stages.
- **Prometheus:** Collects metrics on latency, throughput, error rates, and cost.
- **Structured Logging:** Centralized JSON-formatted event logs with transaction correlation IDs.
- **Audit Service:** Maintains the SHA-256 cryptographically chained, tamper-evident audit ledger (preserved from MIRAGE 2.x).

---

## 6. Component Interactions and Data Flow (The Governed Turn Loop)

1. **Ingestion & Input Assurance:** Request enters via Gateway $\to$ Identity Service (resolves actor/agent) $\to$ Intent Classifier $\to$ Policy Engine evaluates baseline admission $\to$ assigns initial taint tags.
2. **Context Assurance:** Context Assembler gathers evidence (RAG) & governed memory $\to$ enforces Instruction/Data separation $\to$ applies Information Flow Control (IFC) taint rules.
3. **The Governed Turn Loop (Iterative ReAct Execution):**
   - **Reasoning Turn:** Model generates intermediate plan and proposed tool invocation.
   - **Action Assurance:** Action Governor checks capabilities, parameter schemas, IFC constraints (blocking external egress if untrusted + confidential taints coincide), and sliding-window aggregate blast radius.
   - **Invocation:** Tool Proxy invokes authorized MCP server or external API.
   - **Outcome Assurance:** Reality Verifier evaluates target system according to its Epistemic Observability Class (`OBS_DIRECT`, `OBS_EVENTUAL`, `OBS_INFERRED`, `OBS_BLIND`), emitting an outcome tuple `(OutcomeStatus, EpistemicConfidence)`.
   - **Context Mutation:** Tool results are sanitized, new taints appended, and verified outcome returned to agent for next turn.
4. **Output Assurance:** Upon loop completion, agent generates final response $\to$ Verification Engine evaluates factual consistency (RAV, NLI, SCS, ICS, VGS, HRS).
5. **Streaming / Speculative Assurance:** In interactive streaming mode, tokens pass through regex/PII gates with speculative status, while heavy statistical checks execute asynchronously in background workers.
6. **Persistence & Audit:** Transaction Manager commits the complete turn trace to MongoDB and appends the cryptographic block hash to the PostgreSQL Audit Ledger.

---

## 7. Technology Stack

- **Language:** Python 3.12+ (strictly typed via mypy)
- **API Framework:** FastAPI
- **Async Workers:** Celery / RabbitMQ
- **Databases:** PostgreSQL, MongoDB, Redis, Qdrant
- **Frontend:** React 18 / JSX (No TypeScript/TSX)

---

## 8. Scalability and Resilience

- **Horizontal Scaling:** FastAPI Gateway, Verification Engine workers, Tool Proxy, and Risk/Policy engines scale horizontally.
- **Resilience:** Circuit Breakers (pybreaker) protect against cascading failures when calling external models or MCP servers. Systems fail closed on critical security paths and fail open on non-critical verification steps.
- **Streaming Architecture:** LLM streams are intercepted by the Gateway and processed incrementally by the Verification Engine, buffering outputs until Gate 4 confidence thresholds are met.

---

## 9. Container Topology

Extends the MIRAGE 2.x topology to support 15+ containers across 3 tiers (Public, App, Data):
1. `mirage-gateway` (FastAPI)
2. `mirage-control-plane` (Admin/Policy APIs)
3. `mirage-execution-engine` (Transaction/Risk/Action/Routing)
4. `mirage-verification-engine` (RAV/SCS/NLI/ICS core)
5. `mirage-tool-proxy` (MCP Integration)
6. `postgres`, `mongo`, `redis`, `qdrant`, `rabbitmq`
7. `otel-collector`, `prometheus`, `audit-service`
8. `mirage-dashboard` (React)
