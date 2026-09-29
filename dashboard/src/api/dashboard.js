/**
 * Dashboard & Analytics API endpoints.
 *
 * Implements communication with:
 * - GET /v1/dashboard/stats
 * - GET /v1/dashboard/sessions
 * - GET /v1/sessions/{session_id}
 * - GET /v1/drift
 */

import { apiFetch } from "./client";

/**
 * Retrieve executive summary metrics, risk tier distributions, and drift status.
 * @param {object} [params={}] - Query parameters (e.g. { tenant_id })
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function getDashboardStats(params = {}, options = {}) {
  return apiFetch("/v1/dashboard/stats", { params, ...options });
}

/**
 * Retrieve paginated verification sessions with full claim breakdowns.
 * @param {object} [params={}] - Query parameters: { tenant_id, risk_tier, min_hrs, max_hrs, page, page_size }
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function getDashboardSessions(params = {}, options = {}) {
  return apiFetch("/v1/dashboard/sessions", { params, ...options });
}

/**
 * Retrieve complete verification session details, claims, and execution trace by session ID.
 * @param {string} sessionId - Verification session ID
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function getSessionById(sessionId, options = {}) {
  if (!sessionId) {
    throw new Error("sessionId is required");
  }
  return apiFetch(`/v1/sessions/${encodeURIComponent(sessionId)}`, options);
}

/**
 * Retrieve longitudinal HRS drift analysis (PSI, KS test) and daily trend time-series.
 * @param {object} [params={}] - Query parameters: { tenant_id, days }
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function getDriftReport(params = {}, options = {}) {
  return apiFetch("/v1/drift", { params, ...options });
}
