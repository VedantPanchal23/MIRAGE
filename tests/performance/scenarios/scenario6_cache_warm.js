/**
 * Performance Scenario 6: SCS Cache Warm Load & Telemetry Profiling (P3.2)
 *
 * Implements Testing Strategy §8 Scenario 6:
 * - Repeatedly exercises 10 identical deterministic benchmark prompts against the live verification gateway.
 * - Authoritative cache hit/miss verification: Measures cached_scs_hit directly from backend response metadata
 *   (not inferred from latency alone).
 * - Validates the governing performance target of >90% SCS cache hit rate.
 * - Verifies cross-tenant cache isolation: Proves cache entries are keyed by tenant_id (scs:{hash(prompt:model:tenant)})
 *   and do not leak data across tenants.
 * - Preserves approved Redis fail-open SCS bypass semantics.
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, validateVerificationResponse } from '../config.js';
import { getAuthHeaders } from '../auth.js';
import { BENCHMARK_PAYLOADS } from '../payloads.js';
import {
  createSummaryHandler,
  recordPrimaryCacheMetrics,
  recordCrossTenantMetrics,
} from '../metrics.js';

// Governing Testing Strategy §8 Scenario 6: "Blast 10 identical prompts repeatedly."
// Supports two authoritative workload interpretations:
// - 'identical' (default): One canonical benchmark prompt repeated across all iterations,
//   ensuring every prompt in the repeated blast is identical.
// - 'distinct_10': A working set of 10 distinct prompt templates each repeatedly exercised.
const PROMPT_MODE = __ENV.CACHE_PROMPT_MODE || 'identical';
const CANONICAL_PROMPT = BENCHMARK_PAYLOADS[0];
const TEN_PROMPTS = BENCHMARK_PAYLOADS.slice(0, 10);

const iterations = __ENV.CACHE_ITERATIONS ? parseInt(__ENV.CACHE_ITERATIONS) : 100;
const vus = __ENV.CACHE_VUS ? parseInt(__ENV.CACHE_VUS) : 1;

export const options = {
  scenarios: {
    cache_warm: {
      executor: 'per-vu-iterations',
      vus: vus,
      iterations: Math.floor(iterations / vus),
      maxDuration: '10m',
    },
  },
  thresholds: {
    // Official non-smoke execution strictly enforces governing >90% target per Testing Strategy §8
    scs_cache_hit_rate: __ENV.MIRAGE_SMOKE === 'true' ? ['rate>0.50'] : ['rate>0.90'],
    http_req_duration: ['p(95)<3000'],
    mirage_http_5xx_rate: ['rate<0.01'],
  },
};

export const handleSummary = createSummaryHandler('scenario6_cache_warm');

export default function () {
  const template = PROMPT_MODE === 'distinct_10'
    ? TEN_PROMPTS[__ITER % TEN_PROMPTS.length]
    : CANONICAL_PROMPT;
  const promptIdx = PROMPT_MODE === 'distinct_10' ? (__ITER % TEN_PROMPTS.length) : 0;
  const primaryTenant = __ENV.CACHE_TENANT_ID || 'cache_tenant_p32';

  // Construct request payload bound to primary tenant
  const payloadObj = {
    prompt: template.prompt,
    response: template.response,
    tenant_id: primaryTenant,
    model_id: 'llama-3.1-70b-versatile',
    session_id: `s_cache_${promptIdx}_${__ITER}_${Date.now()}`,
    auto_correct: false,
  };

  const headers = getAuthHeaders(primaryTenant, __VU);

  const res = http.post(`${BASE_URL}/v1/verify`, JSON.stringify(payloadObj), {
    headers: headers,
    tags: { scenario: 'scenario6_cache_warm', tenant: primaryTenant },
    timeout: '15s',
  });

  const valid = validateVerificationResponse(res);

  let isHit = false;
  if (res.status === 200) {
    try {
      const data = JSON.parse(res.body);
      // Authoritative application telemetry: metadata.cached_scs_hit from VerificationResponse
      isHit = Boolean(data && data.metadata && data.metadata.cached_scs_hit === true);
    } catch {
      isHit = false;
    }
  }

  // Record strictly against primary cache workload (used for >90% criterion)
  recordPrimaryCacheMetrics(isHit, res.timings.duration);

  check(res, {
    'cache verification response is valid': () => valid,
  });

  // Cross-tenant cache isolation check: Every 20 iterations, verify that a distinct tenant
  // requesting the exact same prompt does NOT leak or produce a cross-tenant cache hit on first lookup.
  // Tracked strictly separate from primary cache workload.
  if (__ITER % 20 === 0 && __ITER > 0) {
    const isolatedTenant = `${primaryTenant}_cross_${__ITER}_${Date.now()}`;
    const isolatedHeaders = getAuthHeaders(isolatedTenant, __VU);
    const isolatedPayload = JSON.stringify({
      ...payloadObj,
      tenant_id: isolatedTenant,
      session_id: `s_cross_${isolatedTenant}_${Date.now()}`,
    });

    const crossRes = http.post(`${BASE_URL}/v1/verify`, isolatedPayload, {
      headers: isolatedHeaders,
      tags: { scenario: 'scenario6_cache_warm', tenant: 'cross_tenant_check' },
      timeout: '15s',
    });

    let crossHit = false;
    if (crossRes.status === 200) {
      try {
        const crossData = JSON.parse(crossRes.body);
        crossHit = Boolean(crossData && crossData.metadata && crossData.metadata.cached_scs_hit === true);
      } catch {
        crossHit = false;
      }
    }

    // Record cross-tenant isolation telemetry separately
    recordCrossTenantMetrics(crossHit);

    check(crossRes, {
      'cross-tenant cache isolation verified (first lookup is a miss)': () => !crossHit,
    });
  }

  // Pacing: 1.0s - 1.2s between iterations (staying within 1.0 token/s refill rate)
  const pacingSec = __ENV.MIRAGE_PACING ? parseFloat(__ENV.MIRAGE_PACING) : (1.0 + Math.random() * 0.2);
  sleep(pacingSec);
}
