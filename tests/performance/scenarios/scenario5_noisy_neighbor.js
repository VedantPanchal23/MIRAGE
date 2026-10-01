/**
 * Performance Scenario 5: Noisy Neighbor / Multi-Tenant Isolation Profiling (P3.2)
 *
 * Implements Testing Strategy §8 Scenario 5:
 * - Tenant A (Noisy Neighbor): Generates 10x the normal workload volume (20 concurrent VUs).
 * - Tenant B (Control Tenant): Runs concurrently as normal control workload (2 concurrent VUs).
 * - Genuinely concurrent execution: Both scenarios run simultaneously in parallel via k6 multi-scenario engine.
 * - Cryptographically isolated: Independently signed HMAC-SHA256 JWTs with authoritative tenant identities.
 * - Validates whether Tenant A's 10x burst degrades Tenant B's latency or causes cross-tenant 429 starvation.
 * - Collects and reports Tenant A and Tenant B performance metrics separately.
 */

import http from 'k6/http';
import { sleep } from 'k6';
import { BASE_URL, validateVerificationResponse } from '../config.js';
import { getAuthHeaders } from '../auth.js';
import { getVerificationPayload } from '../payloads.js';
import {
  createSummaryHandler,
  recordTenantAMetrics,
  recordTenantBMetrics,
} from '../metrics.js';

const duration = __ENV.NOISY_DURATION || '3m';
const tenantAVus = __ENV.TENANT_A_VUS ? parseInt(__ENV.TENANT_A_VUS) : 20; // 10x workload
const tenantBVus = __ENV.TENANT_B_VUS ? parseInt(__ENV.TENANT_B_VUS) : 2;  // 1x baseline control

export const options = {
  scenarios: {
    tenant_a_noisy: {
      executor: 'constant-vus',
      exec: 'tenantAFunction',
      vus: tenantAVus,
      duration: duration,
      gracefulStop: '10s',
    },
    tenant_b_control: {
      executor: 'constant-vus',
      exec: 'tenantBFunction',
      vus: tenantBVus,
      duration: duration,
      gracefulStop: '10s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    tenant_b_429_rate: ['rate<0.01'], // Control tenant must NOT be starved by noisy neighbor
    mirage_http_5xx_rate: ['rate<0.01'],
  },
};

export const handleSummary = createSummaryHandler('scenario5_noisy_neighbor');

/**
 * Tenant A: Generates intense 10x volume burst to stress tenant token buckets and database rows.
 */
export function tenantAFunction() {
  const tenantId = 'noisy_tenant_a';
  const headers = getAuthHeaders(tenantId, __VU);
  const payload = JSON.stringify(getVerificationPayload(__ITER, tenantId));

  const res = http.post(`${BASE_URL}/v1/verify`, payload, {
    headers: headers,
    tags: { scenario: 'scenario5_noisy_neighbor', tenant: 'tenant_a' },
    timeout: '15s',
  });

  const success = validateVerificationResponse(res);
  const is429 = res.status === 429;
  recordTenantAMetrics(res.timings.duration, success, is429);

  // Aggressive pacing: 0.4s - 0.8s for Tenant A (driving high request density)
  const pacingSec = __ENV.TENANT_A_PACING ? parseFloat(__ENV.TENANT_A_PACING) : (0.4 + Math.random() * 0.4);
  sleep(pacingSec);
}

/**
 * Tenant B: Normal control tenant executing concurrent verification requests.
 */
export function tenantBFunction() {
  const tenantId = 'control_tenant_b';
  const headers = getAuthHeaders(tenantId, __VU);
  const payload = JSON.stringify(getVerificationPayload(__ITER, tenantId));

  const res = http.post(`${BASE_URL}/v1/verify`, payload, {
    headers: headers,
    tags: { scenario: 'scenario5_noisy_neighbor', tenant: 'tenant_b' },
    timeout: '15s',
  });

  const success = validateVerificationResponse(res);
  const is429 = res.status === 429;
  recordTenantBMetrics(res.timings.duration, success, is429);

  // Standard pacing for 2 VUs: 2.0s - 2.4s (generating ~0.88 req/s, within 1.0 token/s refill rate)
  const pacingSec = __ENV.TENANT_B_PACING ? parseFloat(__ENV.TENANT_B_PACING) : (2.0 + Math.random() * 0.4);
  sleep(pacingSec);
}

export default function () {
  // Default entrypoint unused when named scenario exec functions are defined
}
