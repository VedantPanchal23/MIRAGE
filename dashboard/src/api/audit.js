/**
 * Audit Ledger, Chain Integrity, and Compliance Evidence API Client.
 *
 * Implements MIRAGE SaaS Audit & Observability:
 * - Query paginated tenant audit events
 * - Verify cryptographic hash chain and external anchor integrity
 * - Export self-contained, digest-verified compliance evidence bundle
 * - Commit signed checkpoint anchor to external storage
 */

import { apiFetch } from "./client";

/**
 * Query tenant audit events with pagination and filters.
 *
 * @param {object} [params]
 * @param {string} [params.start_time]
 * @param {string} [params.end_time]
 * @param {string} [params.event_type]
 * @param {string} [params.action_id]
 * @param {string} [params.transaction_id]
 * @param {string} [params.session_id]
 * @param {number} [params.limit=50]
 * @param {number} [params.offset=0]
 * @returns {Promise<{events: Array, total_count: number, limit: number, offset: number, next_offset: number|null}>}
 */
export async function getAuditEvents(params = {}) {
  return apiFetch("/v1/audit/events", {
    method: "GET",
    params,
  });
}

/**
 * Verify cryptographic hash chain integrity and external anchor consistency.
 *
 * @returns {Promise<{
 *   tenant_id: string,
 *   status: string,
 *   chain_valid: boolean,
 *   total_records: number,
 *   head_sequence: number,
 *   head_chain_hash: string,
 *   latest_anchor: object|null,
 *   defects: Array<string>
 * }>}
 */
export async function getAuditIntegrity() {
  return apiFetch("/v1/audit/integrity", {
    method: "GET",
  });
}

/**
 * Export a cryptographically sealed compliance evidence bundle.
 *
 * @param {object} payload
 * @param {string} [payload.start_time]
 * @param {string} [payload.end_time]
 * @param {string} [payload.transaction_id]
 * @param {string} [payload.session_id]
 * @param {number} [payload.limit=500]
 * @returns {Promise<object>} AuditEvidenceBundle
 */
export async function exportEvidenceBundle(payload = {}) {
  return apiFetch("/v1/audit/export-bundle", {
    method: "POST",
    body: payload,
  });
}

/**
 * Commit current audit ledger head to external anchor backend (SUPER_ADMIN / TENANT_ADMIN).
 *
 * @param {object} [payload]
 * @param {string} [payload.signer_identity="notary:system_primary"]
 * @param {string} [payload.ledger_identity="audit_logs"]
 * @returns {Promise<{status: string, tenant_id: string, checkpoint: object, anchor: object}>}
 */
export async function commitAuditAnchor(payload = {}) {
  return apiFetch("/v1/audit/anchor", {
    method: "POST",
    body: payload,
  });
}
