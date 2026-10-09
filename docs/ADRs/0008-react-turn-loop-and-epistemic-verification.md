# ADR-0008: Agentic ReAct Turn Loops, Epistemic Reality Verification, and Information Flow Control

**Status:** Accepted  
**Date:** 2026-10-06  

## Context
A rigorous pre-implementation red-team audit of the MIRAGE 3.0 specification (`docs/MIRAGE_3.0_Architecture_Audit.md`) identified four critical architectural vulnerabilities in the initial draft:
1. **Linear Transaction Assumption:** Modeling AI Transactions as a single linear sequence fails for iterative reasoning-action (ReAct) agent loops.
2. **Epistemic Overclaiming in Outcome Assurance:** Claiming real-world state verification for unobservable, asynchronous, or write-only systems creates false confidence.
3. **The Dangerous Triad Vector:** Lack of deterministic Information Flow Control (IFC) allows indirect prompt injection combined with private data to exfiltrate secrets via external communication tools.
4. **Salami-Slicing Aggregate Risk:** Evaluating risk purely per action allows agents to decompose high-risk actions into many micro-actions that evade autonomy controls.

## Decision
We ratify the following architectural enhancements to the MIRAGE 3.0 specification:
1. **Governed Turn-Loop Transaction Model:** The AI Transaction lifecycle is refactored from a linear sequence to a bounded state machine supporting iterative planning turns, action authorization, and outcome verification loops.
2. **Epistemic Observability Model:** Gate 4 (Outcome Assurance) evaluates targets across four observability classes (`OBS_DIRECT`, `OBS_EVENTUAL`, `OBS_INFERRED`, `OBS_BLIND`) and emits qualified confidence tuples rather than binary verification claims.
3. **Dynamic Taint Tracking (IFC):** Context is tagged with `TAINT_UNTRUSTED` and `TAINT_CONFIDENTIAL`. When both taints are present, external communication capabilities are automatically demoted to L4 (Mandatory Human Approval).
4. **Sliding-Window Aggregate Blast Radius Quotas:** The Risk Engine calculates effective risk as $\max(\text{Instantaneous Risk}, \text{Cumulative Window Risk})$, preventing salami-slicing evasion.
5. **Semantic Gate Designations:** Numbering gates as 1-5 is subordinated to canonical semantic names (`input_assurance`, `context_assurance`, `action_assurance`, `outcome_assurance`, `output_assurance`).

## Consequences
- **Positive:** Closes critical security vulnerabilities, aligns the execution model with real-world agent frameworks, eliminates impossible epistemic claims, and protects against cumulative blast radius attacks.
- **Negative:** Slightly increased state management complexity in the Transaction Manager and Context Assembler.
- **Migration:** Fully backward-compatible with MIRAGE 2.x verification endpoints (which operate as single-turn transactions).

## Alternatives Considered
- *Strict single-turn transactions:* Rejected because modern agents inherently loop.
- *Heuristic NLP exfiltration scanning:* Rejected because prompt injection can bypass regex/NLP scanning via encoding.
