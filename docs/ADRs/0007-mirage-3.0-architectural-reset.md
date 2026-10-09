# ADR-0007: MIRAGE 3.0 Architectural Reset

**Status:** Accepted
**Date:** 2026-10-05

## Context
MIRAGE 2.x was built as a hallucination detection platform. However, as enterprise AI usage shifted from simple chatbots to autonomous agents, RAG workflows, and multi-agent systems invoking real-world tools, hallucination detection alone became insufficient. 

Organizations face systemic risks across the entire AI lifecycle: malicious inputs, poisoned context, unauthorized tool use, unchecked resource consumption, and unverified real-world outcomes. A point solution for output verification cannot secure the full AI interaction.

## Decision
We are evolving MIRAGE from a hallucination detection tool into an **AI Execution Assurance Platform**. 

The architecture is fundamentally restructured to include:
1. **Control and Execution Planes:** Separation of policy/identity management from real-time transaction processing.
2. **Five Assurance Gates:** Comprehensive verification across Input, Context, Action, Output, and Outcome.
3. **AI Transactions:** Treating end-to-end AI interactions as traceable, governed transactions.
4. **Subsystem Repositioning:** The MIRAGE 2.x verification stack (RAV, SCS, NLI, VGS, HRS) is preserved but repositioned as the Verification Engine within Gate 4 (Output Assurance).

## Consequences
- **Positive:** MIRAGE can now govern autonomous agents, secure MCP tool usage, optimize model routing costs, and verify real-world outcomes, vastly increasing its addressable market and enterprise value.
- **Negative:** Increased architectural complexity. Gateway latency must be strictly managed to support real-time synchronous gate evaluation.
- **Migration:** Existing 2.x deployments will require a data migration to support the new Control Plane schema and Capability model. Streamlit dashboards will be replaced.

## Alternatives Considered
- *Maintain two separate products (Security vs. Verification):* Rejected. Customers need a unified assurance fabric.
- *Keep 2.x architecture and bolt on pre-execution checks:* Rejected. The AI Transaction lifecycle requires a fundamentally different routing and state management approach than a simple verification proxy.
