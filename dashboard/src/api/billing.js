/**
 * Commercial Billing and Subscription API Client.
 */

import { apiFetch } from "./client";

/**
 * Fetch available commercial subscription tiers.
 * @returns {Promise<Array<Object>>}
 */
export async function getBillingPlans() {
  return apiFetch("/v1/billing/plans");
}

/**
 * Fetch current tenant subscription status, active plan, and budget utilization.
 * @returns {Promise<Object>}
 */
export async function getTenantSubscription() {
  return apiFetch("/v1/billing/subscription");
}

/**
 * Transition tenant subscription tier.
 * @param {string} targetTier - "developer", "business", or "enterprise"
 * @returns {Promise<Object>}
 */
export async function subscribePlan(targetTier) {
  return apiFetch("/v1/billing/subscribe", {
    method: "POST",
    body: { target_tier: targetTier },
  });
}
