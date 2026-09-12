import React from "react";
import { SignalAttribution } from "../types";

interface SHAPWaterfallProps {
  attribution: SignalAttribution;
  hrsScore: number;
}

export const SHAPWaterfall: React.FC<SHAPWaterfallProps> = ({
  attribution,
  hrsScore,
}) => {
  const signals = [
    { name: "RAV (Retrieval Support)", value: attribution.rav, color: "bg-blue-500", desc: "Knowledge Base semantic matching" },
    { name: "SCS (Semantic Entropy)", value: attribution.scs, color: "bg-indigo-500", desc: "n=5 sampling consistency" },
    { name: "NLI (Entailment Verifier)", value: attribution.nli, color: "bg-purple-500", desc: "DeBERTa-v3 cross-encoder" },
    { name: "ICS (Internal Inconsistency)", value: attribution.ics, color: "bg-amber-500", desc: "Pairwise intra-response contradiction" },
  ];

  if (attribution.vgs !== undefined && attribution.vgs !== null) {
    signals.push({
      name: "VGS (Visual Grounding)",
      value: attribution.vgs,
      color: "bg-emerald-500",
      desc: "CLIP pre-filter & LLaVA-1.6 VQA",
    });
  }

  const total = signals.reduce((acc, s) => acc + s.value, 0) || 1.0;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">TreeSHAP Feature Attribution</h3>
          <p className="text-xs text-slate-400 mt-0.5">
            Marginal signal contribution to Calibrated HRS ({hrsScore.toFixed(3)})
          </p>
        </div>
        <span className="text-xs font-mono bg-slate-800 text-slate-300 px-2 py-1 rounded">
          ∑ Φ_i = 100%
        </span>
      </div>

      <div className="space-y-4 mt-5">
        {signals.map((sig) => {
          const percentage = Math.round((sig.value / total) * 100);
          return (
            <div key={sig.name}>
              <div className="flex justify-between items-center text-xs mb-1.5">
                <span className="font-medium text-slate-300">{sig.name}</span>
                <div className="flex items-center space-x-2">
                  <span className="text-slate-400 font-mono text-[11px]">{sig.value.toFixed(3)}</span>
                  <span className="font-semibold text-slate-200 w-9 text-right">{percentage}%</span>
                </div>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden">
                <div
                  className={`h-2.5 rounded-full transition-all duration-500 ${sig.color}`}
                  style={{ width: `${percentage}%` }}
                  title={`${sig.desc}: ${percentage}%`}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
