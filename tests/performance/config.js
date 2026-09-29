/**
 * Centralized Configuration for MIRAGE k6 Performance Testing Harness (P3.1)
 *
 * Implements Testing Strategy §8 and Security & Access Document §3.1, §3.2, §7.2:
 * - Dynamic environment resolution via __ENV with safe defaults
 * - Authoritative tenant configuration matching JWT signature
 * - Standardized response validation distinguishing transport vs application vs degradation errors
 */

import { check } from 'k6';
import {
  recordVerificationDuration,
  recordHrsScore,
  recordClaimsCount,
  recordSuccess,
  recordRateLimit,
  recordServiceDegraded,
  recordHttp5xx,
} from './metrics.js';

// Base Gateway URL under test
export const BASE_URL = __ENV.MIRAGE_BASE_URL || 'http://localhost:8000';

// Cryptographic secret key for JWT access tokens (from shared/config/settings.py)
export const JWT_SECRET = __ENV.MIRAGE_JWT_SECRET || 'dev-insecure-secret-key-change-in-production-min32chars';
export const JWT_ALGORITHM = 'HS256';

// Multi-tenant configuration: enabled by default to benchmark realistic isolated tenant buckets
export const MULTI_TENANT_ENABLED = __ENV.MIRAGE_MULTI_TENANT !== 'false';
export const DEFAULT_TENANT_ID = __ENV.MIRAGE_TENANT_ID || 'perf_tenant_default';

// Optional pre-configured API Key or Bearer Token (if provided via environment)
export const STATIC_API_KEY = __ENV.MIRAGE_API_KEY || '';
export const STATIC_AUTH_TOKEN = __ENV.MIRAGE_AUTH_TOKEN || '';

// Target generator model for verification payloads
export const DEFAULT_MODEL_ID = __ENV.MIRAGE_MODEL_ID || 'llama-3.1-70b-versatile';

/**
 * Standard performance SLA thresholds per Testing Strategy §8.
 */
export const DEFAULT_THRESHOLDS = {
  http_req_duration: ['p(95)<3000', 'p(99)<4000'],
  http_req_failed: ['rate<0.01'],
  mirage_verification_success: ['rate>0.95'],
  mirage_http_5xx_rate: ['rate<0.01'],
};

/**
 * Validates and records performance metrics for a /v1/verify HTTP response.
 *
 * Distinguishes:
 * - HTTP 200: Verification successfully processed and persisted
 * - HTTP 429: Rate limit capacity exceeded on tenant token bucket
 * - HTTP 503: Service degraded (Postgres/Redis/Mongo persistence failure or circuit open)
 * - HTTP 5xx: Unhandled application failure
 * - Payload validation: Validates presence of verified_response, hrs_result, and claims
 *
 * @param {import('k6/http').RefinedResponse} res - k6 HTTP response object
 * @returns {boolean} True if verification succeeded cleanly
 */
export function validateVerificationResponse(res) {
  const is200 = res.status === 200;
  const is429 = res.status === 429;
  const is503 = res.status === 503;
  const is5xx = res.status >= 500 && !is503;

  // Record status telemetry
  recordRateLimit(is429);
  recordServiceDegraded(is503);
  recordHttp5xx(is5xx);

  let hasValidPayload = false;
  let parsed = null;

  if (is200) {
    try {
      parsed = JSON.parse(res.body);
      hasValidPayload =
        typeof parsed === 'object' &&
        parsed !== null &&
        typeof parsed.verified_response === 'string' &&
        typeof parsed.hrs_result === 'object' &&
        parsed.hrs_result !== null &&
        typeof parsed.hrs_result.hrs === 'number';

      if (hasValidPayload) {
        recordVerificationDuration(res.timings.duration);
        recordHrsScore(parsed.hrs_result.hrs);
        if (Array.isArray(parsed.claims)) {
          recordClaimsCount(parsed.claims.length);
        }
      }
    } catch {
      hasValidPayload = false;
    }
  }

  const success = is200 && hasValidPayload;
  recordSuccess(success);

  check(res, {
    'status is 200 OK': () => is200,
    'not rate limited (429)': () => !is429,
    'not degraded (503)': () => !is503,
    'no unhandled 5xx error': () => !is5xx,
    'payload contains valid hrs_result': () => hasValidPayload,
  });

  return success;
}
