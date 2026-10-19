# Runbook 10: Uncertain Action Investigation Without Blind Redispatch

## 1. Overview and Core Invariants
In distributed AI execution, network partitions, worker crashes, or tool timeouts can leave an action in an uncertain state.

### The Epistemic Invariant:
**Never claim unverified success.**
An agent assertion or a tool's internal execution return value is NOT proof of a real-world outcome.

### The Anti-Pattern: Blind Redispatch
When an external HTTP webhook, payment capture, email dispatch, or remote API mutation times out, **DO NOT automatically re-execute the action**. Blind redispatch against non-idempotent external endpoints causes duplicate side effects (e.g. double payments or duplicate customer emails).

## 2. The Execution State Machine
Every action in `action_contracts` progresses through:
- `PROPOSED` -> `AUTHORIZED` -> `EXECUTING`
- If execution is interrupted: `EXECUTION_UNCERTAIN`
- Only Gate 5 reality verification moves the state to `VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, or `PARTIAL_ACHIEVEMENT`.

## 3. Investigating Uncertain Actions

### Step 1: Identify Stranded or Uncertain Actions
Query actions stuck in `EXECUTING` or `EXECUTION_UNCERTAIN`:
```sql
SELECT id, transaction_id, capability, target_resource, execution_state, lease_token, updated_at
FROM action_contracts
WHERE execution_state IN ('EXECUTING', 'EXECUTION_UNCERTAIN')
  AND updated_at < now() - INTERVAL '5 minutes';
```

### Step 2: Check Lease Fencing Status
Check whether the concurrency lease has expired or been fenced:
```sql
SELECT lease_id, resource_id, owner_agent_id, fencing_token, expires_at, status
FROM resource_leases
WHERE resource_id = '<target_resource>';
```
If `expires_at < now()`, the lease has expired. The stranded worker can no longer commit changes under this fencing token.

### Step 3: Reality Verification Reconciliation
Run independent reality verification to observe whether the side effect actually occurred:
1. Probe the target system independently (e.g., query database row, inspect target API resource by idempotency key).
2. Report the outcome using the outcome reporting endpoint:
```bash
curl -X POST http://localhost:8000/v1/actions/<action_id>/outcome \
  -H "Authorization: Bearer <operator_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "disposition": "VERIFIED_SUCCESS",
    "evidence": {"independent_check": "Target order 12345 exists in database", "verified_by": "operator"}
  }'
```
Or record `VERIFIED_FAILURE` if the side effect never reached the external target.
