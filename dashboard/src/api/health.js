/**
 * Health and Readiness API endpoints.
 *
 * Implements communication with:
 * - GET /v1/health
 * - GET /v1/ready
 */

import { apiFetch } from "./client";

/**
 * Retrieve system liveness status and circuit breaker states.
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function getHealth(options = {}) {
  return apiFetch("/v1/health", options);
}

/**
 * Retrieve backend readiness status across all backing services.
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function getReadiness(options = {}) {
  return apiFetch("/v1/ready", options);
}
