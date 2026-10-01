/**
 * Custom Telemetry and Metrics Collection for k6 Performance Tests (P3.1)
 *
 * Implements Testing Strategy §8:
 * - Differentiates transport vs application vs dependency metrics
 * - Custom k6 Trends, Rates, and Counters
 * - handleSummary report generator producing structured JSON and ASCII summary
 */

import { Trend, Rate, Counter } from 'k6/metrics';

// Custom Metrics
export const mirageVerificationDuration = new Trend('mirage_verification_duration', true);
export const mirageHrsScore = new Trend('mirage_hrs_score', true);
export const mirageClaimsCount = new Counter('mirage_claims_extracted');
export const mirageVerificationSuccess = new Rate('mirage_verification_success');
export const mirageRateLimitHit = new Rate('mirage_http_429_rate');
export const mirageServiceDegraded = new Rate('mirage_service_degraded_rate');
export const mirageHttp5xx = new Rate('mirage_http_5xx_rate');

export function recordVerificationDuration(val) {
  mirageVerificationDuration.add(val);
}

export function recordHrsScore(score) {
  mirageHrsScore.add(score);
}

export function recordClaimsCount(count) {
  mirageClaimsCount.add(count);
}

export function recordSuccess(success) {
  mirageVerificationSuccess.add(success);
}

export function recordRateLimit(hit) {
  mirageRateLimitHit.add(hit);
}

export function recordServiceDegraded(degraded) {
  mirageServiceDegraded.add(degraded);
}

export function recordHttp5xx(is5xx) {
  mirageHttp5xx.add(is5xx);
}

// Scenario 5: Noisy Neighbor Isolated Telemetry
export const mirageTenantADuration = new Trend('tenant_a_duration', true);
export const mirageTenantBDuration = new Trend('tenant_b_duration', true);
export const mirageTenantAReqs = new Counter('tenant_a_reqs_total');
export const mirageTenantBReqs = new Counter('tenant_b_reqs_total');
export const mirageTenantASuccess = new Rate('tenant_a_success_rate');
export const mirageTenantBSuccess = new Rate('tenant_b_success_rate');
export const mirageTenantA429 = new Rate('tenant_a_429_rate');
export const mirageTenantB429 = new Rate('tenant_b_429_rate');

export function recordTenantAMetrics(duration, success, is429) {
  mirageTenantADuration.add(duration);
  mirageTenantAReqs.add(1);
  mirageTenantASuccess.add(success);
  mirageTenantA429.add(is429);
}

export function recordTenantBMetrics(duration, success, is429) {
  mirageTenantBDuration.add(duration);
  mirageTenantBReqs.add(1);
  mirageTenantBSuccess.add(success);
  mirageTenantB429.add(is429);
}

// Scenario 6: Primary Cache Workload Metrics
export const mirageScsCacheHitRate = new Rate('scs_cache_hit_rate');
export const mirageScsCacheHits = new Counter('scs_cache_hits_total');
export const mirageScsCacheMisses = new Counter('scs_cache_misses_total');
export const mirageCacheHitDuration = new Trend('cache_hit_duration', true);
export const mirageCacheMissDuration = new Trend('cache_miss_duration', true);

// Scenario 6: Cross-Tenant Isolation Metrics (tracked strictly separate from primary cache workload)
export const mirageCrossTenantChecks = new Counter('cross_tenant_checks_total');
export const mirageCrossTenantMisses = new Counter('cross_tenant_misses_total');
export const mirageCrossTenantHits = new Counter('cross_tenant_hits_total');
export const mirageCrossTenantIsolationRate = new Rate('cross_tenant_isolation_rate');

export function recordPrimaryCacheMetrics(isHit, duration) {
  mirageScsCacheHitRate.add(isHit);
  if (isHit) {
    mirageScsCacheHits.add(1);
    mirageCacheHitDuration.add(duration);
  } else {
    mirageScsCacheMisses.add(1);
    mirageCacheMissDuration.add(duration);
  }
}

export function recordCrossTenantMetrics(isHit) {
  mirageCrossTenantChecks.add(1);
  if (isHit) {
    mirageCrossTenantHits.add(1);
    mirageCrossTenantIsolationRate.add(0); // isolation violated
  } else {
    mirageCrossTenantMisses.add(1);
    mirageCrossTenantIsolationRate.add(1); // isolation preserved
  }
}

// Backward compatibility helper
export function recordCacheMetrics(isHit, duration) {
  recordPrimaryCacheMetrics(isHit, duration);
}

/**
 * Standard k6 summary callback: generates clean JSON and text summaries.
 *
 * @param {object} data - k6 raw summary data
 * @returns {object} Formatted output map
 */
export function createSummaryHandler(scenarioName) {
  return function (data) {
    const httpDuration = data.metrics.http_req_duration ? data.metrics.http_req_duration.values : {};
    const httpReqs = data.metrics.http_reqs ? data.metrics.http_reqs.values : {};
    const successRate = data.metrics.mirage_verification_success ? data.metrics.mirage_verification_success.values : {};
    const rateLimitRate = data.metrics.mirage_http_429_rate ? data.metrics.mirage_http_429_rate.values : {};
    const degradedRate = data.metrics.mirage_service_degraded_rate ? data.metrics.mirage_service_degraded_rate.values : {};
    const unhandled5xx = data.metrics.mirage_http_5xx_rate ? data.metrics.mirage_http_5xx_rate.values : {};
    const hrsTrend = data.metrics.mirage_hrs_score ? data.metrics.mirage_hrs_score.values : {};

    const summaryReport = {
      scenario: scenarioName,
      timestamp: new Date().toISOString(),
      metadata: {
        vus_max: data.metrics.vus ? data.metrics.vus.values.max : 0,
        total_requests: httpReqs.count || 0,
        throughput_rps: Number((httpReqs.rate || 0).toFixed(2)),
      },
      latency_ms: {
        min: Number((httpDuration.min || 0).toFixed(2)),
        avg: Number((httpDuration.avg || 0).toFixed(2)),
        med_p50: Number((httpDuration.med || 0).toFixed(2)),
        p90: Number((httpDuration['p(90)'] || 0).toFixed(2)),
        p95: Number((httpDuration['p(95)'] || 0).toFixed(2)),
        p99: Number((httpDuration['p(99)'] || 0).toFixed(2)),
        max: Number((httpDuration.max || 0).toFixed(2)),
      },
      reliability: {
        verification_success_rate: Number(((successRate.rate || 0) * 100).toFixed(2)),
        http_429_rate_limit_rate: Number(((rateLimitRate.rate || 0) * 100).toFixed(2)),
        service_degraded_503_rate: Number(((degradedRate.rate || 0) * 100).toFixed(2)),
        unhandled_5xx_error_rate: Number(((unhandled5xx.rate || 0) * 100).toFixed(2)),
      },
      verification_telemetry: {
        mean_hrs: Number((hrsTrend.avg || 0).toFixed(4)),
        claims_evaluated: data.metrics.mirage_claims_extracted ? data.metrics.mirage_claims_extracted.values.count : 0,
      },
    };

    // Scenario 5: Tenant Isolation Breakdown
    if (data.metrics.tenant_a_reqs_total || data.metrics.tenant_b_reqs_total) {
      const aReqs = data.metrics.tenant_a_reqs_total ? data.metrics.tenant_a_reqs_total.values.count : 0;
      const bReqs = data.metrics.tenant_b_reqs_total ? data.metrics.tenant_b_reqs_total.values.count : 0;
      const aDuration = data.metrics.tenant_a_duration ? data.metrics.tenant_a_duration.values : {};
      const bDuration = data.metrics.tenant_b_duration ? data.metrics.tenant_b_duration.values : {};
      const aSuccess = data.metrics.tenant_a_success_rate ? data.metrics.tenant_a_success_rate.values.rate : 0;
      const bSuccess = data.metrics.tenant_b_success_rate ? data.metrics.tenant_b_success_rate.values.rate : 0;
      const a429 = data.metrics.tenant_a_429_rate ? data.metrics.tenant_a_429_rate.values.rate : 0;
      const b429 = data.metrics.tenant_b_429_rate ? data.metrics.tenant_b_429_rate.values.rate : 0;

      summaryReport.tenant_isolation_breakdown = {
        tenant_a_noisy: {
          requests: aReqs,
          p50_ms: Number((aDuration.med || 0).toFixed(2)),
          p95_ms: Number((aDuration['p(95)'] || 0).toFixed(2)),
          success_rate_pct: Number((aSuccess * 100).toFixed(2)),
          rate_limited_429_rate_pct: Number((a429 * 100).toFixed(2)),
        },
        tenant_b_control: {
          requests: bReqs,
          p50_ms: Number((bDuration.med || 0).toFixed(2)),
          p95_ms: Number((bDuration['p(95)'] || 0).toFixed(2)),
          success_rate_pct: Number((bSuccess * 100).toFixed(2)),
          rate_limited_429_rate_pct: Number((b429 * 100).toFixed(2)),
        },
        workload_ratio_a_to_b: bReqs > 0 ? Number((aReqs / bReqs).toFixed(2)) : 'N/A',
      };
    }

    // Scenario 6: SCS Cache Performance & Isolation Accounting
    if (data.metrics.scs_cache_hit_rate) {
      const hitRateVal = data.metrics.scs_cache_hit_rate.values.rate || 0;
      const hitsCount = data.metrics.scs_cache_hits_total ? data.metrics.scs_cache_hits_total.values.count : 0;
      const missesCount = data.metrics.scs_cache_misses_total ? data.metrics.scs_cache_misses_total.values.count : 0;
      const hitDuration = data.metrics.cache_hit_duration ? data.metrics.cache_hit_duration.values : {};
      const missDuration = data.metrics.cache_miss_duration ? data.metrics.cache_miss_duration.values : {};

      const crossChecks = data.metrics.cross_tenant_checks_total ? data.metrics.cross_tenant_checks_total.values.count : 0;
      const crossMisses = data.metrics.cross_tenant_misses_total ? data.metrics.cross_tenant_misses_total.values.count : 0;
      const crossHits = data.metrics.cross_tenant_hits_total ? data.metrics.cross_tenant_hits_total.values.count : 0;
      const isolationRate = data.metrics.cross_tenant_isolation_rate ? data.metrics.cross_tenant_isolation_rate.values.rate : 1.0;

      summaryReport.cache_performance = {
        primary_cache_workload: {
          total_requests: hitsCount + missesCount,
          cache_hits_count: hitsCount,
          cache_misses_count: missesCount,
          cache_hit_rate_pct: Number((hitRateVal * 100).toFixed(2)),
          hit_latency_p50_ms: Number((hitDuration.med || 0).toFixed(2)),
          miss_latency_p50_ms: Number((missDuration.med || 0).toFixed(2)),
          latency_reduction_factor: (hitDuration.med && missDuration.med && hitDuration.med > 0)
            ? Number((missDuration.med / hitDuration.med).toFixed(2))
            : 'N/A',
          governing_target_met: hitRateVal >= 0.90,
        },
        cross_tenant_isolation_workload: {
          total_checks: crossChecks,
          cross_tenant_misses: crossMisses,
          cross_tenant_hits: crossHits,
          isolation_rate_pct: Number((isolationRate * 100).toFixed(2)),
          cross_tenant_leakage_detected: crossHits > 0,
        },
        // Flat aliases for backwards compatibility with existing summary consumers
        cache_hit_rate_pct: Number((hitRateVal * 100).toFixed(2)),
        cache_hits_count: hitsCount,
        cache_misses_count: missesCount,
        total_cache_lookups: hitsCount + missesCount,
        hit_latency_p50_ms: Number((hitDuration.med || 0).toFixed(2)),
        miss_latency_p50_ms: Number((missDuration.med || 0).toFixed(2)),
        latency_reduction_factor: (hitDuration.med && missDuration.med && hitDuration.med > 0)
          ? Number((missDuration.med / hitDuration.med).toFixed(2))
          : 'N/A',
        governing_target_met: hitRateVal >= 0.90,
      };
    }

    const outputPath = __ENV.MIRAGE_REPORT_FILE || `results/${scenarioName}_summary.json`;

    return {
      [outputPath]: JSON.stringify(summaryReport, null, 2),
      stdout: formatTextSummary(summaryReport),
    };
  };
}

function formatTextSummary(report) {
  const bar = '='.repeat(70);
  let text = `
${bar}
  MIRAGE PERFORMANCE TEST EXECUTION: ${report.scenario.toUpperCase()}
${bar}
  Execution Timestamp: ${report.timestamp}
  Total Requests:      ${report.metadata.total_requests}
  Peak Concurrency:    ${report.metadata.vus_max} VUs
  Sustained Rate:      ${report.metadata.throughput_rps} req/sec

  Latency Profile (E2E):
    - P50 (Median):    ${report.latency_ms.med_p50} ms
    - P90:             ${report.latency_ms.p90} ms
    - P95:             ${report.latency_ms.p95} ms (SLA Target: < 3000 ms)
    - P99:             ${report.latency_ms.p99} ms
    - Min / Max:       ${report.latency_ms.min} ms / ${report.latency_ms.max} ms

  Reliability & Error Breakdown:
    - Verification Success Rate: ${report.reliability.verification_success_rate}%
    - Rate Limited (429):        ${report.reliability.http_429_rate_limit_rate}%
    - Service Degraded (503):    ${report.reliability.service_degraded_503_rate}%
    - Unhandled 5xx Errors:      ${report.reliability.unhandled_5xx_error_rate}%

  Application Telemetry:
    - Mean Calibrated HRS:       ${report.verification_telemetry.mean_hrs}
    - Total Claims Evaluated:    ${report.verification_telemetry.claims_evaluated}
`;

  if (report.tenant_isolation_breakdown) {
    const tb = report.tenant_isolation_breakdown;
    text += `
  Tenant Isolation Breakdown (Scenario 5):
    - Workload Ratio (A:B):   ${tb.workload_ratio_a_to_b}x
    - Tenant A (Burst):       ${tb.tenant_a_noisy.requests} reqs, P50: ${tb.tenant_a_noisy.p50_ms} ms, P95: ${tb.tenant_a_noisy.p95_ms} ms, Success: ${tb.tenant_a_noisy.success_rate_pct}%, 429: ${tb.tenant_a_noisy.rate_limited_429_rate_pct}%
    - Tenant B (Control):     ${tb.tenant_b_control.requests} reqs, P50: ${tb.tenant_b_control.p50_ms} ms, P95: ${tb.tenant_b_control.p95_ms} ms, Success: ${tb.tenant_b_control.success_rate_pct}%, 429: ${tb.tenant_b_control.rate_limited_429_rate_pct}%
`;
  }

  if (report.cache_performance) {
    const cp = report.cache_performance;
    text += `
  SCS Cache Telemetry (Scenario 6):
    - Cache Hit Rate:         ${cp.cache_hit_rate_pct}% (Governing Target > 90%: ${cp.governing_target_met ? 'MET' : 'NOT MET'})
    - Cache Hits / Misses:    ${cp.cache_hits_count} / ${cp.cache_misses_count} (Total: ${cp.total_cache_lookups})
    - Latency (Hit vs Miss):  ${cp.hit_latency_p50_ms} ms vs ${cp.miss_latency_p50_ms} ms (Speedup: ${cp.latency_reduction_factor}x)
`;
  }

  text += `${bar}\n`;
  return text;
}
