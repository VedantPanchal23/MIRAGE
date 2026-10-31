# Architecture Decision Records (ADRs)

This directory contains the Architecture Decision Records (ADRs) for MIRAGE 3.0.

## 1. When an ADR is Mandatory
An ADR must be created when making decisions that affect:
- Architectural boundaries or service decoupling
- Data authority or storage systems
- Security or identity models
- Transaction semantics
- Policy semantics or evaluation mechanisms
- Public API contracts
- Model routing strategies
- External dependencies
- System fail-safe behaviors

## 2. ADR Template
All new ADRs must include the following sections:
- **Title:** A clear, concise title.
- **Status:** Proposed / Accepted / Deprecated / Superseded
- **Date:** YYYY-MM-DD
- **Context:** The problem, context, and requirements.
- **Decision:** The specific technical decision being made.
- **Consequences:** The impact of this decision (positive and negative).
- **Alternatives Considered:** What other options were evaluated and why they were rejected.

## 3. ADR Numbering
MIRAGE 3.0 continues the numbering scheme established in MIRAGE 2.x.
New ADRs start at `0007`.

## 4. Authoritative Architecture Decision Records (0001-0008)

All ratified ADRs reside in this directory:

### Foundation ADRs (0001-0006)
- **ADR-0001:** [MongoDB Trace Collection Architecture](0001-mongodb-trace-collection-architecture.md) — Durable raw payload and trace retention.
- **ADR-0002:** [Rate Limiting Algorithm Unification](0002-rate-limiting-algorithm-unification.md) — Token-bucket rate limiting with tenant tier allocations.
- **ADR-0003:** [Celery Broker Durability and Idempotency](0003-celery-broker-durability-and-idempotency.md) — Asynchronous task verification and deduplication.
- **ADR-0004:** [Docker Compose Production Topology](0004-docker-compose-production-topology.md) — Standardized multi-container orchestration topology.
- **ADR-0005:** [REST API Contracts and Storage Architecture](0005-rest-api-contracts-and-storage-architecture.md) — Authoritative PostgreSQL storage and OpenAPI schemas.
- **ADR-0006:** [Phase P4 Comprehensive Benchmark Evaluation](0006-phase-p4-comprehensive-benchmark-evaluation.md) — Empirical benchmarking methodologies and datasets.

### MIRAGE 3.0 Ratified ADRs (0007-0008)
- **ADR-0007:** [MIRAGE 3.0 Architectural Reset](0007-mirage-3.0-architectural-reset.md) — Pivot to AI Execution Assurance Platform and 5-Gate lifecycle.
- **ADR-0008:** [Agentic ReAct Turn Loops, Epistemic Reality Verification, and Information Flow Control](0008-react-turn-loop-and-epistemic-verification.md) — Hardening against dangerous triad, salami attacks, and epistemic overclaiming.

