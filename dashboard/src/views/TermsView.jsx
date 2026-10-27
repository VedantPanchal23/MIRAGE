import React from 'react';
import { useSEO } from '../hooks/useSEO';
import Breadcrumbs from '../components/Breadcrumbs';

export default function TermsView({ onNavigateHome, onNavigateContact }) {
  useSEO({
    title: 'Terms of Service',
    description: 'Enterprise B2B Terms of Service for the MIRAGE AI Execution Assurance Platform. Governing five-gate execution boundaries, tenant RLS isolation, and epistemic outcome reality verification.',
    path: '/terms',
  });

  const breadcrumbs = [
    { label: 'Home', onClick: onNavigateHome },
    { label: 'Terms of Service', current: true },
  ];

  return (
    <article className="max-w-4xl mx-auto px-4 py-8">
      <Breadcrumbs items={breadcrumbs} />

      <header className="mb-8 border-b border-apple-border pb-6">
        <span className="text-xs font-semibold uppercase tracking-wider text-apple-gray">
          Effective Date: October 27, 2026 | Version 3.0
        </span>
        <h1 className="text-3xl font-bold tracking-tight text-apple-text mt-2">
          Enterprise Terms of Service
        </h1>
        <p className="text-sm text-apple-subtext mt-2">
          These Enterprise Terms of Service ("Agreement") govern access to and use of the MIRAGE AI Execution Assurance Platform provided by MIRAGE Technologies Inc. ("MIRAGE", "we", "us", or "our").
        </p>
      </header>

      <div className="prose prose-sm max-w-none text-apple-text space-y-6 text-xs leading-relaxed">
        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            1. Platform Scope & The Five Assurance Gates
          </h2>
          <p className="text-apple-subtext">
            MIRAGE provides an autonomous AI Execution Assurance layer sitting between client AI systems (including LLMs, agents, and orchestrators) and real-world execution environments. Every transactional request is evaluated sequentially across the Five Inviolable Assurance Gates:
          </p>
          <ul className="list-disc pl-5 mt-2 space-y-1 text-apple-subtext">
            <li><strong>Gate 1 (Input Assurance):</strong> Verification of caller identity, tenant attribution, prompt-injection defense, and jailbreak containment.</li>
            <li><strong>Gate 2 (Context Assurance):</strong> Provenance verification, knowledge-base retrieval validation, and anti-poisoning filtering.</li>
            <li><strong>Gate 3 (Action Assurance):</strong> Governed tool proxy execution, distributed lease fencing, parameter schema validation, and human-in-the-loop (HITL) gatekeeping.</li>
            <li><strong>Gate 4 (Output Assurance):</strong> Hallucination Risk Scoring (HRS), semantic safety evaluation, and factual consistency scoring.</li>
            <li><strong>Gate 5 (Outcome Assurance):</strong> Independent reality verification comparing observed real-world state transitions against predicted postconditions.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            2. Epistemic Outcome Independence Invariant
          </h2>
          <p className="text-apple-subtext">
            Customer explicitly acknowledges that an AI agent's internal reasoning, completion text, or tool return code (such as HTTP 200 OK) does not, by itself, constitute verifiable proof of real-world outcome achievement. MIRAGE Gate 5 performs independent verification against target state machines. Outcome verification statuses (<code className="font-mono text-apple-blue">VERIFIED_SUCCESS</code>, <code className="font-mono text-amber-600">EXECUTION_UNCERTAIN</code>, <code className="font-mono text-red-600">VERIFIED_FAILURE</code>) represent epistemic measurements based on available evidence and do not warrant third-party network infallibility.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            3. Execution Boundaries & Fencing Reality
          </h2>
          <p className="text-apple-subtext">
            MIRAGE enforces two-phase distributed execution commits (<code className="font-mono text-apple-blue">EXECUTING</code> state transition prior to external dispatch) to eliminate local duplicate dispatches. However, Customer understands that external protocols lacking native conditional mutation primitives (e.g. standard SMTP email, unversioned third-party webhooks) are mediated at Gate 3; universal target-side fencing is guaranteed only on database and storage adapters supporting atomic conditional writes.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            4. Multi-Tenant Isolation & PostgreSQL Row-Level Security (RLS)
          </h2>
          <p className="text-apple-subtext">
            MIRAGE architecture strictly enforces tenant isolation at the database kernel via PostgreSQL Row-Level Security. Every connection context carries an authenticated <code className="font-mono text-apple-text">tenant_id</code>. All audit logs, tool records, and session data remain cryptographically inaccessible across tenant boundaries.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            5. Intellectual Property & Zero-Training Guarantee
          </h2>
          <p className="text-apple-subtext">
            Customer retains all right, title, and interest in and to Customer Prompts, Knowledge Base Embeddings, and Tool Invocation Payloads. MIRAGE does not use Customer Data to train, fine-tune, or calibrate public or foundational machine learning models.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            6. Service Level Agreement (SLA) & Subscriptions
          </h2>
          <p className="text-apple-subtext">
            Enterprise tier subscriptions include a 99.95% monthly uptime SLA. Fees are billed in advance in accordance with the selected tier (Developer, Team, or Enterprise) in USD via Stripe or INR via Razorpay. Cancellations take effect at the end of the active billing cycle.
          </p>
        </section>

        <section className="pt-4 border-t border-apple-border flex items-center justify-between">
          <span className="text-xs text-apple-gray">
            Questions regarding our Enterprise Master Services Agreement?
          </span>
          <button
            onClick={onNavigateContact}
            className="text-xs text-apple-blue hover:underline font-medium"
          >
            Contact Legal & Assurance Counsel &rarr;
          </button>
        </section>
      </div>
    </article>
  );
}
