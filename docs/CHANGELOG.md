# Changelog

All notable changes to the MIRAGE platform will be documented in this file.

## [v3.0.0-draft] - 2026-10-05

### Architectural Reset & Pre-Implementation Hardening
MIRAGE has evolved from a hallucination detection platform (2.x) to a comprehensive **AI Execution Assurance Platform** (3.0). Following a comprehensive pre-implementation red-team audit (`docs/MIRAGE_3.0_Architecture_Audit.md`), the architecture was hardened with ADR-0008:
- **Governed ReAct Turn Loops:** Iterative agent execution graph replacing linear transaction pipeline.
- **Epistemic Observability Model:** Formalized 4-class outcome qualification (`OBS_DIRECT`, `OBS_EVENTUAL`, `OBS_INFERRED`, `OBS_BLIND`) preventing unprovable reality verification claims.
- **Information Flow Control (IFC):** Dynamic taint tracking eliminating the Dangerous Triad (Private Data + Untrusted Content + External Communication).
- **Sliding-Window Aggregate Blast Radius:** Quantitative defense against salami-slicing micro-action attacks.
- **Asynchronous Speculative Assurance:** Latency-optimized streaming protocol for interactive chat.

### Added
- **AI Transaction Model:** End-to-end traceable units of AI work.
- **Five Assurance Gates:** Input, Context, Action, Output, and Outcome assurance.
- **Control Plane Services:** Identity Service, Policy Service, Model Registry, Capability Manager, Budget Manager.
- **Execution Plane Services:** Intent Classifier, Risk Engine, Model Router, Action Governor, Reality Verifier.
- **Memory Governance:** Provenance-tracked, access-controlled memory storage.
- **New Documentation:**
  - `Technical_Architecture.md`
  - `Development_Workflow.md`
  - `Compatibility_and_Migration.md`
  - `ADRs/README.md`
  - `ADRs/0007-mirage-3.0-architectural-reset.md`

### Changed
- The MIRAGE 2.x Verification Stack (RAV, SCS, NLI, ICS, VGS, HRS) has been repositioned as a subsystem within Gate 4 (Output Assurance).
- Authorization transitioned from simple RBAC to a unified ABAC + Capability model.
- Gateway expanded to handle full lifecycle interception and Gate 1 processing.

### Implemented Milestones

#### Phase 0 & 1 — Control Plane & Gate 1 Input Assurance
- Authoritative PostgreSQL identity & access management; removed hardcoded credentials and unauthenticated demo token issuers.
- Implemented ASGI/WebSocket identity header sanitization defense against proxy spoofing.
- Established deterministic Gate 1 Input Assurance with DLP pattern detection and prompt-injection defenses.
- Dynamic Information Flow Control (DIFC) taint lattice with concurrency restrictions.
- AI Transaction state machine with optimistic concurrency control and child transaction confinement.
- Tamper-evident SHA-256 cryptographic audit chaining.

#### Phase 2 — Gate 2 Context Assurance & Governed Memory
- Context Assembler with strict `<trusted_instructions>` and `<untrusted_data>` delimiter encapsulation.
- Neutralization of XML/ChatML prompt injection breakout attempts from untrusted tool observations.
- Governed Memory subsystem with epistemic attestation tiers (`ATTESTED` vs `ADVISORY`).
- Prevention of autonomous agent self-attestation and cryptographic shredding of poisoned memory.
- Dynamic RAG provenance and generation validation rejecting stale vector indexes.

#### Phase 3 — Gate 3 Action Assurance & Tool Governance
- Authoritative Governed Tool Registry with strict egress classification (`INTERNAL_ISOLATED` vs `EGRESS_EXTERNAL`).
- Action Contract proposals with deterministic parameter normalization, anti-traversal / SSRF validation, and immutable SHA-256 parameter hash locking.
- Dynamic Information Flow Control (DIFC) Dangerous Triad Interlock strictly blocking external egress when untrusted and confidential data coexist.
- Salami-slicing aggregate blast radius defense with a 1-hour rolling window tracking dollar spend and risk points.
- Time-bounded L4 Human-in-the-Loop approval workflows with tamper-proof parameter locks and prohibition of agent self-approvals.
- Governed Tool Proxy dispatcher verifying preconditions and recording postcondition evidence for Reality Verification.
- Dashboard Action Assurance view (`ActionAssuranceView.jsx`) implemented with React 18 / JSX.

#### Phase 3.5 — Security and Execution-Path Hardening Pass
- **Mandatory Tool Proxy Enforcement:** Hardened execution boundary with `GovernedToolProxy`; direct tool calls or unverified contracts immediately rejected with `ToolProxyBypassError`. Verifiable invocation count tracking.
- **Cryptographic Contract Binding Hash:** Replaced simple parameter hash locks with holistic `compute_contract_binding_hash` fingerprints binding `tenant_id`, `transaction_id`, `action_id`, `tool_name`, `action_type`, `target_resource`, `parameters_hash`, `required_capability`, `estimated_dollar_cost`, and `taint_flags`. Post-approval modification of target resources, capabilities, or action types is cryptographically detected and rejected.
- **Approval Replay & Single-Use Defense:** Approvals transition to `CONSUMED` upon execution; replaying consumed tokens or presenting tokens across actions/transactions is strictly blocked with HTTP 403 Forbidden.
- **Agent Self-Approval Prevention:** Blocked `API_CLIENT` identities and enforced `requested_by != identity_id` in approval grant paths; distinct human sign-off mandatory.
- **Tool Registry Governance:** Tool registration restricted to Super Admin and Tenant Admin; security demotion of `EGRESS_EXTERNAL` to `INTERNAL_ISOLATED` prohibited without Super Admin privileges.
- **Advanced Anti-SSRF Defense:** IPv4/IPv6 private and loopback validation, decimal integer IPs (`2130706433`), hexadecimal IPs (`0x7f000001`), octal IPs (`0177.0.0.1`), IPv4-mapped IPv6, cloud metadata addresses (`169.254.169.254`, `metadata.google.internal`), userinfo credentials stripping, and non-HTTP scheme blocking (`file://`, `gopher://`, etc.).
- **Advanced Path Traversal Defense:** Neutralization of URL-encoded `%2e%2e`, Unicode NFKC normalization, null-byte rejection (`\x00`, `%00`), Windows drive letters (`C:\`), and UNC network paths (`\\`).
- **Salami-Slicing Financial Parameter Extraction:** Automatic inspection of financial parameters (`amount`, `amount_usd`, `spend`, `cost`) to prevent cost spoofing (`$0` claimed vs `$1,500` transferred).
- **Concurrency & Race Condition Protection:** PostgreSQL row-level locks via `select(...).with_for_update()` on `ActionContract` and `ActionApproval`.
- **Fail-Closed Runtime Capability Revocation:** Re-verification of capability validity and expiry at execution time immediately aborts actions if permissions were revoked during pending approval.
- **Postcondition Honesty & Verifiable Probe Observability:** Explicit separation of tool execution and acknowledgment from Gate 5 Reality Verification. Dedicated adversarial test suite (16/16 passed; 58/58 full regression).

#### Phase 4 — Gate 4 Output Assurance & Verification Engine Modernization
- **Adaptive Verification Escalation Ladder:** Multi-tier assurance pipeline (Tier 1 Cheap Deterministic Regex/DLP -> Tier 2 Lightweight Classifier -> Tier 3 Retrieval-Augmented NLI + ICS + LightGBM HRS Meta-Learner -> Tier 4 Frontier Multimodal Judge -> Tier 5 Human-in-the-Loop review). Escalates expensive verification checks only when factual propositions or untrusted taints require it.
- **Strict Verification Budgets & Graceful Degradation:** Real-time enforcement of latency (`max_latency_ms`), token counts, financial budgets (`max_cost_usd`), model calls, and maximum verification tier. When budgets are exhausted, Gate 4 gracefully returns `DEGRADED` status with `ALLOW_WITH_UNCERTAINTY` decision without fabricating epistemic certainty.
- **Empirical Uncertainty Calibration & Conformal Prediction:** Isotonic Regression calibration of Holistic Reliability Score (HRS) with Mondrian Conformal Prediction generating finite-sample valid 95% confidence intervals `[lower, upper]`. Computes Expected Calibration Error (ECE < 0.05) and TreeSHAP attribution across signals (`s_rav`, `s_scs`, `s_nli`, `s_ics`, `s_vgs`).
- **Postcondition Honesty & Action Consistency:** Semantic validation preventing models from falsely asserting that actions succeeded when their corresponding `ActionContract` is in `PROPOSED`, `AWAITING_APPROVAL`, or `BLOCKED` states. Epistemic output verification is cleanly demarcated from Gate 5 external reality verification.
- **Dynamic Information Flow Control (DIFC) Dangerous Triad Interlock:** Automatic detection and blocking of confidential data leakage into model outputs when `TAINT_UNTRUSTED` and `TAINT_CONFIDENTIAL` co-exist.
- **Stale Evidence & Indirect Instruction Neutralization:** Automated validation of retrieved RAG evidence against active knowledge base document generations (`generation < active_generation` rejected). Neutralization of `<trusted_instructions>` in retrieved evidence prevents passive document payloads from overriding Gate 4 policy.
- **Tier 1 Cheap Deterministic DLP & Sanitization:** High-throughput regex scanning and automatic redaction for private keys, AWS/Stripe tokens, database credentials, passwords, SSNs, phone numbers, email addresses, and prompt injection markers (`[REDACTED_SECRET]`, `[REDACTED_PII]`).
- **Autonomous LangGraph Self-Correction Loop:** Integration with LangGraph StateGraph correction loop for contradicted claims (`VerificationStatus.CONTRADICTED`), with bounded retry limits (K=2) and re-verification of rewritten claims before release.
- **Authoritative PostgreSQL Persistence & RLS:** `OutputAssuranceRecord` entity with Row-Level Security isolation, SHA-256 output fingerprinting, and cryptographic audit log hash chain linkage (`AuditLogRecord`).
- **Gate 4 Operational Dashboard:** React 18 / JSX operational interface (`OutputAssuranceView.jsx`) featuring interactive text submission, real-time HRS gauges, Conformal 95% confidence intervals, claim decomposition breakdowns, verification tier path tracing, DLP detection tables, and budget consumption telemetry.

#### Phase 4.5 — Gate 4 Output Assurance Security, Scientific Integrity, and Runtime-Path Hardening
- **Unicode Normalization & Anti-Obfuscation:** Standardized NFKC Unicode normalization and zero-width spaces/joiners (`\u200b`, `\u200c`, `\u200d`, `\ufeff`) / control byte stripping across the DLP pipeline to eliminate token-splitting obfuscation attacks.
- **Comprehensive Secret & Injection Scanning:** Extended DLP detection to cover AWS access keys (`AKIA/ASIA/AROA`), GitHub personal access tokens (`ghp_`), Slack bot/user tokens (`xoxb-/xoxp-`), Bearer tokens, private keys (`-----BEGIN PRIVATE KEY-----`), and prompt-injection/jailbreak control tokens (`<|im_start|>`, `<|endoftext|>`, `[INST]`, `[SYSTEM]`, `DAN mode`).
- **Postcondition Honesty Hardening:** Expanded action-consistency checks to detect claims in active or passive voice, past-tense verbs (`sent`, `transferred`, `deleted`, `paid`), and zero-action claims; strictly enforces that asserting real-world action execution with zero action contracts or uncompleted contracts causes a hard `BLOCK`.
- **Transaction State Machine Gate 4 Invariant:** Enforced mandatory Gate 4 evaluation on `transition_transaction` to `COMPLETED`; transitions without a Gate 4 record or following a `BLOCK` / `REQUIRE_HUMAN_REVIEW` decision are rejected with HTTP 409 Conflict.
- **Conformal Uncertainty Escalation:** When conformal prediction intervals indicate elevated upper-bound risk ($\text{upper} \ge 0.85$, even with moderate nominal HRS), Gate 4 escalates to `REQUIRE_HUMAN_REVIEW` and marks the output as `PARTIALLY_VERIFIED`.
- **Scientific Integrity & Calibration Disclosure:** Analytical conformal intervals derived under exchangeability are explicitly marked with `is_certified=False` and `certification_status="NOT_SCIENTIFICALLY_CERTIFIED"` pending empirical evaluation on benchmark corpora (HaluEval, FActScore). Empty factual claims default to `UNVERIFIED` with `ALLOW`.
- **Runtime Egress Paths Hardened:** OpenAI-compatible proxy (`/v1/chat/completions`) redacts secrets and provides honest verification headers (`X-Mirage-Verified`); WebSocket streaming (`/v1/stream/transactions`) emits truthful `verification_status` and `safety` payloads in the terminal event.
#### Phase 5 — Gate 5 Outcome Assurance & Reality Verification
- **Epistemic Observability Classification:** Formal implementation of the 4-tier model (`OBS_DIRECT`, `OBS_EVENTUAL`, `OBS_INFERRED`, `OBS_BLIND`) binding every outcome verification request to physical observability realities.
- **7 Canonical Outcome Statuses:** Formalization of outcome qualifications (`SUCCESS_CONFIRMED`, `SUCCESS_EVENTUALLY_OBSERVED`, `ACKNOWLEDGED_UNVERIFIED`, `FAILED`, `PARTIAL`, `UNKNOWN`, `UNOBSERVABLE`) with calibrated epistemic confidence scores ($0.00$ to $1.00$).
- **Fundamental Epistemic Invariant:** Enforced core axiom: `Request accepted != Tool acknowledged != Final state verified`. Models are strictly prevented from claiming confirmed physical success on uninspected or write-only sinks.
- **Modular Reality Verifier Adapters:**
  - `DatabaseStateAdapter`: Direct read-only SQL queries with row presence and column postcondition verification.
  - `HttpResourceAdapter`: Hardened REST/webhook probe with DNS-level anti-SSRF protections against private, loopback, and cloud metadata targets.
  - `AsyncEventAdapter`: Polling-based eventual consistency verification with exponential backoff and timeout detection.
  - `SimulatedTestAdapter`: Explicitly disclosed simulation adapter for testbeds with mandatory provenance flags.
- **Output ↔ Outcome Consistency Reconciliation:** Runtime interlock detecting false completion claims in model responses and returning `REWRITE_WITH_CAVEAT` or `BLOCK`.
- **Cryptographic Audit Ledger & Chain Linkage:** Generation of SHA-256 verification hashes mathematically binding tenant, transaction, action, status, confidence, and observed state bytes into the immutable `AuditLogRecord` chain.
- **Alembic Migration & PostgreSQL RLS:** Migration `009_gate5_outcome_assurance.py` provisioning `outcome_verification_records` with Row-Level Security.
- **Gateway Endpoints:** `/v1/outcomes/verify`, `/v1/outcomes/{outcome_id}`, `/v1/outcomes/transaction/{transaction_id}`, and `/v1/outcomes/reconcile`.
- **Operational Dashboard View:** React 18 / JSX view (`OutcomeAssuranceView.jsx`) featuring verification contracts, observability distribution, adapter probes, and reconciliation tools.
- **Test Suite & Verification:** 18/18 dedicated Gate 5 tests passing (unit, security, integration); 481/481 full regression tests passing across all gates. Live demo Scenario 9 executing cleanly.

#### Phase 5.5 — Reality Verification Red-Team, Integrity Hardening & Release Readiness
- **Monotonic State Machine:** Formalized state transition matrix (`VALID_OUTCOME_TRANSITIONS`) preventing outcome regressions (e.g. `SUCCESS_CONFIRMED` -> `UNKNOWN` or `FAILED` -> `SUCCESS_CONFIRMED`) with HTTP 409 Conflict enforcement.
- **Canonical JSON SHA-256 Hashing:** Upgraded verification fingerprinting to sorted canonical JSON under schema `mirage.outcome.v1`, eliminating delimiter collision vulnerabilities and cryptographically binding previous audit log entries into `AuditLogRecord`.
- **ActionContract State Invariant:** Prohibited verification probes against unexecuted actions (`PROPOSED`, `AWAITING_APPROVAL`, `BLOCKED`) with HTTP 409 Conflict.
- **Strict Target Resource & Environment Binding:** Math-bound probes against authorized `ActionContract.target_resource` and `blast_radius.target_environment`, rejecting mismatched tables, foreign URLs, or spoofed environments.
- **Production Simulation Isolation:** Strictly prohibited `SimulatedTestAdapter` in production (`PROD`) environments, ensuring simulation evidence cannot satisfy `SUCCESS_CONFIRMED`.
- **Advanced Anti-SSRF & Redirect Protection:** In `HttpResourceAdapter`, enforced single-hop redirect inspection (`follow_redirects=False`) with IP validation against private/loopback/cloud-metadata addresses, eliminating redirect-based SSRF.
- **SQL Injection Defenses:** In `DatabaseStateAdapter`, sanitized table names with strict regex validation (`^[a-zA-Z_][a-zA-Z0-9_]*$`) and executed all inspection queries under `SET TRANSACTION READ ONLY`.
- **Bounded Eventual Consistency & Timeout Guarantees:** In `AsyncEventAdapter`, bounded poll attempts and timeouts; ensured that timeouts strictly yield `UNKNOWN` with confidence `0.0`.
- **Gate 4 ↔ Gate 5 Reconciliation Hardening:** Strengthened `reconcile_output_with_outcome` with tenant isolation, transaction correlation, action correlation, and plural/postfix verb assertion pattern matching.
- **Compensating Action Governance:** Enforced that Gate 5 reality verifier routes compensating actions strictly through Gate 3 (`ActionGovernorService`).
- **Dedicated Adversarial Hardening Suite:** Implemented 30 dedicated adversarial test vectors (`tests/security/test_phase5_5_hardening.py`) with 30/30 passing; 511/511 passing across full regression suite.

### Deprecated
- Streamlit dashboard deprecated in favor of React 18/JSX frontend.

---

## [v2.x] - Reference

MIRAGE 2.x represents the legacy hallucination detection platform. The engineering foundation (PostgreSQL, MongoDB, Qdrant, Redis, Verification Engine algorithms) is preserved and integrated into the 3.0 architecture.
