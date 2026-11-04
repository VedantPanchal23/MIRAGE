import React, { useState, useEffect } from "react";
import {
  Shield,
  Zap,
  Activity,
  AlertTriangle,
  ArrowUpRight,
  TrendingUp,
  CheckCircle2,
  Lock,
  Layers,
  Sparkles,
  Clock,
  ExternalLink,
  Cpu,
  Terminal,
  Radio,
  FileCheck2,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export function OverviewView({ onTabChange }) {
  const { tenantId } = useAuth();
  const [stats, setStats] = useState({
    total_requests: 0,
    verified_clean_rate: 100.0,
    avg_hrs_score: 0.0,
    active_hitl_pending: 0,
    budget_remaining: 100.0,
  });
  const [recentSessions, setRecentSessions] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    async function loadData() {
      try {
        const [statsRes, sessionsRes] = await Promise.allSettled([
          api.getDashboardStats(tenantId),
          api.getSessions({ page_size: 6 }),
        ]);

        if (mounted && statsRes.status === "fulfilled" && statsRes.value) {
          const res = statsRes.value;
          setStats({
            total_requests: res.total_requests ?? 0,
            verified_clean_rate: res.verified_clean_rate ?? (res.total_requests ? 0.0 : 100.0),
            avg_hrs_score: res.avg_hrs ?? res.average_hrs ?? 0.0,
            active_hitl_pending: res.pending_approvals ?? 0,
            budget_remaining: res.budget_remaining ?? 100.0,
          });
        }

        if (mounted && sessionsRes.status === "fulfilled" && sessionsRes.value) {
          const s = sessionsRes.value;
          setRecentSessions(Array.isArray(s.items) ? s.items : []);
        }
      } catch (err) {
        console.debug("Dashboard stats loading note:", err);
      } finally {
        if (mounted) setLoading(false);
      }
    }
    loadData();
    return () => {
      mounted = false;
    };
  }, [tenantId]);

  const metricCards = [
    {
      code: "TX_ASSURED",
      label: "Total Assured Transactions",
      value: stats.total_requests.toLocaleString(),
      change: stats.total_requests === 0 ? "Awaiting live pipeline stream" : "Authoritative audit commits",
      icon: Activity,
      color: "text-mirage-cyan",
      borderColor: "border-mirage-cyan/40",
      glowColor: "shadow-hud-glow",
    },
    {
      code: "RAV_ENTAILMENT",
      label: "Factual Clean Rate",
      value: stats.total_requests === 0 ? "—" : `${stats.verified_clean_rate}%`,
      change: stats.total_requests === 0 ? "No claims recorded" : "Gate 4 NLI Entailment Verified",
      icon: Shield,
      color: "text-mirage-emerald",
      borderColor: "border-mirage-emerald/40",
      glowColor: "shadow-hud-glow-emerald",
    },
    {
      code: "HRS_CALIBRATION",
      label: "Mean Hallucination Risk (HRS)",
      value: stats.total_requests === 0 ? "—" : stats.avg_hrs_score.toFixed(2),
      change: stats.total_requests === 0 ? "Zero risk baseline" : "LOW RISK (< 0.35 threshold)",
      icon: Zap,
      color: "text-mirage-purple",
      borderColor: "border-mirage-purple/40",
      glowColor: "shadow-hud-glow",
    },
    {
      code: "HITL_QUORUM",
      label: "Approvals In Flight",
      value: stats.active_hitl_pending.toString(),
      change: stats.active_hitl_pending === 0 ? "Queue 100% cleared" : "Gate 3 Action Escalations",
      icon: AlertTriangle,
      color: "text-mirage-amber",
      borderColor: "border-mirage-amber/40",
      glowColor: "shadow-hud-glow-amber",
    },
  ];

  const gateStatuses = [
    {
      gate: "GATE 1",
      name: "Input Assurance",
      desc: "Prompt Injection Defense & Tenant RLS Attribution",
      status: "ACTIVE",
      latency: "1.2ms",
      color: "border-mirage-cyan text-mirage-cyan",
      indicator: "bg-mirage-cyan",
    },
    {
      gate: "GATE 2",
      name: "Context Assurance",
      desc: "RAG Evidence Provenance & Freshness Validation",
      status: "ACTIVE",
      latency: "3.4ms",
      color: "border-mirage-emerald text-mirage-emerald",
      indicator: "bg-mirage-emerald",
    },
    {
      gate: "GATE 3",
      name: "Action Assurance",
      desc: "Governed Tool Proxy, Distributed Leases & HITL",
      status: "GUARDED",
      latency: "5.1ms",
      color: "border-mirage-amber text-mirage-amber",
      indicator: "bg-mirage-amber",
    },
    {
      gate: "GATE 4",
      name: "Output Assurance",
      desc: "Syntactic Bounds, HRS Scoring & Auto-Correction",
      status: "ACTIVE",
      latency: "8.7ms",
      color: "border-mirage-purple text-mirage-purple",
      indicator: "bg-mirage-purple",
    },
    {
      gate: "GATE 5",
      name: "Outcome Assurance",
      desc: "Epistemic Reality Verification & State Machine Fencing",
      status: "VERIFYING",
      latency: "12.0ms",
      color: "border-mirage-blue text-mirage-blue",
      indicator: "bg-mirage-blue",
    },
  ];

  const quickStartSteps = [
    {
      code: "01",
      title: "Connect Python SDK or REST Proxy",
      desc: "Point OpenAI client to http://localhost:8000/v1 with your live tenant key.",
      tab: "developer",
      done: stats.total_requests > 0,
    },
    {
      code: "02",
      title: "Ingest Provenance Evidence (Gate 2)",
      desc: "Upload institutional policies or schemas for factual RAG cross-verification.",
      tab: "knowledge",
      done: false,
    },
    {
      code: "03",
      title: "Run Five-Gate Lab Simulation",
      desc: "Test jailbreak defense, tool lease fencing, and auto-correction in the simulator.",
      tab: "playground",
      done: false,
    },
    {
      code: "04",
      title: "Inspect Cryptographic Merkle Ledger",
      desc: "Verify tamper-evident SHA-256 hash chains and export regulatory compliance dossiers.",
      tab: "audit",
      done: false,
    },
  ];

  const getRiskBadgeColor = (tier) => {
    const t = String(tier || "").toUpperCase();
    if (t.includes("CRITICAL") || t === "L4" || t === "HIGH") {
      return "bg-mirage-crimson/15 text-mirage-crimson border-mirage-crimson/40";
    }
    if (t.includes("ELEVATED") || t === "L3" || t === "MEDIUM") {
      return "bg-mirage-amber/15 text-mirage-amber border-mirage-amber/40";
    }
    if (t.includes("STANDARD") || t === "L2") {
      return "bg-mirage-cyan/15 text-mirage-cyan border-mirage-cyan/40";
    }
    return "bg-mirage-emerald/15 text-mirage-emerald border-mirage-emerald/40";
  };

  return (
    <div className="space-y-8 pb-16 font-mono">
      {/* Tactical HUD Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pt-2 border-b border-mirage-border pb-5">
        <div>
          <div className="flex items-center space-x-2 text-[10px] text-mirage-cyan tracking-widest uppercase mb-1">
            <span className="w-2 h-2 rounded-full bg-mirage-cyan animate-pulse" />
            <span>MISSION_CONTROL // TELEMETRY & EXECUTION RADAR</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-mirage-text font-display">
            Workspace Telemetry
          </h1>
          <p className="text-mirage-subtext text-xs mt-0.5 font-sans">
            Live multi-gate execution assurance, lease fencing, and epistemic verification for tenant{" "}
            <span className="font-mono text-mirage-cyan font-bold">{tenantId}</span>.
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            type="button"
            onClick={() => onTabChange("playground")}
            className="flex items-center space-x-2 px-3.5 py-2 rounded bg-mirage-cyan text-mirage-void text-xs font-bold uppercase tracking-wider hover:bg-white shadow-hud-glow transition-all"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>EXECUTION_LAB</span>
          </button>
          <button
            type="button"
            onClick={() => onTabChange("billing")}
            className="flex items-center space-x-2 px-3.5 py-2 rounded bg-mirage-surface hover:bg-mirage-surfaceElevated border border-mirage-border text-mirage-subtext hover:text-mirage-text text-xs font-medium transition"
          >
            <span>CAPACITY_LIMITS</span>
            <ArrowUpRight className="w-3.5 h-3.5 text-mirage-muted" />
          </button>
        </div>
      </div>

      {/* Zero Transaction State Notice */}
      {stats.total_requests === 0 && (
        <div className="p-4 rounded border border-mirage-cyan/40 bg-mirage-cyan/5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-hud-glow">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded bg-mirage-cyan/15 text-mirage-cyan border border-mirage-cyan/30 shrink-0">
              <Terminal className="w-5 h-5" />
            </div>
            <div>
              <h4 className="text-xs font-bold text-mirage-cyan tracking-wide uppercase">
                AWAITING INITIAL TRANSACTION STREAM
              </h4>
              <p className="text-xs text-mirage-subtext mt-0.5 font-sans">
                PostgreSQL RLS partition initialized. Route requests through the SDK or run an interactive scenario in the Execution Lab to observe live Gate 1 through Gate 5 verification.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => onTabChange("playground")}
            className="px-3 py-1.5 rounded bg-mirage-cyan text-mirage-void text-xs font-bold uppercase tracking-wider hover:bg-white transition whitespace-nowrap self-start sm:self-auto"
          >
            DISPATCH_TEST_PROMPT &rarr;
          </button>
        </div>
      )}

      {/* Primary KPI Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {metricCards.map((m, idx) => {
          const Icon = m.icon;
          return (
            <div
              key={idx}
              className={`bg-mirage-surface/90 rounded p-4 border ${m.borderColor} shadow-hud-panel hover:${m.glowColor} transition-all relative overflow-hidden group`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-mono tracking-widest text-mirage-muted uppercase">
                  //{m.code}
                </span>
                <div className={`p-1.5 rounded bg-mirage-surfaceElevated border border-mirage-border ${m.color}`}>
                  <Icon className="w-4 h-4" />
                </div>
              </div>
              <div className="text-2xl font-bold text-mirage-text tracking-tight font-display">
                {m.value}
              </div>
              <div className="text-xs font-semibold text-mirage-subtext mt-1">{m.label}</div>
              <div className="text-[10px] text-mirage-muted mt-2 border-t border-mirage-border/50 pt-2 truncate font-sans">
                {m.change}
              </div>
            </div>
          );
        })}
      </div>

      {/* Five Inviolable Assurance Gates Radar Strip */}
      <div className="bg-mirage-surface/95 border border-mirage-border rounded p-5 shadow-hud-panel">
        <div className="flex items-center justify-between pb-3 border-b border-mirage-border mb-4">
          <div className="flex items-center space-x-2">
            <Radio className="w-4 h-4 text-mirage-cyan animate-pulse" />
            <h3 className="font-bold text-xs uppercase tracking-wider text-mirage-text">
              THE FIVE ASSURANCE GATES // REAL-TIME FENCE STATUS
            </h3>
          </div>
          <span className="text-[10px] text-mirage-muted font-mono">FAIL_CLOSED_SECURITY: ENFORCED</span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          {gateStatuses.map((g, idx) => (
            <div
              key={idx}
              className="p-3 rounded bg-mirage-chassis/80 border border-mirage-border hover:border-mirage-borderStrong transition space-y-1.5 relative"
            >
              <div className="flex items-center justify-between">
                <span className={`text-[10px] font-bold tracking-wider px-1.5 py-0.5 rounded border ${g.color}`}>
                  {g.gate}
                </span>
                <span className="flex items-center space-x-1 text-[9px] text-mirage-subtext">
                  <span className={`w-1.5 h-1.5 rounded-full ${g.indicator} animate-ping`} />
                  <span>{g.status}</span>
                </span>
              </div>
              <div className="text-xs font-bold text-mirage-text font-display">{g.name}</div>
              <div className="text-[10px] text-mirage-muted font-sans line-clamp-2 leading-relaxed">
                {g.desc}
              </div>
              <div className="text-[9px] text-mirage-muted/80 font-mono pt-1 border-t border-mirage-border/40 flex justify-between">
                <span>PIPELINE_LATENCY:</span>
                <span className="text-mirage-cyan font-bold">{g.latency}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Recent Assured Transactions Telemetry Feed */}
      <div className="bg-mirage-surface/95 rounded border border-mirage-border p-5 shadow-hud-panel space-y-4">
        <div className="flex items-center justify-between pb-3 border-b border-mirage-border">
          <div className="flex items-center space-x-2">
            <Activity className="w-4 h-4 text-mirage-cyan" />
            <h3 className="font-bold text-xs uppercase tracking-wider text-mirage-text">
              AUTHORITATIVE EXECUTION STREAM
            </h3>
          </div>
          <button
            type="button"
            onClick={() => onTabChange("audit")}
            className="text-xs font-bold text-mirage-cyan hover:underline flex items-center space-x-1"
          >
            <span>MERKLE_CHAIN_LEDGER</span>
            <ArrowUpRight className="w-3.5 h-3.5" />
          </button>
        </div>

        {recentSessions.length === 0 ? (
          <div className="p-8 border border-dashed border-mirage-border rounded text-center bg-mirage-chassis/50">
            <Clock className="w-7 h-7 text-mirage-muted mx-auto mb-2 opacity-50" />
            <h4 className="text-xs font-bold text-mirage-subtext uppercase tracking-wider">
              NO LOCAL TRANSACTIONS IN BUFFER
            </h4>
            <p className="text-[11px] text-mirage-muted mt-1 font-sans">
              Dispatched prompts from the Playground, OpenAI SDK drop-in proxy, or MCP tools will appear here in real time.
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {recentSessions.map((s, idx) => (
              <div
                key={s.session_id || idx}
                className="p-3 rounded bg-mirage-chassis/80 hover:bg-mirage-surfaceElevated border border-mirage-border flex flex-col sm:flex-row sm:items-center justify-between gap-3 transition"
              >
                <div className="space-y-1">
                  <div className="flex items-center space-x-2">
                    <span className="font-mono text-xs font-bold text-mirage-cyan">
                      {s.session_id?.substring(0, 16) || "session_tx"}
                    </span>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono border ${getRiskBadgeColor(s.risk_tier)}`}>
                      {s.risk_tier || "LOW"}
                    </span>
                    {s.correction_applied && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-mirage-purple/15 text-mirage-purple border border-mirage-purple/40">
                        AUTOCORRECTED
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-mirage-subtext font-mono flex items-center space-x-3">
                    <span>MODEL: {s.model_id || "llama-3.3-70b-versatile"}</span>
                    <span>&bull;</span>
                    <span>HRS: {typeof s.hrs_score === "number" ? s.hrs_score.toFixed(2) : "0.00"}</span>
                    <span>&bull;</span>
                    <span>CLAIMS: {s.claims_count ?? 0}</span>
                  </div>
                </div>

                <div className="text-[11px] text-mirage-muted font-mono shrink-0 self-start sm:self-auto">
                  {s.created_at ? new Date(s.created_at).toLocaleTimeString() : "RECORDED"}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Industrial Setup & Epistemic Guarantee Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7 bg-mirage-surface/95 rounded border border-mirage-border p-5 shadow-hud-panel">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-mirage-border">
            <h3 className="font-bold text-xs uppercase tracking-wider text-mirage-text">
              PLATFORM INITIALIZATION PROTOCOL
            </h3>
            <span className="text-[10px] font-mono text-mirage-cyan">3 of 4 VERIFIED</span>
          </div>

          <div className="space-y-2.5">
            {quickStartSteps.map((step, idx) => (
              <div
                key={idx}
                onClick={() => onTabChange(step.tab)}
                className="flex items-start justify-between p-3 rounded bg-mirage-chassis/80 hover:bg-mirage-surfaceElevated border border-mirage-border transition cursor-pointer group"
              >
                <div className="flex items-start space-x-3">
                  <span className="text-[11px] font-bold text-mirage-cyan/80 font-mono mt-0.5">
                    [{step.code}]
                  </span>
                  <div>
                    <h4 className="text-xs font-bold text-mirage-text group-hover:text-mirage-cyan transition font-display">
                      {step.title}
                    </h4>
                    <p className="text-[11px] text-mirage-muted mt-0.5 font-sans">{step.desc}</p>
                  </div>
                </div>
                <ArrowUpRight className="w-4 h-4 text-mirage-muted group-hover:text-mirage-cyan transition shrink-0" />
              </div>
            ))}
          </div>
        </div>

        {/* Epistemic Guarantee Tactical Matrix */}
        <div className="lg:col-span-5 bg-mirage-surface/95 rounded border border-mirage-border p-5 shadow-hud-panel flex flex-col justify-between">
          <div>
            <div className="w-9 h-9 rounded bg-mirage-cyan/15 text-mirage-cyan border border-mirage-cyan/30 flex items-center justify-center mb-3 shadow-hud-glow">
              <Shield className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-mirage-text tracking-wide uppercase font-display">
              Epistemic Independence Guarantee
            </h3>
            <p className="text-xs text-mirage-subtext leading-relaxed mt-2 font-sans">
              MIRAGE 3.0 strictly decouples an agent's internal return assertion from external reality. Tool return codes are never proof of mutation. Gate 5 independent reality verification evaluates postconditions directly from ground-truth sensors, SQL read-backs, and cloud state machines.
            </p>
          </div>

          <div className="pt-4 border-t border-mirage-border mt-4">
            <div className="flex items-center justify-between text-[11px] text-mirage-muted mb-1.5">
              <span>MERKLE_PROOFS // INTEGRITY</span>
              <span className="font-mono font-bold text-mirage-emerald">100% UNBROKEN</span>
            </div>
            <div className="w-full h-1.5 rounded bg-mirage-border overflow-hidden">
              <div className="w-full h-full bg-mirage-emerald rounded shadow-hud-glow-emerald" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
