/**
 * Centralized Authentication & Credential Management for k6 Harness (P3.1)
 *
 * Implements Security & Access Document §3.1, §3.2, §13:
 * - Generates cryptographically authentic HMAC-SHA256 JWT access tokens inside k6
 * - Eliminates hardcoded magic credentials while avoiding client-injected headers
 * - Supports multi-tenant virtual user scoping without cross-tenant IDOR
 */

import crypto from 'k6/crypto';
import encoding from 'k6/encoding';
import {
  JWT_SECRET,
  JWT_ALGORITHM,
  DEFAULT_TENANT_ID,
  MULTI_TENANT_ENABLED,
  STATIC_API_KEY,
  STATIC_AUTH_TOKEN,
} from './config.js';

/**
 * Generates a valid cryptographically signed JWT access token using k6 native crypto.
 *
 * @param {string} tenantId - Authoritative tenant identifier
 * @param {string} [role='api_client'] - Authoritative role (Role.API_CLIENT possesses VERIFY_WRITE)
 * @param {string} [userId='perf_vu_user'] - Subject user identifier
 * @param {number} [expiresInSeconds=86400] - Token expiration in seconds
 * @returns {string} Signed JWT token string
 */
export function generateJwtToken(
  tenantId = DEFAULT_TENANT_ID,
  role = 'api_client',
  userId = 'perf_vu_user',
  expiresInSeconds = 86400
) {
  const header = {
    alg: JWT_ALGORITHM,
    typ: 'JWT',
  };

  const now = Math.floor(Date.now() / 1000);
  const payload = {
    sub: userId,
    tenant_id: tenantId,
    role: role,
    iat: now,
    nbf: now,
    exp: now + expiresInSeconds,
    iss: 'mirage-auth',
  };

  const encHeader = encoding.b64encode(JSON.stringify(header), 'rawurl');
  const encPayload = encoding.b64encode(JSON.stringify(payload), 'rawurl');
  const message = `${encHeader}.${encPayload}`;

  const signature = crypto.hmac('sha256', JWT_SECRET, message, 'base64rawurl');
  return `${message}.${signature}`;
}

/**
 * Returns the tenant identifier for a given Virtual User ID.
 *
 * In multi-tenant mode, spreads VUs across isolated tenants (perf_tenant_1, perf_tenant_2, ...)
 * to accurately benchmark tenant isolation and prevent cross-tenant rate limit starvation.
 *
 * @param {number} vuId - k6 Virtual User ID (__VU)
 * @returns {string} Resolved tenant ID
 */
export function getTenantForVu(vuId = 1, iter = null) {
  if (MULTI_TENANT_ENABLED) {
    if (iter !== null && iter !== undefined) {
      return `perf_tenant_${vuId || 1}_${iter % 10}`;
    }
    return `perf_tenant_${vuId || 1}`;
  }
  return DEFAULT_TENANT_ID;
}

/**
 * Returns complete HTTP headers including authentication for a given tenant.
 *
 * Prioritizes:
 * 1. Explicit static token (__ENV.MIRAGE_AUTH_TOKEN)
 * 2. Explicit static API key (__ENV.MIRAGE_API_KEY)
 * 3. Dynamically generated cryptographically signed JWT for the tenant
 *
 * @param {string} tenantId - Tenant identifier
 * @param {number} [vuId=1] - Virtual User ID
 * @returns {object} Headers map
 */
export function getAuthHeaders(tenantId, vuId = 1) {
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  };

  if (STATIC_AUTH_TOKEN) {
    headers['Authorization'] = `Bearer ${STATIC_AUTH_TOKEN}`;
    return headers;
  }

  if (STATIC_API_KEY) {
    headers['X-API-Key'] = STATIC_API_KEY;
    return headers;
  }

  const jwt = generateJwtToken(tenantId, 'api_client', `vu_${vuId}_user`);
  headers['Authorization'] = `Bearer ${jwt}`;
  return headers;
}
