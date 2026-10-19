/**
 * API Key Lifecycle Administration Client.
 *
 * Implements MIRAGE SaaS Control Plane:
 * - List API key metadata for caller's tenant
 * - Generate cryptographically secure API keys (one-time secret disclosure)
 * - Rotate API keys with immediate or grace-period revocation
 * - Revoke active API keys
 */

import { apiFetch } from "./client";

/**
 * List active and revoked API key metadata.
 *
 * @param {object} [params]
 * @param {string} [params.tenantId] - Super admin override for tenant scoping
 * @param {number} [params.limit=50]
 * @param {number} [params.offset=0]
 * @returns {Promise<{items: Array, total: number}>}
 */
export async function listApiKeys({ tenantId, limit = 50, offset = 0 } = {}) {
  const queryParams = { limit, offset };
  if (tenantId) {
    queryParams.tenant_id = tenantId;
  }
  return apiFetch("/v1/auth/api-keys", {
    method: "GET",
    params: queryParams,
  });
}

/**
 * Issue a new cryptographically secure API key.
 *
 * SECURITY INVARIANT: The response contains the plaintext secret `key_secret`
 * which is returned ONLY ONCE and must never be persisted on the client.
 *
 * @param {object} payload
 * @param {string} payload.name - Key label/identifier
 * @param {string} [payload.tenant_id] - Super admin target tenant
 * @param {Array<string>} [payload.scopes] - Permission scopes (e.g. ["*"])
 * @param {number} [payload.expires_in_days] - Validity period in days
 * @returns {Promise<object>} ApiKeyCreatedResponse with key_secret
 */
export async function createApiKey(payload) {
  return apiFetch("/v1/auth/api-keys", {
    method: "POST",
    body: payload,
  });
}

/**
 * Retrieve metadata for a specific API key.
 *
 * @param {string} keyId - Credential UUID
 * @returns {Promise<object>} ApiKeyMetadata
 */
export async function getApiKey(keyId) {
  return apiFetch(`/v1/auth/api-keys/${encodeURIComponent(keyId)}`, {
    method: "GET",
  });
}

/**
 * Rotate an existing API key.
 *
 * SECURITY INVARIANT: The response contains the plaintext secret `key_secret`
 * which is returned ONLY ONCE and must never be persisted on the client.
 *
 * @param {string} keyId - Credential UUID
 * @param {object} [payload]
 * @param {boolean} [payload.immediate_revocation=true] - Whether old key expires immediately
 * @param {number} [payload.grace_period_seconds=0] - Overlap window if not immediate
 * @returns {Promise<object>} ApiKeyCreatedResponse with new key_secret
 */
export async function rotateApiKey(keyId, payload = {}) {
  return apiFetch(`/v1/auth/api-keys/${encodeURIComponent(keyId)}/rotate`, {
    method: "POST",
    body: payload,
  });
}

/**
 * Revoke an API key immediately.
 *
 * @param {string} keyId - Credential UUID
 * @returns {Promise<object>} ApiKeyMetadata
 */
export async function revokeApiKey(keyId) {
  return apiFetch(`/v1/auth/api-keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
  });
}
