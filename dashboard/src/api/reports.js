/**
 * Compliance Reports & Audit API endpoints.
 *
 * Implements communication with:
 * - POST /v1/reports/generate (202 Accepted)
 * - GET /v1/reports/{report_id}
 * - GET /v1/reports/{report_id}/pdf
 * - POST /v1/audit/verify-chain
 * - GET /v1/audit/report/{session_id}
 * - GET /v1/audit/report/{session_id}/pdf
 * - GET /v1/audit/export
 * - POST /v1/audit/query
 */

import { apiFetch } from "./client";

/**
 * Enqueue asynchronous compliance audit report generation.
 * @param {object} data - { start_date, end_date, model_id, risk_tier }
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>} Status HTTP 202 response
 */
export async function generateReport(data, options = {}) {
  return apiFetch("/v1/reports/generate", {
    method: "POST",
    body: data,
    ...options,
  });
}

/**
 * Poll compliance report compilation status and analytical summary.
 * @param {string} reportId - Generated report ID
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function getReportById(reportId, options = {}) {
  if (!reportId) {
    throw new Error("reportId is required");
  }
  return apiFetch(`/v1/reports/${encodeURIComponent(reportId)}`, options);
}

/**
 * Download compiled multi-session compliance audit PDF.
 * @param {string} reportId - Generated report ID
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<Blob>} PDF Blob
 */
export async function getReportPdf(reportId, options = {}) {
  if (!reportId) {
    throw new Error("reportId is required");
  }
  return apiFetch(`/v1/reports/${encodeURIComponent(reportId)}/pdf`, options);
}

/**
 * Verify cryptographic SHA-256 hash chain across all audit logs for the authenticated tenant.
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function verifyAuditChain(options = {}) {
  return apiFetch("/v1/audit/verify-chain", {
    method: "POST",
    ...options,
  });
}

/**
 * Retrieve compliance audit report JSON for an inspected session.
 * @param {string} sessionId - Session ID
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function getSessionAuditReport(sessionId, options = {}) {
  if (!sessionId) {
    throw new Error("sessionId is required");
  }
  return apiFetch(`/v1/audit/report/${encodeURIComponent(sessionId)}`, options);
}

/**
 * Download single-session compliance verification certificate as PDF.
 * @param {string} sessionId - Session ID
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<Blob>} PDF Blob
 */
export async function getSessionCertificatePdf(sessionId, options = {}) {
  if (!sessionId) {
    throw new Error("sessionId is required");
  }
  return apiFetch(`/v1/audit/report/${encodeURIComponent(sessionId)}/pdf`, options);
}

/**
 * Export all audit logs and verification records in JSON Lines format (GDPR Art. 20).
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<Blob>} ndjson Blob
 */
export async function exportAuditLogs(options = {}) {
  return apiFetch("/v1/audit/export", options);
}

/**
 * Execute natural language search query across tenant audit records.
 * @param {string} query - Natural language query text
 * @param {object} [options={}] - Additional fetch options
 * @returns {Promise<object>}
 */
export async function queryAuditLogs(query, options = {}) {
  return apiFetch("/v1/audit/query", {
    method: "POST",
    body: { query },
    ...options,
  });
}
