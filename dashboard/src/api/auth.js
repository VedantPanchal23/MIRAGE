/**
 * Identity and Authentication API.
 * Endpoint: GET /v1/auth/me
 */

import { apiFetch } from "./client";

/**
 * Fetch the current authenticated user identity context.
 * @returns {Promise<object>} Identity context payload
 */
export async function getIdentity() {
  return apiFetch("/v1/auth/me");
}

