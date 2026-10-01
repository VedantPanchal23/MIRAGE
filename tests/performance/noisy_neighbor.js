/**
 * Entrypoint: Performance Scenario 5 — Noisy Neighbor (P3.2)
 *
 * Implements Testing Strategy §8 Scenario 5:
 * Command: k6 run tests/performance/noisy_neighbor.js
 */

export {
  options,
  handleSummary,
  tenantAFunction,
  tenantBFunction,
  default,
} from './scenarios/scenario5_noisy_neighbor.js';
