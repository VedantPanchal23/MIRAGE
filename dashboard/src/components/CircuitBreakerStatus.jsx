import React from "react";

const NAMES_MAP = {
  llm_api: { label: "Primary LLM API", role: "Groq / OpenAI / OpenRouter" },
  qdrant: { label: "Qdrant Vector DB", role: "Knowledge Base Retrieval" },
  nli_verifier: { label: "DeBERTa NLI Verifier", role: "TorchServe Entailment Server" },
  flan_t5_decomposer: { label: "FLAN-T5 Decomposer", role: "Atomic Claim Extraction" },
  redis_cache: { label: "Redis Cache", role: "SCS Semantic Cluster Cache" },
  rabbitmq_broker: { label: "RabbitMQ Broker", role: "Celery Task Queue" },
  llava_model: { label: "LLaVA-1.6 Vision", role: "Multimodal VQA Grounding" },
};

export function CircuitBreakerStatus({ circuits = {} }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-6 shadow-xs">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Dependency Circuit Breakers</h3>
          <p className="text-xs text-slate-500 mt-0.5">
            pybreaker real-time health and automatic fault isolation
          </p>
        </div>
        <span className="text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 rounded-full">
          All Systems Operational
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5 mt-4">
        {Object.entries(circuits).map(([key, info]) => {
          const meta = NAMES_MAP[key] || { label: key, role: "Backend Subsystem" };
          const isClosed = info.state === "closed";
          const isOpen = info.state === "open";

          const statusBadge = isClosed ? (
            <span className="inline-flex items-center text-[11px] font-semibold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mr-1.5 animate-pulse"></span>
              CLOSED
            </span>
          ) : isOpen ? (
            <span className="inline-flex items-center text-[11px] font-semibold text-rose-700 bg-rose-50 px-2 py-0.5 rounded-md border border-rose-200">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500 mr-1.5"></span>
              OPEN (DEGRADED)
            </span>
          ) : (
            <span className="inline-flex items-center text-[11px] font-semibold text-amber-800 bg-amber-50 px-2 py-0.5 rounded-md border border-amber-200">
              HALF-OPEN
            </span>
          );

          return (
            <div
              key={key}
              className="bg-slate-50/70 border border-slate-200 rounded-lg p-3.5 flex flex-col justify-between hover:border-slate-300 transition"
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-900">{meta.label}</span>
                  {statusBadge}
                </div>
                <p className="text-[11px] text-slate-500 mt-1">{meta.role}</p>
              </div>

              <div className="mt-3 pt-2 border-t border-slate-200 flex justify-between text-[10px] text-slate-500 font-mono">
                <span>Failures: {info.fail_counter || 0}/{info.fail_max || 3}</span>
                <span>Timeout: {info.reset_timeout || 30}s</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
