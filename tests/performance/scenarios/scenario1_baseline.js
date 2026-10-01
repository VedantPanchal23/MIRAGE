/**
 * Performance Scenario 1: Baseline Performance & Latency Profile (P3.1)
 *
 * Implements Testing Strategy §8 Scenario 1:
 * - 1 concurrent user (VU)
 * - 100 requests
 * - Captures baseline P50, P95, P99 E2E verification latency
 * - Measures throughput (req/s), HTTP status distribution, and verification telemetries
 * - Establishes initial un-contended baseline before load/chaos testing
 */

import http from 'k6/http';
import { sleep } from 'k6';
import { BASE_URL, validateVerificationResponse } from '../config.js';
import { getAuthHeaders, getTenantForVu } from '../auth.js';
import { getVerificationPayload } from '../payloads.js';
import { createSummaryHandler } from '../metrics.js';

export const options = {
  scenarios: {
    baseline: {
      executor: 'per-vu-iterations',
      vus: 1,
      iterations: __ENV.MIRAGE_ITERATIONS ? parseInt(__ENV.MIRAGE_ITERATIONS) : 100,
      maxDuration: '5m',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    http_req_failed: ['rate<0.01'],
    mirage_verification_success: ['rate>0.95'],
  },
};

export const handleSummary = createSummaryHandler('scenario1_baseline');

export default function () {
  const tenantId = getTenantForVu(__VU, __ITER);
  const headers = getAuthHeaders(tenantId, __VU);
  const payload = JSON.stringify(getVerificationPayload(__ITER, tenantId));

  const res = http.post(`${BASE_URL}/v1/verify`, payload, {
    headers: headers,
    tags: { scenario: 'scenario1_baseline' },
    timeout: '10s',
  });

  validateVerificationResponse(res);

  // Pacing: 0.6s delay between sequential requests to simulate realistic client pacing within token refill rate
  const pacingSec = __ENV.MIRAGE_PACING ? parseFloat(__ENV.MIRAGE_PACING) : 0.6;
  if (pacingSec > 0) {
    sleep(pacingSec);
  }
}
