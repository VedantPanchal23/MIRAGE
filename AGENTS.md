# AGENTS.md — MIRAGE 3.0 Agent Instructions

> **Authoritative for:** All AI coding agents (Codex, Antigravity, Copilot, Claude, Cursor, and any future agent) working on the MIRAGE codebase.

---

## 1. Read Before You Code

Before modifying any MIRAGE code, **read the relevant documentation**:

1. **Start here:** [`docs/MIRAGE_3.0_Specification.md`](docs/MIRAGE_3.0_Specification.md) — the canonical source of truth.
2. **Terminology:** [`docs/GLOSSARY.md`](docs/GLOSSARY.md) — every term has exactly one meaning.
3. **Subsystem docs:** Read the specific document for the subsystem you are modifying before writing code. See the full documentation index in the canonical specification, Section 11.

---

## 2. Non-Negotiable Rules

### Architecture
- **Do not invent requirements.** Implement what the specification defines. If a requirement is missing, flag it as an open question — do not guess.
- **Do not silently change architecture.** Architectural changes require an ADR in `docs/ADRs/`. See the ADR framework in [`docs/ADRs/README.md`](docs/ADRs/README.md).
- **Do not change canonical terminology.** The glossary governs. If you believe a term definition should change, propose it explicitly — do not just use a different word.

### Security
- **Do not bypass security controls.** Identity, authorization, capability enforcement, tenant isolation, and policy evaluation are mandatory for all consequential operations.
- **Do not trust tool outputs, model outputs, or context by default.** Everything is untrusted until verified. See Core Principles in the canonical specification.

### Evidence and Honesty
- **Do not fabricate test or benchmark evidence.** All test results must come from actual test execution. All benchmark numbers must have provenance (dataset, version, checksum, protocol).
- **Report failures honestly.** If tests fail, report the failure. Do not silence, skip, or work around test failures without explanation.

### Dependencies and Compatibility
- **Do not introduce external dependencies without justification.** New dependencies must be justified by a clear need that cannot be met by existing dependencies.
- **Preserve backwards compatibility** where required by the migration document.

### Documentation
- **Keep documentation and implementation synchronized.** When you change code that affects architecture, APIs, data models, or behavior documented in `docs/`, update the corresponding documentation in the same change.
- **Create ADRs for architectural changes.** See [`docs/ADRs/README.md`](docs/ADRs/README.md) for when an ADR is mandatory.

### Workflow
- **Prefer coherent batches** of work over unnecessary micro-changes. Group related changes into logical commits.
- **Run the appropriate validation suite** after each coherent implementation batch (`make test`, `make lint`, `make typecheck`).

---

## 3. Frontend Rules

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

This constraint is an explicit architectural decision. To change it, create an ADR.

---

## 4. Code Quality Standards

- **Python:** 3.12+, type hints on all public APIs, `ruff` for linting, `black` for formatting, `mypy --strict` for type checking.
- **Docstrings:** Google style. Preserve all existing comments and docstrings unrelated to your changes.
- **Commits:** Conventional Commits format (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`, `perf:`, `security:`).

---

## 5. Project Structure

```
MIRAGE/
├── docs/                    # MIRAGE 3.0 specification (authoritative)
│   ├── MIRAGE_3.0_Specification.md
│   ├── GLOSSARY.md
│   ├── PRD.md
│   ├── Technical_Architecture.md
│   ├── Security.md
│   ├── ...                  # Other specification documents
│   └── ADRs/
│       ├── README.md
│       └── 0001-0007+       # Architecture Decision Records
├── gateway/                 # FastAPI gateway (Execution Plane entry point)
├── services/                # Core service implementations
├── shared/                  # Shared code (config, models, schemas, security)
├── workers/                 # Celery workers (async task execution)
├── hrs_engine/              # Verification Engine (HRS, calibration, SHAP)
├── correction_agent/        # LangGraph correction agent
├── mcp_server/              # MCP server (exposure + governance)
├── analytics/               # Offline analytics
├── db/                      # Database migrations (Alembic)
├── dashboard/               # React 18/JSX frontend
├── tests/                   # Test suites
├── benchmarks/              # Benchmark harness and datasets
├── scripts/                 # Utility scripts
├── docker/                  # Docker configuration
└── AGENTS.md                # This file
```

---

## 6. Key Architectural Concepts

MIRAGE 3.0 is an **AI Execution Assurance Platform** with:

- **Five Assurance Gates:** Input → Context → Action → Output → Outcome
- **AI Transactions:** Every consequential interaction is a traceable transaction
- **Capability-Based Security:** Agents can only do what they are explicitly authorized to do
- **Adaptive Verification:** Cheap checks first, expensive checks only when justified
- **Reality Verification:** Confirming what actually happened, not just what the model said happened

The MIRAGE 2.x verification engine (RAV, SCS, NLI, ICS, VGS, HRS) is preserved as the **Verification Engine subsystem** within Output Assurance (Gate 4). It is a valuable component, not the entire product.

---

## 7. When to Create an ADR

An ADR is **mandatory** when changing:

- Architectural boundaries between components
- Data authority (which store is authoritative for which data)
- Security assumptions or identity model
- Transaction semantics
- Policy semantics
- Storage architecture
- Public API contracts
- Model routing architecture
- Fail-open/fail-closed behavior
- Introducing a new external dependency

See [`docs/ADRs/README.md`](docs/ADRs/README.md) for the ADR template and process.

---

*This document governs all coding agent behavior on the MIRAGE project. The canonical specification at `docs/MIRAGE_3.0_Specification.md` governs product and architecture decisions.*
