/**
 * Synthetic Verification Request Generator for k6 Performance Harness (P3.1)
 *
 * Implements Testing Strategy §8:
 * - Exercises realistic verification paths through the full gateway pipeline
 * - Exercises multi-proposition claim decomposition (FLAN-T5)
 * - Ensures deterministic, non-contaminating test payloads
 * - Strictly binds payload.tenant_id to the authenticated tenant to prevent IDOR rejection
 */

import { DEFAULT_MODEL_ID } from './config.js';

export const BENCHMARK_PAYLOADS = [
  {
    prompt: 'Describe the atmospheric composition of Earth and its major layers.',
    response:
      'Earth atmosphere consists of roughly 78 percent nitrogen and 21 percent oxygen. ' +
      'The troposphere is the lowest layer where weather phenomena occur, followed by the stratosphere which contains the ozone layer.',
  },
  {
    prompt: 'Summarize the Apollo 11 lunar landing mission milestones.',
    response:
      'Apollo 11 launched from Kennedy Space Center on July 16, 1969. ' +
      'Commander Neil Armstrong and Lunar Module Pilot Buzz Aldrin landed the Lunar Module Eagle on the Moon on July 20, 1969.',
  },
  {
    prompt: 'Explain the principles of mRNA vaccines and how they stimulate immunity.',
    response:
      'mRNA vaccines deliver genetic instructions to human cells to produce a harmless viral spike protein. ' +
      'The immune system recognizes this protein as an antigen, prompting B-cells to produce neutralizing antibodies without causing viral infection.',
  },
  {
    prompt: 'What are the core properties of carbon nanotubes and their electrical conductivity?',
    response:
      'Carbon nanotubes are cylindrical allotropes of carbon with nanometer-scale diameters. ' +
      'Depending on their chiral angle and diameter, single-walled carbon nanotubes can exhibit either metallic or semiconducting electronic behavior.',
  },
  {
    prompt: 'Describe the mechanics of plate tectonics and continental drift.',
    response:
      'The lithosphere of Earth is divided into major tectonic plates that glide over the fluid asthenosphere. ' +
      'Convection currents in the mantle drive seafloor spreading at divergent boundaries and subduction at convergent boundaries.',
  },
  {
    prompt: 'Explain how transformers use self-attention in natural language processing.',
    response:
      'Transformer architectures compute scaled dot-product attention across all input tokens simultaneously. ' +
      'This multi-head attention mechanism calculates dynamic contextual representations without the sequential recurrence limitations of RNNs.',
  },
  {
    prompt: 'Explain the discovery and biochemical structure of penicillin.',
    response:
      'Penicillin was discovered by Scottish bacteriologist Alexander Fleming in 1928 at St. Mary Hospital in London. ' +
      'Its core structure features a thiazolidine ring fused to a beta-lactam ring that inhibits bacterial cell wall synthesis.',
  },
  {
    prompt: 'What is the speed of light in vacuum and its fundamental role in relativity?',
    response:
      'The speed of light in vacuum is exactly 299,792,458 meters per second. ' +
      'According to special relativity, this constant c is invariant across all inertial reference frames and establishes the universal cosmic speed limit.',
  },
];

/**
 * Returns a realistic, structured VerificationRequest payload.
 *
 * @param {number} [iteration=0] - Iteration index or sequence counter
 * @param {string} [tenantId='perf_tenant'] - Authenticated tenant ID to bind
 * @param {string} [modelId=DEFAULT_MODEL_ID] - Target generator model identifier
 * @returns {object} JSON-serializable request payload conforming to shared/schemas/verification.py
 */
export function getVerificationPayload(iteration = 0, tenantId = 'perf_tenant', modelId = DEFAULT_MODEL_ID) {
  const template = BENCHMARK_PAYLOADS[iteration % BENCHMARK_PAYLOADS.length];

  return {
    prompt: template.prompt,
    response: template.response,
    tenant_id: tenantId,
    model_id: modelId,
    session_id: `s_${Math.random().toString(36).slice(2, 10)}_${Date.now()}_${iteration}`,
    auto_correct: false, // Performance baseline measures verification pipeline latency without correction loop overhead
  };
}
