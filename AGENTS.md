# AGENTS.md — MIRAGE 3.0 Agent Instructions and Final Product Roadmap

> **Authoritative for:** All AI coding agents (Codex, Antigravity, Copilot, Claude, Cursor, and any future agent) working on the MIRAGE codebase.

---

## 1. Read Before You Code

Before modifying any MIRAGE code or documentation, **read the relevant canonical specifications**:

1. **Start here:** [`docs/MIRAGE_3.0_Specification.md`](docs/MIRAGE_3.0_Specification.md) — the canonical source of truth.
2. **Terminology:** [`docs/GLOSSARY.md`](docs/GLOSSARY.md) — every term has exactly one authoritative meaning.
3. **Subsystem docs:** Read the specific document for the subsystem you are modifying before writing code (see index in `MIRAGE_3.0_Specification.md`, Section 11).
4. **Architecture Decision Records:** Inspect [`docs/ADRs/README.md`](docs/ADRs/README.md) and all accepted ADRs before proposing architectural adjustments.

---

## 2. Product Direction and Core Architectural Invariants

MIRAGE 3.0 is an **AI Execution Assurance Platform**. It sits between AI systems and the real world to govern execution lifecycle, enforce identity, security, policy, reliability, and cost controls.

### Product Promise
> **“Control AI before it acts. Verify AI after it acts.”**

### The Five Assurance Gates
Every consequential AI interaction traverses the Five Assurance Gates:
- **Gate 1 — Input Assurance:** Identity verification, tenant attribution, prompt-injection defense, policy evaluation, and abuse prevention.
- **Gate 2 — Context Assurance:** RAG evidence provenance, freshness validation, memory governance, and context poisoning prevention.
- **Gate 3 — Action Assurance:** Capability-based access control, tool registration/trust verification, blast-radius limiting, concurrency lease acquisition, parameter validation, and human-in-the-loop approval.
- **Gate 4 — Output Assurance:** Syntactic and semantic validation, factual consistency, safety bounds, and verification engine evaluation (RAV, SCS, NLI, ICS, VGS, HRS).
- **Gate 5 — Outcome Assurance:** Independent reality verification confirming actual real-world state transitions against predicted postconditions.

### Fundamental Security & Execution Invariants
- **Epistemic Outcome Independence:** A tool’s internal execution return value or an agent’s assertion is **not**, by itself, proof of a real-world outcome. Outcome claims must be confirmed by independent evidence gathered through Gate 5 reality verification.
- **State Machine Precision:** Always explicitly distinguish `PROPOSED`, `AUTHORIZED`, `EXECUTING`, `EXECUTION_UNCERTAIN`, `VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, `PARTIAL_ACHIEVEMENT`, and terminal cancellation. Never conflate an unconfirmed in-flight state with verified success.
- **Execution Boundaries and Fencing Reality:** Two-phase execution commits `EXECUTING` prior to dispatch to prevent local blind redispatch. However, agents must never claim exactly-once remote side effects or universal target-side fencing across external protocols (e.g., SMTP or generic webhooks) unless the target system natively enforces conditional mutations. External targets are mediated at Gate 3; internal SQL adapters enforce conditional writes.
- **Fail-Closed Security:** Security, authorization, tenant isolation (PostgreSQL RLS), lease fencing, policy evaluation, and audit recording must remain strictly fail-closed. If context or tenant attribution is missing, the operation must abort.

---

## 3. Non-Negotiable Engineering Rules

### Architecture
- **Do not invent requirements.** Implement what the specification defines. If a requirement is missing, flag it as an explicit open question — do not guess.
- **Do not silently change architecture.** Architectural changes require an ADR in `docs/ADRs/`. See the ADR framework in [`docs/ADRs/README.md`](docs/ADRs/README.md).
- **Do not change canonical terminology.** The glossary governs. Propose terminology changes explicitly; never introduce parallel jargon.

### Security
- **Do not bypass security controls.** Identity, authorization, capability enforcement, tenant isolation (PostgreSQL RLS), and policy evaluation are mandatory for all consequential operations.
- **Do not trust untrusted data.** Model outputs, tool outputs, external webhook payloads, and retrieved context are untrusted until verified.

### Evidence and Honesty
- **Do not fabricate test or benchmark evidence.** All test results must come from actual, executed commands. All benchmark metrics must include provenance (dataset, version, checksum, protocol).
- **Report failures honestly.** If tests fail, report the exact failure. Never silence, skip, or work around test failures without explicit justification.
- **Distinguish test environments.** Explicitly distinguish unit tests, mocks, SQLite tests, live PostgreSQL/Redis Testcontainers, and unprovisioned production infrastructure. Never substitute a mock while claiming real-database verification.

### Dependencies and Compatibility
- **Do not introduce external dependencies without justification.** New dependencies must be justified by a clear need that cannot be met by existing libraries.
- **Preserve backwards compatibility** across API schemas, database migrations, and persistent audit ledgers.

### Documentation
- **Keep documentation and implementation synchronized.** When changing code that affects architecture, APIs, data models, or behavior documented in `docs/`, update the corresponding documentation in the same work package.

---

## 4. Frontend Rules

**JavaScript and JSX only.** The MIRAGE frontend uses:
- React 18
- Vite
- JavaScript (`.js`)
- JSX (`.jsx`)

**Do NOT introduce:**
- `.ts` or `.tsx` files
- `tsc` or TypeScript compiler
- TypeScript ESLint plugins
- TypeScript dependencies

This constraint is an explicit architectural decision. To change it, an accepted ADR is required.

---

## 5. Code Quality Standards

- **Python:** 3.12+, strict type hints on all public APIs, `ruff` for linting and formatting, `mypy --strict` for type checking.
- **Docstrings:** Google style. Preserve all existing comments and docstrings unrelated to your changes.
- **Commits:** Conventional Commits format (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, `perf:`, `security:`).
- **Git Discipline:** Never force-push or discard user work in the tree.

---

## 6. Project Structure

```
MIRAGE/
├── docs/                    # MIRAGE 3.0 specification (authoritative)
│   ├── MIRAGE_3.0_Specification.md
│   ├── GLOSSARY.md
│   ├── PRD.md
│   ├── Technical_Architecture.md
│   ├── Security.md
│   ├── ...                  # Subsystem specification documents
│   ├── reports/             # Phase audit and closure reports
│   └── ADRs/                # Architecture Decision Records
│       ├── README.md
│       └── 0001-0008+
├── gateway/                 # FastAPI gateway (Execution Plane entry point)
│   ├── middleware/          # Auth, CORS, RBAC, PII, rate-limiting
│   └── routes/              # Versioned API routes (/v1/...)
├── services/                # Core service implementations (Action, Governance, Reality, Memory, etc.)
├── shared/                  # Shared models, schemas, config, audit utilities
├── workers/                 # Celery workers (async task execution)
├── hrs_engine/              # Verification Engine (HRS, calibration, SHAP)
├── correction_agent/        # LangGraph correction agent
├── mcp_server/              # MCP server (exposure + governance)
├── analytics/               # Offline analytics and calibration
├── db/                      # Database migrations (Alembic) and session managers
├── dashboard/               # React 18 / JSX frontend
├── tests/                   # Comprehensive test pyramid (unit, integration, security)
├── benchmarks/              # Benchmark harness and datasets
├── scripts/                 # Operational and utility scripts
├── docker/                  # Docker container definitions
└── AGENTS.md                # This file
```

---

## 7. The Consolidated Final Phase Roadmap

The remaining product roadmap is organized as **one consolidated final phase**, not separate future phases for each subsystem. No follow-on phases will be proposed after this phase.

All remaining implementation, hardening, and verification work is organized across six integrated workstreams within this single final phase:

### Workstream A: Tool Governance, MCP, and API Integration
- Complete tool and MCP server registration, lifecycle, trust scoring, health checks, and runtime revocation.
- Governed tool discovery and invocation via `GovernedToolProxy`.
- Strict agent identity binding, capability checks, tenant boundaries, and policy enforcement on every tool call.
- Risk assessment, approval workflows, schema parameter validation, and fail-closed handling of malformed or malicious inputs.
- Comprehensive tool-call tracing and outcome evidence capture.
- REST/API contract consistency across all `/v1/` routes.
- Protection against SSRF, unauthorized egress, credential leakage, and instruction injection in untrusted tool outputs.
- Explicit documentation of target-side fencing boundaries (internal conditional mutation vs. mediated-only external targets).

### Workstream B: Observability, Audit, and Compliance
- Correlated distributed tracing across AI transactions, agent handoffs, policy evaluations, tool invocations, and Gate 5 outcomes.
- Structured JSON logging, Prometheus metrics, operational alerts, and real-time error visibility.
- Tenant-scoped audit querying, filtering, and export (JSONL / compliance summaries).
- Cryptographic audit-chain integrity verification, retention enforcement, and access controls.
- Clear distinctions between database-resident hash chains, externally anchored notary evidence, and immutable object storage.
- Audit evidence sufficient to reconstruct denials, retries, stranded execution, and reality discrepancies.

### Workstream C: Dashboard and Developer SDK
- Complete operator management workflows for agents, delegations, handoffs, tools, MCP servers, policies, approvals, transactions, execution states, leases, outcomes, and audit ledgers.
- Accurate representation of loading, error, denied, pending, uncertain, retry, and terminal states (no mock data in production flows).
- Stable, documented Python SDK supporting authenticated transactions, schema validation, pagination, idempotency keys, safe retries, and comprehensive contract tests.
- Full alignment between React 18/JSX dashboard components, Python SDK methods, and backend OpenAPI contracts.

### Workstream D: SaaS Readiness
- Complete tenant and user lifecycle management (provisioning, suspension, offboarding).
- Role-based and attribute-based access control with least-privilege administrative boundaries.
- API-key generation, hashing, rotation, expiration, and instant revocation.
- Tenant-safe quotas, rate limits, usage metering, and transaction cost attribution.
- Data retention policies, tenant-scoped export, and verifiable cryptographic sanitization/deletion.
- Cost accounting and budget tracking; billing integration only if explicitly defined by the core product scope (do not invent unneeded billing mechanisms).

### Workstream E: Production Deployment and Operations
- Fully reproducible deployment topology across Docker Compose and Kubernetes.
- Container hardening (non-root execution, read-only root filesystems, dropped Linux capabilities).
- Production TLS enforcement, secrets management integration, and zero hardcoded credentials.
- Reliable Alembic database migrations with automated pre-flight checks and rollback procedures.
- Health (`/v1/health`), readiness (`/v1/ready`), and metrics (`/v1/metrics`) endpoints for orchestrator probes.
- Operational runbooks for incident triage, stranded-action reconciliation, backup/restore validation, and capacity planning.
- Clear demarcation between locally verified behavior, integration-tested behavior, and cloud infrastructure that has not been provisioned.

### Workstream F: Whole-Platform Integration and Final Closure
- End-to-end integration testing of all Five Assurance Gates executing as a unified pipeline.
- Live PostgreSQL verification of multi-tenant Row-Level Security, transaction boundaries, connection pooling, and advisory locking.
- Adversarial security validation covering cross-agent privilege escalation, delegation revocation cascades, stale fencing tokens, replay attacks, and Gate 5 epistemic independence.
- Supported MCP protocol integration tests and target-adapter verification.
- Full regression test execution across unit, integration, security, and frontend suites.
- Production of an exhaustive Requirements-to-Implementation-to-Test Evidence Matrix.
- Formulation of a residual-risk register and release-quality deployment readiness report.

---

## 8. High-Throughput Agent Workflow: Larger, Coherent Work Packages

To maximize engineering velocity while ensuring architectural integrity, coding agents and prompt authors must follow these work-packaging rules:

- **Substantial, Coherent Batches:** Plan and execute work in substantial vertical slices or bounded subsystem integration packages. Avoid micro-prompts that modify only single lines or isolated trivial files.
- **Full Vertical Slice Scope:** Combine closely related database schemas, Alembic migrations, service logic, API endpoints, dashboard components, regression tests, and documentation updates into one logically bounded work package.
- **Comprehensive Test Coverage in the Batch:** Every package must include positive unit tests, negative error handling, adversarial edge cases, regression verification, and live integration tests where infrastructure permits.
- **No Artificially Bloated Packages:** Do not bundle unrelated changes together merely to make a package larger. Each work package must have well-defined boundaries, unambiguous acceptance criteria, and a clean, reviewable diff.
- **Inspect Before Rebuilding:** Thoroughly inspect existing services and utilities before writing code. Reuse and harden existing components rather than inventing parallel mechanisms.
- **Strict Validation Reporting:** Execute the appropriate validation suite (`pytest`, `vitest`, `ruff`) for the entire batch. Report exact commands, exit codes, pass/fail counts, and any skipped tests with reasons.
- **Stop at Architectural Boundaries:** If an implementation batch encounters an unexpected dependency blocker, architectural contradiction, or security gap, stop immediately. Document the evidence and propose the minimal safe decision before proceeding.
- **Never Claim Unverified Success:** Writing code or passing a mock unit test does not prove a real-world guarantee. State exactly what was tested and what remains unverified.

---

## 9. The User's One-Prompt-at-a-Time Collaboration Protocol

All coding-agent engagements on MIRAGE adhere to this strict sequence:

```
[Assistant] Formulates one detailed prompt for a substantial, coherent work package
     │
     ▼
[User] Executes that prompt in their repository coding agent
     │
     ▼
[Coding Agent] Executes work, runs validation, commits, and returns evidence report
     │
     ▼
[Assistant] Critically reviews report (security assumptions, test results, diff, regressions)
     │
     ▼
[Assistant] Formulates the NEXT prompt only after the previous batch is verified
```

### Collaboration Rules:
1. **No Prompt Queues:** Never provide the user with a speculative queue of multiple prompts in advance. Each prompt depends on the verified repository state and test results of the prior prompt.
2. **Review Is Mandatory:** Larger, higher-throughput prompts do not bypass critical review. Every completed work package must be reviewed for security rigor, test authenticity, and architectural alignment.
3. **Honest Execution Claims:** Do not claim that repository changes were committed or tests were executed unless the commands actually ran and succeeded.

---

## 10. When to Create an ADR

An Architecture Decision Record (ADR) in `docs/ADRs/` is **mandatory** when:
- Altering architectural boundaries between subsystems.
- Changing data authority (which data store is authoritative for an entity).
- Modifying security assumptions, identity models, or capability structures.
- Changing transaction, policy, or execution lifecycle semantics.
- Introducing a new external dependency or service.
- Modifying public REST API contracts or error schemas.
- Changing fail-open vs. fail-closed behavior.

See [`docs/ADRs/README.md`](docs/ADRs/README.md) for the ADR template and numbering convention.

---

## 11. Final Release Dispositions

At the conclusion of the consolidated final phase, the project must issue exactly one evidence-backed release disposition:

### `MIRAGE PROJECT CLOSED — ACCEPTED WITH DOCUMENTED LIMITATIONS`
Use only when:
- All core guarantees across the Five Assurance Gates have adequate empirical evidence.
- Critical and high-priority security findings are remediated or demonstrably bounded.
- All residual limitations (e.g., target-side fencing limits on external protocols, database-resident vs. externally anchored audit logs) are explicitly documented.
- Full test suites pass with zero regressions.

### `MIRAGE PROJECT HOLD — CRITICAL REMEDIATION REQUIRED`
Use when:
- Any critical security or architectural invariant fails.
- Essential evidence for tenant isolation, durable execution, or authorization is unavailable.
- Unresolved regressions or vulnerabilities block production readiness.

> **Finality Commitment:** No subsequent phases or extensions will be proposed following final project closure.
