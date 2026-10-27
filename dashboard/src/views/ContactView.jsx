import React, { useState } from 'react';
import { api } from '../api';
import { useSEO } from '../hooks/useSEO';
import { useAnalytics } from '../hooks/useAnalytics';
import Breadcrumbs from '../components/Breadcrumbs';

export default function ContactView({ onNavigateHome, onNavigateApp }) {
  useSEO({
    title: 'Enterprise Demo & Inquiries',
    description: 'Contact the MIRAGE engineering and assurance team. Request an architecture review, custom SLA, on-premises deployment, or proof-of-concept.',
    path: '/contact',
  });

  const { trackEvent } = useAnalytics();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  const [teamSize, setTeamSize] = useState('10-50');
  const [inquiryType, setInquiryType] = useState('enterprise_demo');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submittedData, setSubmittedData] = useState(null);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (!fullName.trim() || !email.trim() || !company.trim() || !message.trim()) {
      setError('Please fill in all required fields.');
      return;
    }

    setSubmitting(true);
    trackEvent('contact_form_submitted', { company, inquiryType });

    try {
      const res = await api.createInquiry({
        name: fullName.trim(),
        email: email.trim(),
        company: company.trim(),
        team_size: teamSize,
        use_case: inquiryType,
        message: message.trim(),
      });

      if (res && res.id) {
        setSubmittedData(res);
      } else {
        setError('Submission succeeded but confirmation was missing.');
      }
    } catch (err) {
      setError(err.message || 'Failed to submit inquiry. Please verify your details.');
    } finally {
      setSubmitting(false);
    }
  };

  const breadcrumbs = [
    { label: 'Home', onClick: onNavigateHome },
    { label: 'Contact & Enterprise Inquiries', current: true },
  ];

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <Breadcrumbs items={breadcrumbs} />

      <header className="mb-8">
        <span className="text-xs font-semibold uppercase tracking-wider text-apple-blue bg-apple-blue/10 px-2.5 py-1 rounded-full">
          Direct Engineering Channel
        </span>
        <h1 className="text-3xl font-bold tracking-tight text-apple-text mt-3">
          Request an Architecture Review or Custom SLA
        </h1>
        <p className="text-sm text-apple-subtext mt-2 max-w-2xl leading-relaxed">
          Speak directly with our execution assurance architects. We assist organizations with high-consequence AI deployments across banking, healthcare, automated DevOps, and autonomous agent orchestration.
        </p>
      </header>

      {submittedData ? (
        <div className="bg-apple-card border border-apple-green/30 rounded-2xl p-8 shadow-apple-md text-center max-w-xl mx-auto space-y-4 animate-fade-in">
          <div className="w-14 h-14 bg-apple-green/10 text-apple-green rounded-full flex items-center justify-center mx-auto">
            <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <h2 className="text-2xl font-semibold text-apple-text">Inquiry Dispatched</h2>
          <p className="text-xs text-apple-subtext">
            Reference Ticket: <span className="font-mono text-apple-text font-bold">{submittedData.id}</span>
          </p>
          <p className="text-xs text-apple-text/80 bg-apple-bg p-4 rounded-xl border border-apple-border text-left leading-relaxed">
            {submittedData.confirmation_message || 'Thank you for reaching out. An AI Assurance Solutions Engineer will review your technical requirements and respond within 4 business hours.'}
          </p>
          <div className="pt-2 flex justify-center space-x-3">
            <button
              onClick={() => {
                setSubmittedData(null);
                setFullName('');
                setEmail('');
                setCompany('');
                setMessage('');
              }}
              className="px-4 py-2 text-xs border border-apple-border rounded-xl font-medium text-apple-text hover:bg-apple-bg transition-colors"
            >
              Submit Another Inquiry
            </button>
            <button
              onClick={onNavigateApp}
              className="px-4 py-2 text-xs bg-apple-blue text-white rounded-xl font-medium hover:bg-apple-blue/90 shadow-sm transition-all"
            >
              Open Operator Dashboard &rarr;
            </button>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-12 gap-8 items-start">
          {/* Form */}
          <div className="md:col-span-7 bg-apple-card border border-apple-border/70 rounded-2xl p-6 shadow-apple-sm">
            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl flex items-center space-x-2">
                <span className="font-bold">Error:</span>
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-apple-text mb-1">
                  Full Name *
                </label>
                <input
                  type="text"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Sarah Chen"
                  className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-apple-text mb-1">
                  Enterprise Work Email *
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="sarah.chen@globalbank.com"
                  className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-apple-text mb-1">
                  Company / Institution *
                </label>
                <input
                  type="text"
                  required
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder="Acme Financial Services"
                  className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-apple-text mb-1">
                  Inquiry Purpose
                </label>
                <select
                  value={inquiryType}
                  onChange={(e) => setInquiryType(e.target.value)}
                  className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all"
                >
                  <option value="enterprise_demo">Enterprise Custom Demonstration</option>
                  <option value="architecture_review">AI Safety Architecture Review</option>
                  <option value="custom_sla">Dedicated On-Prem / VPC Deployment & SLA</option>
                  <option value="compliance_audit">SOC2 / ISO 42001 Cryptographic Audit Advisory</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-apple-text mb-1">
                  Architecture & Assurance Requirements *
                </label>
                <textarea
                  required
                  rows={4}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Describe your AI agent stack, expected concurrency, tool execution boundaries, and assurance requirements..."
                  className="w-full px-3 py-2 text-xs border border-apple-border rounded-xl bg-apple-bg focus:bg-white focus:outline-none focus:ring-2 focus:ring-apple-blue/20 focus:border-apple-blue transition-all resize-y"
                />
              </div>

              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2.5 px-4 bg-apple-blue text-white rounded-xl font-medium text-xs hover:bg-apple-blue/90 shadow-sm transition-all disabled:opacity-50"
              >
                {submitting ? 'Connecting to MIRAGE Gateway...' : 'Submit Enterprise Request &rarr;'}
              </button>
            </form>
          </div>

          {/* Sidebar Specs */}
          <div className="md:col-span-5 space-y-4">
            <div className="bg-apple-card border border-apple-border/70 rounded-2xl p-5 shadow-apple-sm">
              <h3 className="text-xs font-semibold text-apple-text uppercase tracking-wider mb-2">
                Guaranteed Response SLA
              </h3>
              <p className="text-xs text-apple-subtext leading-relaxed">
                Every inquiry is routed directly to a designated Assurance Solutions Architect. For Tier 1 critical banking or healthcare deployments, 24/7 dedicated engineering support channels are provisioned within 1 business day.
              </p>
            </div>

            <div className="bg-apple-card border border-apple-border/70 rounded-2xl p-5 shadow-apple-sm">
              <h3 className="text-xs font-semibold text-apple-text uppercase tracking-wider mb-2">
                Security & Data Protection
              </h3>
              <ul className="text-xs text-apple-subtext space-y-2">
                <li className="flex items-center space-x-2">
                  <span className="w-1.5 h-1.5 bg-apple-green rounded-full"></span>
                  <span>Zero retention for training on client queries</span>
                </li>
                <li className="flex items-center space-x-2">
                  <span className="w-1.5 h-1.5 bg-apple-green rounded-full"></span>
                  <span>PostgreSQL Row-Level Security (RLS) tenant isolation</span>
                </li>
                <li className="flex items-center space-x-2">
                  <span className="w-1.5 h-1.5 bg-apple-green rounded-full"></span>
                  <span>SHA-256 Merkle audit chains for verifiable compliance</span>
                </li>
                <li className="flex items-center space-x-2">
                  <span className="w-1.5 h-1.5 bg-apple-green rounded-full"></span>
                  <span>Available on AWS VPC, Azure Dedicated, or On-Prem</span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
