# MIRAGE 3.0 — AI Execution Assurance Platform

> **Governing Principle:** *“Control AI before it acts. Verify AI after it acts.”*

MIRAGE 3.0 sits between AI systems and the real world to govern execution lifecycles, enforce identity, security, policy, reliability, and cost controls across multi-tenant production environments.

---

## 👥 Authors & Academic Affiliation
- **Vedant (23AIML042)** — CSPIT, CHARUSAT
- **Dax (23AIML076)** — CSPIT, CHARUSAT
- **Institution**: Chandubhai S. Patel Institute of Technology (CSPIT), CHARUSAT
- **Date**: October 2026

---

## 🏛️ The Five Assurance Gates

Every consequential AI interaction traverses the Five Assurance Gates:

1. **Gate 1 — Input Assurance**:
   - Identity verification, tenant attribution, and ASGI/WebSocket client header spoofing defense.
   - Dynamic Information Flow Control (DIFC) taint tracking (confidential, untrusted).
   - High-throughput prompt injection defense and DLP secret/PII sanitization.
   - Fail-closed security boundaries: unauthenticated or suspended tenants are immediately blocked.

2. **Gate 2 — Context Assurance**:
   - RAG evidence provenance, freshness validation, and knowledge-base generation tracking.
   - Strict `<trusted_instructions>` and `<untrusted_data>` delimiter encapsulation.
   - Governed Memory lifecycle with epistemic attestation tiers (`ATTESTED` vs `ADVISORY`).
   - Prevention of autonomous agent self-attestation and quarantine of poisoned context.

3. **Gate 3 — Action Assurance**:
   - Capability-based access control, tool trust verification, and schema parameter validation.
   - Blast-radius limiting with sliding-window aggregate spend and risk ceilings.
   - Mandatory dispatch through `GovernedToolProxy`; direct tool calls or unverified contracts immediately fail closed.
   - Cryptographic contract binding hashes detecting post-approval parameter and target resource tampering.
   - Single-use human-in-the-loop (HITL) approval tokens prohibiting agent self-approval.
   - Network egress security blocking SSRF, DNS-rebinding, decimal/hex/IPv6 obfuscations, and cloud metadata endpoints.
   - Governed MCP server integration (`STDIO` and `HTTP_STREAM`) with instant cascading tool revocation.

4. **Gate 4 — Output Assurance**:
   - Verification Engine featuring RAV, SCS, NLI, ICS, and VGS with LightGBM Meta-Learner.
   - Empirical uncertainty calibration via Isotonic Regression ($ECE < 0.05$) and Mondrian Conformal Prediction intervals (95% coverage).
   - Postcondition honesty: model claims of action completion without verified action execution are strictly blocked.
   - Real-time verification budgets with graceful degradation (`ALLOW_WITH_UNCERTAINTY`).
   - Autonomous LangGraph self-correction loop with bounded retries.

5. **Gate 5 — Outcome Assurance**:
   - **Epistemic Outcome Independence**: Core invariant enforcing that a tool execution return value or an agent's assertion is *not*, by itself, proof of a real-world outcome.
   - 4-class epistemic observability model: `OBS_DIRECT`, `OBS_EVENTUAL`, `OBS_INFERRED`, `OBS_BLIND`.
   - Independent reality verification adapters (`DatabaseStateAdapter`, `HttpResourceAdapter`, `AsyncEventAdapter`, `IndependentObserverAdapter`).
   - Monotonic outcome state machine (`PENDING_VERIFICATION`, `VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, `PARTIAL_ACHIEVEMENT`, `UNKNOWN`, `UNVERIFIABLE`).
   - Epistemic confidence scoring ($0.00$ to $1.00$) and automatic downgrade to `UNKNOWN` on deadline expiration.

---

## 📦 Project Architecture & Components

```
MIRAGE/
├── gateway/                 # FastAPI gateway (Execution Plane entry point, /v1/ routes)
│   ├── middleware/          # Auth, CORS, RBAC, PII, rate-limiting, tracing
│   └── routes/              # Tenants, auth, verify, actions, outcomes, memory, MCP, audit
├── services/                # Core domain services (Action, Governance, Reality, Memory, Audit)
├── sdk/                     # Official Python SDK (mirage-sdk) with sync and async clients
├── hrs_engine/              # Verification Engine (HRS, calibration, TreeSHAP)
├── workers/                 # Celery workers (async tasks, RAG ingestion, verification)
├── mcp_server/              # Governed MCP exposure and discovery server
├── db/                      # Database migrations (Alembic 001–023)
├── dashboard/               # React 18 / JSX operator dashboard (zero TypeScript)
├── tests/                   # Comprehensive test pyramid (unit, contract, security, integration)
├── scripts/                 # Operational utilities (migration preflight, backup & restore)
└── docker/                  # Hardened multi-container topology definitions
```

---

## 🚀 Quick Start (Development & Operations)

### Prerequisites
- Python 3.12+ (or 3.13)
- Docker & Docker Compose
- Node.js 20+ (for Dashboard)

### 1. Environment Setup
```bash
# Clone the repository
git clone https://github.com/VedantPanchal23/MIRAGE.git
cd MIRAGE

# Copy and configure environment variables
cp .env.example .env

# Verify database migration preflight
python scripts/migration_preflight.py --target-head 023_governed_mcp_servers
```

### 2. Launch Backing Services
```bash
# Start hardened multi-container topology
docker-compose up -d
```

### 3. Run Test Suites
```bash
# Backend Unit Tests
pytest tests/unit/

# Five Gates End-to-End Integration Tests
pytest tests/integration/test_five_gates_e2e.py

# Whole-Platform Security & Adversarial Tests
pytest tests/security/test_whole_platform_security.py tests/security/test_durable_execution_mcp_adversarial.py

# Python SDK Contract Tests
pytest tests/contract/test_sdk_contract.py

# Dashboard Tests (React 18 / JSX)
cd dashboard && npm test -- --run
```

---

## 🐍 Official Python SDK (`mirage-sdk`)

MIRAGE provides a typed Python SDK respecting all Five Assurance Gates:

```python
from mirage_sdk import MirageClient
from mirage_sdk.models import ActionProposal, PostconditionRule, PostconditionOperator

with MirageClient(base_url="http://localhost:8000", api_key="mirage_live_...") as client:
    # 1. Propose governed action
    action = client.propose_action(
        ActionProposal(
            action_type="EXECUTE_SQL",
            tool_name="database_query",
            parameters={"query": "UPDATE accounts SET balance = balance - 100 WHERE id = 1"},
            target_resource="db.accounts",
            idempotency_key="transfer-tx-98214-step-1",
            postconditions=[
                PostconditionRule(
                    target="db.accounts",
                    field="balance",
                    operator=PostconditionOperator.EQUALS,
                    expected_value=900,
                )
            ],
        )
    )

    # 2. Execute action under concurrency lease
    executed = client.execute_action(action.action_id)

    # 3. Verify real-world outcome independently (Gate 5)
    outcome = client.verify_outcome(
        action_id=executed.action_id,
        observations={"observed_balance": 900},
    )
    print(f"Outcome disposition: {outcome.status} (confidence: {outcome.epistemic_confidence})")
```

---

## 🛡️ Documented System Limitations

As established by the authoritative architectural specification and ADRs:
1. **Target-Side Fencing Boundary**: MIRAGE enforces two-phase commit leases (`EXECUTING`) prior to dispatch to prevent local duplicate redispatch. External systems without native conditional mutation support (e.g., SMTP or generic third-party webhooks) remain mediated-only; universal target-side fencing is not claimed across arbitrary third-party protocols.
2. **Database-Resident vs. External Storage**: Tamper-evident SHA-256 audit hash chains are serialized under PostgreSQL row locks and cross-checked against filesystem/HMAC-SHA256 notary anchor proofs. Full external WORM (Write Once Read Many) cloud object storage or public blockchain notarization requires provisioned external enterprise infrastructure.
3. **Hardware KMS Epistemic Shredding**: Memory deletion enforces cryptographic tombstoning and multi-store cache/vector eviction. True physical hardware key destruction requires integration with external dedicated HSM / KMS hardware.

---

## 📜 Documentation Index
- [Canonical Specification](docs/MIRAGE_3.0_Specification.md)
- [Glossary](docs/GLOSSARY.md)
- [Technical Architecture](docs/Technical_Architecture.md)
- [Security Architecture](docs/Security.md)
- [API Specification](docs/API_Specification.md)
- [Python SDK & Integration](docs/SDK_and_Integration.md)
- [Observability & Audit](docs/Observability_and_Audit.md)
- [Deployment & Operations](docs/Deployment_and_Operations.md)
- [Operational Runbooks](docs/runbooks/)
- [Architecture Decision Records (ADRs)](docs/ADRs/README.md)
- [Changelog](docs/CHANGELOG.md)

---

## 📜 License & Citation
Research project developed at CSPIT, CHARUSAT. All rights reserved.
