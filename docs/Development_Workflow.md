# MIRAGE 3.0 — Development Workflow

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05

This document outlines the development workflow, quality standards, and AI agent instructions for the MIRAGE 3.0 codebase.

---

## 1. Core Principles

- **Documentation-First Development:** Developers and AI coding agents MUST read the governing specification and architecture documents before modifying code.
- **Consistency:** Use terminology consistent with `GLOSSARY.md`.
- **Quality:** Maintain high test coverage, strict typing, and comprehensive linting.

---

## 2. Git Workflow

- **Trunk-Based Development:** Main branch is `main`. Feature branches are merged via Pull Requests.
- **Conventional Commits:** Commit messages must follow conventional commits (e.g., `feat:`, `fix:`, `docs:`, `chore:`).

---

## 3. Code Quality Standards

- **Python Version:** Python 3.12+
- **Formatting:** `black`
- **Linting:** `ruff`
- **Type Checking:** `mypy --strict`
- **Frontend Constraints:** The frontend dashboard MUST use **JavaScript/JSX ONLY**. TypeScript, TSX, and `tsc` are strictly prohibited.

---

## 4. CI/CD Pipeline

The GitHub Actions pipeline consists of multiple stages:
1. **Linting & Formatting:** Runs `ruff`, `black`, and `eslint` (for React).
2. **Type Checking:** Runs `mypy --strict`.
3. **Unit Testing:** Runs `pytest`.
4. **Security Analysis:** Runs `bandit` and dependency vulnerability scans.
5. **Build & Integration:** Builds Docker containers and runs integration tests.

---

## 5. Agent Instructions (Rules for AI Coding Agents)

AI coding agents contributing to MIRAGE 3.0 MUST adhere to the following rules:
1. **Read governing documentation before coding.**
2. **Do not invent requirements.**
3. **Do not silently change architecture.**
4. **Do not change canonical terminology.**
5. **Do not bypass security controls.**
6. **Do not fabricate test or benchmark evidence.**
7. **Do not introduce dependencies without justification.**
8. **Preserve backwards compatibility where required.**
9. **Create ADRs for architectural changes.**
10. **Update documentation when architecture changes.**
11. **Run validation after coherent batches of work.**
12. **Report failures honestly.**

---

## 6. Testing Workflow

Use the provided Make targets for testing and development:
- `make test` — Run all tests
- `make test-unit` — Run unit tests
- `make lint` — Run linters
- `make docker-up` — Start the local development environment

---

## 7. Architecture Decision Records (ADRs)

Any change to architectural boundaries, security, identity, data storage, public APIs, or external dependencies requires an ADR. See `ADRs/README.md`.

---

## 8. Dependency Management

All Python dependencies are pinned using `requirements.txt` or `poetry.lock`. Any new dependency requires a security review and explicit justification.
