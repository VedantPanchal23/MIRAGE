import React, { useState, useEffect, useRef } from 'react';
import { X, Send, CheckCircle2, AlertTriangle } from 'lucide-react';
import { api } from '../../api/client';
import { trackEvent } from '../../utils/analytics';

export function EnterpriseInquiryModal({ isOpen, onClose = () => {} }) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [company, setCompany] = useState('');
  const [teamSize, setTeamSize] = useState('50-250');
  const [useCase, setUseCase] = useState('Autonomous Financial & Tool Governance');
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(null);
  const [error, setError] = useState(null);
  const closeRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    closeRef.current?.focus();
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    if (!name.trim() || !email.trim() || !company.trim() || message.trim().length < 10) {
      setError('Please complete your name, work email, company, and a brief 10+ character project note.');
      return;
    }
    try {
      setSubmitting(true);
      const res = await api.submitInquiry({
        name: name.trim(),
        email: email.trim(),
        company: company.trim(),
        team_size: teamSize,
        use_case: useCase,
        message: message.trim(),
      });
      trackEvent('enterprise_inquiry_submitted', { team_size: teamSize });
      setSubmitted(res);
    } catch (err) {
      setError(err.message || 'Could not submit inquiry right now. Please retry.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="inquiry-modal-title"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg bg-white rounded-2xl border border-[#ededed] shadow-2xl p-6 sm:p-8 max-h-[90vh] overflow-y-auto overscroll-contain"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between pb-4 border-b border-[#ededed] mb-5">
          <h2 id="inquiry-modal-title" className="text-lg font-medium text-[#0c152a]">
            Schedule Enterprise Architecture Review
          </h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close inquiry dialog"
            className="p-2 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-100"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {submitted ? (
          <div className="space-y-4 text-xs">
            <div role="status" className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-900 flex items-start gap-2.5">
              <CheckCircle2 className="w-5 h-5 text-emerald-700 shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold mb-1">Inquiry Registered ({submitted.id})</div>
                <p>{submitted.confirmation_message}</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                setSubmitted(null);
                onClose();
              }}
              className="w-full py-2.5 rounded-full bg-[#0c152a] text-white font-medium text-xs"
            >
              Done
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3.5 text-xs">
            {error && (
              <div role="alert" className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label htmlFor="inq-name" className="block font-semibold text-slate-700 mb-1">Full Name</label>
                <input id="inq-name" type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="Alex Rivera" className="w-full px-3 py-2 rounded-lg border border-slate-300" />
              </div>
              <div>
                <label htmlFor="inq-email" className="block font-semibold text-slate-700 mb-1">Work Email</label>
                <input id="inq-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="alex@company.com" className="w-full px-3 py-2 rounded-lg border border-slate-300" />
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label htmlFor="inq-company" className="block font-semibold text-slate-700 mb-1">Company</label>
                <input id="inq-company" type="text" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Apex Financial" className="w-full px-3 py-2 rounded-lg border border-slate-300" />
              </div>
              <div>
                <label htmlFor="inq-team-size" className="block font-semibold text-slate-700 mb-1">Engineering Size</label>
                <select id="inq-team-size" value={teamSize} onChange={(e) => setTeamSize(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-slate-300 bg-white">
                  <option value="1-50">1-50</option>
                  <option value="50-250">50-250</option>
                  <option value="250-1000">250-1000</option>
                  <option value="1000+">1000+</option>
                </select>
              </div>
            </div>

            <div>
              <label htmlFor="inq-use-case" className="block font-semibold text-slate-700 mb-1">Primary Use Case</label>
              <input id="inq-use-case" type="text" value={useCase} onChange={(e) => setUseCase(e.target.value)} className="w-full px-3 py-2 rounded-lg border border-slate-300" />
            </div>

            <div>
              <label htmlFor="inq-message" className="block font-semibold text-slate-700 mb-1">Workload &amp; Compliance Requirements</label>
              <textarea id="inq-message" rows={3} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Describe agent tools, target systems, and compliance requirements..." className="w-full px-3 py-2 rounded-lg border border-slate-300" />
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full py-2.5 px-4 rounded-full bg-[#0c152a] text-white font-medium flex items-center justify-center gap-2 hover:bg-[#19171b] transition-colors"
            >
              <Send className="w-3.5 h-3.5" />
              <span>{submitting ? 'Submitting...' : 'Submit Enterprise Inquiry'}</span>
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
