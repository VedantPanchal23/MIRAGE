# MIRAGE 3.0 — Consolidated Residual Risk & Documented Operational Limitations Register

> **Authoritative Specification:** [`docs/MIRAGE_3.0_Specification.md`](file:///c:/Users/vedan/Desktop/MIRAGE/docs/MIRAGE_3.0_Specification.md) (Section 12.7)  
> **Governance Document:** [`AGENTS.md`](file:///c:/Users/vedan/Desktop/MIRAGE/AGENTS.md) (Sections 7 & 11, Workstream F)  
> **Repository Commit SHA:** [`e5e5d52b1bdf69a686b24d788390b2e811c045aa`](https://github.com/VedantPanchal23/MIRAGE/commit/e5e5d52b1bdf69a686b24d788390b2e811c045aa)  
> **Release Target Disposition:** `MIRAGE PROJECT CLOSED — ACCEPTED WITH DOCUMENTED LIMITATIONS`

---

## 1. Executive Summary & Purpose

In accordance with Section 11 of [`AGENTS.md`](file:///c:/Users/vedan/Desktop/MIRAGE/AGENTS.md) and Section 12.7 of [`docs/MIRAGE_3.0_Specification.md`](file:///c:/Users/vedan/Desktop/MIRAGE/docs/MIRAGE_3.0_Specification.md), closing the MIRAGE 3.0 platform requires an explicit, evidence-backed accounting of all known operational boundaries, distributed execution constraints, and residual risks.

MIRAGE 3.0 enforces the core product promise:
$$\text{“Control AI before it acts. Verify AI after it acts.”}$$

While internal mutations, tenant isolation, and cryptographic audit ledgers are mathematically guaranteed under PostgreSQL ACID transactions and Row-Level Security, real-world AI execution interacts with external heterogeneous protocols, unprovisioned cloud environments, and physical hardware boundaries. This register records those boundaries with complete transparency.

---

## 2. Residual Risk & Limitations Register

| Risk ID | Title & Boundary Area | Affected Subsystem / Gate | Likelihood | Impact | Existing Architectural Controls | Residual Exposure | Mitigation & Acceptance Rationale | Responsible Role | Closure Status |
|:---|:---|:---|:---:|:---:|:---|:---|:---|:---:|:---:|
| `RSK-FENCE-01` | **Target-Side Fencing on External Protocols** | Gate 3 Action Assurance<br>[`services/action_governor.py`](file:///c:/Users/vedan/Desktop/MIRAGE/services/action_governor.py) | **High** | **Medium** | Pre-dispatch commit to `EXECUTING`; short-lived concurrency leases; `GovernedToolProxy` mediation; Gate 5 independent observation. | If an unmediated external target (SMTP, generic webhook) drops connection post-mutation, duplicate execution cannot be fenced on the target. | Inherent distributed systems boundary for protocols lacking conditional writes. Mediated fail-closed at Gate 3; operator reconciliation workflow enforced. | Platform Architect & Integration Lead | `ACCEPTED WITH DOCUMENTED LIMITATIONS` |
| `RSK-ANCHOR-02` | **Audit Ledger Storage & Notary Scope** | Gate 5 Reality Verifier<br>[`services/reality_verifier.py`](file:///c:/Users/vedan/Desktop/MIRAGE/services/reality_verifier.py) | **Low** | **Medium** | Database-resident SHA-256 hash chains; advisory locks; local HMAC-SHA256 notary file proofs; PostgreSQL RLS. | Host-level superuser compromise could tamper with database records and local keys offline. | Production enterprise deployments must integrate cloud WORM storage (S3 Object Lock Compliance Mode) or public ledger anchoring as documented in specification. | Security Engineer & Compliance Officer | `ACCEPTED WITH DOCUMENTED LIMITATIONS` |
| `RSK-CLOUD-03` | **Unprovisioned Cloud Staging Boundary** | Production Deployment<br>[`infra/terraform/`](file:///c:/Users/vedan/Desktop/MIRAGE/infra/terraform/) | **Medium** | **Low** | `scripts/verify_staging_release.py` validates all 22 Terraform & deployment artifacts; local PostgreSQL/MongoDB Testcontainers verified. | Live AWS network routing, VPC endpoints, and KMS key latency unverified in AWS cloud to preserve $0.00 cloud cost policy. | Deliberate engineering decision honoring the zero-AWS-charge constraint. Preflight code readiness verified; staging apply ready upon cloud authorization. | DevOps & Cloud Infrastructure Lead | `ACCEPTED WITH DOCUMENTED LIMITATIONS` |
| `RSK-SHRED-04` | **Cryptographic Memory Tombstoning vs. HSM Destruction** | Governed Memory<br>[`services/memory_service.py`](file:///c:/Users/vedan/Desktop/MIRAGE/services/memory_service.py) | **Low** | **Low** | Multi-store tombstoning; PostgreSQL RLS hard row deletion; Qdrant vector index eviction. | Unencrypted physical disk slack space could retain residual vector embeddings until overwritten. | Physical hardware key shredding requires dedicated enterprise HSM/KMS hardware. Mitigated by hosting on encrypted EBS/NVMe block storage. | Security Engineer | `ACCEPTED WITH DOCUMENTED LIMITATIONS` |
| `RSK-MCP-05` | **Untrusted Tool Output Instruction Injection** | Governed MCP Proxy<br>[`services/action_governor.py`](file:///c:/Users/vedan/Desktop/MIRAGE/services/action_governor.py) | **Low** | **Medium** | Tool outputs wrapped in `<untrusted_data>` delimiters; Dangerous Triad interlock blocks egress if confidential data present. | Novel adversarial injection payloads in tool responses could deceive the agent's internal reasoning turn. | Agent cannot execute unauthorized external actions even if deceived: Gate 3 evaluates all subsequent actions independently against capabilities and budgets. | AI Safety & Platform Architect | `ACCEPTED WITH DOCUMENTED LIMITATIONS` |
| `RSK-LATENCY-06` | **Heavy Verification Latency Under High Load** | Gate 4 Output Assurance<br>[`services/output_assurance.py`](file:///c:/Users/vedan/Desktop/MIRAGE/services/output_assurance.py) | **High** | **Low** | Verification escalation ladder (cheap deterministic checks first); speculative streaming buffer with out-of-band verification. | Interactive streaming chat experiences may experience 200ms–1500ms verification overhead for high-risk queries. | Formal trade-off between verification rigor and latency documented in `docs/Cost_Optimization.md`. Low-risk operations bypass heavy NLI. | ML Platform Engineer | `ACCEPTED WITH DOCUMENTED LIMITATIONS` |

---

## 3. In-Depth Operational Limitation Profiles

### Profile 1: External Protocol Fencing (`RSK-FENCE-01`)
- **Canonical Clause:** [`docs/MIRAGE_3.0_Specification.md §12.7.1`](file:///c:/Users/vedan/Desktop/MIRAGE/docs/MIRAGE_3.0_Specification.md#L520), [`AGENTS.md §2`](file:///c:/Users/vedan/Desktop/MIRAGE/AGENTS.md)
- **Detailed Mechanics:**  
  When an action mutates an internal SQL database, MIRAGE injects an expected fencing token into the mutation condition (`UPDATE target SET ... WHERE active_token = :token`). If another worker acquired a higher lease token in the interim, the target database natively rejects the mutation (`rows_affected == 0`).  
  However, when an agent dispatches an action across an external protocol that does not support conditional mutations (e.g., SMTP email dispatch, unversioned third-party REST webhooks, or legacy enterprise message queues), target-side fencing cannot be enforced remotely.
- **Failure Scenario:**  
  If the network drops between the tool proxy dispatch and the acknowledgment reception, the external side effect may have occurred remotely while MIRAGE records an execution timeout.
- **Compensating Controls:**
  1. **Two-Phase Commit:** MIRAGE commits `contract.state = EXECUTING` prior to dispatch. Local blind redispatch is rejected with HTTP 409 Conflict.
  2. **Gate 5 Observation:** When execution transport is unconfirmed, the action enters `EXECUTION_UNCERTAIN`. Epistemic outcome independence prohibits inferred transport acknowledgments (`OBS_INFERRED`) from resolving uncertain states.
  3. **Operator Reconciliation:** The action must be reconciled by an operator via `/v1/actions/reconcile` or confirmed via an independent Gate 5 read probe before retry is permitted.
- **Disposition:** **ACCEPTED WITH DOCUMENTED LIMITATIONS**.

---

### Profile 2: Audit Ledger Anchoring Scope (`RSK-ANCHOR-02`)
- **Canonical Clause:** [`docs/MIRAGE_3.0_Specification.md §12.7.2`](file:///c:/Users/vedan/Desktop/MIRAGE/docs/MIRAGE_3.0_Specification.md#L522), [`docs/Observability_and_Audit.md §7`](file:///c:/Users/vedan/Desktop/MIRAGE/docs/Observability_and_Audit.md)
- **Detailed Mechanics:**  
  MIRAGE maintains tamper-evident audit ledgers using PostgreSQL transaction-scoped advisory locks (`pg_advisory_xact_lock`) and monotonic sequence numbers ($N+1$). Each audit record's `chain_hash` is computed as:
  $$\text{chain\_hash} = \text{SHA-256}(\text{prev\_hash} \,\|\, \text{entry\_id} \,\|\, \text{decision} \,\|\, \text{verified\_at})$$
  This guarantees that any unauthorized update or deletion within the database table immediately breaks the cryptographic hash pointer chain during `/v1/audit/verify-chain`.
- **Limitation Boundary:**  
  The current implementation anchors trust internally within PostgreSQL tables and verifies against local HMAC-SHA256 notary checkpoint records on disk. While this defends against application-level attacks, SQL injection, and unauthorized API mutations, it does not provide true hardware non-repudiation against a rogue database administrator with direct physical disk access.
- **Compensating Controls:**
  1. PostgreSQL Row-Level Security isolates audit queries strictly by tenant.
  2. Non-root container privileges prevent application processes from accessing raw PostgreSQL data directories.
  3. The schema and architecture are fully prepared to export daily notary checkpoints to AWS S3 Object Lock in Compliance Mode.
- **Disposition:** **ACCEPTED WITH DOCUMENTED LIMITATIONS**.

---

### Profile 3: Unprovisioned Cloud Staging Boundary (`RSK-CLOUD-03`)
- **Canonical Clause:** [`AGENTS.md §2, §7`](file:///c:/Users/vedan/Desktop/MIRAGE/AGENTS.md), Phase Staging Directive
- **Detailed Mechanics:**  
  Throughout the MIRAGE 3.0 implementation, a strict non-negotiable policy was enforced: **zero AWS cloud resources provisioned and zero AWS charges incurred ($0.00).**
- **Validation Scope:**
  1. All AWS Terraform modules ([`infra/terraform/main.tf`](file:///c:/Users/vedan/Desktop/MIRAGE/infra/terraform/main.tf), [`ec2.tf`](file:///c:/Users/vedan/Desktop/MIRAGE/infra/terraform/ec2.tf), [`s3.tf`](file:///c:/Users/vedan/Desktop/MIRAGE/infra/terraform/s3.tf), [`variables.tf`](file:///c:/Users/vedan/Desktop/MIRAGE/infra/terraform/variables.tf)) have been reviewed, hardened, and verified via [`scripts/verify_staging_release.py`](file:///c:/Users/vedan/Desktop/MIRAGE/scripts/verify_staging_release.py).
  2. The bootstrap script was rewritten to eliminate insecure piped `jq` execution, replacing it with the canonical [`scripts/fetch_secrets.py`](file:///c:/Users/vedan/Desktop/MIRAGE/scripts/fetch_secrets.py) utility that writes runtime `.env` atomically (`0600` permissions) and fails closed on missing secrets.
  3. Ephemeral multi-service integration was validated using local Testcontainers (PostgreSQL 16 and MongoDB 7).
- **Limitation Boundary:**  
  Actual live network traffic passing through AWS Internet Gateways, NAT Gateways, VPC Security Groups, and real AWS Secrets Manager API endpoints in `us-east-1` has not been executed because doing so would violate the $0.00 cost directive.
- **Disposition:** **ACCEPTED WITH DOCUMENTED LIMITATIONS**.

---

### Profile 4: Governed Memory Sanitization & Hardware Key Destruction (`RSK-SHRED-04`)
- **Canonical Clause:** [`docs/MIRAGE_3.0_Specification.md §12.7.3`](file:///c:/Users/vedan/Desktop/MIRAGE/docs/MIRAGE_3.0_Specification.md#L525), [`docs/Memory.md §5`](file:///c:/Users/vedan/Desktop/MIRAGE/docs/Memory.md)
- **Detailed Mechanics:**  
  Governed memory deletion triggers a multi-store purge:
  1. PostgreSQL metadata row is marked tombstoned (`deleted_at = now`) or hard-deleted under tenant RLS.
  2. Associated vector embeddings in Qdrant are deleted via the vector collection API.
  3. Active working-memory cache keys in Redis are evicted immediately.
- **Limitation Boundary:**  
  In the absence of a dedicated Hardware Security Module (HSM) or per-tenant cryptographically wrapped envelope encryption, magnetic or flash memory drive blocks may retain deleted vector bytes in physical slack space until overwritten by the host OS.
- **Disposition:** **ACCEPTED WITH DOCUMENTED LIMITATIONS**.

---

## 4. Formal Acceptance & Risk Ownership Sign-Off

The six residual risks detailed above represent standard, well-bounded architectural constraints of distributed software execution and local deployment environments. None of the risks violate the core invariants of MIRAGE 3.0:
- **Identity & Authorization:** Strictly fail-closed.
- **Tenant Boundaries:** Mathematically partitioned via PostgreSQL RLS.
- **Two-Phase Commit:** EXECUTING state committed prior to tool dispatch.
- **Epistemic Outcome Independence:** Tool return value never accepted as proof of outcome.
- **Audit Hash Continuity:** Monotonically linked under advisory and row-level locks.

All six residual risks are formally **ACCEPTED WITH DOCUMENTED LIMITATIONS**.
