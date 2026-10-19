/**
 * Governed MCP Server & Tool Registry API Client.
 *
 * Implements MIRAGE SaaS MCP Integration:
 * - List registered MCP servers
 * - Register new external MCP servers (STDIO / HTTP_STREAM)
 * - Transition trust status (PENDING_APPROVAL -> TRUSTED, SUSPENDED, REVOKED)
 * - Discover and synchronize remote tools into tool_registry
 */

import { apiFetch } from "./client";

/**
 * List registered external MCP servers.
 *
 * @param {object} [params]
 * @param {number} [params.limit=50]
 * @param {number} [params.offset=0]
 * @returns {Promise<{items: Array, total: number}>}
 */
export async function listMCPServers({ limit = 50, offset = 0 } = {}) {
  return apiFetch("/v1/mcp/servers", {
    method: "GET",
    params: { limit, offset },
  });
}

/**
 * Register a new external MCP server in PENDING_APPROVAL status.
 *
 * @param {object} payload
 * @param {string} payload.name
 * @param {string} [payload.description]
 * @param {string} payload.transport_type - "STDIO" | "HTTP_STREAM"
 * @param {object} payload.connection_config
 * @param {Array<string>} [payload.permitted_capabilities]
 * @param {Array<string>} [payload.egress_allowlist]
 * @param {number} [payload.timeout_seconds=30]
 * @returns {Promise<object>} MCPServerResponse
 */
export async function registerMCPServer(payload) {
  return apiFetch("/v1/mcp/servers", {
    method: "POST",
    body: payload,
  });
}

/**
 * Retrieve details for a specific MCP server.
 *
 * @param {string} serverId
 * @returns {Promise<object>} MCPServerResponse
 */
export async function getMCPServer(serverId) {
  return apiFetch(`/v1/mcp/servers/${encodeURIComponent(serverId)}`, {
    method: "GET",
  });
}

/**
 * Update trust status of an MCP server (PENDING_APPROVAL, TRUSTED, SUSPENDED, REVOKED).
 *
 * @param {string} serverId
 * @param {object} payload
 * @param {string} payload.trust_status
 * @param {string} payload.reason
 * @returns {Promise<object>} MCPServerResponse
 */
export async function updateMCPServerTrust(serverId, payload) {
  return apiFetch(`/v1/mcp/servers/${encodeURIComponent(serverId)}/trust`, {
    method: "PUT",
    body: payload,
  });
}

/**
 * Trigger tool discovery and schema synchronization from a TRUSTED MCP server.
 *
 * @param {string} serverId
 * @returns {Promise<object>} MCPToolDiscoveryResult
 */
export async function discoverMCPTools(serverId) {
  return apiFetch(`/v1/mcp/servers/${encodeURIComponent(serverId)}/discover`, {
    method: "POST",
  });
}
