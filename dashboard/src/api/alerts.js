/**
 * Operator Alerts API endpoints.
 *
 * Implements communication with:
 * - GET /v1/alerts
 * - POST /v1/alerts/{alert_id}/acknowledge
 */

import { apiFetch } from "./client";

/**
 * Retrieve operator alerts for the authenticated tenant.
 * @param {object} [params={}] - Query parameters: { status, limit, offset }
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function getAlerts(params = {}, options = {}) {
  return apiFetch("/v1/alerts", { params, ...options });
}

/**
 * Acknowledge an active operator alert.
 * @param {string} alertId - ID of the alert to acknowledge
 * @param {object} [data={}] - Request body (e.g. { operator_id })
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function acknowledgeAlert(alertId, data = {}, options = {}) {
  if (!alertId) {
    throw new Error("alertId is required");
  }
  return apiFetch(`/v1/alerts/${encodeURIComponent(alertId)}/acknowledge`, {
    method: "POST",
    body: data,
    ...options,
  });
}
