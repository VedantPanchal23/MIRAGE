# MIRAGE 3.0 — REST API, Streaming & SDK Guide

> **Status:** Authoritative | **Version:** 3.0.0  
> **Related:** [`ARCHITECTURE.md`](ARCHITECTURE.md) | [`SECURITY_AND_COMPLIANCE.md`](SECURITY_AND_COMPLIANCE.md)

---

## 1. Authentication & Scope Attenuation

All protected `/v1/` routes authenticate via `Authorization: Bearer <token>` (JWT or `mirage_live_...` API key) or `X-API-Key`.

- **Anti-Spoofing:** Client-supplied `X-Role`, `X-Tenant-ID`, and `X-User-ID` headers are stripped at ASGI ingress. Identity and tenant binding derive exclusively from verified credentials in PostgreSQL.
- **Tenant Lifecycle Gate:** Stored credential resolution (`mirage_resolve_api_credential`, `mirage_resolve_jwt_identity`) rejects `SUSPENDED` or `OFFBOARDED` tenants immediately.
- **Scope Attenuation Formula:**
  $$\text{Effective Permissions} = \text{Role Permission Ceiling} \cap \text{Granted API Key Scopes}$$
  A key carrying `scopes: ["verify:read"]` cannot invoke `POST /v1/verify` (`verify:write`), even if bound to `tenant_admin`.

### Canonical Roles & Permissions (`shared/schemas/auth.py`)
- **Roles:** `super_admin`, `tenant_admin`, `operator`, `viewer`, `api_client`
- **Permissions:** `verify:write`, `verify:read`, `dashboard:read`, `config:write`, `audit:read`, `audit:export`, `circuits:manage`, `kb:write`, `kb:read`, `alerts:acknowledge`

### Standardized Error Envelope (`gateway/main.py`)
All errors return structured JSON carrying `detail` plus `error: {code, message, trace_id, timestamp}`. Key codes: `BAD_REQUEST` (400), `UNAUTHORIZED` (401), `FORBIDDEN` (403), `NOT_FOUND` (404), `CONFLICT` (409), `RATE_LIMIT_EXCEEDED` (429), `SERVICE_DEGRADED` (503).

---

## 2. Authoritative `/v1/` Endpoint Inventory

Verified directly against [`gateway/main.py`](../gateway/main.py) and `gateway/routes/*.py`:

| Domain | Endpoints | Purpose |
| :--- | :--- | :--- |
| **Auth & Keys** (`auth.py`) | `POST /v1/auth/register-tenant`, `GET /v1/auth/me`, `POST /v1/auth/api-keys`, `GET /v1/auth/api-keys`, `GET /v1/auth/api-keys/{key_id}`, `POST /v1/auth/api-keys/{key_id}/rotate`, `POST /v1/auth/api-keys/{key_id}/revoke` | Tenant onboarding, identity inspection, hashed API key creation/rotation/revocation |
| **Tenant Admin** (`admin.py`) | `GET /v1/admin/tenants`, `POST /v1/admin/tenants`, `GET /v1/admin/tenants/{tenant_id}`, `PATCH /v1/admin/tenants/{tenant_id}`, `POST .../suspend`, `.../reactivate`, `.../offboard` | Super-admin multi-tenant provisioning and fail-closed lifecycle transitions |
| **Transactions & Input** (`transactions.py`) | `POST /v1/input-assurance`, `POST /v1/transactions`, `GET /v1/transactions/{transaction_id}`, `POST .../transitions`, `POST .../cancel`, `POST /v1/capabilities/validate`, `GET .../outcomes`, `GET .../hierarchy` | AI Transaction initialization, state machine transitions, Gate 1 input scans |
| **Context, Memory & KB** (`context.py`, `knowledge_base.py`) | `POST /v1/context/assemble`, `POST/GET /v1/memory`, `GET/PUT/DELETE /v1/memory/{memory_id}`, `POST .../dispute`, `.../hold`, `/v1/memory/search`, `/maintenance/sweep`, `.../provenance`; `POST /v1/kb/upload`, `/upload/file`, `GET /v1/kb/documents`, `DELETE /v1/kb/documents/{document_id}`, `POST /v1/kb/search` | Governed RAG/Memory lifecycle (`ATTESTED` vs `ADVISORY`), legal holds, Qdrant + PG document indexing |
| **Action Assurance & Approvals** (`actions.py`, `concurrency.py`) | `POST/GET /v1/tools`, `POST /v1/actions/propose`, `/authorize`, `/batch`, `GET /v1/actions/stranded`, `GET /v1/actions/{action_id}`, `POST /v1/actions/execute`, `POST .../reconcile`, `GET/POST /v1/actions/{action_id}/outcome`; `GET /v1/approvals/pending`, `POST /v1/approvals/{approval_id}/grant\|deny`; `POST/GET/release/renew /v1/resources/leases` | Gate 3 capability checks, salami limits, two-phase execution, HITL approvals, Redis distributed leases |
| **Agents, Delegations & Handoffs** (`agents.py`, `delegations.py`, `handoffs.py`) | `POST/GET /v1/agents`, `POST /v1/agents/{agent_id}/activate\|suspend\|revoke`; `POST/GET /v1/delegations`, `activate\|revoke\|validate`; `POST/GET /v1/handoffs`, `accept\|cancel\|complete` | Scoped agent registration, non-escalating delegation chains, verified handoffs |
| **Outcome Assurance (Gate 5)** (`outcomes.py`) | `POST /v1/outcomes/verify`, `GET /v1/outcomes/pending`, `GET /v1/outcomes/action/{action_id}`, `GET /v1/outcomes/transaction/{transaction_id}`, `POST /v1/outcomes/reconcile`, `POST /v1/outcomes/{outcome_id}/escalate`, `GET /v1/outcomes/{outcome_id}` | Independent reality verification (`OBS_DIRECT`..`OBS_BLIND`), uncertainty reconciliation, escalation |
| **Output Verification & Streaming** (`verify.py`, `output.py`, `proxy.py`, `stream.py`) | `POST /v1/verify`, `POST /v1/output/assure`, `GET /v1/output/{output_id}`, `POST /v1/chat/completions`, `POST` & `WebSocket /v1/verify/stream` | Gate 4 HRS scoring, OpenAI-compatible proxy, progressive SSE/WebSocket verification |
| **Governed MCP** (`mcp.py`) | `POST /v1/mcp/rpc`, `POST/GET /v1/mcp/servers`, `GET /v1/mcp/servers/{server_id}`, `PUT .../trust`, `POST .../discover` | Inbound JSON-RPC 2.0 server & external SSRF-safe MCP registry/discovery |
| **Audit, Reports & Telemetry** (`audit.py`, `reports.py`, `sessions.py`, `dashboard.py`, `alerts.py`) | `POST /v1/audit/verify-chain`, `GET .../events`, `GET .../integrity`, `POST .../export-bundle`, `POST .../anchor`, `POST/GET /v1/audit/checkpoints`; `POST /v1/reports/generate`, `GET .../dossier`, `GET .../pdf`; `GET /v1/sessions`, `/v1/dashboard/stats`, `/v1/drift`, `/v1/alerts` | Tamper-evident hash chain checks, notary anchoring, compliance PDFs & dossiers, drift analytics |
| **Models, Budgets, Billing, Webhooks, Health** (`models.py`, `budgets.py`, `billing.py`, `webhooks.py`, `inquiries.py`, `health.py`) | `GET/POST /v1/models`, `GET/PUT/POST /v1/budgets`, `/v1/billing/*`, `POST/GET/DELETE/test /v1/webhooks`, `POST/GET /v1/inquiries`, `GET /v1/health`, `GET /v1/ready`, `GET /metrics` | Routing profiles, tenant budgets, billing hooks, outbound webhooks, Kubernetes/Docker probes |

---

## 3. Official SDKs & CLI

### 3.1 Python SDK (`sdk/` — `mirage-sdk`)
Install locally or editable for development:
```bash
pip install -e "./sdk"
```

Provides synchronous `MirageClient` and async `AsyncMirageClient` (`httpx`-backed, PEP 561 typed via `py.typed`, automatic secret redaction in exceptions/logs).

**Core SDK Safety Guarantees:**
1. **Safe Read Retries Only:** `GET` endpoints retry transient `502`/`503`/`504` responses honoring `Retry-After`. **Mutating requests (`POST`/`PUT`/`DELETE`) never auto-retry** to prevent duplicate side effects.
2. **Uncertainty Exception Handling:** Transport disconnects or timeouts during `execute_action()` raise `MirageExecutionUncertainError` with `state="EXECUTION_UNCERTAIN"`. Callers must query status or trigger Gate 5 reconciliation—never re-dispatch blindly.

```python
from mirage_sdk import MirageClient, MirageExecutionUncertainError
from mirage_sdk.models import (
    ActionProposal,
    ActionType,
    BlastRadius,
    OutcomeVerificationRequest,
    OutcomeVerifierType,
    PostconditionRule,
)

with MirageClient(base_url="http://localhost:8000", api_key="mirage_live_...") as client:
    # 1. Propose governed action
    decision = client.propose_action(
        ActionProposal(
            transaction_id="tx_demo_01",
            action_type=ActionType.WRITE,
            tool_name="database_query",
            target_resource="db.accounts",
            parameters={"query": "UPDATE accounts SET balance = 750 WHERE id = 42"},
            blast_radius=BlastRadius(estimated_dollar_cost=250.0, target_environment="STAGING"),
            postconditions=[PostconditionRule(field="balance", operator="eq", expected_value=750)],
        )
    )

    # 2. Execute via proxy (never blindly retry on uncertainty)
    try:
        executed = client.execute_action(decision.action_id)
    except MirageExecutionUncertainError as exc:
        print(f"Uncertain action {exc.action_id}: inspect physical state before acting.")
        raise

    # 3. Independently verify outcome (Gate 5)
    outcome = client.verify_outcome(
        OutcomeVerificationRequest(
            action_id=executed.action_id,
            verifier_type=OutcomeVerifierType.INDEPENDENT_OBSERVER,
            observations={"balance": 750},
        )
    )
    print(f"Outcome: {outcome.outcome_status} (confidence={outcome.epistemic_confidence})")
```

Runnable examples live in [`sdk/examples/`](../sdk/examples/): `01_verify_completion.py`, `02_action_governance_and_outcome.py`, `03_handling_execution_uncertainty.py`, `04_mcp_server_governance.py`. LangChain adapters live in [`sdk/mirage_sdk/integrations/langchain.py`](../sdk/mirage_sdk/integrations/langchain.py).

### 3.2 JavaScript SDK (`sdk/js/` — `@mirage-ai/sdk`)
Zero-dependency ESM client using native `fetch` (`sdk/js/index.js`, `sdk/js/index.d.ts`, tested via `sdk/js/test/client.test.js`) supporting `verify()`, `verifyStream()`, `proposeAction()`, `executeAction()`, and `verifyOutcome()`. See [`sdk/js/README.md`](../sdk/js/README.md).

### 3.3 Developer CLI (`cli/main.py`)
Installed as console script `mirage`:
```bash
mirage health                       # Probe GET /v1/health
mirage quickstart                   # Run guided developer 5-gate sandbox walkthrough
mirage verify --text "..."          # Submit text to Gate 4 output verification
```
