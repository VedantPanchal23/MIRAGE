# MIRAGE 3.0 — SDK and Integration Guide

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-19
>
> This document defines how developers integrate MIRAGE 3.0 into their AI applications, workflows, and autonomous agents using the official Python SDK (`mirage-sdk`), the REST API, and governed MCP tooling.

---

## 1. Developer Experience Design Principles

MIRAGE is an **AI Execution Assurance Platform** built on the core promise:
> **“Control AI before it acts. Verify AI after it acts.”**

The developer interfaces are designed around five foundational tenets:
- **Zero Ambiguity & Explicit Guarantees:** Tool execution acknowledgment is fundamentally decoupled from real-world outcome assurance (epistemic outcome independence).
- **Execution Uncertainty Safety:** Mutating actions that encounter timeouts or disconnects are marked `EXECUTION_UNCERTAIN` and are **never** blindly redispatched.
- **Fail-Closed Security & Scope Attenuation:** API keys operate within least-privilege scope attenuation bounded by an immutable role ceiling.
- **Type Safety & Forward Compatibility:** Built on PEP 561 typed Pydantic models with `extra="ignore"` to safely tolerate server schema additions without client breakage.
- **Credential Hygiene:** API keys and sensitive tokens are strictly redacted from string representations, debug dumps, and error payloads.

---

## 2. Official Python SDK (`mirage-sdk`)

The official Python client package is located in `sdk/` and distributed as `mirage-sdk`.

### 2.1 Installation

```bash
pip install mirage-sdk
```

Requirements: Python >= 3.11, < 3.14.

### 2.2 Client Architecture

The SDK exposes two client implementations sharing an identical contract:
1. `MirageClient`: Synchronous, thread-safe client leveraging `httpx.Client`.
2. `AsyncMirageClient`: Fully asynchronous client leveraging `httpx.AsyncClient` for high-throughput async pipelines and event loops.

Both clients support context manager lifecycles (`with` and `async with`) ensuring reliable connection pooling and prompt cleanup.

```python
from mirage_sdk import MirageClient, AsyncMirageClient

# Synchronous usage
with MirageClient(api_key="mirage_live_...", base_url="https://api.mirage.ai") as client:
    resp = client.verify(prompt="Is the invoice paid?", claim="Invoice 1042 was marked paid.")
    print("Verification passed:", resp.is_verified)

# Asynchronous usage
async with AsyncMirageClient(api_key="mirage_live_...", base_url="https://api.mirage.ai") as client:
    resp = await client.verify(prompt="Is the invoice paid?", claim="Invoice 1042 was marked paid.")
    print("Verification passed:", resp.is_verified)
```

---

## 3. Core Architectural Invariants in the SDK

### 3.1 Epistemic Outcome Independence (Gate 4 vs Gate 5)

An external tool returning `{"status": "ok"}` or an agent claiming an action succeeded is **not proof** of a real-world state transition.

1. **Gate 3 (Action Execution):** The agent proposes an action (`client.propose_action`), evaluates blast radius and preconditions, and dispatches execution (`client.execute_action`). This transitions the contract to `ActionState.EXECUTED` (or `EXECUTION_UNCERTAIN`).
2. **Gate 5 (Outcome Assurance):** Outcome claims must be independently verified using real-world observations (`client.verify_outcome`). Reality verification queries independent data sources (e.g. read-replica SQL queries, cloud provider APIs) and confirms expected postconditions before issuing `OutcomeStatus.VERIFIED_SUCCESS`.

### 3.2 Handling Execution Uncertainty (No Blind Redispatch)

If a mutating action (e.g., executing a bank transfer, creating an infrastructure resource) experiences a transport timeout or dropped connection during dispatch:
- The remote system may have executed the action, failed before starting, or crashed midway.
- The SDK raises `MirageExecutionUncertainError` containing the `action_id` and state `EXECUTION_UNCERTAIN`.
- **Automatic retries are strictly disabled on mutating requests.** The client must query Gate 5 outcome reconciliation or alert human operators rather than blindly redispatching the request.

```python
from mirage_sdk import MirageClient, MirageExecutionUncertainError

with MirageClient(api_key="mirage_live_...") as client:
    try:
        result = client.execute_action(action_id="act_payment_4821")
    except MirageExecutionUncertainError as exc:
        # Crucial: DO NOT re-call execute_action!
        print(f"Action {exc.action_id} is in state {exc.state}. Initiating outcome reconciliation...")
        reconciliation = client.get_action(exc.action_id)
```

### 3.3 Safe GET Retries vs Non-Idempotent Protection

- **Safe Reads (`GET`):** Operations like `get_output()`, `get_session()`, and `get_action()` automatically retry transient server errors (`502`, `503`, `504`) and transport hiccups up to `max_retries` (default: 2), honoring HTTP `Retry-After` headers.
- **Mutating Operations (`POST`, `PUT`, `DELETE`):** Never retried automatically. Any failure surfaces immediately to prevent accidental duplicate execution.

---

## 4. Complete Code Examples

### 4.1 Output Verification (Gate 4)

```python
from mirage_sdk import MirageClient, VerificationRequest

with MirageClient(api_key="mirage_live_readwrite...") as client:
    request = VerificationRequest(
        prompt="What is the capital of France?",
        claim="Paris is the capital of France.",
        evidence=["Paris is the capital and most populous city of France."],
    )
    res = client.verify(request)
    print(f"Verified: {res.is_verified}, Score: {res.overall_score:.2f}")
```

### 4.2 Governed Action Life-Cycle & Gate 5 Outcome Verification

```python
from datetime import datetime, UTC
from mirage_sdk import (
    MirageClient,
    ActionProposal,
    ActionType,
    PostconditionRule,
    OutcomeVerificationRequest,
    OutcomeVerificationContract,
    IndependentObservation,
    OutcomeStatus,
)

with MirageClient(api_key="mirage_live_...") as client:
    # 1. Propose Action Contract
    proposal = ActionProposal(
        action_type=ActionType.TOOL_INVOCATION,
        target_system="inventory_db",
        payload={"sku": "WIDGET-99", "quantity": 10},
        postconditions=[
            PostconditionRule(
                property="stock_level",
                operator="eq",
                expected_value=100,
            )
        ],
    )
    decision = client.propose_action(proposal)
    action_id = decision.action_id

    # 2. Execute Action (Gate 3)
    exec_result = client.execute_action(action_id)
    print(f"Action execution status: {exec_result.state}")

    # 3. Independent Outcome Verification (Gate 5)
    outcome_req = OutcomeVerificationRequest(
        transaction_id="tx_ord_9012",
        action_id=action_id,
        contract=OutcomeVerificationContract(
            action_id=action_id,
            target_system="inventory_db",
            rules=[
                PostconditionRule(
                    property="stock_level",
                    operator="eq",
                    expected_value=100,
                )
            ],
        ),
        observations=[
            IndependentObservation(
                observation_id="obs_warehouse_read_01",
                source_id="inventory_read_replica",
                target_resource="inventory_db.widgets",
                observed_at=datetime.now(UTC),
                observed_state={"stock_level": 100},
                evidence_digest="sha256:d8a9f...",
            )
        ],
    )
    outcome = client.verify_outcome(outcome_req)
    if outcome.status == OutcomeStatus.VERIFIED_SUCCESS:
        print("Real-world state transition verified successfully!")
```

### 4.3 Governed MCP Server Registration

```python
from mirage_sdk import MirageClient, MCPServerCreateRequest, MCPServerTransport

with MirageClient(api_key="mirage_live_admin...") as client:
    # Register an external MCP server
    server = client.register_mcp_server(
        MCPServerCreateRequest(
            name="github-mcp",
            transport=MCPServerTransport.HTTP_STREAM,
            endpoint_url="https://mcp.internal.company.com/sse",
            capabilities_declared=["repos:read", "issues:write"],
            egress_allowlist=["github.com", "api.github.com"],
        )
    )
    print(f"Registered MCP Server: {server.id}, Trust Status: {server.trust_status}")
```

---

## 5. Exception Hierarchy

All SDK exceptions inherit from `MirageError` (`sdk/mirage_sdk/exceptions.py`):

```text
MirageError
 ├── MirageTransportError (Network connectivity, DNS failure)
 ├── MirageExecutionUncertainError (Mutating action timeout; blind retry forbidden)
 └── MirageServerError (HTTP 5xx responses)
      ├── MirageAuthenticationError (HTTP 401 - missing/invalid/revoked API key)
      ├── MirageAuthorizationError (HTTP 403 - scope attenuation or role violation)
      ├── MirageNotFoundError (HTTP 404 - resource does not exist)
      ├── MirageValidationError (HTTP 422 - schema validation failure)
      └── MirageRateLimitError (HTTP 429 - quota exceeded, includes retry_after)
```

---

## 6. API Key Scopes & Least-Privilege Attenuation

When issuing API keys via the Control Plane (`POST /v1/auth/api-keys`), scopes can be tightly restricted.

The effective permission is calculated as:
$$\text{Effective Permissions} = \text{Role Ceiling} \cap \text{Key Scopes}$$

| Scope | Allowed Capabilities |
| :--- | :--- |
| `verify:read` | Read verification results (`GET /v1/verify/{id}`) |
| `verify:write` | Execute verification jobs (`POST /v1/verify`) |
| `action:read` | Inspect action contracts and states (`GET /v1/actions/{id}`) |
| `action:write` | Propose and execute actions (`POST /v1/actions/*`) |
| `output:read` | Retrieve output assurance reports (`GET /v1/output/*`) |
| `session:read` | Query session history (`GET /v1/sessions/*`) |
| `session:write` | Create or update sessions (`POST /v1/sessions`) |
| `mcp:read` | List registered MCP servers and tools (`GET /v1/mcp/*`) |
| `mcp:write` | Register, update, and revoke MCP servers (`POST /v1/mcp/*`) |
| `tenant:admin` | Manage tenant lifecycle, API keys, and configurations |
| `*` | Full permissions within the role ceiling |

Attempting to perform a mutating action with a read-only key (e.g. calling `POST /v1/verify` with only `["verify:read"]`) will fail closed with `MirageAuthorizationError` (HTTP 403).

---

## 7. Migration from MIRAGE 2.x

1. **Endpoint Relocation:** Legacy `/verify` routes are mapped to `/v1/verify`.
2. **Authentication Modernization:** Replace unauthenticated or demo tokens with hashed `mirage_live_...` API keys issued via `/v1/auth/api-keys`.
3. **Outcome Decoupling:** Update custom workflows to separate action execution from Gate 5 outcome verification contracts.
