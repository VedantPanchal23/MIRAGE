/**
 * API client module for Gate 4 Output Assurance & Verification Engine.
 */

import { apiFetch } from "./client";

/**
 * Submit output completion for Gate 4 Output Assurance inspection.
 * @param {Object} payload - OutputAssuranceRequest
 * @returns {Promise<Object>} OutputAssuranceContract
 */
export async function assureOutput(payload) {
  return apiFetch("/v1/output/assure", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Fetch a persistent Output Assurance record by ID.
 * @param {string} outputId
 * @returns {Promise<Object>}
 */
export async function getOutputAssuranceRecord(outputId) {
  return apiFetch(`/v1/output/${outputId}`);
}
