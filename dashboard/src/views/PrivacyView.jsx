import React from 'react';
import { useSEO } from '../hooks/useSEO';
import Breadcrumbs from '../components/Breadcrumbs';

export default function PrivacyView({ onNavigateHome, onNavigateContact }) {
  useSEO({
    title: 'Enterprise Privacy Policy',
    description: 'Enterprise Privacy Policy for MIRAGE. Learn how our Five-Gate architecture protects your prompts, embeddings, and execution payloads with PostgreSQL RLS and Zero-Training guarantees.',
    path: '/privacy',
  });

  const breadcrumbs = [
    { label: 'Home', onClick: onNavigateHome },
    { label: 'Privacy Policy', current: true },
  ];

  return (
    <article className="max-w-4xl mx-auto px-4 py-8">
      <Breadcrumbs items={breadcrumbs} />

      <header className="mb-8 border-b border-apple-border pb-6">
        <span className="text-xs font-semibold uppercase tracking-wider text-apple-gray">
          Last Updated: October 27, 2026 | Version 3.0
        </span>
        <h1 className="text-3xl font-bold tracking-tight text-apple-text mt-2">
          Enterprise Privacy & Data Governance Policy
        </h1>
        <p className="text-sm text-apple-subtext mt-2">
          MIRAGE Technologies Inc. is dedicated to institutional data privacy, tenant data segregation, and cryptographic execution accountability.
        </p>
      </header>

      <div className="prose prose-sm max-w-none text-apple-text space-y-6 text-xs leading-relaxed">
        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            1. Zero-Training Architecture Guarantee
          </h2>
          <p className="text-apple-subtext">
            We adhere to a strict <span className="font-semibold text-apple-text">Zero-Training</span> policy:
          </p>
          <ul className="list-disc pl-5 mt-2 space-y-1 text-apple-subtext">
            <li>Customer input prompts, system messages, and agent interaction payloads are never used to train, retrain, or improve foundational AI models.</li>
            <li>Knowledge Base vector embeddings uploaded to Qdrant are isolated to customer-scoped collections and destroyed upon tenant offboarding.</li>
            <li>Tool invocation arguments, credential tokens, and execution outputs pass through ephemeral memory buffers and are retained solely for customer audit review.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            2. Row-Level Security (RLS) & Encryption at Rest
          </h2>
          <p className="text-apple-subtext">
            Data separation is enforced at the database engine tier using PostgreSQL Row-Level Security (RLS). Every query is parameterized with the tenant's authenticated context. All persistent data is encrypted at rest using AES-256-GCM, and all in-transit traffic is secured with TLS 1.3.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            3. Cryptographic Audit Chain Preservation
          </h2>
          <p className="text-apple-subtext">
            Audit events (including Gate approvals, denial decisions, and tool lease executions) are immutably recorded into a SHA-256 Merkle hash chain. Each audit entry contains the cryptographic hash of its predecessor, creating mathematical tamper evidence. These records are exportable in standard JSONL format for external SOC 2 Type II or ISO 42001 verification.
          </p>
        </section>

        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            4. GDPR, CCPA, and Global Compliance Rights
          </h2>
          <p className="text-apple-subtext">
            Subject to applicable privacy statutes (GDPR Articles 15-22, California Consumer Privacy Act):
          </p>
          <ul className="list-disc pl-5 mt-2 space-y-1 text-apple-subtext">
            <li><strong>Right to Access & Portability:</strong> Operators can export their entire audit trail and policy database as JSONL at any time via the Operator Dashboard or API.</li>
            <li><strong>Right to Erasure:</strong> Upon tenant termination, all customer-specific data, vector embeddings, and transient caches are purged within 30 calendar days.</li>
          </ul>
        </section>

        <section>
          <h2 className="text-base font-semibold text-apple-text mb-2">
            5. Subprocessors and Data Residency
          </h2>
          <p className="text-apple-subtext">
            Customer data is stored within customer-designated geographical regions (US-East AWS, EU-Frankfurt, or India-Mumbai). We do not transfer customer telemetry to third-party ad networks or data brokers.
          </p>
        </section>

        <section className="pt-4 border-t border-apple-border flex items-center justify-between">
          <span className="text-xs text-apple-gray">
            Need a signed Business Associate Agreement (BAA) or Data Processing Addendum (DPA)?
          </span>
          <button
            onClick={onNavigateContact}
            className="text-xs text-apple-blue hover:underline font-medium"
          >
            Request Enterprise DPA &rarr;
          </button>
        </section>
      </div>
    </article>
  );
}
