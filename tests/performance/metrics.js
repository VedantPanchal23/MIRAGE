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

    const outputPath = __ENV.MIRAGE_REPORT_FILE || `results/${scenarioName}_summary.json`;

    return {
      [outputPath]: JSON.stringify(summaryReport, null, 2),
      stdout: formatTextSummary(summaryReport),
    };
  };
}

function formatTextSummary(report) {
  const bar = '='.repeat(70);
  return `
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
${bar}
`;
}
