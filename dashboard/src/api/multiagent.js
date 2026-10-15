/**
 * API client module for Phase 8 Multi-Agent Governance, Delegation,
 * Handoffs, Resource Concurrency, and Hierarchical Outcome Assurance.
 */

import { apiFetch } from "./client";

// ==========================================
// 1. AGENT LIFECYCLE GOVERNANCE
// ==========================================

/**
 * List registered agents within the authenticated tenant.
 * @param {Object} [params] - Optional query parameters: { status, limit, offset }
 * @returns {Promise<{ agents: Array<Object>, total: number, limit: number, offset: number }>}
 */
export async function listAgents(params = {}) {
  return apiFetch("/v1/agents", { params });
}

/**
 * Retrieve a specific agent by ID.
 * @param {string} agentId
 * @returns {Promise<Object>} AgentResponse
 */
export async function getAgent(agentId) {
  return apiFetch(`/v1/agents/${agentId}`);
}

/**
 * Register a new governed agent.
 * @param {Object} payload - AgentRegistrationRequest: { name, max_autonomy_level, initial_status, metadata }
 * @returns {Promise<Object>} AgentResponse
 */
export async function registerAgent(payload) {
  return apiFetch("/v1/agents", {
    method: "POST",
    body: payload,
  });
}

/**
 * Activate an agent.
 * @param {string} agentId
 * @param {string} [reason="Agent activation"]
 * @returns {Promise<Object>} AgentResponse
 */
export async function activateAgent(agentId, reason = "Agent activation") {
  return apiFetch(`/v1/agents/${agentId}/activate`, {
    method: "POST",
    body: { reason },
  });
}

/**
 * Suspend an active agent.
 * @param {string} agentId
 * @param {string} reason - Required audit justification
 * @returns {Promise<Object>} AgentResponse
 */
export async function suspendAgent(agentId, reason) {
  return apiFetch(`/v1/agents/${agentId}/suspend`, {
    method: "POST",
    body: { reason },
  });
}

/**
 * Permanently revoke an agent.
 * @param {string} agentId
 * @param {string} reason - Required audit justification
 * @returns {Promise<Object>} AgentResponse
 */
export async function revokeAgent(agentId, reason) {
  return apiFetch(`/v1/agents/${agentId}/revoke`, {
    method: "POST",
    body: { reason },
  });
}

// ==========================================
// 2. CROSS-AGENT DELEGATION GRANTS
// ==========================================

/**
 * List delegation grants with optional filtering.
 * @param {Object} [params] - { status, parent_transaction_id, child_agent_id, limit, offset }
 * @returns {Promise<Array<Object>>} List of DelegationGrantResponse
 */
export async function listDelegations(params = {}) {
  return apiFetch("/v1/delegations", { params });
}

/**
 * Retrieve a delegation grant by ID.
 * @param {string} delegationId
 * @returns {Promise<Object>} DelegationGrantResponse
 */
export async function getDelegation(delegationId) {
  return apiFetch(`/v1/delegations/${delegationId}`);
}

/**
 * Create a new attenuated delegation grant.
 * @param {Object} payload - DelegationGrantRequest
 * @returns {Promise<Object>} DelegationGrantResponse
 */
export async function createDelegation(payload) {
  return apiFetch("/v1/delegations", {
    method: "POST",
    body: payload,
  });
}

/**
 * Bind a pending delegation grant to a child transaction and activate it.
 * @param {string} delegationId
 * @param {string} childTransactionId
 * @returns {Promise<Object>} DelegationGrantResponse
 */
export async function activateDelegation(delegationId, childTransactionId) {
  return apiFetch(`/v1/delegations/${delegationId}/activate`, {
    method: "POST",
    body: { child_transaction_id: childTransactionId },
  });
}

/**
 * Explicitly revoke a delegation grant.
 * @param {string} delegationId
 * @param {string} reason - Required audit justification
 * @returns {Promise<Object>} DelegationGrantResponse
 */
export async function revokeDelegation(delegationId, reason) {
  return apiFetch(`/v1/delegations/${delegationId}/revoke`, {
    method: "POST",
    body: { reason },
  });
}

/**
 * Evaluate whether a delegation grant authorizes an operation.
 * @param {string} delegationId
 * @param {Object} payload - { capability_type, resource, requested_autonomy_level }
 * @returns {Promise<Object>} PolicyDecision
 */
export async function validateDelegation(delegationId, payload) {
  return apiFetch(`/v1/delegations/${delegationId}/validate`, {
    method: "POST",
    body: payload,
  });
}

// ==========================================
// 3. GOVERNED AGENT HANDOFFS
// ==========================================

/**
 * List agent handoff records with optional filtering.
 * @param {Object} [params] - { status, parent_transaction_id, child_agent_id, limit, offset }
 * @returns {Promise<Array<Object>>} List of AgentHandoffResponse
 */
export async function listHandoffs(params = {}) {
  return apiFetch("/v1/handoffs", { params });
}

/**
 * Retrieve a specific handoff by ID.
 * @param {string} handoffId
 * @returns {Promise<Object>} AgentHandoffResponse
 */
export async function getHandoff(handoffId) {
  return apiFetch(`/v1/handoffs/${handoffId}`);
}

/**
 * Initiate a governed agent handoff.
 * @param {Object} payload - AgentHandoffCreateRequest
 * @returns {Promise<Object>} AgentHandoffResponse
 */
export async function createHandoff(payload) {
  return apiFetch("/v1/handoffs", {
    method: "POST",
    body: payload,
  });
}

/**
 * Accept a pending handoff and spawn child execution.
 * @param {string} handoffId
 * @param {Object} [payload={ input_context: {} }] - AgentHandoffAcceptRequest
 * @returns {Promise<Object>} AgentHandoffAcceptResponse
 */
export async function acceptHandoff(handoffId, payload = { input_context: {} }) {
  return apiFetch(`/v1/handoffs/${handoffId}/accept`, {
    method: "POST",
    body: payload,
  });
}

/**
 * Cancel a pending or active handoff with an explicit reason.
 * @param {string} handoffId
 * @param {string} reason - Audit justification
 * @returns {Promise<Object>} AgentHandoffResponse
 */
export async function cancelHandoff(handoffId, reason) {
  return apiFetch(`/v1/handoffs/${handoffId}/cancel`, {
    method: "POST",
    body: { reason },
  });
}

/**
 * Mark an accepted handoff as completed following outcome verification.
 * @param {string} handoffId
 * @returns {Promise<Object>} AgentHandoffResponse
 */
export async function completeHandoff(handoffId) {
  return apiFetch(`/v1/handoffs/${handoffId}/complete`, {
    method: "POST",
  });
}

// ==========================================
// 4. RESOURCE CONCURRENCY & LEASES
// ==========================================

/**
 * List active or historical resource leases.
 * @param {Object} [params] - { resource_uri, holder_transaction_id, status, limit, offset }
 * @returns {Promise<Array<Object>>} List of ResourceLeaseResponse
 */
export async function listLeases(params = {}) {
  return apiFetch("/v1/resources/leases", { params });
}

/**
 * Acquire a concurrency lease on a shared resource with a monotonic fencing token.
 * @param {Object} payload - ResourceLeaseAcquireRequest
 * @returns {Promise<Object>} ResourceLeaseResponse
 */
export async function acquireLease(payload) {
  return apiFetch("/v1/resources/leases/acquire", {
    method: "POST",
    body: payload,
  });
}

/**
 * Safely release an acquired lease using its verified fencing token.
 * @param {string} leaseId
 * @param {Object} payload - { transaction_id, agent_id, fencing_token }
 * @returns {Promise<Object>} ResourceLeaseResponse
 */
export async function releaseLease(leaseId, payload) {
  return apiFetch(`/v1/resources/leases/${leaseId}/release`, {
    method: "POST",
    body: payload,
  });
}

/**
 * Extend the duration of an active lease before expiration.
 * @param {string} leaseId
 * @param {Object} payload - { duration_seconds, transaction_id, agent_id, fencing_token }
 * @returns {Promise<Object>} ResourceLeaseResponse
 */
export async function renewLease(leaseId, payload) {
  return apiFetch(`/v1/resources/leases/${leaseId}/renew`, {
    method: "POST",
    body: payload,
  });
}

// ==========================================
// 5. HIERARCHICAL OUTCOME ASSURANCE
// ==========================================

/**
 * Fetch aggregated hierarchical outcome assurance and lineage for an AI Transaction.
 * @param {string} transactionId
 * @returns {Promise<Object>} HierarchicalOutcomeResponse
 */
export async function getTransactionHierarchy(transactionId) {
  return apiFetch(`/v1/transactions/${transactionId}/hierarchy`);
}
