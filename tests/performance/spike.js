/**
 * Entrypoint: Performance Scenario 4 — Spike / Burst (P3.2)
 *
 * Implements Testing Strategy §8 Scenario 4:
 * Command: k6 run tests/performance/spike.js
 */

export { options, handleSummary, default } from './scenarios/scenario4_spike.js';
