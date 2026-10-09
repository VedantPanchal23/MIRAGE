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

## 4. Retained MIRAGE 2.x ADRs (0001-0006)
ADRs `0001` through `0006` are retained from the MIRAGE 2.x era. They remain valid for the scope of their specific technical domains (e.g., database schema decisions, trace storage mechanisms, etc.).

## 5. MIRAGE 3.0 Ratified ADRs
- **ADR-0007:** [MIRAGE 3.0 Architectural Reset](0007-mirage-3.0-architectural-reset.md) — Pivot to AI Execution Assurance Platform.
- **ADR-0008:** [Agentic ReAct Turn Loops, Epistemic Reality Verification, and Information Flow Control](0008-react-turn-loop-and-epistemic-verification.md) — Hardening against dangerous triad, salami attacks, and epistemic overclaiming.

