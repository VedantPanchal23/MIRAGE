/**
 * API client module for Gate 2 Context Assurance & Governed Memory.
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
 * Fetch active governed memories for the current tenant.
 *
 * @param {Object} [params] - Optional query params: { scope, memory_type }
 * @returns {Promise<Array<Object>>}
 */
export async function getMemories(params = {}) {
  const query = new URLSearchParams();
  if (params.scope) query.append("scope", params.scope);
  if (params.memory_type) query.append("memory_type", params.memory_type);
  const qs = query.toString();
  return apiFetch(`/v1/memory${qs ? `?${qs}` : ""}`);
}

/**
 * Register a new Governed Memory entry.
 *
 * @param {Object} payload - { owner_id, memory_type, scope, content, attestation_status, declared_taint, ttl_seconds }
 * @returns {Promise<Object>}
 */
export async function createMemory(payload) {
  return apiFetch("/v1/memory", {
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
