import React from "react";
import { Clock } from "lucide-react";

/**
 * Placeholder view for upcoming P2 views according to the implementation roadmap.
 */
export function PlaceholderView({ title, phase, description }) {
  return (
    <section
      aria-labelledby="placeholder-heading"
      className="bg-slate-900 border border-slate-800 rounded-xl p-8 max-w-2xl mx-auto my-8 text-center shadow-lg"
    >
      <div className="w-12 h-12 rounded-full bg-sky-500/10 border border-sky-500/30 flex items-center justify-center mx-auto text-sky-400 mb-4">
        <Clock className="w-6 h-6" aria-hidden="true" />
      </div>
      <h2 id="placeholder-heading" className="text-xl font-bold text-white mb-2">
        {title}
      </h2>
      <span className="inline-block text-xs font-mono px-2.5 py-0.5 rounded-full bg-sky-950 text-sky-400 border border-sky-800 font-semibold mb-4">
        Planned for {phase}
      </span>
      <p className="text-sm text-slate-300 leading-relaxed mb-6">
        {description}
      </p>
      <div className="text-xs text-slate-400 border-t border-slate-800 pt-4">
        Infrastructure contracts and API bindings are established. View implementation will activate in the scheduled phase.
      </div>
    </section>
  );
}

export default PlaceholderView;
