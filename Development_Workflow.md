# MIRAGE: Development Workflow & CI/CD
**Version:** 2.1.0
**Date:** September 2026
**Status:** Approved

---

## 1. Development Philosophy

For the MIRAGE project, our development philosophy is tailored to maximize efficiency, quality, and velocity for a two-person engineering team.

- **Trunk-based development adapted for a 2-person team:** We optimize for continuous integration. Short-lived feature branches are merged frequently into the integration branch.
- **Feature flags over long-lived branches:** Incomplete features are merged behind feature flags rather than kept in isolated, long-lived branches, reducing merge conflicts and integration pain.
- **Documentation-driven development (docs before code):** Architectural decisions, API contracts, and core interfaces must be documented and reviewed before implementation begins.
- **Observability from Day 1:** Logging, tracing, and metrics are not an afterthought. Every service must be instrumented before being merged.

## 2. Repository Structure

MIRAGE uses a monorepo approach to maintain consistency across services and simplify dependency management.

```text
mirage/
├── gateway/                 # FastAPI gateway service
├── workers/
│   ├── rav/                 # RAV module worker
│   ├── scs/                 # SCS module worker (n=5 Semantic Entropy)
│   ├── visual/              # Visual grounding worker (LLaVA + CLIP)
│   └── ics/                 # Internal Consistency worker (intra-response NLI)
├── models/
│   ├── flan_t5/             # FLAN-T5 claim decomposer server
│   ├── deberta/             # DeBERTa NLI verifier server
│   └── llava/               # LLaVA visual grounding server
├── hrs_engine/              # HRS aggregation (LightGBM) + Mondrian CP + TreeSHAP
├── correction_agent/        # LangGraph correction loop
├── dashboard/               # React 18 frontend
├── shared/                  # Shared utilities, schemas, config
│   ├── schemas/             # Pydantic models shared across services
│   ├── config/              # pydantic-settings configuration
│   ├── logging/             # structlog configuration
│   └── tracing/             # OpenTelemetry instrumentation
├── db/
│   ├── migrations/          # Alembic migrations
│   └── seeds/               # Seed data for development
├── tests/
│   ├── unit/
│   ├── model_unit/
│   ├── integration/
│   ├── contract/
│   ├── security/
│   ├── performance/
│   ├── chaos/
│   ├── adversarial/
│   └── fixtures/
├── scripts/                 # Utility scripts (benchmark runners, data prep)
├── docs/                    # Documentation
├── docker/
│   ├── Dockerfile.gateway
│   ├── Dockerfile.worker
│   ├── Dockerfile.ics_worker
│   ├── Dockerfile.flan_t5
│   ├── Dockerfile.deberta
│   ├── Dockerfile.llava
│   ├── Dockerfile.hrs_engine
│   ├── Dockerfile.correction_agent
│   └── Dockerfile.dashboard

├── docker-compose.yml
├── docker-compose.dev.yml
├── docker-compose.test.yml
├── pyproject.toml
├── .github/
│   └── workflows/
│       ├── ci.yml
│       ├── deploy-staging.yml
│       └── deploy-production.yml
├── .env.example
├── Makefile
└── README.md
```

## 3. Git Workflow

We utilize a simplified Git Flow suitable for a rapid-iteration small team.

### Branch Strategy
- **`main`**: Protected, always deployable. Represents the production state.
- **`develop`**: Integration branch. The default PR target for new features.
- **`feature/{module}-{description}`**: Short-lived branches for new functionality (e.g., `feature/rav-retrieval-pipeline`).
- **`fix/{description}`**: Branches for bug fixes.
- **`release/v{version}`**: Final stabilization branch before merging to `main` for a new release.

### Commit Conventions
We follow [Conventional Commits](https://www.conventionalcommits.org/).
- `feat:` A new feature
- `fix:` A bug fix
- `docs:` Documentation only changes
- `test:` Adding missing tests or correcting existing tests
- `chore:` Changes to the build process or auxiliary tools
- `refactor:` A code change that neither fixes a bug nor adds a feature
- `perf:` A code change that improves performance
- `security:` Security fixes or enhancements

*Example:* `feat(rav): implement dense retrieval using Qdrant`

### Pull Request Requirements
- At least 1 approval (from the other team member).
- All CI checks must pass.
- No decrease in overall test coverage (Codecov integration).

## 4. CI/CD Pipeline

Our GitHub Actions pipelines ensure code quality, security, and automated deployments.

### 4.1 CI Pipeline (on every PR)
Triggered on pull requests targeting `develop` or `main`.

```yaml
Stages:
  1. Lint & Format: ruff check, ruff format --check, isort --check, eslint (dashboard)
  2. Type Check: mypy --strict on all Python packages
  3. Unit Tests: pytest -m unit --cov, fail if coverage < 85%
  4. Security Scan: bandit -r ., safety check, npm audit (dashboard), trivy image scan
  5. Integration Tests: pytest -m integration (testcontainers)
  6. Contract Tests: schemathesis run openapi.yaml
  7. Build Images: docker build for all services (verify builds succeed)
```

### 4.2 Staging Deploy (on merge to `develop`)
```text
  1. Build and push Docker images to ECR
  2. Run Alembic migrations on staging DB
  3. Deploy via docker-compose on staging server
  4. Smoke tests against staging
  5. OWASP ZAP scan against staging
  6. k6 quick performance baseline
  7. Notify team via Slack/Discord
```

### 4.3 Production Deploy (on merge to `main`)
```text
  1. Build and push Docker images to ECR (tagged with version)
  2. Full k6 load test on staging
  3. SBOM generation (Syft)
  4. Docker Content Trust signing
  5. Run Alembic migrations on production DB
  6. Blue-green deployment via docker-compose (or EKS rolling update in Month 6)
  7. Post-deploy smoke tests
  8. Post-deploy monitoring (15-minute window for automatic rollback)
  9. Tag release in git
  10. Generate changelog
```

## 5. Code Standards

### Python
- **Formatter:** `ruff format` (Black-compatible).
- **Linter:** `ruff` (replaces flake8, isort, pyflakes).
- **Type Checker:** `mypy --strict`.
- **Style:** Max line length 120. Google-style docstrings.
- **Contracts:** All public functions must have type hints and docstrings. All Pydantic models require field descriptions. All FastAPI endpoints must have exhaustive OpenAPI descriptions.

### TypeScript/React (Dashboard)
- **Formatter:** Prettier.
- **Linter:** ESLint with React and TypeScript plugins.
- **Architecture:** All components must be functional components utilizing TypeScript. All API calls must route through a centralized API client.

### Docker
- Multi-stage builds are mandatory to minimize image size.
- Containers must execute as a non-root user.
- Comprehensive `.dockerignore` files for all contexts.
- Every `Dockerfile` must define a `HEALTHCHECK` instruction.

### SQL & Database
- Manual DDL is strictly prohibited; all changes via Alembic migrations.
- Queries must be parameterized to prevent SQL injection.
- Row-Level Security (RLS) policies must be reviewed on every schema alteration.

## 6. Development Environment Setup

### Prerequisites
- Python 3.12
- Node.js 20
- Docker & Docker Compose
- *GPU instance recommended for local model execution (e.g., A10G).*

### Makefile Targets
We rely on `make` for consistent local operations:
```bash
make setup          # Install dependencies, pre-commit hooks
make dev            # Start all services in dev mode
make test           # Run unit + model unit tests
make test-all       # Run all test categories
make lint           # Run all linters
make migrate        # Run Alembic migrations
make seed           # Seed development databases
make benchmark      # Run benchmark suite (requires GPU)
```

### Tooling
- **Pre-commit hooks:** Enforce `ruff`, `mypy`, and `bandit` locally before commits are accepted.
- **IDE:** VS Code with Ruff, Python, Pylance, Docker, and GitHub Pull Requests extensions.

## 7. Dependency Management

- **Python:** Managed via `pyproject.toml` with pinned dependencies. Use `pip-compile` to generate lockfiles.
- **Node.js:** Standard `package-lock.json`.
- **Docker:** Base images must be pinned by SHA-256 digest, not tags (e.g., `python:3.12-slim@sha256:...`).
- **Updates:** Monthly dependency update cycle driven by Dependabot. Minor and patch updates are auto-merged if CI passes; major version bumps require manual review and testing.

## 8. Environment Configuration

Configuration follows the 12-Factor App methodology.

- **Implementation:** `pydantic-settings` handles all configuration loading and validation.
- **Hierarchy:** Default values → `.env` file (local) → Environment Variables → AWS Secrets Manager.
- **Environments:** `development`, `test`, `staging`, `production`.
- **Security:** Sensitive values (API keys, DB credentials) are never hardcoded. In staging/production, they are fetched exclusively from AWS Secrets Manager.
- **Feature Flags:** Simple JSON configurations stored in Redis, allowing dynamic, per-tenant querying without redeployment.

## 9. Release Process

We adhere to **Semantic Versioning (MAJOR.MINOR.PATCH)**.

### Release Checklist
1. Verify all tests pass on the `develop` branch.
2. Create `release/vX.Y.Z` branch from `develop`.
3. Update version string in `pyproject.toml` and `package.json`.
4. Update `CHANGELOG.md` detailing new features, fixes, and breaking changes.
5. Execute the full benchmark suite on the release candidate.
6. Open PR against `main`, conduct final review, and merge.
7. Tag the release commit in Git (`vX.Y.Z`).
8. CI/CD automatically deploys to Production.
9. Conduct post-deployment verification (smoke tests in prod).
10. Announce release to stakeholders.

## 10. Monitoring and Rollback

- **Monitoring Window:** The system is closely monitored for 15 minutes post-deployment.
- **Automatic Rollbacks:** Triggered automatically if error rates exceed 5%, P95 latency exceeds 5 seconds, or critical health checks fail.
- **Manual Rollback:** Involves reverting `docker-compose` to the previous image tags. If schema changes are involved, execute an Alembic downgrade.
- **Model Rollbacks:** Model versioning is independent of application versioning. Models can be rolled back via configuration pointer updates and hot-swapped without restarting the application logic.

## 11. Documentation Standards

- Every code module (e.g., `gateway`, `workers/rav`) must contain a comprehensive `README.md`.
- All API endpoints are self-documenting via OpenAPI, strictly enforced by FastAPI and Pydantic constraints.
- **ADRs:** Architectural Decision Records must be maintained in `docs/adr/` for all major design choices.
- **Meeting Notes:** Design discussions and sync notes reside in `docs/decisions/`.
- Document versions are tracked, and a changelog is maintained for major structural updates.

## 12. Work Distribution (2-Person Team)

To maximize parallel execution while maintaining system cohesion, component ownership across the advanced v2.1.0 architecture is distributed as follows:

### Primary Ownership

#### Vedant (23AIML042)
- **Gateway & Proxy Layer:** FastAPI gateway, streaming/WebSocket endpoints, client authentication (JWT/API keys), rate limiting, circuit breaker middleware (`pybreaker`).
- **HRS Engine & Uncertainty Quantification:** LightGBM GBDT meta-learner (12-feature pipeline), 3-way calibration protocol (Isotonic Regression, Platt Scaling, Temperature Scaling), Mondrian (Group-Conditional) Conformal Prediction, TreeSHAP feature attribution engine.
- **Frontend Dashboard:** React 18 dashboard, real-time WebSocket verification feed, claim inspection tree, TreeSHAP waterfall charts, drift monitoring charts, and human evaluation consensus UI.
- **Observability & Infrastructure:** OpenTelemetry distributed tracing, Grafana Tempo, Prometheus metrics instrumentation, `structlog` JSON logging pipelines, and Docker Compose orchestration.
- **Benchmarking & Human Evaluation:** Offline benchmark runners (HaluEval, TruthfulQA, FActScoring), calibration curve generation, cross-model generalization benchmarks (Llama 3.1, Mixtral 8x7B, Gemma 2), k6 load testing, and double-blind human consensus protocol ($\kappa > 0.80$).

#### Dax (23AIML076)
- **RAV Module:** Qdrant vector database integration, hybrid retrieval (dense `all-mpnet-base-v2` + sparse BM25), multi-chunk evidence extraction, and source metadata tracking.
- **SCS Module (Semantic Entropy):** Asynchronous $n=5$ parallel generation sampling, DeBERTa bidirectional entailment clustering (Kuhn et al., 2023), semantic cluster probability aggregation, and discrete Semantic Entropy calculation.
- **ICS Module (Internal Consistency Scorer):** Intra-response pairwise claim extraction, symmetric contradiction matrix construction, and aggregate self-contradiction risk scoring ($ICS_{\text{resp}}$).
- **NLI Verifier & Claim Decomposition:** FLAN-T5 atomic claim decomposition with criticality classification (`high`, `medium`, `low`), DeBERTa-v3-large fine-tuning on HaluEval/MNLI, multi-evidence NLI score aggregation, and TorchServe / TGI model serving.
- **Visual Grounding:** Adaptive CLIP pre-filter ($t=0.85$), LLaVA-1.6 4-bit AWQ inference serving, and Visual Grounding Score (VGS) computation.
- **LangGraph Agentic Correction Loop:** Multi-step cyclical graph with bounded retries ($k \le 2$), evidence-grounded reprompting, and mandatory re-verification gating.
- **Security & Adversarial Testing:** Multi-tenant isolation (PostgreSQL RLS, MongoDB collection scoping), threat model implementation, secrets management, and 4-vector adversarial attack suite (ATK-01 through ATK-04).

### Shared Responsibilities
- **Zero-Cost Compute Strategy:** Leveraging Groq free tier, OpenRouter, Hugging Face Inference API, and institute GPU cluster (NVIDIA A10G 24GB).
- **CI/CD Pipeline Maintenance:** GitHub Actions workflows (linting, type checking, unit tests, integration tests with testcontainers, contract testing).
- **Integration & Chaos Testing:** End-to-end verification pipeline tests, toxiproxy fault injection, and network degradation simulations.
- **Human Annotation:** Active participation as primary annotators (Annotator 1 & Annotator 2) in the double-blind 100-response evaluation suite.
- **Academic Publication & Documentation:** Co-authoring the conference research paper, generating publication-ready LaTeX figures, and maintaining comprehensive technical documentation.

### Collaboration Mechanics
- **Code Review:** Every Pull Request MUST be reviewed and approved by the other team member with zero unresolved comments.
- **Branch Protection:** Direct commits to `main` and `develop` are prohibited; CI must pass 100% of checks before merge.
- **Weekly Sync:** A mandatory 1-hour weekly meeting to review milestone progress, benchmark results, unblock architectural dependencies, and align interfaces.

---

## 13. Document Changelog

| Version | Date | Description |
|---|---|---|
| 1.0.0 | August 2026 | Initial Draft Development Workflow & CI/CD Specification |
| 2.0.0 | September 2026 | Comprehensive rewrite: Monorepo layout, Git flow, 3-tier CI/CD pipelines, code standards (Ruff, mypy, Prettier), local setup Makefile, 12-factor config with pydantic-settings, release & rollback procedures. |
| 2.1.0 | September 2026 | Advanced Research Overhaul: Updated monorepo layout with `workers/ics/`, `Dockerfile.ics_worker`, `tests/adversarial/`; distributed ownership across new components (LightGBM meta-learner, Mondrian CP, TreeSHAP, Semantic Entropy clustering, Internal Consistency Scorer, Human Evaluation Protocol, and 4-vector adversarial testing). |

---
> [!NOTE]
> This workflow is engineered for high velocity, scientific rigor, and production reliability. Processes are reviewed monthly during team retrospectives.
