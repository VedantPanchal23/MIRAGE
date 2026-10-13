# MIRAGE 3.0 — Phase 6: Outcome Assurance Implementation Report

> **Status:** Implementation Complete | **Version:** 3.0.0-phase6 | **Date:** 2026-10-12  
> **Repository:** `VedantPanchal23/MIRAGE` | **Branch:** `main` | **Baseline Commit:** `006cfa7c976a522aab2784a85ab45cf3a75cc151`  
> **Authoritative Specification:** [`docs/MIRAGE_3.0_Specification.md`](../MIRAGE_3.0_Specification.md), [`docs/Reality_Verification.md`](../Reality_Verification.md), [`docs/AI_Action_Contract.md`](../AI_Action_Contract.md)

---

## 1. Executive Summary

Phase 6 delivers the canonical **Outcome Assurance Lifecycle and Evidence State Machine** for MIRAGE 3.0. This implementation operationalizes **Gate 5 (Outcome Assurance)** and establishes the non-negotiable platform core invariant:

> **The Core Invariant:** A tool acknowledgment, transport HTTP success response (e.g., HTTP 200/202), completed model generation, or self-reported model assertion is **not proof of real-world success**. An action outcome may be marked verified only when sufficient, independently observed, unexpired evidence establishes that the intended target state postconditions have actually been satisfied.

### Summary of Accomplishments:
1. **Outcome Contract Specification (`OutcomeContractSpec`):** Every governed action requiring outcome assurance must define its expected postconditions, acceptable evidence sources allowlist, positive verification deadline, risk-sensitive verification policy (`STRICT_DIRECT_ONLY`, `DEFAULT`, `LENIENT_PERMISSIVE`), and partial/uncertain completion strategies (`on_partial`, `on_uncertain`) prior to execution. Mutating actions lacking required postconditions fail closed (`Decision.BLOCK` / `ActionState.BLOCKED`).
2. **Evidence-Based Monotonic State Machine:** Canonical Phase 6 states (`PENDING_VERIFICATION`, `VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, `PARTIAL_ACHIEVEMENT`, `UNKNOWN`, `UNVERIFIABLE`) with strict monotonic transition rules and terminal immutability preventing regressions or overwrites.
3. **Decoupled Execution & Verification Boundary:** Mutating actions transition to `ActionState.EXECUTED` (not `COMPLETED`), dispatching to tool targets and creating an `OutcomeVerificationRecord` in `PENDING_VERIFICATION` state with `epistemic_confidence = 0.0`.
4. **Independent Observation Verification (`IndependentObserverAdapter`):** Decoupled verification adapter validating target resource binding, anti-staleness enforcement (`observed_at >= executed_at`), authorized `acceptable_evidence_sources` allowlist, 64-character SHA-256 evidence digests, and target-state discrepancy detection.
5. **Sensitive Payload Sanitization:** Recursive payload redaction scrubbing Bearer tokens, API keys (`sk-...`, `ghp_...`), database credentials, and secret key/value pairs from evidence payloads and observation records before persistence.
6. **Output ↔ Outcome Reconciliation:** Gate 4/5 interlock preventing models from claiming completion when underlying actions remain in `PENDING_VERIFICATION`, `VERIFIED_FAILURE`, or `PARTIAL_ACHIEVEMENT`.
7. **Human Operator Escalation Workflow:** Endpoint `POST /v1/outcomes/{outcome_id}/escalate` supporting manual investigation, status progression, and cryptographic audit chaining.
8. **Additive Database Migration 016:** Alembic migration adding `requires_outcome_assurance`, `outcome_contract`, and `outcome_status` to `action_contracts`, and `evidence_source`, `evidence_digest`, `observed_at`, `verification_deadline`, `escalation_status`, `escalation_notes` to `outcome_verification_records` with PostgreSQL Row-Level Security (`mirage_app`).
9. **Pure React 18 / JSX Frontend:** Zero TypeScript introduced. Updated dashboard client and `OutcomeAssuranceView.jsx` with canonical Phase 6 badges, pending outcome inspection, and escalation controls.
10. **Validation Suite:** 43 tests executed and passing (100% pass rate) across unit, security, and regression batteries. Ruff lint checks passing cleanly with zero errors.

---

## 2. Invariant & Architecture Specifications

### 2.1 The Evidence-Based State Machine Lattice

```
                     ┌──────────────────────────────────────────────┐
                     │             Action Dispatched                │
                     │    (Transport ACK != Verified Success)       │
                     └──────────────────────┬───────────────────────┘
                                            │
                                            ▼
                     ┌──────────────────────────────────────────────┐
                     │             PENDING_VERIFICATION             │
                     │          (epistemic_confidence = 0.0)        │
                     └──────┬───────────────┼───────────────┬───────┘
                            │               │               │
            Independent     │   Observed    │   Deadline    │  Target is
             Observer       │  Discrepancy  │    Expired    │  Write-Only
            All Satis.      │  or Failure   │   (Timeout)   │ (OBS_BLIND)
                            │               │               │
                            ▼               ▼               ▼
                   ┌────────────────┐ ┌───────────┐ ┌─────────────┐
                   │VERIFIED_SUCCESS│ │  UNKNOWN  │ │UNVERIFIABLE │
                   │  (Conf >= 0.9) │ │ (Conf 0.0)│ │ (Conf 0.0)  │
                   └────────────────┘ └─────┬─────┘ └─────────────┘
                            ▲               │
            All Succeeded   │               │ Sub-operations
             in Batch       │               │ Failed in Batch
                            │               ▼
                   ┌────────────────────────────────┐
                   │      PARTIAL_ACHIEVEMENT       │
                   │        (Conf 0.4 - 0.7)        │
                   └────────────────────────────────┘
                                            │
                                            ▼
                   ┌────────────────────────────────┐
                   │        VERIFIED_FAILURE        │
                   │         (Conf >= 0.9)          │
                   └────────────────────────────────┘
```

### 2.2 Invariant Guarantees

| Invariant | Definition | Implementation Enforcement |
| :--- | :--- | :--- |
| **INV-P6-01: Acknowledgment is Not Verification** | HTTP 200, tool response payloads, or model assertions cannot mark an action outcome verified. | `ActionGovernorService.execute_action` sets `ActionState.EXECUTED` and creates `OutcomeVerificationRecord` in `PENDING_VERIFICATION` with `epistemic_confidence = 0.0` and `postconditions_satisfied = False`. |
| **INV-P6-02: Mandatory Outcome Contracts** | Consequential actions (mutating, risk $\ge 40$, autonomy $\ge 2$, cost $> 0$) cannot execute without outcome contracts and postconditions. | `ActionGovernorService.propose_and_authorize_action` fails closed with `Decision.BLOCK` (`ActionState.BLOCKED`) if required postconditions or acceptable sources are missing. |
| **INV-P6-03: Monotonic State Lattice** | Terminal states (`VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, `PARTIAL_ACHIEVEMENT`, `UNVERIFIABLE`) cannot be silently overwritten or downgraded. | `RealityVerifierService._validate_monotonic_transition` enforces transition rules defined in `VALID_OUTCOME_TRANSITIONS`, raising `HTTPException(409)`. |
| **INV-P6-04: Independent Observer Decoupling** | Physical reality must be confirmed by an authoritative observer decoupled from the tool dispatcher. | `IndependentObserverAdapter` (`OutcomeVerifierType.INDEPENDENT_OBSERVER`) verifies observation against resource, timestamp, and source allowlists. |
| **INV-P6-05: Anti-Staleness Protection** | Target-state observations must be recorded at or after the action execution timestamp. | `IndependentObserverAdapter.verify` rejects observations where `observed_at < action.executed_at` (`HTTPException(400)`). |
| **INV-P6-06: Strict Risk Policies** | High-risk/production actions cannot rely on simulated or inferred probes. | `RealityVerifierService.verify_action_outcome` enforces `STRICT_DIRECT_ONLY`, rejecting `SimulatedTestAdapter`, `OBS_INFERRED`, and `OBS_BLIND`. |
| **INV-P6-07: Sensitive Payload Scrubbing** | Credentials and secrets must never be leaked into observation evidence or audit trails. | `_redact_sensitive_payload` recursively cleans tokens, API keys, and credentials from all evidence dictionaries and nested arrays. |
| **INV-P6-08: Deadline Enforced Downgrade** | Pending outcomes past their verification deadline cannot silently succeed or linger indefinitely. | `RealityVerifierService.get_outcome_by_id` and list queries evaluate `verification_deadline`, monotonically transitioning expired records to `UNKNOWN` with confidence `0.0`. |
| **INV-P6-09: Output Reconciliation Interlock** | Models claiming completion when reality is pending, failed, or partial must be intercepted. | `RealityVerifierService.reconcile_output_with_outcome` evaluates epistemic conflicts, recommending `REWRITE_WITH_CAVEAT` or `REJECT`. |

---

## 3. Implementation Details

### 3.1 Schemas & Data Models

- **`shared/schemas/outcome.py`**:
  - `OutcomeStatus`: Canonical Phase 6 states (`PENDING_VERIFICATION`, `VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, `PARTIAL_ACHIEVEMENT`, `UNKNOWN`, `UNVERIFIABLE`) with legacy aliases (`SUCCESS_CONFIRMED`, `FAILED`, `PARTIAL`, `ACKNOWLEDGED_UNVERIFIED`, `UNOBSERVABLE`).
  - `RiskSensitiveVerificationPolicy`: `STRICT_DIRECT_ONLY`, `DEFAULT`, `LENIENT_PERMISSIVE`.
  - `PartialHandlingStrategy`: `HOLD_FOR_REVIEW`, `RETRY_FAILED_SUBOPERATIONS`, `COMPENSATE_ALL`, `MARK_PARTIAL_AND_CONTINUE`.
  - `UncertainHandlingStrategy`: `ESCALATE`, `RETRY_WITH_BACKOFF`, `PROCEED_WITH_WARNING`, `FAIL_CLOSED`.
  - `OutcomeContractSpec`: Pydantic schema with positive deadline validation and postcondition rules.
  - `IndependentObservation`: Authoritative observer payload with anti-staleness timestamp and 64-character SHA-256 evidence digest.
  - `OutcomeEscalationRequest` & `OutcomeEscalationResponse`: Human-in-the-loop escalation workflows.
- **`shared/schemas/action.py`**:
  - Added `outcome_contract` to `ActionProposal`.
  - Added `outcome_status`, `outcome_id`, and `requires_outcome_assurance` to `ActionExecutionResult`.
- **`db/models.py`**:
  - `ActionContract`: Added `requires_outcome_assurance` (Boolean), `outcome_contract` (JSONB), and `outcome_status` (String, indexed).
  - `OutcomeVerificationRecord`: Added `evidence_source` (String), `evidence_digest` (String, 64-char), `observed_at` (DateTime TZ), `verification_deadline` (DateTime TZ), `escalation_status` (String), and `escalation_notes` (Text).
- **`db/migrations/versions/016_phase6_outcome_assurance_lifecycle.py`**:
  - Additive migration for PostgreSQL 14+, creating column definitions, index on `action_contracts.outcome_status`, and granting `SELECT, INSERT, UPDATE` to `mirage_app` under Row-Level Security.

### 3.2 Action Governor Lifecycle Integration

- **`services/action_governor.py`**:
  - In `propose_and_authorize_action`: Evaluates whether the proposed action requires outcome assurance based on mutating type (`WRITE`, `DELETE`, `EXECUTE`, `EGRESS`), risk score $\ge 40$, autonomy $\ge 2$, or dollar cost $> 0$. Validates postconditions, acceptable sources, and positive deadlines. If missing and not escalated to human approval, blocks autonomously.
  - In `execute_action`: Enforces that transport acknowledgment != verified destination state. Mutating actions transition to `ActionState.EXECUTED` and create an `OutcomeVerificationRecord` in `PENDING_VERIFICATION` state with `epistemic_confidence = 0.0`.

### 3.3 Reality Verifier & Independent Observer

- **`services/reality_verifier.py`**:
  - `IndependentObserverAdapter`: Validates target resource, timestamp (`observed_at >= executed_at`), acceptable sources, digest format, and computes discrepancy violations.
  - `_redact_sensitive_payload`: Recursively sanitizes bearer tokens, API keys, passwords, and secrets.
  - `_validate_monotonic_transition`: Enforces state machine transition matrix.
  - `verify_action_outcome`: Auto-routes to `IndependentObserverAdapter` when observation payload is provided.
  - `reconcile_output_with_outcome`: Flags epistemic conflicts on `PENDING_VERIFICATION`, `VERIFIED_FAILURE`, and `PARTIAL_ACHIEVEMENT`.
  - `get_outcome_by_id`, `get_outcome_by_action_id`, `get_pending_outcomes`, and `escalate_outcome`: Queries, deadline expiration downgrade, and human escalation handler.

### 3.4 Gateway REST Endpoints

- **`gateway/routes/outcomes.py`**:
  - `GET /v1/outcomes/pending`: List all pending outcomes awaiting verification for tenant.
  - `GET /v1/outcomes/action/{action_id}`: Look up outcome record by action ID.
  - `POST /v1/outcomes/{outcome_id}/escalate`: Human operator escalation route.
  - Placed static route paths (`/pending`, `/action/{action_id}`) prior to parameterized `/{outcome_id}` to prevent FastAPI route collision.

### 3.5 Dashboard Frontend

- **`dashboard/src/api/outcomes.js`**:
  - Added `listPendingOutcomes`, `getOutcomeByAction`, and `escalateOutcome`.
- **`dashboard/src/views/OutcomeAssuranceView.jsx`**:
  - Updated `getStatusBadge` with canonical Phase 6 statuses (`PENDING_VERIFICATION`, `VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, `PARTIAL_ACHIEVEMENT`, `UNKNOWN`, `UNVERIFIABLE`).
  - Added pending verification filter and escalation review status tags.
  - Pure React 18 / JSX, zero TypeScript dependencies or `.ts` files. Build verified (`npm run build`: 1611 modules transformed in 2.04s).

---

## 4. Verification & Validation Evidence

### 4.1 Test Battery Execution Results

The comprehensive test battery was executed directly via Python `pytest` against actual PostgreSQL models and service instances. All 43 tests executed and passed cleanly:

```
tests/unit/test_outcome_state_machine.py::test_monotonic_state_machine_transition_rules PASSED
tests/unit/test_outcome_state_machine.py::test_independent_observer_adapter_verifies_success PASSED
tests/unit/test_outcome_state_machine.py::test_independent_observer_adapter_rejects_target_mismatch PASSED
tests/unit/test_outcome_state_machine.py::test_independent_observer_adapter_rejects_stale_observation PASSED
tests/unit/test_outcome_state_machine.py::test_independent_observer_adapter_rejects_untrusted_source PASSED
tests/unit/test_outcome_state_machine.py::test_independent_observer_adapter_rejects_malformed_digest PASSED
tests/unit/test_outcome_state_machine.py::test_sensitive_payload_redaction PASSED
tests/unit/test_outcome_state_machine.py::test_deadline_expiration_downgrades_to_unknown PASSED

tests/unit/test_outcome_contracts.py::test_action_proposal_blocks_mutating_action_without_postconditions PASSED
tests/unit/test_outcome_contracts.py::test_action_proposal_blocks_negative_verification_deadline PASSED
tests/unit/test_outcome_contracts.py::test_action_proposal_authorizes_valid_outcome_contract PASSED
tests/unit/test_outcome_contracts.py::test_execution_creates_pending_verification_record PASSED
tests/unit/test_outcome_contracts.py::test_read_only_action_completes_without_gate5_pending PASSED

tests/security/test_phase6_outcome_assurance.py::test_discrepancy_detection_flags_postcondition_failure PASSED
tests/security/test_phase6_outcome_assurance.py::test_partial_achievement_detected_on_multi_condition_batch PASSED
tests/security/test_phase6_outcome_assurance.py::test_strict_direct_only_policy_rejects_simulated_probes PASSED
tests/security/test_phase6_outcome_assurance.py::test_strict_direct_only_policy_rejects_inferred_observability PASSED
tests/security/test_phase6_outcome_assurance.py::test_reconciliation_flags_completion_claim_when_outcome_is_pending PASSED
tests/security/test_phase6_outcome_assurance.py::test_reconciliation_rejects_completion_claim_when_outcome_failed PASSED
tests/security/test_phase6_outcome_assurance.py::test_reconciliation_permits_honest_model_acknowledging_uncertainty PASSED
tests/security/test_phase6_outcome_assurance.py::test_operator_escalation_workflow PASSED
tests/security/test_phase6_outcome_assurance.py::test_cross_tenant_outcome_access_prevented PASSED

tests/unit/test_reality_verifier.py::test_database_adapter_direct_success PASSED
tests/unit/test_reality_verifier.py::test_database_adapter_mismatch_discrepancy PASSED
tests/unit/test_reality_verifier.py::test_http_adapter_ssrf_protection PASSED
tests/unit/test_reality_verifier.py::test_async_event_adapter_eventual_success PASSED
tests/unit/test_reality_verifier.py::test_async_event_adapter_timeout_unknown PASSED
tests/unit/test_reality_verifier.py::test_simulated_adapter_disclosure PASSED
tests/unit/test_reality_verifier.py::test_observability_class_blind_confidence_zero PASSED
tests/unit/test_reality_verifier.py::test_observability_class_inferred_transport_ack PASSED
tests/unit/test_reality_verifier.py::test_reconciliation_detects_false_completion_claims PASSED

tests/unit/test_action_contract.py::test_parameter_normalization_strips_whitespace_and_preserves_clean_values PASSED
tests/unit/test_action_contract.py::test_parameter_normalization_blocks_path_traversal PASSED
tests/unit/test_action_contract.py::test_parameter_normalization_blocks_ssrf_to_loopback_and_metadata PASSED
tests/unit/test_action_contract.py::test_parameter_normalization_canonicalizes_urls PASSED
tests/unit/test_compute_parameters_hash_is_invariant_to_key_insertion_order PASSED
tests/unit/test_action_contract.py::test_action_proposal_schema_defaults PASSED

tests/security/test_phase3_action_security.py::test_action_proposed_without_capability_is_denied PASSED
tests/security/test_phase3_action_security.py::test_action_violating_capability_constraints_is_denied PASSED
tests/security/test_phase3_action_security.py::test_dangerous_triad_interlock_blocks_external_egress PASSED
tests/security/test_phase3_action_security.py::test_salami_slicing_attack_triggers_approval_escalation PASSED
tests/security/test_phase3_action_security.py::test_agent_cannot_self_grant_human_approvals PASSED
tests/security/test_phase3_action_security.py::test_parameter_tampering_after_approval_invalidates_execution PASSED

======================= 43 passed, 14 warnings in 7.36s =======================
```

### 4.2 Static Analysis & Code Quality
- **Ruff Linter:** Ran `python -m ruff check shared/ db/ gateway/ services/ tests/`. Result: `All checks passed!` (zero lint or formatting violations).
- **Frontend Vite Build:** Ran `npm run build` in `dashboard/`. Result: `✓ 1611 modules transformed; built in 2.33s` with pure React 18 / JSX (zero TypeScript code or compiler dependencies).

---

## 5. Architectural Boundaries

- **Phase 7 Boundary Preserved:** Phase 7 Governed Memory and MCP Governance were strictly untouched and not begun.
- **Fail-Closed Guarantees:** All security and financial invariants preserved; missing postconditions fail closed; transport ACKs never masquerade as verification; expired deadlines strictly downgrade to UNKNOWN (confidence 0.0).

---

## 6. Phase 6 Validation, In-Scope Remediation, and Release Closure

### 6.1 In-Scope Remediation Summary
During the Phase 6 release closure review, four critical integrity and lifecycle gaps were identified, remediated, and empirically verified:

1. **Evidence Digest Cryptographic Recomputation:**
   - In `shared/schemas/outcome.py`, added canonical `compute_evidence_digest(observed_state)` and `compute_bound_evidence_digest(target_resource, observed_state)` utilizing sorted JSON keys (`json.dumps(..., sort_keys=True, separators=(",", ":"))`).
   - In `services/reality_verifier.py`, `IndependentObserverAdapter.verify` validates the SHA-256 format and recomputes the expected digest over the canonical payload. Any digest mismatch or payload tampering immediately fails closed with HTTP 400 Bad Request.

2. **Temporal Integrity Protections:**
   - `IndependentObserverAdapter.verify` now strictly rejects future timestamps (`observed_at > now_utc + 60s`) with HTTP 400 Bad Request.
   - It also rejects observations captured after the contract's verification deadline (`observed_at > executed_at + verification_deadline_seconds`) with HTTP 400 Bad Request.

3. **Observation ID Replay Defense & Terminal State Immutability:**
   - In `RealityVerifierService.verify_action_outcome`, cross-action observation reuse is strictly detected by querying existing tenant records. Recycled observation IDs are rejected with HTTP 409 Conflict.
   - Actions in terminal states (`VERIFIED_SUCCESS`, `SUCCESS_CONFIRMED`, `VERIFIED_FAILURE`, `FAILED`) are strictly immutable. Reverification attempts under distinct idempotency keys are rejected with HTTP 409 Conflict.
   - Expired verification deadlines strictly downgrade outcome status to `UNKNOWN` with confidence `0.0`, preventing late observations from converting expired actions into verified success.

4. **Gateway Alias Endpoints:**
   - Provisioned canonical alias routes:
     - `GET /v1/actions/{action_id}/outcome`
     - `POST /v1/actions/{action_id}/outcome`
     - `GET /v1/transactions/{transaction_id}/outcomes`
   - Verified tenant isolation and 404 behavior across tenant boundaries.

### 6.2 Empirical Test Execution Evidence

#### 1. Unit & Security Outcome Test Battery
Command: `pytest tests/unit/test_outcome_state_machine.py tests/unit/test_outcome_contracts.py tests/security/test_phase6_outcome_assurance.py tests/integration/test_phase5_reality_verification.py tests/unit/test_reality_verifier.py tests/unit/test_action_contract.py`
Output: **49 passed in 8.47s**

#### 2. Migration, Concurrency & Gate 5 Security Suite
Command: `pytest tests/security/test_postgres_outcome_migration.py tests/security/test_phase5_5_1_independent_audit.py tests/security/test_phase5_5_2_challenge.py tests/security/test_phase5_5_3_residual_closure.py tests/security/test_phase5_5_4_trusted_root.py tests/security/test_phase5_5_5_gate5_red_team.py tests/security/test_phase5_5_6_gate5_fail_closed.py tests/security/test_phase5_5_hardening.py`
Output: **169 passed in 10.92s** (including live PostgreSQL 16 Testcontainer migration downgrade/reupgrade cycles and concurrent audit ledger serialization).

#### 3. PostgreSQL Row-Level Security Isolation Battery
Command: `pytest tests/security/test_postgres_rls.py`
Output: **9 passed in 7.35s** (including `test_9_phase6_outcome_assurance_rls_isolation` testing SELECT isolation, cross-tenant UPDATE prevention, and RLS WITH CHECK policy rejection on spoofed cross-tenant INSERTs under the unprivileged `mirage_app` role).

#### 4. Static Analysis & Frontend Compilation
- `python -m ruff check shared/ db/ gateway/ services/ tests/`: **All checks passed!**
- `npm run build` (in `dashboard/`): **1611 modules transformed; built in 2.33s** (Pure React 18 / JSX, zero TypeScript).

---

## 7. Release Gate Decision

| Criterion | Requirement | Result | Status |
|:---|:---|:---|:---:|
| **Physical Reality Decoupling** | Tool ACKs and HTTP 200/202 never confer verified success | Enforced via `PENDING_VERIFICATION` (confidence 0.0) | **PASS** |
| **Evidence Digest Recomputation** | Recomputed over canonical observed state and bound resource | Enforced via SHA-256 canonical digest checks | **PASS** |
| **Temporal Integrity** | Future timestamps and expired observations rejected | Enforced with HTTP 400 Bad Request | **PASS** |
| **Replay Defense** | Observation IDs cannot be reused across actions | Enforced with HTTP 409 Conflict | **PASS** |
| **Terminal Immutability** | Terminal states cannot be mutated or reverified | Enforced with HTTP 409 Conflict | **PASS** |
| **PostgreSQL RLS** | Cross-tenant isolation on contracts and outcome records | Verified on PostgreSQL 16 under `mirage_app` role | **PASS** |
| **Frontend Conformance** | Pure React 18 / JSX; zero TypeScript compiler or files | Verified clean build (`npm run build`) | **PASS** |
| **Regression Safety** | Zero regressions across all existing gates | 227/227 outcome & security tests passing | **PASS** |

### **Final Release Decision: PASS**

Phase 6 (Outcome Assurance) is fully implemented, verified against live PostgreSQL infrastructure, hardened against adversarial tampering, and certified for release closure.

---
*Report certified by MIRAGE Core Engineering Team.*
