/**
 * API client module for Gate 3 Action Assurance & Tool Governance.
 */

import { apiFetch } from "./client";

/**
 * Fetch registered governed tools for the current tenant.
 *
 * @returns {Promise<Array<Object>>}
 */
export async function getTools() {
  return apiFetch("/v1/tools");
}

/**
 * Register a governed tool definition.
 *
 * @param {Object} payload - { name, description, tool_type, egress_type, trust_level, required_capability, parameters_schema, config, active }
 * @returns {Promise<Object>}
 */
export async function registerTool(payload) {
  return apiFetch("/v1/tools", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Submit an action proposal for Gate 3 authorization.
 *
 * @param {Object} payload - { transaction_id, tool_name, action_type, target_resource, parameters, idempotency_key, blast_radius, preconditions, postconditions }
 * @returns {Promise<Object>} ActionAuthorizationDecision
 */
export async function proposeAction(payload) {
  return apiFetch("/v1/actions/propose", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Submit an atomic batch of action proposals.
 *
 * @param {Object} payload - { transaction_id, actions }
 * @returns {Promise<Object>} BatchAuthorizationDecision
 */
export async function proposeActionBatch(payload) {
  return apiFetch("/v1/actions/batch", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Dispatch an authorized action contract through the Tool Proxy.
 *
 * @param {Object} payload - { action_id }
 * @returns {Promise<Object>} ActionExecutionResult
 */
export async function executeAction(payload) {
  return apiFetch("/v1/actions/execute", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Retrieve an action contract by ID.
 *
 * @param {string} actionId
 * @returns {Promise<Object>}
 */
export async function getAction(actionId) {
  return apiFetch(`/v1/actions/${encodeURIComponent(actionId)}`);
}

/**
 * Fetch pending L4 human approval tickets for the current tenant.
 *
 * @returns {Promise<Array<Object>>}
 */
export async function getPendingApprovals() {
  return apiFetch("/v1/approvals/pending");
}

/**
 * Grant a pending human approval ticket.
 *
 * @param {string} approvalId
 * @param {string} reason
 * @returns {Promise<Object>}
 */
export async function grantApproval(approvalId, reason) {
  return apiFetch(`/v1/approvals/${encodeURIComponent(approvalId)}/grant`, {
    method: "POST",
    body: JSON.stringify({ decision: "GRANT", reason }),
  });
}

/**
 * Deny a pending human approval ticket.
 *
 * @param {string} approvalId
 * @param {string} reason
 * @returns {Promise<Object>}
 */
export async function denyApproval(approvalId, reason) {
  return apiFetch(`/v1/approvals/${encodeURIComponent(approvalId)}/deny`, {
    method: "POST",
    body: JSON.stringify({ decision: "DENY", reason }),
  });
}
