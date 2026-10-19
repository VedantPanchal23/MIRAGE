/**
 * Tenant Administration API Client.
 *
 * Implements MIRAGE SaaS Control Plane:
 * - List tenants with status filtering and pagination
 * - Provision new tenants with transactional isolation
 * - Tenant inspection, updates, suspension, reactivation, and offboarding
 */

import { apiFetch } from "./client";

/**
 * List tenants with optional status filter and pagination.
 *
 * @param {object} [params]
 * @param {string} [params.status] - Optional TenantStatus filter (ACTIVE, SUSPENDED, OFFBOARDED)
 * @param {number} [params.limit=50]
 * @param {number} [params.offset=0]
 * @returns {Promise<{items: Array, total: number}>}
 */
export async function listTenants({ status, limit = 50, offset = 0 } = {}) {
  const queryParams = { limit, offset };
  if (status) {
    queryParams.status = status;
  }
  return apiFetch("/v1/admin/tenants", {
    method: "GET",
    params: queryParams,
  });
}

/**
 * Provision a new tenant.
 *
 * @param {object} payload
 * @param {string} payload.id - Unique tenant identifier
 * @param {string} payload.name - Organization or workspace name
 * @param {string} [payload.environment="production"] - Target deployment environment
 * @param {number} [payload.monthly_budget=1000.0] - Allocated monthly USD budget
 * @returns {Promise<object>} Created TenantResponse
 */
export async function createTenant(payload) {
  return apiFetch("/v1/admin/tenants", {
    method: "POST",
    body: payload,
  });
}

/**
 * Retrieve metadata for a specific tenant.
 *
 * @param {string} tenantId - Tenant identifier
 * @returns {Promise<object>} TenantResponse
 */
export async function getTenant(tenantId) {
  return apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenantId)}`, {
    method: "GET",
  });
}

/**
 * Update mutable properties of a tenant.
 *
 * @param {string} tenantId - Tenant identifier
 * @param {object} payload
 * @param {string} [payload.name]
 * @param {string} [payload.environment]
 * @returns {Promise<object>} Updated TenantResponse
 */
export async function updateTenant(tenantId, payload) {
  return apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenantId)}`, {
    method: "PATCH",
    body: payload,
  });
}

/**
 * Suspend an active tenant.
 *
 * @param {string} tenantId - Tenant identifier
 * @param {object} [payload]
 * @param {string} [payload.reason] - Explanation for administrative suspension
 * @returns {Promise<object>} Suspended TenantResponse
 */
export async function suspendTenant(tenantId, payload = {}) {
  return apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenantId)}/suspend`, {
    method: "POST",
    body: payload,
  });
}

/**
 * Reactivate a suspended tenant.
 *
 * @param {string} tenantId - Tenant identifier
 * @returns {Promise<object>} Active TenantResponse
 */
export async function reactivateTenant(tenantId) {
  return apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenantId)}/reactivate`, {
    method: "POST",
  });
}

/**
 * Offboard and terminate a tenant lifecycle.
 *
 * @param {string} tenantId - Tenant identifier
 * @returns {Promise<object>} Offboarded TenantResponse
 */
export async function offboardTenant(tenantId) {
  return apiFetch(`/v1/admin/tenants/${encodeURIComponent(tenantId)}/offboard`, {
    method: "POST",
  });
}
