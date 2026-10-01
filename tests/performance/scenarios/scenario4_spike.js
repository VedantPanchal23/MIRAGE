/**
 * Performance Scenario 4: Spike / Burst Concurrency & Pool Surge Recovery (P3.2)
 *
 * Implements Testing Strategy §8 Scenario 4:
 * - Concurrency profile: 10 -> 200 -> 10 concurrent users (VUs)
 * - Stage 1 (Warmup): 10 VUs for 30s
 * - Stage 2 (Spike Surge): 10 -> 200 VUs over 30s
 * - Stage 3 (Peak Hold): 200 VUs sustained for 1m
 * - Stage 4 (Recovery Drain): 200 -> 10 VUs over 30s
 * - Stage 5 (Cooldown / Verification): 10 VUs for 30s
 * - Validates swift recovery of database connection pools and broker queues after extreme burst
 * - Captures throughput, latency percentiles, 429/503/5xx distributions, and post-spike stability
 */

import http from 'k6/http';
import { sleep } from 'k6';
import { BASE_URL, validateVerificationResponse } from '../config.js';
import { getAuthHeaders, getTenantForVu } from '../auth.js';
import { getVerificationPayload } from '../payloads.js';
import { createSummaryHandler } from '../metrics.js';

// Configurable stage durations for agile testing and CI validation
const warmupDuration = __ENV.SPIKE_WARMUP_DURATION || '30s';
const spikeDuration = __ENV.SPIKE_SURGE_DURATION || '30s';
const holdDuration = __ENV.SPIKE_HOLD_DURATION || '1m';
const recoveryDuration = __ENV.SPIKE_RECOVERY_DURATION || '30s';
const cooldownDuration = __ENV.SPIKE_COOLDOWN_DURATION || '30s';
const peakVus = __ENV.SPIKE_PEAK_VUS ? parseInt(__ENV.SPIKE_PEAK_VUS) : 200;
const baselineVus = __ENV.SPIKE_BASELINE_VUS ? parseInt(__ENV.SPIKE_BASELINE_VUS) : 10;

export const options = {
  scenarios: {
    spike_burst: {
      executor: 'ramping-vus',
      startVUs: baselineVus,
      stages: [
        { duration: warmupDuration, target: baselineVus },       // 1. Warmup baseline
        { duration: spikeDuration, target: peakVus },            // 2. Rapid spike to 200 VUs
        { duration: holdDuration, target: peakVus },             // 3. Peak burst stress hold
        { duration: recoveryDuration, target: baselineVus },     // 4. Swift recovery ramp down
        { duration: cooldownDuration, target: baselineVus },     // 5. Post-spike stability verification
      ],
      gracefulRampDown: '15s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    http_req_failed: ['rate<0.10'], // Under 200-VU extreme spike, permit up to 10% transient contention/rejection
    mirage_http_5xx_rate: ['rate<0.01'], // Zero unhandled internal 5xx errors permitted
  },
};

export const handleSummary = createSummaryHandler('scenario4_spike');

export default function () {
  const tenantId = getTenantForVu(__VU, __ITER);
  const headers = getAuthHeaders(tenantId, __VU);
  const payload = JSON.stringify(getVerificationPayload(__ITER, tenantId));

  const res = http.post(`${BASE_URL}/v1/verify`, payload, {
    headers: headers,
    tags: { scenario: 'scenario4_spike' },
    timeout: '15s',
  });

  validateVerificationResponse(res);

  // Dynamic pacing: 0.5s - 1.0s to allow intense concurrency during peak stage
  const pacingSec = __ENV.MIRAGE_PACING ? parseFloat(__ENV.MIRAGE_PACING) : (0.5 + Math.random() * 0.5);
  sleep(pacingSec);
}
