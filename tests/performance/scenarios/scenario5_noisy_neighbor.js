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
const tenantARate = __ENV.TENANT_A_RATE ? parseInt(__ENV.TENANT_A_RATE) : 10; // 10 req/s (10x workload)
const tenantBRate = __ENV.TENANT_B_RATE ? parseInt(__ENV.TENANT_B_RATE) : 1;  // 1 req/s (1x control baseline)

export const options = {
  scenarios: {
    tenant_a_noisy: {
      executor: 'constant-arrival-rate',
      exec: 'tenantAFunction',
      rate: tenantARate,
      timeUnit: '1s',
      duration: duration,
      preAllocatedVUs: 15,
      maxVUs: 40,
      gracefulStop: '10s',
    },
    tenant_b_control: {
      executor: 'constant-arrival-rate',
      exec: 'tenantBFunction',
      rate: tenantBRate,
      timeUnit: '1s',
      duration: duration,
      preAllocatedVUs: 2,
      maxVUs: 10,
      gracefulStop: '10s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<3000'],
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
}

export default function () {
  // Default entrypoint unused when named scenario exec functions are defined
}
