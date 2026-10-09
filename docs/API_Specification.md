# MIRAGE 3.0 — API Specification

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document outlines the authoritative external API for developers integrating with MIRAGE 3.0.

---

## 1. API Design Principles

The MIRAGE 3.0 API adheres to the following core principles:

- **RESTful Architecture:** Built around predictable, resource-oriented URLs and standard HTTP methods (GET, POST, PUT, DELETE).
- **Versioning:** All endpoints are strictly versioned using URI path versioning (e.g., `/v1/`). The API avoids breaking changes within a major version.
- **JSON Standard:** Request and response bodies are formatted as JSON (application/json).
- **Tenant Isolation:** Every request is strictly tenant-scoped. Cross-tenant access is physically and logically prohibited.
- **Pagination:** Collection endpoints (e.g., GET lists) support cursor-based pagination using `limit` and `cursor` query parameters. Responses include a `next_cursor`.
- **Consistent Error Format:** All errors follow a standardized format for easy programmatic parsing.

## 2. Authentication

MIRAGE 3.0 supports multiple authentication flows tailored to different integration models. All requests require authentication via the `Authorization` header.

### 2.1 API Key Flow (Machine-to-Machine)
The primary method for server-side SDKs and backend integrations.
- **Format:** `Authorization: Bearer <API_KEY>`
- **Scope:** API Keys are bound to specific Tenants and Roles.

### 2.2 JWT Flow (Short-Lived Tokens)
For ephemeral access, particularly in governed workflows where specific microservices need temporary, scoped access.
- **Format:** `Authorization: Bearer <JWT>`
- **Validation:** Cryptographically signed by the MIRAGE Control Plane; includes claims for tenant, identity, and expiration.

### 2.3 OAuth2 / OIDC Flow (User Context)
Used for dashboard interactions or integrations requiring human context.
- Integrates with standard OIDC providers.
- Access tokens represent the user's identity within the MIRAGE system.

## 3. Authorization

All API endpoints evaluate the caller's Capabilities via the Policy Engine.
- **ABAC (Attribute-Based Access Control):** Access is determined by attributes of the caller (Identity, Role), the resource (Tenant, Sensitivity), and the context (Network, Time).
- **Capability Model:** A specific, bounded permission is required to perform any action. E.g., `policy:write`, `transaction:initiate`.

## 4. Endpoint Groups

### 4.1 Transaction API
Manages the end-to-end AI workload.

**`POST /v1/transactions`**
- **Description:** Initiate a new transaction context.
- **Request Fields:** `intent` (string), `context_id` (optional, string), `agent_id` (string), `budget` (object).
- **Response Fields:** `id` (string), `status` (string), `created_at` (timestamp).
- **Required Capability:** `transaction:create`

**`GET /v1/transactions/{id}`**
- **Description:** Retrieve transaction state and assurance score.
- **Response Fields:** `id`, `status` (pending, active, completed, blocked, failed), `assurance_score` (number), `gates_passed` (array).
- **Required Capability:** `transaction:read`

**`POST /v1/transactions/{id}/cancel`**
- **Description:** Cancel a running transaction.
- **Response Fields:** `id`, `status` (cancelled).
- **Required Capability:** `transaction:cancel`

### 4.2 Verification API
**`POST /v1/verify`**
- **Description:** Backward-compatible with MIRAGE 2.x for stateless verification (Gate 4).
- **Request Fields:** `claim` (string), `evidence` (string/array).
- **Response Fields:** `score` (number 0-1), `is_verified` (boolean), `reasoning` (string).
- **Required Capability:** `verification:execute`

**`GET /v1/verify/{id}/status`**
- **Description:** Poll status of asynchronous verification.
- **Required Capability:** `verification:read`

**`GET /v1/verify/{id}/result`**
- **Description:** Retrieve final verification result.
- **Required Capability:** `verification:read`

### 4.3 Policy API
**`POST /v1/policies`**
- **Description:** Create a new declarative policy.
- **Request Fields:** `name`, `description`, `rules` (array of conditions and effects).
- **Required Capability:** `policy:write`

**`GET /v1/policies`**
- **Description:** List policies with scoping filters.
- **Required Capability:** `policy:read`

**`PUT /v1/policies/{id}`**
- **Description:** Update policy definition.
- **Required Capability:** `policy:write`

**`DELETE /v1/policies/{id}`**
- **Description:** Delete a policy.
- **Required Capability:** `policy:delete`

### 4.4 Action API
**`POST /v1/actions/authorize`**
- **Description:** Request authorization for an intended action (Gate 3).
- **Request Fields:** `transaction_id`, `tool_name`, `arguments`.
- **Response Fields:** `decision` (allow, deny, require_approval), `reason`.
- **Required Capability:** `action:authorize`

**`POST /v1/actions/{id}/outcome`**
- **Description:** Report real-world outcome of an executed action (Gate 5).
- **Request Fields:** `status` (success, failure), `result_data`.
- **Required Capability:** `action:report`

### 4.5 Approval API
**`GET /v1/approvals/pending`**
- **Description:** List pending approvals.
- **Required Capability:** `approval:read`

**`POST /v1/approvals/{id}/grant`**
- **Description:** Grant approval.
- **Required Capability:** `approval:grant`

**`POST /v1/approvals/{id}/deny`**
- **Description:** Deny approval.
- **Required Capability:** `approval:deny`

### 4.6 Agent API
**`POST /v1/agents`**
- **Description:** Register a new agent.
- **Request Fields:** `name`, `description`, `autonomy_level` (L0-L5).
- **Required Capability:** `agent:write`

**`GET /v1/agents/{id}`**
- **Description:** Get agent configuration.
- **Required Capability:** `agent:read`

**`PUT /v1/agents/{id}/capabilities`**
- **Description:** Assign capabilities to an agent.
- **Required Capability:** `agent:grant_capability`

### 4.7 Tool API
**`POST /v1/tools`**
- **Description:** Register a tool or MCP server.
- **Request Fields:** `name`, `schema`, `mcp_endpoint` (optional).
- **Required Capability:** `tool:write`

**`GET /v1/tools/{id}`**
- **Description:** Retrieve tool details.
- **Required Capability:** `tool:read`

**`POST /v1/tools/{id}/revoke`**
- **Description:** Revoke a tool's availability.
- **Required Capability:** `tool:revoke`

### 4.8 Memory API
**`POST /v1/memory`**
- **Description:** Write a new memory item with provenance.
- **Request Fields:** `content`, `metadata`, `provenance_id`.
- **Required Capability:** `memory:write`

**`GET /v1/memory/search`**
- **Description:** Semantic search over governed memory.
- **Required Capability:** `memory:read`

**`DELETE /v1/memory/{id}`**
- **Description:** Delete memory item.
- **Required Capability:** `memory:delete`

### 4.9 Audit API
**`GET /v1/audit/events`**
- **Description:** Query audit ledger.
- **Required Capability:** `audit:read`

**`GET /v1/audit/transactions/{id}`**
- **Description:** Complete audit trail for a transaction.
- **Required Capability:** `audit:read`

**`POST /v1/audit/reports`**
- **Description:** Generate compliance report.
- **Required Capability:** `audit:report`

### 4.10 Telemetry API
**`GET /v1/health`**
- **Description:** Health check.
- **Required Capability:** None

**`GET /v1/ready`**
- **Description:** Readiness probe.
- **Required Capability:** None

**`GET /v1/metrics`**
- **Description:** Prometheus-compatible metrics.
- **Required Capability:** `telemetry:read`

### 4.11 Admin API
**`POST /v1/admin/tenants`**
- **Description:** Create tenant.
- **Required Capability:** Superadmin only.

**`GET /v1/admin/tenants/{id}`**
- **Description:** Get tenant info.
- **Required Capability:** Superadmin only.

### 4.12 Streaming API
**`WebSocket /v1/stream/transactions`**
- **Description:** Real-time bi-directional stream for a transaction.

**`SSE /v1/stream/events`**
- **Description:** Server-Sent Events for general tenant audit logs and alerts.

## 5. Error Response Format

Errors return a standard JSON structure:
```json
{
  "error": {
    "code": "POLICY_VIOLATION",
    "message": "The requested action violates the maximum token budget.",
    "details": {
      "limit": 5000,
      "requested": 6500
    },
    "correlation_id": "req-987654321"
  }
}
```

## 6. Rate Limiting Headers

The API enforces rate limits to ensure stability. Responses include the following headers:
- `X-RateLimit-Limit`: Maximum requests permitted per window.
- `X-RateLimit-Remaining`: Requests remaining in the current window.
- `X-RateLimit-Reset`: Unix timestamp when the limit resets.

## 7. Backward Compatibility

MIRAGE 3.0 ensures smooth transition for MIRAGE 2.x users:
- The legacy `/verify` endpoint is mapped internally to `/v1/verify` executing Gate 4 Verification Engine logic.
- API keys generated in 2.x are valid in 3.x, automatically mapped to default tenant roles.
- Previous verification scores map directly to Output Assurance scores.
