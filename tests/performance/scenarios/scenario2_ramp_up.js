/**
 * Performance Scenario 2: Concurrency Ramp-Up & Inflection Point Profiling (P3.1)
 *
 * Implements Testing Strategy §8 Scenario 2:
 * - 1 -> 100 concurrent users (VUs) ramped smoothly over 5 minutes
 * - Identifies latency and throughput inflection breaking points
 * - Records measured throughput vs. response time curves as concurrency scales
 * - Supports configurable stage durations via environment variables for agile execution
 */

import http from 'k6/http';
import { sleep } from 'k6';
import { BASE_URL, validateVerificationResponse } from '../config.js';
import { getAuthHeaders, getTenantForVu } from '../auth.js';
import { getVerificationPayload } from '../payloads.js';
import { createSummaryHandler } from '../metrics.js';

// Configurable ramp duration (default 5m per Testing Strategy §8)
const rampDuration = __ENV.RAMP_DURATION || '5m';
const plateauDuration = __ENV.PLATEAU_DURATION || '1m';
const targetVus = __ENV.TARGET_VUS ? parseInt(__ENV.TARGET_VUS) : 100;

export const options = {
  scenarios: {
    ramp_up: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: rampDuration, target: targetVus },       // Smooth ramp from 1 to 100 VUs
        { duration: plateauDuration, target: targetVus },   // Measure peak behavior at max concurrency
        { duration: '30s', target: 0 },                     // Graceful ramp down
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    http_req_failed: ['rate<0.05'],
  },
};

export const handleSummary = createSummaryHandler('scenario2_ramp_up');

export default function () {
  const tenantId = getTenantForVu(__VU, __ITER);
  const headers = getAuthHeaders(tenantId, __VU);
  const payload = JSON.stringify(getVerificationPayload(__ITER, tenantId));

  const res = http.post(`${BASE_URL}/v1/verify`, payload, {
    headers: headers,
    tags: { scenario: 'scenario2_ramp_up' },
    timeout: '15s',
  });

  validateVerificationResponse(res);

  // Pacing: realistic think time between requests per tenant (0.8s - 1.2s)
  // Ensures realistic client pacing while 100 concurrent VUs sustain > 80 req/s aggregate throughput
  const pacingSec = __ENV.MIRAGE_PACING ? parseFloat(__ENV.MIRAGE_PACING) : (0.8 + Math.random() * 0.4);
  sleep(pacingSec);
}
