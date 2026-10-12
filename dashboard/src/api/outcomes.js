/**
 * API client module for Gate 5 Outcome Assurance & Reality Verification.
 */

import { apiFetch } from "./client";

/**
 * Submit an action outcome for Gate 5 Reality Verification inspection.
 * @param {Object} payload - OutcomeVerificationRequest
 * @returns {Promise<Object>} OutcomeVerificationContract
 */
export async function verifyActionOutcome(payload) {
  return apiFetch("/v1/outcomes/verify", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Fetch a persistent Outcome Verification record by ID.
 * @param {string} outcomeId
 * @returns {Promise<Object>} OutcomeVerificationContract
 */
export async function getOutcomeRecord(outcomeId) {
  return apiFetch(`/v1/outcomes/${outcomeId}`);
}

/**
 * Fetch outcome verification record for an Action ID.
 * @param {string} actionId
 * @returns {Promise<Object>} OutcomeVerificationContract
 */
export async function getOutcomeByAction(actionId) {
  return apiFetch(`/v1/outcomes/action/${actionId}`);
}

/**
 * Fetch all pending outcomes awaiting verification.
 * @returns {Promise<Array<Object>>}
 */
export async function listPendingOutcomes() {
  return apiFetch("/v1/outcomes/pending");
}

/**
 * Fetch all outcome records for a transaction.
 * @param {string} transactionId
 * @returns {Promise<Array<Object>>}
 */
export async function listOutcomesForTransaction(transactionId) {
  return apiFetch(`/v1/outcomes/transaction/${transactionId}`);
}

/**
 * Reconcile model output text against verified outcome state.
 * @param {Object} payload - OutcomeReconciliationRequest
 * @returns {Promise<Object>} OutcomeReconciliationResult
 */
export async function reconcileOutputAndOutcome(payload) {
  return apiFetch("/v1/outcomes/reconcile", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * Escalate an outcome record for operator review.
 * @param {string} outcomeId
 * @param {string} reason
 * @param {string} [escalationNotes]
 * @returns {Promise<Object>} OutcomeEscalationResponse
 */
export async function escalateOutcome(outcomeId, reason, escalationNotes) {
  return apiFetch(`/v1/outcomes/${outcomeId}/escalate`, {
    method: "POST",
    body: JSON.stringify({
      outcome_id: outcomeId,
      reason,
      escalation_notes: escalationNotes || null,
    }),
  });
}
