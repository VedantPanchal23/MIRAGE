import React from "react";
import { CheckCircle2, XCircle, AlertCircle, FileText, Sparkles } from "lucide-react";

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
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg space-y-6">
      {/* Section Header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-bold text-white">
            Claim Decomposition & Evidence Verification
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Propositional claim breakdown evaluated across RAV, SCS, NLI, and ICS verification signals
          </p>
        </div>
        <span className="text-xs text-slate-400 font-mono bg-slate-950 px-2.5 py-1 rounded-md border border-slate-800">
          {claims.length} {claims.length === 1 ? "Claim" : "Claims"} Evaluated
        </span>
      </div>

      {/* Claims List */}
      {claims.length === 0 ? (
        <div className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-5 text-center text-xs text-slate-400 font-mono">
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
                    ? "bg-rose-950/20 border-rose-900/60 text-slate-200"
                    : isSupported
                    ? "bg-slate-950/70 border-slate-800/80 text-slate-300"
                    : "bg-amber-950/20 border-amber-900/60 text-slate-200"
                }`}
              >
                {/* Claim Metadata Line */}
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <div className="flex items-center space-x-2">
                    <span className="font-mono font-bold text-slate-300">
                      {claimId}
                    </span>
                    <span className="text-[10px] uppercase font-mono px-2 py-0.5 bg-slate-800 text-slate-300 rounded border border-slate-700">
                      {claimType}
                    </span>
                    <span className="text-[10px] uppercase font-mono px-2 py-0.5 bg-slate-800 text-slate-400 rounded">
                      {criticality} priority
                    </span>
                  </div>

                  <div className="flex items-center space-x-2.5">
                    {riskScore !== null && (
                      <span className="font-mono text-[11px] text-slate-400">
                        Risk: <span className="font-bold text-slate-200">{riskScore.toFixed(3)}</span>
                      </span>
                    )}

                    <span
                      className={`text-[11px] font-semibold px-2 py-0.5 rounded border inline-flex items-center space-x-1 ${
                        isSupported
                          ? "text-emerald-400 bg-emerald-950/80 border-emerald-800"
                          : isContradicted
                          ? "text-rose-400 bg-rose-950/80 border-rose-800"
                          : "text-amber-400 bg-amber-950/80 border-amber-800"
                      }`}
                    >
                      {isSupported && <CheckCircle2 className="w-3 h-3 mr-1" aria-hidden="true" />}
                      {isContradicted && <XCircle className="w-3 h-3 mr-1" aria-hidden="true" />}
                      {isNeutral && <AlertCircle className="w-3 h-3 mr-1" aria-hidden="true" />}
                      <span>{rawStatus}</span>
                    </span>
                  </div>
                </div>

                {/* Claim Statement Text */}
                <p className="text-slate-200 leading-relaxed font-sans text-xs">
                  {claimText}
                </p>

                {/* Sub-signal scores if available on claim */}
                {(c.rav_score !== undefined ||
                  c.scs_score !== undefined ||
                  c.nli_score !== undefined ||
                  c.ics_score !== undefined) && (
                  <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex flex-wrap items-center gap-3 text-[11px] font-mono text-slate-400">
                    {typeof c.rav_score === "number" && (
                      <span>RAV: <strong className="text-slate-300">{c.rav_score.toFixed(3)}</strong></span>
                    )}
                    {typeof c.scs_score === "number" && (
                      <span>SCS: <strong className="text-slate-300">{c.scs_score.toFixed(3)}</strong></span>
                    )}
                    {typeof c.nli_score === "number" && (
                      <span>NLI: <strong className="text-slate-300">{c.nli_score.toFixed(3)}</strong></span>
                    )}
                    {typeof c.ics_score === "number" && (
                      <span>ICS: <strong className="text-slate-300">{c.ics_score.toFixed(3)}</strong></span>
                    )}
                    {typeof c.vgs_score === "number" && (
                      <span>VGS: <strong className="text-slate-300">{c.vgs_score.toFixed(3)}</strong></span>
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
        <div className="pt-4 border-t border-slate-800 grid grid-cols-1 md:grid-cols-2 gap-4">
          {originalText && (
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/80">
              <span className="text-[11px] font-semibold text-slate-400 block mb-1.5 uppercase tracking-wider font-mono">
                Original Response / Prompt
              </span>
              <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap font-mono">
                {originalText}
              </p>
            </div>
          )}

          {verifiedText && (
            <div className="bg-slate-950 rounded-xl p-4 border border-slate-800/80">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider font-mono">
                  Verified & Guarded Output
                </span>
                {correctionApplied && (
                  <span className="inline-flex items-center space-x-1 text-[10px] text-emerald-400 font-semibold bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800">
                    <Sparkles className="w-3 h-3 mr-0.5" aria-hidden="true" />
                    <span>Agentic Rewrite Applied</span>
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-200 leading-relaxed whitespace-pre-wrap font-mono">
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
