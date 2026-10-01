/**
 * Entrypoint: Performance Scenario 6 — SCS Cache Warm Load (P3.2)
 *
 * Implements Testing Strategy §8 Scenario 6:
 * Command: k6 run tests/performance/cache_warm.js
 */

export { options, handleSummary, default } from './scenarios/scenario6_cache_warm.js';
