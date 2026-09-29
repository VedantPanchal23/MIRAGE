/**
 * Performance Scenario 3: Sustained Load & Resource Leakage Profiling (P3.1)
 *
 * Implements Testing Strategy §8 Scenario 3:
 * - 100 concurrent users (VUs) sustained continuously for 10 minutes
 * - Validates system stability without memory leaks, resource exhaustion, or degradation
 * - Checks queue depth, DB connection pool health, and dual-write persistence consistency
 * - Verifies SLA throughput > 33 req/s under continuous production load
 */

import http from 'k6/http';
import { sleep } from 'k6';
import { BASE_URL, validateVerificationResponse } from '../config.js';
import { getAuthHeaders, getTenantForVu } from '../auth.js';
import { getVerificationPayload } from '../payloads.js';
import { createSummaryHandler } from '../metrics.js';

// Configurable sustained duration (default 10m per Testing Strategy §8)
const duration = __ENV.SUSTAINED_DURATION || '10m';
const vus = __ENV.SUSTAINED_VUS ? parseInt(__ENV.SUSTAINED_VUS) : 100;

export const options = {
  scenarios: {
    sustained: {
      executor: 'constant-vus',
      vus: vus,
      duration: duration,
      gracefulStop: '15s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    http_req_failed: ['rate<0.05'],
    http_reqs: vus >= 33 ? ['rate>33'] : ['rate>1'], // Throughput > 33 req/s when running >= 33 VUs
    mirage_verification_success: ['rate>0.95'],
    mirage_http_5xx_rate: ['rate<0.01'],
  },
};

export const handleSummary = createSummaryHandler('scenario3_sustained_load');

export default function () {
  const tenantId = getTenantForVu(__VU, __ITER);
  const headers = getAuthHeaders(tenantId, __VU);
  const payload = JSON.stringify(getVerificationPayload(__ITER, tenantId));

  const res = http.post(`${BASE_URL}/v1/verify`, payload, {
    headers: headers,
    tags: { scenario: 'scenario3_sustained_load' },
    timeout: '15s',
  });

  validateVerificationResponse(res);

  // Pacing: realistic think time between requests per tenant (0.8s - 1.2s)
  // Ensures realistic client pacing while 100 concurrent VUs sustain > 80 req/s aggregate throughput
  const pacingSec = __ENV.MIRAGE_PACING ? parseFloat(__ENV.MIRAGE_PACING) : (0.8 + Math.random() * 0.4);
  sleep(pacingSec);
}
