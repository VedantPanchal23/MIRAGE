import React from "react";

/**
 * Known MIRAGE multi-signal descriptors for TreeSHAP feature attributions.
 * Maps to backend SignalAttribution schema: rav, scs, nli, ics, vgs.
 */
const SIGNAL_METADATA = {
  rav: {
    label: "RAV (Retrieval Support)",
    desc: "Knowledge Base semantic matching & citation grounding",
  },
  scs: {
    label: "SCS (Self-Consistency Sampling)",
    desc: "Multi-sample temperature sampling consistency",
  },
  nli: {
    label: "NLI (Entailment Verifier)",
    desc: "DeBERTa-v3 cross-encoder natural language inference",
  },
  ics: {
    label: "ICS (Internal Inconsistency)",
    desc: "Pairwise intra-response propositional contradiction",
  },
  vgs: {
    label: "VGS (Visual Grounding)",
    desc: "CLIP pre-filter & LLaVA-1.6 multimodal VQA verification",
  },
};

/**
 * SHAPWaterfall Component
 *
 * Renders backend-authoritative TreeSHAP feature attributions.
 *
 * Verified Backend Contract:
 * - Backend `SignalAttribution` schema (`shared/schemas/hrs.py:48-56`) outputs
 *   non-negative relative contribution weights: rav, scs, nli, ics, vgs (ge=0.0, le=1.0).
 * - Per Testing_Strategy.md §6: Sum of active signal attributions in signal_attribution equals 1.0 (±0.01).
 * - Preserves exact backend values without client-side recalculation or artificial normalization.
 * - Does NOT fabricate missing feature contributions (e.g. vgs omitted when no image was processed).
 * - Renders an explicit unavailable state if attribution data is absent, null, or empty.
 * - Displayed additive total ∑ Φ_i is mathematically the exact sum of present backend attribution values.
 * - If signed values are ever supplied, preserves sign cleanly without assuming positive means "increases risk"
 *   when backend outputs normalized importance weights.
 *
 * @param {object} props
 * @param {object|null} [props.attribution] - Key-value map of signal names to TreeSHAP values
 * @param {number} [props.hrsScore=0.0] - Calibrated HRS score for context
 */
export function SHAPWaterfall({ attribution = null, hrsScore = 0.0 }) {
  // Check whether valid backend attribution data is available
  const hasAttribution =
    attribution &&
    typeof attribution === "object" &&
    Object.keys(attribution).length > 0 &&
    Object.values(attribution).some((v) => typeof v === "number" && !isNaN(v));

  if (!hasAttribution) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <h3 className="text-sm font-semibold text-slate-200">
              TreeSHAP Feature Attribution
            </h3>
            <span
              role="status"
              className="text-[11px] font-mono bg-slate-800 text-slate-400 px-2 py-0.5 rounded border border-slate-700"
            >
              Unavailable
            </span>
          </div>
          <span className="text-xs text-slate-500 font-mono">
            HRS: {Number(hrsScore).toFixed(4)}
          </span>
        </div>

        <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-4 text-xs text-slate-400 leading-relaxed">
          TreeSHAP feature attributions are unavailable for this verification session.
          Signal contribution values were not returned by the model server or execution trace.
        </div>
      </div>
    );
  }

  // Parse only the signals actually present in the backend attribution
  const presentSignals = Object.entries(attribution)
    .filter(([_, val]) => typeof val === "number" && !isNaN(val))
    .map(([key, val]) => {
      const lowerKey = key.toLowerCase();
      const meta = SIGNAL_METADATA[lowerKey] || {
        label: key.toUpperCase(),
        desc: "Verification signal contribution",
      };
      return {
        key: lowerKey,
        name: meta.label,
        desc: meta.desc,
        value: val,
      };
    });

  if (presentSignals.length === 0) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-200">
            TreeSHAP Feature Attribution
          </h3>
          <span
            role="status"
            className="text-[11px] font-mono bg-slate-800 text-slate-400 px-2 py-0.5 rounded border border-slate-700"
          >
            Unavailable
          </span>
        </div>
        <p className="text-xs text-slate-400">
          No numeric feature attributions found in session telemetry.
        </p>
      </div>
    );
  }

  // Exact mathematical sum of present attribution values
  const totalSum = presentSignals.reduce((acc, s) => acc + s.value, 0);
  const maxAbs = Math.max(...presentSignals.map((s) => Math.abs(s.value)), 0.001);
  const hasNegativeValues = presentSignals.some((s) => s.value < 0);

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-bold text-white">
            TreeSHAP Feature Attribution
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Exact signal attribution (Φ_i) to Calibrated HRS ({Number(hrsScore).toFixed(4)})
          </p>
        </div>

        <div className="flex items-center space-x-3 text-xs font-mono">
          <span className="text-slate-400">
            ∑ Φ_i ={" "}
            <span className="text-white font-bold">
              {totalSum.toFixed(4)}
            </span>
          </span>
        </div>
      </div>

      {/* Signal Contributions */}
      <div className="space-y-4 pt-1" role="region" aria-label="Feature contributions">
        {presentSignals.map((sig) => {
          const isNegative = sig.value < 0;
          const isPositive = sig.value > 0;
          const formattedValue = isNegative
            ? sig.value.toFixed(4)
            : hasNegativeValues && isPositive
            ? `+${sig.value.toFixed(4)}`
            : sig.value.toFixed(4);

          // Relative percentage share of total attribution
          const percentShare =
            totalSum > 0 && !hasNegativeValues
              ? `${((sig.value / totalSum) * 100).toFixed(1)}%`
              : null;

          const barWidthPercent = Math.min(
            100,
            Math.max(4, Math.round((Math.abs(sig.value) / maxAbs) * 100))
          );

          return (
            <div
              key={sig.key}
              className="bg-slate-950/60 border border-slate-800/80 rounded-lg p-3 hover:border-slate-700 transition"
            >
              <div className="flex items-center justify-between text-xs mb-1.5">
                <div className="flex items-center space-x-2">
                  <span className="font-semibold text-slate-200">{sig.name}</span>
                  <span className="text-[10px] text-slate-400 hidden sm:inline">
                    — {sig.desc}
                  </span>
                </div>

                <div className="flex items-center space-x-2 font-mono">
                  <span
                    className={`text-xs font-bold px-2 py-0.5 rounded border ${
                      isNegative
                        ? "text-emerald-400 bg-emerald-950/80 border-emerald-800"
                        : hasNegativeValues && isPositive
                        ? "text-rose-400 bg-rose-950/80 border-rose-800"
                        : "text-sky-400 bg-sky-950/80 border-sky-800"
                    }`}
                  >
                    {formattedValue}
                  </span>
                  {percentShare && (
                    <span className="text-[10px] text-slate-400 w-20 text-right">
                      {percentShare} share
                    </span>
                  )}
                  {hasNegativeValues && (
                    <span className="text-[10px] text-slate-500 w-24 text-right">
                      {isNegative ? "Negative (-)" : isPositive ? "Positive (+)" : "Neutral"}
                    </span>
                  )}
                </div>
              </div>

              {/* Proportional Magnitude Bar */}
              <div className="w-full bg-slate-900 rounded-full h-2 overflow-hidden flex items-center">
                <div
                  className={`h-full rounded-full transition-all duration-300 ${
                    isNegative
                      ? "bg-emerald-500"
                      : hasNegativeValues && isPositive
                      ? "bg-rose-500"
                      : "bg-sky-500"
                  }`}
                  style={{ width: `${barWidthPercent}%` }}
                  title={`${sig.name}: ${formattedValue}${percentShare ? ` (${percentShare})` : ""}`}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default SHAPWaterfall;
