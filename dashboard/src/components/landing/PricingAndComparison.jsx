import React, { useState, useEffect } from 'react';
import { CheckCircle2, XCircle, ArrowRight } from 'lucide-react';
import { api } from '../../api/client';
import { trackEvent } from '../../utils/analytics';

const FALLBACK_PLANS = [
  {
    tier: 'developer',
    name: 'Developer Sandbox',
    tagline: 'Evaluate all Five Assurance Gates with local agents and test harnesses',
    price_dollars_monthly: 0,
    price_inr_monthly: 0,
    request_quota_monthly: 10000,
    max_concurrent_leases: 2,
    budget_ceiling_usd: 10,
  },
  {
    tier: 'business',
    name: 'Pro / Starter',
    tagline: 'Production assurance with DeBERTa-v3 NLI, Qdrant RAG, and Conformal Bounds',
    price_dollars_monthly: 29,
    price_inr_monthly: 1999,
    request_quota_monthly: 75000,
    max_concurrent_leases: 10,
    budget_ceiling_usd: 150,
  },
  {
    tier: 'enterprise',
    name: 'Enterprise Sentinel',
    tagline: 'Dedicated RLS isolation, governed MCP proxy, L4 HITL approvals, and S3 WORM anchors',
    price_dollars_monthly: 299,
    price_inr_monthly: 24999,
    request_quota_monthly: 2000000,
    max_concurrent_leases: 100,
    budget_ceiling_usd: 2500,
  },
];

const COMPARISON_ROWS = [
  {
    capability: 'Prompt & RAG Injection Filtering',
    mirage: 'Gate 1 + Gate 2 Delimiters & Memory Taint',
    guardrailsOnly: 'Prompt regex / classifier only',
  },
  {
    capability: 'Tool Action Fencing & Concurrency Leases',
    mirage: 'Gate 3 Monotonic Redis Leases + CBAC Binding',
    guardrailsOnly: null,
  },
  {
    capability: 'Multi-Step Financial Salami-Slicing Quotas',
    mirage: '1h rolling spend, risk & op velocity limits',
    guardrailsOnly: null,
  },
  {
    capability: 'Post-Action Physical Reality Verification',
    mirage: 'Gate 5 OBS_DIRECT / Eventual / Reconciliation',
    guardrailsOnly: null,
  },
  {
    capability: 'Immutable Audit Trail',
    mirage: '14-field SHA-256 chain + External S3/File Anchors',
    guardrailsOnly: 'Mutable JSON logs',
  },
];

export function PricingAndComparison({ onOpenAuth = () => {}, onOpenInquiry = () => {} }) {
  const [plans, setPlans] = useState(FALLBACK_PLANS);
  const [currency, setCurrency] = useState('USD');

  useEffect(() => {
    api
      .getBillingPlans()
      .then((res) => {
        if (Array.isArray(res) && res.length > 0) setPlans(res);
      })
      .catch(() => {
        // Authoritative static catalog remains intact when gateway is offline
      });
  }, []);

  return (
    <>
      <section id="comparison" className="py-20 px-6 sm:px-12 border-b border-[#ededed] bg-[#f8f8fa]/50">
        <div className="max-w-5xl mx-auto">
          <div className="max-w-3xl mb-10">
            <h2 className="text-[28px] sm:text-[34px] font-normal text-[#0c152a] tracking-tight">
              Why Execution Assurance Beats Prompt-Only Guardrails
            </h2>
            <p className="text-[15px] text-[#6b6c71] mt-2">
              Text filters inspect words. MIRAGE governs real-world state transitions from capability lease acquisition to post-execution physical verification.
            </p>
          </div>

          <div className="overflow-x-auto rounded-[24px] border border-[#ededed] bg-white">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#f8f8fa] border-b border-[#ededed] text-[#6b6c71] font-mono uppercase text-[11px]">
                <tr>
                  <th className="py-3.5 px-5">Governance Control</th>
                  <th className="py-3.5 px-5 text-[#0c152a]">MIRAGE 3.0 Platform</th>
                  <th className="py-3.5 px-5">Prompt-Only Guardrails</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#ededed]">
                {COMPARISON_ROWS.map((row) => (
                  <tr key={row.capability}>
                    <td className="py-3.5 px-5 font-medium text-[#0c152a]">{row.capability}</td>
                    <td className="py-3.5 px-5 text-emerald-800">
                      <span className="inline-flex items-center gap-1.5">
                        <CheckCircle2 className="w-4 h-4 text-emerald-600 shrink-0" />
                        <span>{row.mirage}</span>
                      </span>
                    </td>
                    <td className="py-3.5 px-5 text-[#6b6c71]">
                      {row.guardrailsOnly ? (
                        row.guardrailsOnly
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-slate-500">
                          <XCircle className="w-4 h-4 text-slate-400 shrink-0" />
                          <span>Not governed</span>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section id="pricing" className="py-20 px-6 sm:px-12 border-b border-[#ededed] bg-white">
        <div className="max-w-5xl mx-auto">
          <div className="flex flex-wrap items-end justify-between gap-4 mb-10">
            <div>
              <h2 className="text-[28px] sm:text-[34px] font-normal text-[#0c152a] tracking-tight">
                Transparent Commercial Tiers
              </h2>
              <p className="text-[15px] text-[#6b6c71] mt-2">
                Start free in Sandbox and scale to dedicated PostgreSQL RLS enterprise throughput.
              </p>
            </div>
            <div className="inline-flex rounded-full border border-[#ededed] p-1 bg-[#f8f8fa] text-xs font-mono">
              <button
                type="button"
                onClick={() => setCurrency('USD')}
                className={`px-3 py-1 rounded-full transition-colors ${currency === 'USD' ? 'bg-[#0c152a] text-white' : 'text-[#6b6c71]'}`}
              >
                USD ($)
              </button>
              <button
                type="button"
                onClick={() => setCurrency('INR')}
                className={`px-3 py-1 rounded-full transition-colors ${currency === 'INR' ? 'bg-[#0c152a] text-white' : 'text-[#6b6c71]'}`}
              >
                INR (&#8377;)
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {plans.map((plan) => {
              const price = currency === 'INR' ? `₹${(plan.price_inr_monthly || 0).toLocaleString()}` : `$${plan.price_dollars_monthly}`;
              const isHighlighted = plan.tier === 'business';
              return (
                <div
                  key={plan.tier}
                  className={`p-7 rounded-[24px] border flex flex-col justify-between ${
                    isHighlighted
                      ? 'border-[#0c152a] bg-[#0c152a] text-white shadow-xl'
                      : 'border-[#ededed] bg-[#f8f8fa] text-[#0c152a]'
                  }`}
                >
                  <div>
                    <div className={`text-xs font-mono uppercase tracking-wider mb-2 ${isHighlighted ? 'text-emerald-400' : 'text-[#6b6c71]'}`}>
                      {plan.tier}
                    </div>
                    <h3 className="text-xl font-medium mb-1">{plan.name}</h3>
                    <p className={`text-xs mb-5 leading-relaxed ${isHighlighted ? 'text-slate-300' : 'text-[#6b6c71]'}`}>
                      {plan.tagline}
                    </p>
                    <div className="text-3xl font-medium font-mono tabular-nums mb-5">
                      {price}
                      <span className={`text-xs font-normal ${isHighlighted ? 'text-slate-400' : 'text-[#6b6c71]'}`}>/mo</span>
                    </div>
                    <ul className={`space-y-2 text-xs mb-6 ${isHighlighted ? 'text-slate-200' : 'text-[#19171b]'}`}>
                      <li>&bull; {(plan.request_quota_monthly || 0).toLocaleString()} monthly verifications</li>
                      <li>&bull; {plan.max_concurrent_leases} concurrent distributed leases</li>
                      <li>&bull; ${(plan.budget_ceiling_usd || 0).toLocaleString()} action budget ceiling</li>
                    </ul>
                  </div>

                  {plan.tier === 'enterprise' ? (
                    <button
                      type="button"
                      onClick={() => {
                        trackEvent('pricing_cta_click', { tier: plan.tier });
                        onOpenInquiry();
                      }}
                      className="w-full py-2.5 px-4 rounded-full bg-white text-[#0c152a] border border-[#ededed] text-xs font-medium hover:bg-[#ededed] transition-colors flex items-center justify-center gap-1.5"
                    >
                      <span>Contact Enterprise Sales</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        trackEvent('pricing_cta_click', { tier: plan.tier });
                        onOpenAuth('register');
                      }}
                      className={`w-full py-2.5 px-4 rounded-full text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${
                        isHighlighted
                          ? 'bg-emerald-500 text-slate-950 hover:bg-emerald-400'
                          : 'bg-[#0c152a] text-white hover:bg-[#19171b]'
                      }`}
                    >
                      <span>Provision {plan.name}</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </section>
    </>
  );
}
