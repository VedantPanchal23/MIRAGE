# MIRAGE 3.0 — AI Execution Assurance Platform

<div align="center">

[![CI](https://github.com/VedantPanchal23/MIRAGE/actions/workflows/ci.yml/badge.svg)](https://github.com/VedantPanchal23/MIRAGE/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/Frontend-React%2018%20%2B%20Vite%20%28JSX%29-61dafb.svg)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-13%20Services%20Hardened-2496ed.svg)](https://www.docker.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16.4%20RLS%20Enforced-336791.svg)](https://www.postgresql.org/)

<br />

**“Control AI before it acts. Verify AI after it acts.”**

*A zero-trust, multi-tenant execution assurance platform governing autonomous agent lifecycles, capability authorizations, real-world tool invocations, and independent postcondition verification.*

</div>

---

## Executive Overview & Core Invariant

Modern autonomous agents invoke external APIs, execute SQL writes, and act across distributed tools without kernel-level mediation. **MIRAGE 3.0** sits between AI models/agents and external infrastructure to route every consequential transaction through the **Five Assurance Gates**:

```mermaid
flowchart LR
    In(["User / Agent Request"]) --> G1["Gate 1: Input Assurance"]
    G1 --> G2["Gate 2: Context Assurance"]
    G2 --> G3["Gate 3: Action Assurance"]
    G3 --> Proxy["Governed Tool / MCP Proxy"]
    Proxy --> G5["Gate 5: Outcome Assurance"]
    G5 --> G4["Gate 4: Output Assurance"]
    G4 --> Out(["Verified Output & SHA-256 Audit Ledger"])

    classDef gate fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#fff;
    classDef io fill:#0f172a,stroke:#64748b,stroke-width:1px,color:#94a3b8;
    class In,Out io;
    class G1,G2,G3,G4,G5,Proxy gate;
```

### The Invariant of Epistemic Outcome Independence
> An agent's self-report or a tool's HTTP `200 OK` return value is **never** proof of a real-world side effect. Outcome claims must be confirmed via independent Gate 5 reality verification probes (`OBS_DIRECT`, `OBS_EVENTUAL`, `OBS_INFERRED`, `OBS_BLIND`).

---

## The Five Assurance Gates

1. **Gate 1 — Input Assurance (`gateway/middleware/`, `gateway/routes/transactions.py`):** Verifies JWTs and hashed API keys (`mirage_live_...`), strips client-spoofable headers (`X-Role`, `X-Tenant-ID`), evaluates scope attenuation ($\text{Role Ceiling} \cap \text{Key Scopes}$), runs Redis Lua token-bucket rate limits, and scans prompts for injection/PII/secrets.
2. **Gate 2 — Context Assurance (`services/context_assurance.py`, `services/governed_memory.py`):** Enforces `<trusted_instructions>`/`<untrusted_data>` delimiters, Qdrant document freshness, `ATTESTED` vs `ADVISORY` memory separation (agents cannot self-attest), and Dynamic Information Flow Control (DIFC) taint tracking.
3. **Gate 3 — Action Assurance (`services/action_governor/`, `services/mcp_registry_service.py`):** Enforces capability authorization, mandatory `GovernedToolProxy` mediation, 1-hour salami-slicing blast radius quotas (`$1,000` spend / `250` risk / `50` ops), anti-SSRF and traversal validation, Redis monotonic leases/fencing tokens, cryptographic `contract_binding_hash`, and single-use L4 HITL approvals.
4. **Gate 5 — Outcome Assurance (`services/reality_verifier/`):** Executes out-of-band reality probes (`DatabaseStateAdapter`, `HttpResourceAdapter`, `AsyncEventAdapter`, `IndependentObserverAdapter`) using monotonic state transitions (`PENDING_VERIFICATION` → `VERIFIED_SUCCESS` / `VERIFIED_FAILURE` / `PARTIAL_ACHIEVEMENT` / `EXECUTION_UNCERTAIN`).
5. **Gate 4 — Output Assurance (`hrs_engine/`, `workers/`, `correction_agent/`):** Runs FLAN-T5 claim decomposition, parallel **RAV / SCS / NLI (DeBERTa-v3) / ICS / VGS** signal scoring, **LightGBM** fusion, **Isotonic Calibration**, **Mondrian Conformal 95% confidence bounds**, **TreeSHAP** attribution, postcondition honesty checks, and bounded **LangGraph** self-correction.

---

## Container Topology (13 Services)

`docker-compose.yml` defines **13 hardened services** (12 persistent containers + 1 one-shot Alembic `migration` runner) across `frontend_net`, `backend_net`, and `observability_net`:

| Service | Image / Dockerfile | Network(s) | Exposed Host Port | Hardening Summary |
| :--- | :--- | :--- | :--- | :--- |
| `dashboard` | `docker/Dockerfile.dashboard` | `frontend_net` | `3000` (`:8080` internal) | Unprivileged Nginx (`101:101`), `read_only`, `cap_drop: ALL` |
| `gateway` | `docker/Dockerfile.gateway` | `frontend_net`, `backend_net`, `observability_net` | `8000` | Non-root (`1000:1000`), `read_only`, `cap_drop: ALL`, `audit_anchors` vol |
| `grafana` | `grafana/grafana:11.2.0` | `observability_net` | `3001` (`:3000` internal) | Provisioned dashboards (`docker/grafana/`) |
| `worker` | `docker/Dockerfile.worker` | `backend_net`, `observability_net` | *Internal only* | Non-root (`1000:1000`), `read_only`, `cap_drop: ALL` |
| `migration` | `docker/Dockerfile.gateway` | `backend_net` | *Internal only* | One-shot `alembic upgrade head` (DDL role `mirage`, head `026`) |
| `postgres` | `postgres:16.4-alpine3.20` | `backend_net` | *Internal only* | `FORCE ROW LEVEL SECURITY`, runtime user `mirage_app` (`NOBYPASSRLS`) |
| `mongodb` | `mongo:7.0.12` | `backend_net` | *Internal only* | Authenticated per-tenant trace collections + TTL indexes |
| `qdrant` | `qdrant/qdrant:v1.12.0` | `backend_net` | *Internal only* | API-key protected HNSW vector engine |
| `redis` | `redis:7.2.5-alpine3.20` | `backend_net` | *Internal only* | Split ACLs (`mirage_app`, `mirage_celery`) + Lua token buckets |
| `rabbitmq` | `rabbitmq:3.13.6-management-alpine` | `backend_net` | *Internal only* | Quorum queues & Dead-Letter Exchange |
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.108.0` | `observability_net` | *Internal only* | OpenTelemetry trace collection & routing |
| `tempo` | `grafana/tempo:2.6.0` | `observability_net` | *Internal only* | Distributed trace backend |
| `prometheus` | `prom/prometheus:v2.54.1` | `observability_net` | *Internal only* | Internal Gateway `/metrics` scraping |

---

## Repository Source Structure

```text
MIRAGE/
├── gateway/               # FastAPI gateway, middleware (auth/rbac/pii/rate/security) & /v1/ routes
├── services/              # Core services (action_governor/, reality_verifier/, providers/, memory, mcp, tenant, audit)
├── workers/               # Celery tasks, orchestrator & signal workers (rav/, scs/, ics/, visual/)
├── hrs_engine/            # LightGBM meta-learner, isotonic calibration, Mondrian CP & TreeSHAP
├── correction_agent/      # LangGraph claim self-correction loop
├── mcp_server/            # Inbound JSON-RPC 2.0 MCP server & shield
├── analytics/             # Drift monitoring, audit service & PDF compliance reporting
├── db/                    # SQLAlchemy async models, session RLS, Redis/Mongo clients & 26 Alembic migrations
├── shared/                # Settings validation, Pydantic schemas, structlog, Prometheus & OTel tracing
├── dashboard/             # React 18 + Vite + Tailwind (JS/JSX only) Operator Console
├── sdk/                   # Python SDK (mirage-sdk) & zero-dependency JS SDK (sdk/js/@mirage-ai/sdk)
├── cli/                   # Developer CLI entrypoint (`mirage`)
├── benchmarks/            # Offline/Tier-1/Tier-2 benchmark datasets, guard & runner
├── scripts/               # Preflight, backup/restore, secrets serializer, smoke tests & Cloudflare tunnel
├── infra/ & k8s/          # AWS Terraform IaC & Kubernetes Helm chart
├── docker/                # Multi-stage Dockerfiles & datastore hardening configs
├── tests/                 # unit/, integration/, security/, contract/, chaos/, model_unit/, performance/
└── docs/                  # Consolidated technical & operational docs
```

---

## Quick Start & Public Demo

### Prerequisites
- Python `3.12+` (or `3.13`)
- Docker & Docker Compose `v2.20+`
- Node.js `20+` (for frontend development & Vitest)

### 1. Launch Stack & Run Verification
```bash
git clone https://github.com/VedantPanchal23/MIRAGE.git
cd MIRAGE

cp .env.example .env

# Run Alembic migration preflight check (26 revisions -> head: 026_add_execution_trace)
python scripts/migration_preflight.py --database-url sqlite:///./tmp_preflight.db

# Build and start all 13 services
docker compose up -d --build
docker compose ps
```
Platform launcher helpers: `./start-mirage.ps1`, `start-mirage.bat`, `./start-mirage.sh`.

- **Dashboard UI:** `http://localhost:3000`
- **FastAPI Gateway:** `http://localhost:8000` (`/v1/health`, `/v1/ready`, `/docs` when `DEBUG=true`)
- **Grafana:** `http://localhost:3001`

To share a zero-cost public HTTPS preview URL for demos:
```powershell
.\scripts\start-public-tunnel.ps1
```

### 2. Test & Quality Verification Suites
```bash
# Linting, formatting, strict typing & security scan
ruff check .
ruff format --check .
mypy --strict gateway hrs_engine correction_agent analytics mcp_server models shared workers benchmarks scripts tests/unit
bandit -r gateway hrs_engine correction_agent shared workers -ll -ii

# Backend tests & frontend Vitest suite
pytest tests/unit -v
cd dashboard && npm test -- --run && npm run build
```

---

## SDKs & Core REST API Overview (`/v1/`)

Install Python SDK & CLI:
```bash
pip install -e ".[dev]"
pip install -e "./sdk"
```

```python
from mirage_sdk import MirageClient
from mirage_sdk.models import (
    ActionProposal,
    ActionType,
    BlastRadius,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
    PostconditionRule,
)

with MirageClient(base_url="http://localhost:8000", api_key="mirage_live_...") as client:
    proposal = client.propose_action(
        ActionProposal(
            transaction_id="tx-acct-42",
            action_type=ActionType.WRITE,
            tool_name="database_query",
            target_resource="db.accounts",
            parameters={"query": "UPDATE accounts SET balance = 750 WHERE id = 42"},
            blast_radius=BlastRadius(estimated_dollar_cost=250.0, target_environment="STAGING"),
            postconditions=[PostconditionRule(field="balance", operator="eq", expected_value=750)],
        )
    )
    executed = client.execute_action(proposal.action_id)
    outcome = client.verify_outcome(
        OutcomeVerificationRequest(
            action_id=executed.action_id,
            verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
            observations={"balance": 750},
        )
    )
    print(outcome.outcome_status, outcome.epistemic_confidence)
```

| Group | Verified Key Endpoints |
| :--- | :--- |
| **Auth & Tenants** | `POST /v1/auth/register-tenant`, `GET /v1/auth/me`, `POST/GET /v1/auth/api-keys`, `.../rotate`, `.../revoke`, `/v1/admin/tenants/*` |
| **Transactions & Context** | `POST /v1/input-assurance`, `/v1/transactions/*`, `POST /v1/context/assemble`, `/v1/memory/*`, `/v1/kb/*` |
| **Actions & Approvals** | `POST/GET /v1/tools`, `POST /v1/actions/propose\|authorize\|execute`, `GET /v1/actions/stranded`, `POST .../reconcile`, `/v1/approvals/*`, `/v1/resources/leases/*` |
| **Verification & Outcomes** | `POST /v1/verify`, `POST /v1/output/assure`, `POST/WS /v1/verify/stream`, `POST /v1/chat/completions`, `POST /v1/outcomes/verify`, `GET /v1/outcomes/pending`, `POST .../reconcile`, `.../escalate` |
| **Governed MCP & Agents** | `POST /v1/mcp/rpc`, `POST/GET /v1/mcp/servers`, `PUT .../trust`, `POST .../discover`, `/v1/agents/*`, `/v1/delegations/*`, `/v1/handoffs/*` |
| **Audit, Reports & Health** | `POST /v1/audit/verify-chain`, `GET /v1/audit/events`, `GET /v1/audit/integrity`, `POST /v1/audit/export-bundle`, `POST /v1/audit/anchor`, `/v1/reports/*`, `GET /v1/health`, `GET /v1/ready`, `GET /metrics` |

---

## Documentation Index

- **[Architecture & System Specification](docs/ARCHITECTURE.md)** — Canonical Five Assurance Gates spec, planes, state machines, data model, source map & all Mermaid diagrams.
- **[API & SDK Reference](docs/API_AND_SDK.md)** — Auth/scope attenuation, complete `/v1/` routes, Python & JS SDKs, and CLI usage.
- **[Security, Compliance & Residual Risks](docs/SECURITY_AND_COMPLIANCE.md)** — Threat model, DIFC, cryptographic audit chain, and formally accepted operational boundaries (`RSK-FENCE-01`–`RSK-LATENCY-06`).
- **[Deployment, Operations & Runbooks](docs/DEPLOYMENT_AND_OPERATIONS.md)** — Docker Compose, Kubernetes Helm, cloud VPS, migrations, backup/restore & incident response.
- **[AWS Private Staging](docs/deployment/aws-private-staging.md)** — Terraform IaC (`infra/terraform/`) & SSM zero-inbound staging specification (ready for review; unprovisioned under `$0.00` cloud cost policy).
- **[Testing & Benchmarks](docs/TESTING_AND_BENCHMARKS.md)** — Test pyramid, CI jobs, benchmark certification guard & developer standards.
- **[Canonical Glossary](docs/GLOSSARY.md)** | **[Changelog](docs/CHANGELOG.md)** | **[ADRs](docs/ADRs/README.md)**

---

## Authors & Affiliation

- **Vedant Panchal (23AIML042)** & **Dax Virani (23AIML076)** — Department of Artificial Intelligence & Machine Learning, CSPIT, CHARUSAT
- **Project Disposition:** `MIRAGE PROJECT CLOSED — ACCEPTED WITH DOCUMENTED LIMITATIONS`
