import React from "react";
import { CircuitInfo } from "../types";

interface CircuitBreakerStatusProps {
  circuits: Record<string, CircuitInfo>;
}

export const CircuitBreakerStatus: React.FC<CircuitBreakerStatusProps> = ({ circuits }) => {
  const namesMap: Record<string, { label: string; role: string }> = {
    llm_api: { label: "Primary LLM API", role: "Groq / OpenAI / OpenRouter" },
    qdrant: { label: "Qdrant Vector DB", role: "Knowledge Base Retrieval" },
    nli_verifier: { label: "DeBERTa NLI Verifier", role: "TorchServe Entailment Server" },
    flan_t5_decomposer: { label: "FLAN-T5 Decomposer", role: "Atomic Claim Extraction" },
    redis_cache: { label: "Redis Cache", role: "SCS Semantic Cluster Cache" },
    rabbitmq_broker: { label: "RabbitMQ Broker", role: "Celery Task Queue" },
    llava_model: { label: "LLaVA-1.6 Vision", role: "Multimodal VQA Grounding" },
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Dependency Circuit Breakers</h3>
          <p className="text-xs text-slate-400 mt-0.5">
            pybreaker real-time health and automatic fault isolation
          </p>
        </div>
        <span className="text-xs font-medium text-emerald-400 bg-emerald-950/80 border border-emerald-800 px-2.5 py-0.5 rounded-full">
          All Systems Operational
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5 mt-4">
        {Object.entries(circuits).map(([key, info]) => {
          const meta = namesMap[key] || { label: key, role: "Backend Subsystem" };
          const isClosed = info.state === "closed";
          const isOpen = info.state === "open";

          const statusBadge = isClosed ? (
            <span className="inline-flex items-center text-[11px] font-semibold text-emerald-400 bg-emerald-950 px-2 py-0.5 rounded-md border border-emerald-800">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-1.5 animate-pulse"></span>
              CLOSED
            </span>
          ) : isOpen ? (
            <span className="inline-flex items-center text-[11px] font-semibold text-rose-400 bg-rose-950 px-2 py-0.5 rounded-md border border-rose-800">
              <span className="w-1.5 h-1.5 rounded-full bg-rose-400 mr-1.5"></span>
              OPEN (DEGRADED)
            </span>
          ) : (
            <span className="inline-flex items-center text-[11px] font-semibold text-amber-400 bg-amber-950 px-2 py-0.5 rounded-md border border-amber-800">
              HALF-OPEN
            </span>
          );

          return (
            <div
              key={key}
              className="bg-slate-950 border border-slate-800/80 rounded-lg p-3.5 flex flex-col justify-between hover:border-slate-700 transition"
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-200">{meta.label}</span>
                  {statusBadge}
                </div>
                <p className="text-[11px] text-slate-500 mt-1">{meta.role}</p>
              </div>

              <div className="mt-3 pt-2 border-t border-slate-900 flex justify-between text-[10px] text-slate-400 font-mono">
                <span>Failures: {info.fail_counter}/{info.fail_max}</span>
                <span>Timeout: {info.reset_timeout}s</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
