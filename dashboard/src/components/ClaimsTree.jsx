import React from "react";
import { CheckCircle2, XCircle, AlertCircle, Sparkles } from "lucide-react";

/**
 * ClaimsTree Component
 *
 * Renders propositional claim breakdown for a verification session,
 * displaying atomic claim texts, verification statuses, criticality weights,
 * risk scores, and sub-signal evaluations.
 *
 * @param {object} props
 * @param {Array<object>} [props.claims=[]] - List of decomposed claim records
 * @param {string} [props.originalText=""] - Original LLM prompt or unverified response
 * @param {string} [props.verifiedText=""] - Guarded or corrected output
 * @param {boolean} [props.correctionApplied=false] - Whether autonomous rewrite was applied
 */
export function ClaimsTree({
  claims = [],
  originalText = "",
  verifiedText = "",
  correctionApplied = false,
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs space-y-6">
      {/* Section Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-slate-900">
            Claim Decomposition & Evidence Verification
          </h3>
          <p className="text-xs text-slate-500 mt-0.5">
            Propositional claim breakdown evaluated across RAV, SCS, NLI, and ICS verification signals
          </p>
        </div>
        <span className="text-xs text-slate-600 font-mono bg-slate-100 px-2.5 py-1 rounded-md border border-slate-200">
          {claims.length} {claims.length === 1 ? "Claim" : "Claims"} Evaluated
        </span>
      </div>

      {/* Claims List */}
      {claims.length === 0 ? (
        <div className="bg-slate-50 border border-slate-200 rounded-lg p-5 text-center text-xs text-slate-500 font-mono">
          No decomposed propositional claims recorded for this verification session.
        </div>
      ) : (
        <div className="space-y-3" role="feed" aria-label="Decomposed claims list">
          {claims.map((c, idx) => {
            const claimId = c.id || c.claim_id || `clm_${idx + 1}`;
            const claimText = c.claim_text || c.text || "";
            const claimType = c.claim_type || c.type || "FACTUAL";
            const criticality = c.criticality || "NORMAL";
            const rawStatus = (c.status || "UNKNOWN").toUpperCase();

            const isSupported = rawStatus === "SUPPORTED";
            const isContradicted = rawStatus === "CONTRADICTED";
            const isNeutral = rawStatus === "NEUTRAL" || rawStatus === "INSUFFICIENT_EVIDENCE";

            const riskScore =
              typeof c.risk_score === "number"
                ? c.risk_score
                : typeof c.hrs_contribution === "number"
                ? c.hrs_contribution
                : null;

            return (
              <article
                key={claimId}
                aria-label={`Claim ${claimId}`}
                className={`p-4 rounded-xl border text-xs transition ${
                  isContradicted
                    ? "bg-rose-50/40 border-rose-200 text-slate-800"
                    : isSupported
                    ? "bg-emerald-50/30 border-emerald-200 text-slate-800"
                    : "bg-amber-50/40 border-amber-200 text-slate-800"
                }`}
              >
                {/* Claim Metadata Line */}
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center space-x-2">
                    <span className="font-mono font-bold text-slate-900">
                      {claimId}
                    </span>
                    <span className="text-[10px] uppercase font-mono px-2 py-0.5 bg-slate-100 text-slate-700 rounded border border-slate-200">
                      {claimType}
                    </span>
                    <span className="text-[10px] uppercase font-mono px-2 py-0.5 bg-slate-100 text-slate-600 rounded">
                      {criticality} priority
                    </span>
                  </div>

                  <div className="flex items-center space-x-2.5">
                    {riskScore !== null && (
                      <span className="font-mono text-[11px] text-slate-600">
                        Risk: <span className="font-bold text-slate-900">{riskScore.toFixed(3)}</span>
                      </span>
                    )}

                    <span
                      className={`text-[11px] font-semibold px-2 py-0.5 rounded border inline-flex items-center space-x-1 ${
                        isSupported
                          ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                          : isContradicted
                          ? "text-rose-700 bg-rose-50 border-rose-200"
                          : "text-amber-800 bg-amber-50 border-amber-200"
                      }`}
                    >
                      {isSupported && <CheckCircle2 className="w-3 h-3 mr-1 text-emerald-600" aria-hidden="true" />}
                      {isContradicted && <XCircle className="w-3 h-3 mr-1 text-rose-600" aria-hidden="true" />}
                      {isNeutral && <AlertCircle className="w-3 h-3 mr-1 text-amber-600" aria-hidden="true" />}
                      <span>{rawStatus}</span>
                    </span>
                  </div>
                </div>

                {/* Claim Statement Text */}
                <p className="text-slate-800 leading-relaxed font-sans text-xs">
                  {claimText}
                </p>

                {/* Sub-signal scores if available on claim */}
                {(c.rav_score !== undefined ||
                  c.scs_score !== undefined ||
                  c.nli_score !== undefined ||
                  c.ics_score !== undefined) && (
                  <div className="mt-3 pt-2.5 border-t border-slate-200 flex flex-wrap items-center gap-3 text-[11px] font-mono text-slate-500">
                    {typeof c.rav_score === "number" && (
                      <span>RAV: <strong className="text-slate-800">{c.rav_score.toFixed(3)}</strong></span>
                    )}
                    {typeof c.scs_score === "number" && (
                      <span>SCS: <strong className="text-slate-800">{c.scs_score.toFixed(3)}</strong></span>
                    )}
                    {typeof c.nli_score === "number" && (
                      <span>NLI: <strong className="text-slate-800">{c.nli_score.toFixed(3)}</strong></span>
                    )}
                    {typeof c.ics_score === "number" && (
                      <span>ICS: <strong className="text-slate-800">{c.ics_score.toFixed(3)}</strong></span>
                    )}
                    {typeof c.vgs_score === "number" && (
                      <span>VGS: <strong className="text-slate-800">{c.vgs_score.toFixed(3)}</strong></span>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}

      {/* Response Comparison (if prompt/response text available) */}
      {(originalText || verifiedText) && (
        <div className="pt-4 border-t border-slate-200 grid grid-cols-1 md:grid-cols-2 gap-4">
          {originalText && (
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <span className="text-[11px] font-semibold text-slate-600 block mb-1.5 uppercase tracking-wider font-mono">
                Original Response / Prompt
              </span>
              <p className="text-xs text-slate-800 leading-relaxed whitespace-pre-wrap font-mono">
                {originalText}
              </p>
            </div>
          )}

          {verifiedText && (
            <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider font-mono">
                  Verified & Guarded Output
                </span>
                {correctionApplied && (
                  <span className="inline-flex items-center space-x-1 text-[10px] text-emerald-700 font-semibold bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                    <Sparkles className="w-3 h-3 mr-0.5 text-emerald-600" aria-hidden="true" />
                    <span>Agentic Rewrite Applied</span>
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-800 leading-relaxed whitespace-pre-wrap font-mono">
                {verifiedText}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ClaimsTree;
