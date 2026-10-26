import React, { useState, useEffect, useCallback, useContext } from "react";
import {
  CreditCard,
  Check,
  ShieldCheck,
  Zap,
  Layers,
  Sparkles,
  RefreshCw,
  Copy,
  ExternalLink,
  DollarSign,
  Lock,
  ArrowRight,
  Sliders,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import { getTenantSubscription, subscribePlan } from "../api/billing";
import { AuthContext, ROLES } from "../context/AuthContext";

/**
 * Commercial SaaS Subscription, Pricing Tiers, and Integration Gateway View.
 *
 * Implements MIRAGE 3.0 B2B SaaS Commercial Model:
 * - Developer ($0), Business ($299/mo), and Enterprise ($1,499/mo) subscription tiers.
 * - Live micro-dollar budget headroom ledger with automatic tier adjustments.
 * - Integration modalities: OpenAI Drop-in Proxy, Direct Assurance API, Governed MCP.
 */
export function SubscriptionView({ isRefreshing, onDataLoaded }) {
  const { tenantId, role, hasRole } = useContext(AuthContext);

  const [subscription, setSubscription] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [upgradingTier, setUpgradingTier] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);
  const [selectedTab, setSelectedTab] = useState("proxy");
  const [copiedSnippet, setCopiedSnippet] = useState(false);
  const [currency, setCurrency] = useState("INR");

  const canManageBilling = hasRole(ROLES.SUPER_ADMIN, ROLES.TENANT_ADMIN);

  const loadSubscription = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getTenantSubscription();
      setSubscription(data);
      if (onDataLoaded) onDataLoaded(new Date().toLocaleTimeString());
    } catch (err) {
      console.error("Failed to load subscription:", err);
      setError(err.message || "Failed to load commercial subscription details");
    } finally {
      setLoading(false);
    }
  }, [onDataLoaded]);

  useEffect(() => {
    loadSubscription();
  }, [loadSubscription]);

  useEffect(() => {
    if (isRefreshing) {
      loadSubscription();
    }
  }, [isRefreshing, loadSubscription]);

  const handleSubscribe = async (tier) => {
    if (!canManageBilling) {
      setError("Only Tenant Administrators can modify commercial subscription tiers.");
      return;
    }
    setUpgradingTier(tier);
    setError(null);
    setSuccessMessage(null);
    try {
      const res = await subscribePlan(tier);
      setSuccessMessage(res.message || `Successfully transitioned to ${tier} tier.`);
      await loadSubscription();
      setTimeout(() => setSuccessMessage(null), 5000);
    } catch (err) {
      setError(err.message || "Failed to change subscription plan");
    } finally {
      setUpgradingTier(null);
    }
  };

  const handleCopy = (text) => {
    if (navigator?.clipboard) {
      navigator.clipboard.writeText(text);
      setCopiedSnippet(true);
      setTimeout(() => setCopiedSnippet(false), 2000);
    }
  };

  const proxySnippet = `# 1. Point your existing agent SDK to MIRAGE Drop-in Proxy
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="mirage_live_YOUR_KEY",  # Authenticates tenant & enforces Gates 1-5
)

# Every completion is automatically evaluated through DeBERTa NLI,
# bounded by micro-dollar budget ledgers, and auto-corrected if refuted!
response = client.chat.completions.create(
    model="allam-2-7b",
    messages=[{"role": "user", "content": "Analyze corporate risk ledger."}],
)`;

  const directApiSnippet = `# 2. Direct Programmatic Assurance REST API
import requests

url = "http://localhost:8000/v1/output/assure"
headers = {"Authorization": "Bearer mirage_live_YOUR_KEY"}
payload = {
    "transaction_id": "txn_live_948a2b",
    "model_id": "allam-2-7b",
    "prompt": "Evaluate clinical paracetamol dose 500mg.",
    "response_text": "Administer 500mg paracetamol orally every 6 hours.",
    "auto_correct": True,
}

res = requests.post(url, json=payload, headers=headers)
print("Assurance Contract:", res.json())`;

  const mcpSnippet = `// 3. Governed MCP Server Configuration (~/.claude/claude_desktop_config.json)
{
  "mcpServers": {
    "mirage-governed-tools": {
      "command": "npx",
      "args": ["-y", "@mirage/mcp-bridge", "--gateway", "http://localhost:8000/v1/mcp"],
      "env": {
        "MIRAGE_API_KEY": "mirage_live_YOUR_KEY",
        "MIRAGE_TENANT_ID": "${tenantId || "YOUR_TENANT_ID"}"
      }
    }
  }
}`;

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                Commercial SaaS Platform
              </span>
              <span className="text-xs text-slate-400">
                Active Tier: <strong className="text-white uppercase font-mono">{subscription?.current_tier || "DEVELOPER"}</strong>
              </span>
            </div>
            <h1 className="text-xl font-bold text-white mt-1">
              Subscription Tiers & Commercial Integration
            </h1>
            <p className="text-sm text-slate-400 mt-0.5">
              Govern enterprise AI agents through monthly subscriptions. Flexible access via Drop-in Gateway Proxy, Direct REST API, or Governed MCP Server.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadSubscription}
              disabled={loading}
              className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium rounded-lg border border-slate-700 flex items-center gap-1.5 transition-colors"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/20 rounded-xl p-4 flex items-center gap-3 text-rose-400 text-sm">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {successMessage && (
        <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-4 flex items-center gap-3 text-emerald-400 text-sm">
          <CheckCircle2 className="w-5 h-5 flex-shrink-0" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Subscription Ledger & Usage Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400 font-medium">Monthly Budget Headroom</span>
            <DollarSign className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold text-white mt-2 font-mono">
            ${subscription ? subscription.monthly_budget_usd.toLocaleString("en-US", { minimumFractionDigits: 2 }) : "0.00"}
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Micro-dollar ceiling limit</p>
        </div>

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400 font-medium">Remaining Headroom</span>
            <ShieldCheck className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-2xl font-bold text-white mt-2 font-mono">
            ${subscription ? subscription.remaining_headroom_usd.toLocaleString("en-US", { minimumFractionDigits: 2 }) : "0.00"}
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Available spend before throttle</p>
        </div>

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400 font-medium">Monthly Request Quota</span>
            <Zap className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-2xl font-bold text-white mt-2 font-mono">
            {subscription ? subscription.monthly_request_quota.toLocaleString() : "0"}
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Included verified requests</p>
        </div>

        <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400 font-medium">Max Concurrent Leases</span>
            <Lock className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="text-2xl font-bold text-white mt-2 font-mono">
            {subscription ? subscription.max_concurrent_leases : 0}
          </div>
          <p className="text-[11px] text-slate-500 mt-1">Distributed Redis lease slots</p>
        </div>
      </div>

      {/* Commercial Plans Matrix */}
      <div>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
          <div>
            <h2 className="text-base font-semibold text-white">Available Subscription Plans</h2>
            <p className="text-xs text-slate-400">Choose an assurance tier for local developer sandboxes or production multi-agent enterprises.</p>
          </div>
          {/* Currency Switcher */}
          <div className="flex items-center gap-1 bg-slate-950 p-1 rounded-lg border border-slate-800 self-start">
            <button
              onClick={() => setCurrency("INR")}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-all ${
                currency === "INR"
                  ? "bg-emerald-500 text-slate-950 shadow"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              ₹ INR (India)
            </button>
            <button
              onClick={() => setCurrency("USD")}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-all ${
                currency === "USD"
                  ? "bg-cyan-500 text-slate-950 shadow"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              $ USD (Global)
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {subscription?.plans?.map((plan) => {
            const isCurrent = (subscription.current_tier || "").toLowerCase() === plan.tier.toLowerCase();
            const isEnterprise = plan.tier === "enterprise";
            const isBusiness = plan.tier === "business";
            const displayPrice =
              currency === "INR"
                ? `₹${(plan.price_inr_monthly || 0).toLocaleString("en-IN")}`
                : `$${plan.price_dollars_monthly}`;

            return (
              <div
                key={plan.tier}
                className={`relative bg-slate-900/80 border rounded-2xl p-6 flex flex-col justify-between transition-all ${
                  isCurrent
                    ? "border-emerald-500/50 shadow-lg shadow-emerald-500/10 ring-1 ring-emerald-500/30"
                    : isBusiness
                    ? "border-cyan-500/30 hover:border-cyan-500/60"
                    : "border-slate-800 hover:border-slate-700"
                }`}
              >
                {isCurrent && (
                  <span className="absolute -top-3 left-6 px-3 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500 text-slate-950 uppercase tracking-wider">
                    Current Active Plan
                  </span>
                )}
                {isBusiness && !isCurrent && (
                  <span className="absolute -top-3 left-6 px-3 py-0.5 rounded-full text-[10px] font-bold bg-cyan-500 text-slate-950 uppercase tracking-wider">
                    Most Popular
                  </span>
                )}

                <div>
                  <div className="flex items-center justify-between">
                    <h3 className="text-lg font-bold text-white">{plan.name}</h3>
                    <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300 uppercase">
                      {plan.tier}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1 min-h-[32px]">{plan.tagline}</p>

                  <div className="mt-4 mb-6">
                    <div className="flex items-baseline gap-1">
                      <span className="text-3xl font-extrabold text-white font-mono">
                        {displayPrice}
                      </span>
                      <span className="text-xs text-slate-400">/ month</span>
                    </div>
                    <span className="text-[11px] text-slate-500">
                      ${plan.budget_ceiling_usd.toLocaleString()} budget ceiling included
                    </span>
                  </div>

                  {/* Feature Checklist */}
                  <div className="space-y-2.5 border-t border-slate-800/80 pt-4 mb-6">
                    {plan.features?.map((f, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs">
                        {f.included ? (
                          <Check className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 mt-0.5" />
                        ) : (
                          <span className="w-3.5 h-3.5 text-slate-600 flex-shrink-0 mt-0.5 font-bold text-center">✕</span>
                        )}
                        <div>
                          <span className={f.included ? "text-slate-200 font-medium" : "text-slate-500 line-through"}>
                            {f.title}
                          </span>
                          <p className="text-[11px] text-slate-500">{f.description}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div>
                  <button
                    onClick={() => handleSubscribe(plan.tier)}
                    disabled={isCurrent || upgradingTier !== null || !canManageBilling}
                    className={`w-full py-2.5 px-4 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all ${
                      isCurrent
                        ? "bg-slate-800 text-slate-400 cursor-not-allowed border border-slate-700"
                        : isEnterprise
                        ? "bg-gradient-to-r from-indigo-600 to-cyan-600 hover:from-indigo-500 hover:to-cyan-500 text-white shadow-md shadow-cyan-500/20"
                        : "bg-cyan-600 hover:bg-cyan-500 text-white shadow-md shadow-cyan-600/20"
                    }`}
                  >
                    {upgradingTier === plan.tier ? (
                      <>
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        <span>Updating Plan...</span>
                      </>
                    ) : isCurrent ? (
                      <>
                        <Check className="w-3.5 h-3.5 text-emerald-400" />
                        <span>Active Plan</span>
                      </>
                    ) : (
                      <>
                        <span>Select {plan.name}</span>
                        <ArrowRight className="w-3.5 h-3.5" />
                      </>
                    )}
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {/* Global & Indian Payment Gateway Methods Banner */}
        <div className="mt-4 bg-slate-950/70 border border-slate-800/80 rounded-xl p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 font-bold text-sm">
              ₹/$
            </div>
            <div>
              <h4 className="text-xs font-bold text-white uppercase tracking-wider">
                Instant Multi-Currency Checkout Supported
              </h4>
              <p className="text-[11px] text-slate-400">
                Seamless settlements via Razorpay & Stripe with zero setup fees.
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-slate-900 border border-slate-800 text-slate-300">
              ⚡ UPI (Google Pay, PhonePe, Paytm, BHIM)
            </span>
            <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-slate-900 border border-slate-800 text-slate-300">
              🏦 Netbanking (50+ Banks)
            </span>
            <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-slate-900 border border-slate-800 text-slate-300">
              💳 RuPay / Visa / Mastercard
            </span>
            <span className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-slate-900 border border-slate-800 text-slate-300">
              🛡️ Test Sandbox (₹0 Free)
            </span>
          </div>
        </div>
      </div>

      {/* Commercial Integration Modalities & Code Snippets */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-4">
          <div>
            <h2 className="text-base font-semibold text-white">Commercial Integration Modalities</h2>
            <p className="text-xs text-slate-400">
              Integrate your subscription in minutes via standard enterprise protocols.
            </p>
          </div>
          <div className="flex items-center gap-1.5 bg-slate-800/80 p-1 rounded-lg border border-slate-700">
            <button
              onClick={() => setSelectedTab("proxy")}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${
                selectedTab === "proxy"
                  ? "bg-cyan-600 text-white shadow-xs"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Drop-In Proxy (:8000)
            </button>
            <button
              onClick={() => setSelectedTab("rest")}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${
                selectedTab === "rest"
                  ? "bg-cyan-600 text-white shadow-xs"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Direct Assurance API
            </button>
            <button
              onClick={() => setSelectedTab("mcp")}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition ${
                selectedTab === "mcp"
                  ? "bg-cyan-600 text-white shadow-xs"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Governed MCP Server
            </button>
          </div>
        </div>

        <div className="relative bg-slate-950 border border-slate-800 rounded-xl p-4 font-mono text-xs text-slate-300">
          <button
            onClick={() => {
              const code = selectedTab === "proxy" ? proxySnippet : selectedTab === "rest" ? directApiSnippet : mcpSnippet;
              handleCopy(code);
            }}
            className="absolute top-3 right-3 px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] flex items-center gap-1 border border-slate-700 transition"
          >
            {copiedSnippet ? (
              <>
                <Check className="w-3 h-3 text-emerald-400" />
                <span className="text-emerald-400">Copied!</span>
              </>
            ) : (
              <>
                <Copy className="w-3 h-3 text-slate-400" />
                <span>Copy Code</span>
              </>
            )}
          </button>

          <pre className="overflow-x-auto py-2 leading-relaxed text-cyan-300/90">
            {selectedTab === "proxy" && proxySnippet}
            {selectedTab === "rest" && directApiSnippet}
            {selectedTab === "mcp" && mcpSnippet}
          </pre>
        </div>
      </div>
    </div>
  );
}
