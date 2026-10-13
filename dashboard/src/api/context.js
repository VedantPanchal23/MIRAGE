/**
 * API client module for Gate 2 Context Assurance & Phase 7 Governed Memory.
 */

import { apiFetch } from "./client";

/**
 * Assemble and assure context items for an AI Transaction.
 *
 * @param {Object} payload - { transaction_id, items, max_context_bytes, min_trust_threshold, quarantine_injections }
 * @returns {Promise<Object>} GovernedContextResponse
 */
export async function assembleContext(payload) {
  return apiFetch("/v1/context/assemble", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Fetch governed memories for the current tenant with optional filtering.
 *
 * @param {Object} [params] - { scope, memory_type, category, purpose, lifecycle_state, trust_level }
 * @returns {Promise<Array<Object>>}
 */
export async function getMemories(params = {}) {
  const query = new URLSearchParams();
  if (params.scope) query.append("scope", params.scope);
  if (params.memory_type) query.append("memory_type", params.memory_type);
  if (params.category) query.append("category", params.category);
  if (params.purpose) query.append("purpose", params.purpose);
  if (params.lifecycle_state) query.append("lifecycle_state", params.lifecycle_state);
  if (params.trust_level) query.append("trust_level", params.trust_level);
  const qs = query.toString();
  return apiFetch(`/v1/memory${qs ? `?${qs}` : ""}`);
}

/**
 * Register a new Governed Memory record.
 *
 * @param {Object} payload
 * @returns {Promise<Object>}
 */
export async function createMemory(payload) {
  return apiFetch("/v1/memory", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Update memory by versioning: supersedes old record and creates new version.
 *
 * @param {string} memoryId
 * @param {Object} payload
 * @returns {Promise<Object>}
 */
export async function updateMemory(memoryId, payload) {
  return apiFetch(`/v1/memory/${encodeURIComponent(memoryId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/**
 * Dispute a memory record, demoting confidence.
 *
 * @param {string} memoryId
 * @param {Object} payload - { dispute_reason }
 * @returns {Promise<Object>}
 */
export async function disputeMemory(memoryId, payload) {
  return apiFetch(`/v1/memory/${encodeURIComponent(memoryId)}/dispute`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Place or release legal/regulatory hold.
 *
 * @param {string} memoryId
 * @param {Object} payload - { hold_active, justification }
 * @returns {Promise<Object>}
 */
export async function setLegalHold(memoryId, payload) {
  return apiFetch(`/v1/memory/${encodeURIComponent(memoryId)}/hold`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Cryptographically shred a memory item.
 *
 * @param {string} memoryId
 * @returns {Promise<Object>}
 */
export async function deleteMemory(memoryId) {
  return apiFetch(`/v1/memory/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
  });
}

/**
 * Purpose-bound semantic and keyword search across governed memory.
 *
 * @param {Object} payload - { query, purpose, category, min_confidence, limit }
 * @returns {Promise<Object>}
 */
export async function searchMemories(payload) {
  return apiFetch("/v1/memory/search", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Trigger maintenance sweep for expired TTLs and retention rules.
 *
 * @returns {Promise<Object>}
 */
export async function sweepMemories() {
  return apiFetch("/v1/memory/maintenance/sweep", {
    method: "POST",
  });
}

/**
 * Inspect full provenance and transformation lineage for a memory record.
 *
 * @param {string} memoryId
 * @returns {Promise<Object>}
 */
export async function getMemoryProvenance(memoryId) {
  return apiFetch(`/v1/memory/${encodeURIComponent(memoryId)}/provenance`);
}
