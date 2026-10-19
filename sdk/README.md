# MIRAGE Python SDK (`mirage-sdk`)

> **"Control AI before it acts. Verify AI after it acts."**

Official Python client library for **MIRAGE 3.0**, the AI Execution Assurance Platform.

MIRAGE sits between AI systems and the real world to govern execution lifecycle, enforce identity, security, policy, reliability, and cost controls across the **Five Assurance Gates**:

- **Gate 1 — Input Assurance:** Identity verification, tenant isolation, prompt-injection defense.
- **Gate 2 — Context Assurance:** RAG evidence provenance, freshness, memory governance.
- **Gate 3 — Action Assurance:** Capability-based access control, tool registration/trust verification, blast-radius limiting, and human approval.
- **Gate 4 — Output Assurance:** Syntactic and semantic validation, Hallucination Risk Score (HRS), Mondrian conformal prediction intervals, TreeSHAP feature attributions.
- **Gate 5 — Outcome Assurance:** Independent reality verification confirming actual real-world state transitions against predicted postconditions.

---

## Supported Python Versions

- Python 3.11
- Python 3.12
- Python 3.13

## Installation

```bash
pip install mirage-sdk
```

Or for development / local repository work:

```bash
pip install -e ./sdk
```

---

## Core Architectural Invariants

1. **Epistemic Outcome Independence:**  
   A tool's return code (e.g., HTTP 200) or an agent's self-assertion is **never** treated as proof of a real-world outcome. Outcome claims must be verified via independent evidence through Gate 5 (`client.verify_outcome`).
2. **Execution Uncertainty Preservation:**  
   When a mutating action times out or encounters a network disconnect during execution, MIRAGE transitions the action to `EXECUTION_UNCERTAIN`. The SDK **never** automatically retries or blindly redispatches mutating actions, preventing catastrophic double-mutations.
3. **Fail-Closed Security & Tenant Isolation:**  
   Tenant context and identity are server-authenticated via the API key. Client-supplied tenant overrides cannot bypass tenant boundaries.

---

## Quickstart

### 1. Synchronous Verification (Gate 4)

```python
import os
from mirage_sdk import MirageClient

api_key = os.environ["MIRAGE_API_KEY"]

with MirageClient(api_key=api_key, base_url="http://localhost:8000") as client:
    response = client.verify(
        prompt="What is the capital of France?",
        response="The capital of France is Paris.",
    )

    print(f"Verified text: {response.verified_response}")
    print(f"Hallucination Risk Score (HRS): {response.hrs_result.hrs:.4f}")
    print(f"Risk Tier: {response.hrs_result.tier}")
    print(f"95% Conformal Interval: [{response.hrs_result.conformal_interval.lower}, {response.hrs_result.conformal_interval.upper}]")
```

### 2. Asynchronous Client (`AsyncMirageClient`)

```python
import asyncio
import os
from mirage_sdk import AsyncMirageClient

async def main():
    api_key = os.environ["MIRAGE_API_KEY"]
    async with AsyncMirageClient(api_key=api_key, base_url="http://localhost:8000") as client:
        resp = await client.verify(
            prompt="Compute 2 + 2",
            response="2 + 2 = 4",
        )
        print("HRS:", resp.hrs_result.hrs)

asyncio.run(main())
```

---

## Governed Action Execution Lifecycle (Gate 3 -> Gate 5)

```python
import uuid
from mirage_sdk import (
    MirageClient,
    ActionProposal,
    ActionType,
    PostconditionRule,
    BlastRadiusAssessment,
    OutcomeVerificationRequest,
    IndependentObservation,
    MirageExecutionUncertainError,
)

with MirageClient(api_key=os.environ["MIRAGE_API_KEY"]) as client:
    # 1. Propose Action Contract to Gate 3
    proposal = ActionProposal(
        transaction_id=f"tx_{uuid.uuid4().hex[:12]}",
        tool_name="order_service.cancel_order",
        action_type=ActionType.WRITE,
        target_resource="order:ord_98765",
        parameters={"order_id": "ord_98765", "reason": "Customer request"},
        idempotency_key=f"idem_{uuid.uuid4().hex[:16]}",
        postconditions=[
            PostconditionRule(
                assertion="STATUS_EQUALS",
                target="order:ord_98765.status",
                expected_value="CANCELLED",
            )
        ],
        blast_radius=BlastRadiusAssessment(
            resource_scope="ORDERS",
            estimated_dollar_cost=150.0,
            reversibility="REVERSIBLE",
        ),
    )

    decision = client.propose_action(proposal)
    print(f"Decision: {decision.decision}, State: {decision.state}, Risk: {decision.risk_score}")

    # 2. Execute Authorized Action
    try:
        exec_result = client.execute_action(decision.action_id)
        print(f"Execution state: {exec_result.state}")
    except MirageExecutionUncertainError as exc:
        print(f"Execution uncertain! Do NOT retry blindly. Action ID: {exc.action_id}")
        # Inspect action or reconcile later
        raise

    # 3. Independent Reality Verification (Gate 5)
    # Never assume tool execution return value proved the database was updated
    outcome = client.verify_outcome(
        action_id=decision.action_id,
        request=OutcomeVerificationRequest(
            action_id=decision.action_id,
            observation=IndependentObservation(
                observer_identity="orders_db_probe",
                observed_state={"status": "CANCELLED", "order_id": "ord_98765"},
            ),
        ),
    )
    print(f"Gate 5 Status: {outcome.outcome_status}, Confidence: {outcome.epistemic_confidence}")
```

---

## Handling Execution Uncertainty

When an action execution times out or a connection breaks:

```python
from mirage_sdk import MirageClient, MirageExecutionUncertainError

client = MirageClient(api_key=...)
try:
    result = client.execute_action(action_id)
except MirageExecutionUncertainError as exc:
    # Action might have executed on the target!
    # Inspect current state:
    action_info = client.get_action(exc.action_id)
    if action_info["state"] == "COMPLETED":
        print("Action succeeded prior to transport disconnect")
    else:
        # Reconcile stranded action with evidence
        client.reconcile_action(
            action_id=exc.action_id,
            resolution_state="FAILED",
            rationale="Timed out; manual inspection confirmed no order mutation",
        )
```

---

## Governed MCP Server Management

```python
from mirage_sdk import (
    MirageClient,
    MCPServerCreateRequest,
    MCPServerTransport,
    MCPTrustStatus,
)

with MirageClient(api_key=os.environ["MIRAGE_API_KEY"]) as client:
    # 1. Register external MCP server (starts in PENDING_APPROVAL)
    server = client.register_mcp_server(
        MCPServerCreateRequest(
            name="github-mcp",
            description="GitHub Repository MCP Server",
            transport_type=MCPServerTransport.STDIO,
            connection_config={"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
            permitted_capabilities=["repo:read"],
            egress_allowlist=["api.github.com"],
        )
    )

    # 2. Transition trust status to TRUSTED (Admin only)
    client.update_mcp_server_trust(
        server_id=server.id,
        trust_status=MCPTrustStatus.TRUSTED,
        reason="Verified vendor and approved scopes",
    )

    # 3. Discover and fingerprint tools
    discovery = client.discover_mcp_tools(server.id)
    print(f"Registered {discovery.tools_discovered_count} tools with SHA-256 schema fingerprints")
```

---

## Cryptographic Audit Chain Verification

```python
with MirageClient(api_key=os.environ["MIRAGE_API_KEY"]) as client:
    audit_check = client.verify_audit_hash_chain()
    print(f"Audit ledger valid: {audit_check.valid}")
    print(f"Total records verified: {audit_check.total_records_verified}")
    print(f"Chain status: {audit_check.chain_status}")
```

---

## Exception Hierarchy

All exceptions inherit from `MirageError`. No credentials or authorization secrets are ever included in error messages or representations.

- `MirageError`
  - `MirageAuthenticationError` (HTTP 401)
  - `MirageAuthorizationError` (HTTP 403)
  - `MirageNotFoundError` (HTTP 404)
  - `MirageValidationError` (HTTP 400 / 422)
  - `MirageRateLimitError` (HTTP 429)
  - `MirageServerError` (HTTP 5xx)
  - `MirageTransportError` (Connection / Transport failures on safe requests)
  - `MirageExecutionUncertainError` (Execution state uncertain, crash / timeout on mutating actions)
