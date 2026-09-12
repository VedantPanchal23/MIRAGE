import React from "react";
import { ClaimItem } from "../types";

interface ClaimsTreeProps {
  claims: ClaimItem[];
  originalText: string;
  verifiedText: string;
  correctionApplied: boolean;
}

export const ClaimsTree: React.FC<ClaimsTreeProps> = ({
  claims,
  originalText,
  verifiedText,
  correctionApplied,
}) => {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg space-y-6">
      <div>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-200">Claim Decomposition & Evidence Verification</h3>
          <span className="text-xs text-slate-400 font-mono">{claims.length} atomic claims extracted</span>
        </div>
        <p className="text-xs text-slate-400 mt-0.5">
          FLAN-T5 decomposed propositions evaluated across RAV, SCS, and NLI
        </p>
      </div>

      {/* Claims List */}
      <div className="space-y-3">
        {claims.map((c) => {
          const isContradicted = c.status === "CONTRADICTED";
          const isSupported = c.status === "SUPPORTED";

          const statusBadge = isSupported ? (
            <span className="text-[11px] font-semibold text-emerald-400 bg-emerald-950 px-2 py-0.5 rounded border border-emerald-800">
              SUPPORTED
            </span>
          ) : isContradicted ? (
            <span className="text-[11px] font-semibold text-rose-400 bg-rose-950 px-2 py-0.5 rounded border border-rose-800">
              CONTRADICTED
            </span>
          ) : (
            <span className="text-[11px] font-semibold text-amber-400 bg-amber-950 px-2 py-0.5 rounded border border-amber-800">
              {c.status}
            </span>
          );

          return (
            <div
              key={c.claim_id}
              className={`p-3.5 rounded-lg border text-xs transition ${
                isContradicted
                  ? "bg-rose-950/20 border-rose-900/60 text-slate-200"
                  : isSupported
                  ? "bg-slate-950/60 border-slate-800/80 text-slate-300"
                  : "bg-amber-950/20 border-amber-900/60 text-slate-200"
              }`}
            >
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center space-x-2">
                  <span className="font-mono text-slate-400 font-bold">{c.claim_id}</span>
                  <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 bg-slate-800 text-slate-300 rounded">
                    {c.type}
                  </span>
                  <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 bg-slate-800 text-slate-400 rounded">
                    {c.criticality} priority
                  </span>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="font-mono text-[11px] text-slate-400">Risk: {c.hrs_contribution.toFixed(3)}</span>
                  {statusBadge}
                </div>
              </div>
              <p className="mt-1 text-slate-200 leading-relaxed font-sans">{c.text}</p>
            </div>
          );
        })}
      </div>

      {/* Response Comparison */}
      <div className="pt-4 border-t border-slate-800 grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-950 rounded-lg p-3.5 border border-slate-800/80">
          <span className="text-[11px] font-semibold text-slate-400 block mb-1">Original Unverified Output</span>
          <p className="text-xs text-slate-300 leading-relaxed font-mono">{originalText}</p>
        </div>

        <div className="bg-slate-950 rounded-lg p-3.5 border border-slate-800/80">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] font-semibold text-slate-400">Verified & Guarded Output</span>
            {correctionApplied && (
              <span className="text-[10px] text-emerald-400 font-semibold bg-emerald-950 px-1.5 py-0.5 rounded border border-emerald-800">
                Agentic Rewrite Applied
              </span>
            )}
          </div>
          <p className="text-xs text-slate-200 leading-relaxed font-mono">{verifiedText}</p>
        </div>
      </div>
    </div>
  );
};
