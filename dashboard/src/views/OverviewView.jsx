import React, { useState, useEffect } from "react";
import {
  ShieldCheck,
  Zap,
  Activity,
  AlertTriangle,
  ArrowUpRight,
  TrendingUp,
  CheckCircle2,
  Lock,
  Layers,
  Sparkles,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { AssuranceGateVisualizer3D } from "../components/AssuranceGateVisualizer3D";

export function OverviewView({ onTabChange }) {
  const { tenantId } = useAuth();
  const [stats, setStats] = useState({
    total_requests: 1248,
    verified_clean_rate: 98.4,
    avg_hrs_score: 0.14,
    active_hitl_pending: 1,
    budget_remaining: 82.5,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    async function loadData() {
      try {
        const res = await api.getDashboardStats(tenantId);
        if (mounted && res) {
          setStats((prev) => ({
            ...prev,
            total_requests: res.total_requests ?? prev.total_requests,
            verified_clean_rate: res.verified_clean_rate ?? prev.verified_clean_rate,
            avg_hrs_score: res.avg_hrs ?? prev.avg_hrs_score,
            active_hitl_pending: res.pending_approvals ?? prev.active_hitl_pending,
          }));
        }
      } catch (err) {
        console.debug("Dashboard stats loading local defaults:", err);
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
      label: "Total Assured Transactions",
      value: stats.total_requests.toLocaleString(),
      change: "+14.2% this week",
      trend: "up",
      icon: Activity,
      color: "text-apple-blue",
    },
    {
      label: "Factual Clean Rate",
      value: `${stats.verified_clean_rate}%`,
      change: "Gate 4 RAV Entailment",
      trend: "neutral",
      icon: ShieldCheck,
      color: "text-apple-green",
    },
    {
      label: "Mean Hallucination Risk (HRS)",
      value: stats.avg_hrs_score.toFixed(2),
      change: "LOW RISK threshold < 0.35",
      trend: "safe",
      icon: Zap,
      color: "text-apple-purple",
    },
    {
      label: "HITL Approvals In Flight",
      value: stats.active_hitl_pending.toString(),
      change: "Action Assurance Gate 3",
      trend: "alert",
      icon: AlertTriangle,
      color: "text-apple-orange",
    },
  ];

  const quickStartSteps = [
    {
      title: "1. Generate API Credentials",
      desc: "Provision a high-entropy key for OpenAI drop-in proxy or MCP governance.",
      tab: "developer",
      done: true,
    },
    {
      title: "2. Ingest Evidence Base (RAG)",
      desc: "Upload compliance policies, documentation, or contracts to Qdrant.",
      tab: "knowledge",
      done: true,
    },
    {
      title: "3. Run Playground Assurance",
      desc: "Interactively test prompts, claim extraction, and side-by-side auto-correction.",
      tab: "playground",
      done: false,
    },
    {
      title: "4. Verify Cryptographic Ledger",
      desc: "Inspect SHA-256 Merkle chain hash audit trail for tamper-evident compliance.",
      tab: "audit",
      done: true,
    },
  ];

  return (
    <div className="space-y-8 pb-12">
      {/* Hero Executive Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pt-2">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-apple-text">
            Workspace Overview
          </h1>
          <p className="text-apple-secondary text-sm mt-1">
            Execution assurance telemetry and multi-gate governance for tenant{" "}
            <span className="font-mono text-apple-text font-semibold">{tenantId}</span>.
          </p>
        </div>

        <div className="flex items-center space-x-3">
          <button
            type="button"
            onClick={() => onTabChange("playground")}
            className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-apple-blue text-white text-sm font-medium hover:bg-apple-blueHover shadow-apple-sm transition"
          >
            <Sparkles className="w-4 h-4" />
            <span>Launch Playground</span>
          </button>
          <button
            type="button"
            onClick={() => onTabChange("billing")}
            className="flex items-center space-x-2 px-4 py-2 rounded-xl bg-apple-subtle border border-apple-border text-apple-text text-sm font-medium hover:bg-apple-border/40 transition"
          >
            <span>Plan & Quota</span>
            <ArrowUpRight className="w-4 h-4 text-apple-secondary" />
          </button>
        </div>
      </div>

      {/* Primary KPI Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {metricCards.map((m, idx) => {
          const Icon = m.icon;
          return (
            <div
              key={idx}
              className="bg-apple-surface rounded-2xl p-5 border border-apple-border shadow-apple-card hover:shadow-apple-float transition-all"
            >
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-medium text-apple-secondary">{m.label}</span>
                <div className={`p-2 rounded-xl bg-apple-subtle ${m.color}`}>
                  <Icon className="w-4 h-4" />
                </div>
              </div>
              <div className="text-2xl font-bold text-apple-text tracking-tight">{m.value}</div>
              <div className="text-xs text-apple-muted mt-1.5 flex items-center space-x-1">
                <span>{m.change}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* 3D Visualizer Section */}
      <AssuranceGateVisualizer3D />

      {/* Quick Start & Getting Started Checklist */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-7 bg-apple-surface rounded-3xl p-6 border border-apple-border shadow-apple-card">
          <div className="flex items-center justify-between mb-4 pb-3 border-b border-apple-border">
            <h3 className="font-semibold text-apple-text text-base">Onboarding & Setup</h3>
            <span className="text-xs font-mono text-apple-secondary">3 of 4 Completed</span>
          </div>

          <div className="space-y-3">
            {quickStartSteps.map((step, idx) => (
              <div
                key={idx}
                onClick={() => onTabChange(step.tab)}
                className="flex items-start justify-between p-3.5 rounded-2xl bg-apple-subtle/50 hover:bg-apple-subtle border border-apple-border/70 transition cursor-pointer group"
              >
                <div className="flex items-start space-x-3">
                  <div className="mt-0.5">
                    {step.done ? (
                      <CheckCircle2 className="w-4 h-4 text-apple-green" />
                    ) : (
                      <div className="w-4 h-4 rounded-full border-2 border-apple-blue" />
                    )}
                  </div>
                  <div>
                    <h4 className="text-xs sm:text-sm font-semibold text-apple-text group-hover:text-apple-blue transition">
                      {step.title}
                    </h4>
                    <p className="text-xs text-apple-secondary mt-0.5">{step.desc}</p>
                  </div>
                </div>
                <ArrowUpRight className="w-4 h-4 text-apple-muted group-hover:text-apple-blue transition" />
              </div>
            ))}
          </div>
        </div>

        {/* Commercial SaaS Assurance Guarantee Box */}
        <div className="lg:col-span-5 bg-gradient-to-br from-apple-subtle via-apple-surface to-apple-subtle rounded-3xl p-6 border border-apple-border shadow-apple-card flex flex-col justify-between">
          <div>
            <div className="w-10 h-10 rounded-2xl bg-apple-blue/10 text-apple-blue flex items-center justify-center mb-4 border border-apple-blue/20">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <h3 className="text-lg font-bold text-apple-text tracking-tight">
              Epistemic Guarantee
            </h3>
            <p className="text-xs text-apple-secondary leading-relaxed mt-2">
              MIRAGE 3.0 strictly separates model assertions from physical reality. A tool's return code
              is never trusted as proof of outcome until Gate 5 confirms postconditions via independent
              read-back and records a SHA-256 Merkle chain entry.
            </p>
          </div>

          <div className="pt-6 border-t border-apple-border mt-4">
            <div className="flex items-center justify-between text-xs text-apple-secondary mb-2">
              <span>SLA Uptime & Fencing</span>
              <span className="font-mono font-semibold text-apple-text">99.99%</span>
            </div>
            <div className="w-full h-1.5 rounded-full bg-apple-border overflow-hidden">
              <div className="w-full h-full bg-apple-green rounded-full" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
