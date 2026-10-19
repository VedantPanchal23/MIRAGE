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

### 4.7.1 Governed MCP Server Management API
**`POST /v1/mcp/servers`**
- **Description:** Register an external MCP server in `PENDING_APPROVAL` trust status. Egress policy validates endpoints against SSRF (RFC 1918, link-local, loopback, cloud metadata) for HTTP streams, or disallows shell metacharacters and directory traversal for STDIO subprocesses.
- **Request Fields:** `name`, `description`, `transport_type` (`STDIO` | `HTTP_STREAM`), `connection_config` (`{"url": "..."}` or `{"command": "...", "args": [...], "env": {...}}`), `permitted_capabilities`, `egress_allowlist`, `timeout_seconds`.
- **Response Fields:** `id`, `tenant_id`, `name`, `transport_type`, `trust_status`, `permitted_capabilities`, `egress_allowlist`, `tool_count`, `created_at`.
- **Required Role:** `SUPER_ADMIN` or `TENANT_ADMIN` (with `config:write` scope).

**`GET /v1/mcp/servers`**
- **Description:** List registered MCP servers for the caller's tenant with active tool counts.
- **Query Parameters:** `limit` (default 50), `offset` (default 0).
- **Response Fields:** `items` (array of `MCPServerResponse`), `total`.
- **Required Role:** Authenticated caller (`verify:read` or `config:write`).

**`GET /v1/mcp/servers/{server_id}`**
- **Description:** Retrieve MCP server details with sensitive authentication tokens or credentials redacted.
- **Response Fields:** `MCPServerResponse`.
- **Required Role:** Authenticated caller.

**`POST /v1/mcp/servers/{server_id}/trust-status`**
- **Description:** Transition server trust status (`PENDING_APPROVAL` $\leftrightarrow$ `TRUSTED`, `SUSPENDED`, `REVOKED`). Transition to `SUSPENDED` or `REVOKED` immediately deactivates all registered child tools under fail-closed governance.
- **Request Fields:** `trust_status` (`TRUSTED` | `SUSPENDED` | `REVOKED`), `reason`.
- **Response Fields:** Updated `MCPServerResponse`.
- **Required Role:** `SUPER_ADMIN` or `TENANT_ADMIN`.

**`POST /v1/mcp/servers/{server_id}/discover`**
- **Description:** Connect to an external server in `TRUSTED` status, query `tools/list`, compute SHA-256 schema fingerprints, and register tools into `tool_registry` with `{server_id}:{tool_name}` namespacing.
- **Response Fields:** `server_id`, `server_name`, `tools_discovered`, `tools_registered`.
- **Required Role:** `SUPER_ADMIN` or `TENANT_ADMIN`.

**`DELETE /v1/mcp/servers/{server_id}`**
- **Description:** Permanently revoke and remove an MCP server. Cascades deletion to all registered tool definitions in `tool_registry`.
- **Response Fields:** HTTP 204 No Content.
- **Required Role:** `SUPER_ADMIN` or `TENANT_ADMIN`.

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

### 4.11 Admin API (Tenant Lifecycle Management)
**`POST /v1/admin/tenants`**
- **Description:** Transactionally provision a new tenant, initial administrative actor, audit ledger, and initial budget.
- **Request Fields:** `name` (string), `tenant_id` (optional string), `tier` ("free" | "developer" | "enterprise"), `scs_enabled` (boolean), `pii_detection_enabled` (boolean), `admin_user_id` (optional string).
- **Response Fields:** `id`, `name`, `tier`, `status` ("ACTIVE" | "SUSPENDED" | "OFFBOARDED"), `scs_enabled`, `pii_detection_enabled`, `created_at`, `updated_at`.
- **Required Role:** `SUPER_ADMIN`

**`GET /v1/admin/tenants`**
- **Description:** List tenants within administrative boundary with cursor-based pagination.
- **Query Parameters:** `limit` (integer 1-100, default 50), `cursor` (optional string).
- **Response Fields:** `tenants` (array of tenant objects), `total` (integer), `next_cursor` (optional string).
- **Required Role:** `SUPER_ADMIN` (sees all tenants) or `TENANT_ADMIN` (scoped strictly to own tenant).

**`GET /v1/admin/tenants/{id}`**
- **Description:** Retrieve authoritative tenant status and configuration.
- **Response Fields:** Tenant object.
- **Required Role:** `SUPER_ADMIN` or caller's own tenant matching `TENANT_ADMIN`.

**`PATCH /v1/admin/tenants/{id}`**
- **Description:** Update permitted tenant settings (name, SCS, PII detection, or subscription tier).
- **Request Fields:** `name` (optional), `tier` (optional, restricted to `SUPER_ADMIN`), `scs_enabled` (optional), `pii_detection_enabled` (optional).
- **Response Fields:** Updated tenant object.
- **Required Role:** `SUPER_ADMIN` or caller's own `TENANT_ADMIN`.

**`POST /v1/admin/tenants/{id}/suspend`**
- **Description:** Immediately suspend tenant operations, cutting off authentication across API key and JWT lookup stored procedures.
- **Request Fields:** `reason` (string, required).
- **Response Fields:** Updated tenant object with status `SUSPENDED` and `suspension_reason`.
- **Required Role:** `SUPER_ADMIN`

**`POST /v1/admin/tenants/{id}/reactivate`**
- **Description:** Reactivate a suspended tenant back to `ACTIVE` status.
- **Response Fields:** Updated tenant object with status `ACTIVE`.
- **Required Role:** `SUPER_ADMIN`

**`POST /v1/admin/tenants/{id}/offboard`**
- **Description:** Irreversibly soft-offboard a tenant, instantly revoking all active API credentials and locking the account.
- **Request Fields:** `reason` (string, optional).
- **Response Fields:** Updated tenant object with status `OFFBOARDED`.
- **Required Role:** `SUPER_ADMIN`

### 4.12 API Key Management API
**`POST /v1/auth/api-keys`**
- **Description:** Generate a cryptographically secure, high-entropy API key (`mirage_live_...`). Plaintext secret is returned **only once** upon creation and never persisted or retrievable again. The database stores only the SHA-256 hash.
- **Request Fields:** `name` (string, default "Default API Key"), `scopes` (array of strings, default `["*"]`), `expires_in_days` (optional integer), `tenant_id` (optional string, `SUPER_ADMIN` only).
- **Response Fields:** `id`, `tenant_id`, `name`, `key_prefix` (e.g. `mirage_live_a1b2`), `scopes`, `is_active`, `created_at`, `expires_at`, `key_secret` (plaintext secret, returned only in this response).
- **Required Role:** `SUPER_ADMIN` or `TENANT_ADMIN`.

**`GET /v1/auth/api-keys`**
- **Description:** List API key metadata for a tenant (without plaintext secrets).
- **Query Parameters:** `tenant_id` (optional string, required for `SUPER_ADMIN` targeting a specific tenant).
- **Response Fields:** `keys` (array of API key metadata), `total` (integer).
- **Required Role:** `SUPER_ADMIN` or `TENANT_ADMIN`.

**`POST /v1/auth/api-keys/{id}/rotate`**
- **Description:** Rotate an API key by generating a new active key and either immediately revoking the previous key or scheduling a grace period.
- **Request Fields:** `immediate_revocation` (boolean, default false), `grace_period_seconds` (integer, default 86400 / 24h).
- **Response Fields:** New API key metadata including `key_secret` for the replacement credential.
- **Required Role:** `SUPER_ADMIN` or `TENANT_ADMIN`.

**`DELETE /v1/auth/api-keys/{id}`**
- **Description:** Instantly and permanently revoke an API key credential.
- **Response Fields:** Updated metadata with `revoked_at` timestamp and `is_active: false`.
- **Required Role:** `SUPER_ADMIN` or `TENANT_ADMIN`.

### 4.13 Streaming API
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
