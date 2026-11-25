# MIRAGE 3.0 — Security Architecture, Compliance & Residual Risk Register

> **Status:** Authoritative — Project Closed | **Version:** 3.0.0  
> **Release Disposition:** `MIRAGE PROJECT CLOSED — ACCEPTED WITH DOCUMENTED LIMITATIONS`  
> **Related:** [`ARCHITECTURE.md`](ARCHITECTURE.md) | [`API_AND_SDK.md`](API_AND_SDK.md)

---

## 1. Threat Model & Active Mitigations

MIRAGE treats prompts, retrieved context, model responses, and external tool/MCP outputs as untrusted.

| Threat Vector | Failure Mode Mitigated | MIRAGE Architectural Enforcement |
| :--- | :--- | :--- |
| **Direct & Indirect Prompt Injection** | Model hijacking via user input or poisoned RAG chunks | Gate 1 scanner + Gate 2 `<trusted_instructions>`/`<untrusted_data>` delimiters + deterministic memory demotion |
| **MCP / Tool Output Poisoning** | Tool returning imperative instructions to hijack next turn | Untrusted output quarantine, `TAINT_UNTRUSTED` propagation, zero tool-to-tool ambient chaining |
| **Dangerous Triad Data Exfiltration** | `Private Data + Untrusted Input + External Egress` | Dynamic IFC Lattice interlock revokes `EGRESS_EXTERNAL` capabilities or escalates to mandatory `L4` HITL |
| **SSRF & Cloud Metadata Theft** | Redirecting HTTP tools or MCP clients to `127.0.0.1` / `169.254.169.254` | `SSRFSafeMCPHttpClient` & `ssrf_validator.py`: socket IP validation, DNS pinning, decimal/hex/octal IP blocking, redirect inspection, per-tenant egress allowlists |
| **Command Injection & Traversal** | Escaping filesystem/shell boundaries (`..`, `%00`, `shell=True`) | `SafeSubprocessMCPClient` (`create_subprocess_exec`, credential-scrubbed env) + NFKC recursive traversal neutralization |
| **Cross-Tenant Leakage & Spoofing** | Header forgery or reading another tenant's rows/vectors | ASGI header sanitization, `mirage_app` `NOBYPASSRLS` PostgreSQL Row-Level Security, per-tenant MongoDB collections, Qdrant tenant metadata filters |
| **Privilege Escalation & Billing Bypass** | API key abuse, agent self-approval, parameter tampering, unsigned billing webhooks | Scope attenuation (`Role Ceiling ∩ Key Scopes`), `requested_by != identity_id`, `contract_binding_hash`, single-use `CONSUMED` approval tokens, HMAC `Stripe-Signature`/`X-Razorpay-Signature` verification & Stripe settlement checks |
| **Salami-Slicing Blast Radius Attacks** | Splitting forbidden `$5,000` action into many `$10` steps | 1-hour rolling window quotas (`$1,000` spend, `250` risk pts, `50` ops) + hidden payload financial key extraction |
| **Epistemic Overclaiming** | Agent asserts success on unverified/write-only sinks | Gate 4 postcondition honesty checks + Gate 5 independent reality verification (`OBS_DIRECT`..`OBS_BLIND`) |
| **Audit Log Tampering / Truncation** | Altering or deleting historical execution evidence | Canonical 14-field SHA-256 hash chaining serialized via `pg_advisory_xact_lock` + external `FileAuditAnchorBackend` or AWS `S3ObjectLockAuditAnchorBackend` (`COMPLIANCE` WORM) |
| **GDPR Portability & Privacy Governance** | Unaudited data exports or unclear retention boundaries | Authenticated `GET /v1/privacy/export` (compliance ZIP dossier / JSON summary) & `GET /v1/privacy/retention` backed by PostgreSQL RLS |

---

## 2. Cryptographic Audit Chain & Integrity Verification

1. **Canonical Record Hashing (`compute_canonical_audit_hash`):** All 14 canonical audit attributes (`seq`, `entry_id`, `tenant_id`, `transaction_id`, `action_id`, `decision`, `prev_hash`, timestamps, digests) are serialized as deterministic compact JSON prior to SHA-256 hashing.
2. **Concurrency Serialization:** Appends acquire PostgreSQL transaction-scoped advisory locks (`pg_advisory_xact_lock`) and row-level locks (`SELECT ... FOR UPDATE` on `tenant_audit_ledgers`) ensuring gap-free monotonic sequences ($N+1$).
3. **External Anchoring & Truncation Detection:** `POST /v1/audit/anchor` commits the ledger head outside mutable PostgreSQL tables via configurable `AUDIT_ANCHOR_BACKEND`: local append-only per-tenant JSONL proof chains (`FileAuditAnchorBackend` with `fsync`) or WORM-locked Amazon S3 objects (`S3ObjectLockAuditAnchorBackend` with `ObjectLockMode="COMPLIANCE"`). `GET /v1/audit/integrity` cross-checks database heads against anchors and raises `INTEGRITY_FAILURE (TRUNCATION_DETECTED)` if rows are missing.

---

## 3. Consolidated Residual Risk & Documented Operational Limitations

In accordance with `AGENTS.md` §11 and final project closure requirements, all remaining distributed systems and unprovisioned infrastructure boundaries are explicitly bounded and accepted:

| Risk ID | Boundary Area | Subsystem | Likelihood / Impact | Compensating Controls | Acceptance Rationale |
| :--- | :--- | :--- | :---: | :--- | :--- |
| `RSK-FENCE-01` | **Target-Side Fencing on External Protocols** | Gate 3 (`action_governor`) | High / Med | Pre-dispatch commit to `EXECUTING`, Redis leases, `GovernedToolProxy`, Gate 5 reconciliation | Internal SQL adapters enforce conditional token writes. Protocols lacking conditional mutations (SMTP, generic webhooks) cannot enforce remote target fencing; mediated fail-closed at Gate 3 with operator `/reconcile`. |
| `RSK-ANCHOR-02` | **Database-Resident vs. External WORM Storage** | Gate 5 & Audit (`audit_anchor`) | Low / Med | PostgreSQL RLS, non-root containers, local HMAC-SHA256 chained anchor files (`fsync`) | Host-level DB superuser compromise can rewrite local tables/keys. Production deployments requiring hardware non-repudiation should bind checkpoints to S3 Object Lock Compliance Mode or a public transparency log. |
| `RSK-CLOUD-03` | **Unprovisioned Cloud Staging Boundary** | Cloud Deployment (`infra/terraform/`) | Med / Low | `verify_staging_release.py` (22 checks), CI `terraform validate`, live Postgres/Redis/Mongo integration tests | Live AWS VPC routing, KMS, and Secrets Manager latency remain unexecuted in AWS to honor the `$0.00` cloud spend policy. Ready to apply when AWS budget is authorized. |
| `RSK-SHRED-04` | **Logical Tombstoning vs. Physical HSM Key Destruction** | Memory (`governed_memory`) | Low / Low | Multi-store tombstoning, PG RLS hard delete, Qdrant index & Redis eviction | Physical disk slack space requires dedicated enterprise HSM/KMS envelope key destruction; mitigated operationally via encrypted EBS/NVMe volumes. |
| `RSK-MCP-05` | **Semantic Deception in Untrusted Tool Responses** | MCP Proxy (`mcp_client`) | Low / Med | `<untrusted_data>` wrapping, Dangerous Triad egress interlock, Gate 3 authorization | Malicious text inside an authorized tool response could confuse an agent's reasoning turn, but Gate 3 independently blocks unauthorized follow-on mutations and external exfiltration. |
| `RSK-LATENCY-06` | **Heavy Verification Latency Under Load** | Gate 4 (`hrs_engine`, `workers`) | High / Low | Adaptive escalation ladder (cheap DLP/regex first), speculative streaming buffer | High-risk factual claims incurring full NLI/SCS/RAV incur higher latency (seconds on CPU if uncached); low-risk traffic stays on fast deterministic paths. |

### Core Security Invariants Confirmed
- **Identity & Authorization:** Strictly fail-closed across JWT/API-key scope attenuation and tenant lifecycle states.
- **Tenant Isolation:** Mathematically enforced at storage via PostgreSQL `FORCE ROW LEVEL SECURITY` under unprivileged `mirage_app` (`NOBYPASSRLS`).
- **Execution Safety:** Two-phase `EXECUTING` commit prevents local blind redispatch; `EXECUTION_UNCERTAIN` forbids unverified `OBS_INFERRED` confirmation.
- **Disposition:** **`MIRAGE PROJECT CLOSED — ACCEPTED WITH DOCUMENTED LIMITATIONS`**.
