import React, { useState, useEffect } from "react";
import {
  Settings,
  Shield,
  DollarSign,
  Lock,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  Sliders,
  Database,
  Key,
  Unlock,
  AlertTriangle,
  ArrowRight,
  UserCheck,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export function SettingsView() {
  const { tenantId, role, token, apiKey } = useAuth();

  // Tab State: "budgets" | "concurrency" | "organization"
  const [activeSection, setActiveSection] = useState("budgets");

  // Budget State
  const [budget, setBudget] = useState(null);
  const [budgetLoading, setBudgetLoading] = useState(false);
  const [budgetError, setBudgetError] = useState(null);
  const [budgetSuccess, setBudgetSuccess] = useState(null);

  // Budget Edit Form
  const [editLimitMicros, setEditLimitMicros] = useState("1000000000"); // $1000.00
  const [editHardLimit, setEditHardLimit] = useState(true);
  const [editResetPeriod, setEditResetPeriod] = useState("MONTHLY");
  const [savingBudget, setSavingBudget] = useState(false);
  const [reconciling, setReconciling] = useState(false);

  // Concurrency Leases State
  const [leases, setLeases] = useState([]);
  const [leasesLoading, setLeasesLoading] = useState(false);
  const [leasesError, setLeasesError] = useState(null);
  const [releasingLeaseId, setReleasingLeaseId] = useState(null);

  // Fetch Budget Data
  const loadBudget = async () => {
    setBudgetLoading(true);
    setBudgetError(null);
    try {
      const data = await api.getTenantBudget();
      setBudget(data);
      if (data) {
        setEditLimitMicros(String(data.total_budget_micros || 1000000000));
        setEditHardLimit(Boolean(data.hard_limit));
        setEditResetPeriod(data.reset_period || "MONTHLY");
      }
    } catch (err) {
      console.warn("Failed to load budget:", err);
      setBudgetError(err?.message || "Could not fetch tenant budget configuration.");
    } finally {
      setBudgetLoading(false);
    }
  };

  // Fetch Leases Data
  const loadLeases = async () => {
    setLeasesLoading(true);
    setLeasesError(null);
    try {
      const data = await api.listResourceLeases({ limit: 50 });
      setLeases(Array.isArray(data) ? data : []);
    } catch (err) {
      console.warn("Failed to load leases:", err);
      setLeasesError(err?.message || "Could not retrieve active concurrency leases.");
    } finally {
      setLeasesLoading(false);
    }
  };

  useEffect(() => {
    loadBudget();
    loadLeases();
  }, [tenantId]);

  // Handle Budget Update
  const handleSaveBudget = async (e) => {
    e.preventDefault();
    setSavingBudget(true);
    setBudgetError(null);
    setBudgetSuccess(null);
    try {
      const parsedMicros = parseInt(editLimitMicros, 10);
      if (isNaN(parsedMicros) || parsedMicros <= 0) {
        throw new Error("Budget limit must be a positive number of micros ($1.00 = 1,000,000 micros).");
      }
      const updated = await api.updateTenantBudget({
        totalBudgetMicros: parsedMicros,
        hardLimit: editHardLimit,
        resetPeriod: editResetPeriod,
      });
      setBudget(updated);
      setBudgetSuccess("Tenant spend ceiling and enforcement bounds updated successfully.");
      setTimeout(() => setBudgetSuccess(null), 5000);
    } catch (err) {
      setBudgetError(err?.message || "Failed to update tenant budget bounds.");
    } finally {
      setSavingBudget(false);
    }
  };

  // Handle Orphaned Reservation Sweep (SUPER_ADMIN)
  const handleReconcileSweeps = async () => {
    setReconciling(true);
    try {
      const res = await api.reconcileBudgetReservations();
      setBudgetSuccess(`Reconciliation complete. Released ${res?.reconciled_reservations ?? 0} orphaned reservations.`);
      await loadBudget();
      setTimeout(() => setBudgetSuccess(null), 5000);
    } catch (err) {
      setBudgetError(err?.message || "Failed to trigger orphaned reservation sweep.");
    } finally {
      setReconciling(false);
    }
  };

  // Handle Manual Lease Release
  const handleReleaseLease = async (leaseId, fencingToken) => {
    if (!window.confirm(`Release concurrency lease '${leaseId}' immediately? This clears active fencer locks.`)) {
      return;
    }
    setReleasingLeaseId(leaseId);
    try {
      await api.releaseResourceLease(leaseId, fencingToken);
      await loadLeases();
    } catch (err) {
      alert(`Error releasing lease: ${err?.message || "Failed to release lease"}`);
    } finally {
      setReleasingLeaseId(null);
    }
  };

  // Calculations for Budget Display
  const totalMicros = budget?.total_budget_micros || 1000000000;
  const spentMicros = budget?.spent_micros || 0;
  const reservedMicros = budget?.reserved_micros || 0;
  const totalUsedMicros = spentMicros + reservedMicros;
  const usedPercent = Math.min(100, Math.round((totalUsedMicros / (totalMicros || 1)) * 100));

  const formatUsd = (micros) => {
    const dollars = (micros || 0) / 1000000;
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(dollars);
  };

  return (
    <div className="space-y-6 pb-12">
      {/* View Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-apple-text flex items-center gap-2">
            <Settings className="w-6 h-6 text-apple-blue" />
            Governance & Organization Settings
          </h1>
          <p className="text-xs text-apple-secondary mt-1">
            Manage tenant micro-budgets, distributed concurrency leases, and Gate 3 execution fencing policies.
          </p>
        </div>

        {/* Section Segmented Switcher */}
        <div className="flex items-center gap-1 p-1 bg-apple-subtle rounded-xl border border-apple-border self-start sm:self-auto">
          <button
            type="button"
            onClick={() => setActiveSection("budgets")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 ${
              activeSection === "budgets"
                ? "bg-white text-apple-text shadow-apple-sm"
                : "text-apple-secondary hover:text-apple-text"
            }`}
          >
            <DollarSign className="w-3.5 h-3.5" />
            Spend Ceilings
          </button>
          <button
            type="button"
            onClick={() => setActiveSection("concurrency")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 ${
              activeSection === "concurrency"
                ? "bg-white text-apple-text shadow-apple-sm"
                : "text-apple-secondary hover:text-apple-text"
            }`}
          >
            <Lock className="w-3.5 h-3.5" />
            Concurrency Leases
          </button>
          <button
            type="button"
            onClick={() => setActiveSection("organization")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 ${
              activeSection === "organization"
                ? "bg-white text-apple-text shadow-apple-sm"
                : "text-apple-secondary hover:text-apple-text"
            }`}
          >
            <Shield className="w-3.5 h-3.5" />
            Tenant Security
          </button>
        </div>
      </div>

      {/* Global Status Notifications */}
      {budgetSuccess && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs rounded-xl flex items-center gap-2 animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{budgetSuccess}</span>
        </div>
      )}
      {budgetError && (
        <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded-xl flex items-center gap-2 animate-in fade-in">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{budgetError}</span>
        </div>
      )}

      {/* ==================================================================== */}
      {/* SECTION 1: SPEND CEILINGS & MICRO-BUDGETS */}
      {/* ==================================================================== */}
      {activeSection === "budgets" && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Live Spend Overview */}
          <div className="lg:col-span-5 space-y-4">
            <div className="bg-apple-surface rounded-2xl p-5 border border-apple-border shadow-apple-card space-y-5">
              <div className="flex items-center justify-between pb-3 border-b border-apple-border">
                <div className="flex items-center gap-2">
                  <DollarSign className="w-4 h-4 text-apple-blue" />
                  <span className="text-xs font-bold uppercase tracking-wider text-apple-text">
                    Budget Headroom
                  </span>
                </div>
                <button
                  type="button"
                  onClick={loadBudget}
                  disabled={budgetLoading}
                  className="p-1 rounded-lg text-apple-secondary hover:text-apple-text hover:bg-apple-subtle transition"
                  title="Refresh budget"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${budgetLoading ? "animate-spin" : ""}`} />
                </button>
              </div>

              {/* High-Level Budget Figures */}
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 rounded-xl bg-apple-subtle border border-apple-border">
                  <span className="text-[10px] uppercase font-bold text-apple-secondary block">Total Ceiling</span>
                  <span className="text-lg font-bold text-apple-text">{formatUsd(totalMicros)}</span>
                </div>
                <div className="p-3 rounded-xl bg-apple-subtle border border-apple-border">
                  <span className="text-[10px] uppercase font-bold text-apple-secondary block">Spent to Date</span>
                  <span className="text-lg font-bold text-apple-text">{formatUsd(spentMicros)}</span>
                </div>
                <div className="p-3 rounded-xl bg-apple-subtle border border-apple-border">
                  <span className="text-[10px] uppercase font-bold text-apple-secondary block">In-Flight Reserved</span>
                  <span className="text-lg font-bold text-apple-blue">{formatUsd(reservedMicros)}</span>
                </div>
                <div className="p-3 rounded-xl bg-apple-subtle border border-apple-border">
                  <span className="text-[10px] uppercase font-bold text-apple-secondary block">Remaining Headroom</span>
                  <span className="text-lg font-bold text-emerald-600">
                    {formatUsd(Math.max(0, totalMicros - totalUsedMicros))}
                  </span>
                </div>
              </div>

              {/* Progress Visualizer */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs font-semibold">
                  <span className="text-apple-secondary">Utilization ({usedPercent}%)</span>
                  <span className="text-apple-text font-mono">
                    {formatUsd(totalUsedMicros)} / {formatUsd(totalMicros)}
                  </span>
                </div>
                <div className="w-full h-2.5 bg-apple-subtle rounded-full overflow-hidden flex border border-apple-border">
                  <div
                    className="bg-apple-text transition-all duration-500"
                    style={{ width: `${Math.min(100, (spentMicros / (totalMicros || 1)) * 100)}%` }}
                    title={`Spent: ${formatUsd(spentMicros)}`}
                  />
                  <div
                    className="bg-apple-blue opacity-70 transition-all duration-500"
                    style={{ width: `${Math.min(100, (reservedMicros / (totalMicros || 1)) * 100)}%` }}
                    title={`Reserved: ${formatUsd(reservedMicros)}`}
                  />
                </div>
                <div className="flex items-center gap-4 text-[10px] text-apple-secondary pt-1">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-apple-text" /> Settled Spend
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-apple-blue" /> In-Flight Leases
                  </span>
                </div>
              </div>

              {/* Fail-Closed Policy Indicator */}
              <div className="p-3 rounded-xl bg-apple-subtle/50 border border-apple-border flex items-start gap-2.5">
                <Shield className="w-4 h-4 text-apple-blue shrink-0 mt-0.5" />
                <div className="text-[11px] leading-relaxed text-apple-secondary">
                  <span className="font-semibold text-apple-text block mb-0.5">
                    {budget?.hard_limit ? "Fail-Closed Enforcement Active" : "Soft-Limit Monitoring"}
                  </span>
                  {budget?.hard_limit
                    ? "Any AI execution exceeding the micro-budget ceiling is denied automatically at Gate 1."
                    : "Overages trigger admin alerts without abruptly halting mission-critical executions."}
                </div>
              </div>

              {/* Reconcile Sweeps (SUPER_ADMIN) */}
              {role === "SUPER_ADMIN" && (
                <div className="pt-2 border-t border-apple-border">
                  <button
                    type="button"
                    onClick={handleReconcileSweeps}
                    disabled={reconciling}
                    className="w-full py-2 px-3 rounded-xl bg-apple-subtle hover:bg-apple-border/50 text-apple-text text-xs font-semibold transition flex items-center justify-center gap-2"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${reconciling ? "animate-spin" : ""}`} />
                    Run Background Reservation Sweep
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Right Column: Edit Budget Bounds Form */}
          <div className="lg:col-span-7">
            <div className="bg-apple-surface rounded-2xl p-5 border border-apple-border shadow-apple-card space-y-5">
              <div className="pb-3 border-b border-apple-border">
                <h3 className="text-sm font-semibold text-apple-text flex items-center gap-2">
                  <Sliders className="w-4 h-4 text-apple-blue" />
                  Configure Spend Ceiling & Reset Bounds
                </h3>
                <p className="text-xs text-apple-secondary mt-0.5">
                  Set enforceable execution ceilings in micro-units ($1.00 USD = 1,000,000 micros).
                </p>
              </div>

              <form onSubmit={handleSaveBudget} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-apple-text mb-1">
                    Total Budget Ceiling (in Micros)
                  </label>
                  <div className="relative">
                    <input
                      type="number"
                      min="1000000"
                      step="1000000"
                      value={editLimitMicros}
                      onChange={(e) => setEditLimitMicros(e.target.value)}
                      className="w-full text-xs sm:text-sm p-3 bg-apple-subtle rounded-xl border border-apple-border text-apple-text focus:outline-none focus:border-apple-blue focus:ring-2 focus:ring-apple-blue/10 font-mono"
                      required
                    />
                    <div className="absolute right-3 top-3 text-xs font-mono text-apple-secondary">
                      ≈ {formatUsd(parseInt(editLimitMicros, 10) || 0)}
                    </div>
                  </div>
                  <span className="text-[10px] text-apple-muted mt-1 block">
                    Presets: $100 = 100,000,000 | $500 = 500,000,000 | $1,000 = 1,000,000,000 micros
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-apple-text mb-1">
                      Reset Period Cycle
                    </label>
                    <select
                      value={editResetPeriod}
                      onChange={(e) => setEditResetPeriod(e.target.value)}
                      className="w-full text-xs p-3 bg-apple-subtle rounded-xl border border-apple-border text-apple-text font-medium focus:outline-none focus:border-apple-blue"
                    >
                      <option value="MONTHLY">Monthly Reset (1st of month)</option>
                      <option value="WEEKLY">Weekly Reset (Mondays)</option>
                      <option value="DAILY">Daily Rolling Window</option>
                      <option value="NEVER">Fixed Enterprise Allocation</option>
                    </select>
                  </div>

                  <div className="flex items-center justify-between p-3 bg-apple-subtle rounded-xl border border-apple-border self-end">
                    <div>
                      <span className="block text-xs font-semibold text-apple-text">Hard Limit</span>
                      <span className="text-[10px] text-apple-muted">Block calls on ceiling</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setEditHardLimit(!editHardLimit)}
                      className={`w-9 h-5 flex items-center rounded-full p-0.5 transition ${
                        editHardLimit ? "bg-apple-blue justify-end" : "bg-apple-border justify-start"
                      }`}
                    >
                      <span className="w-4 h-4 bg-white rounded-full shadow-apple-sm" />
                    </button>
                  </div>
                </div>

                <div className="pt-2 flex justify-end">
                  <button
                    type="submit"
                    disabled={savingBudget}
                    className="px-5 py-2.5 bg-apple-text text-white text-xs font-semibold rounded-xl hover:bg-black transition shadow-apple-sm flex items-center gap-2 disabled:opacity-50"
                  >
                    {savingBudget ? (
                      <>
                        <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Saving Configuration...
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Save Budget Allocation
                      </>
                    )}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* SECTION 2: CONCURRENCY LEASES & FENCING TOKENS */}
      {/* ==================================================================== */}
      {activeSection === "concurrency" && (
        <div className="space-y-4">
          <div className="bg-apple-surface rounded-2xl p-5 border border-apple-border shadow-apple-card space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-apple-border">
              <div>
                <h3 className="text-sm font-semibold text-apple-text flex items-center gap-2">
                  <Lock className="w-4 h-4 text-apple-blue" />
                  Active Distributed Concurrency Leases
                </h3>
                <p className="text-xs text-apple-secondary mt-0.5">
                  Monotonic fencing tokens prevent split-brain and duplicate execution across mutating agent tools.
                </p>
              </div>
              <button
                type="button"
                onClick={loadLeases}
                disabled={leasesLoading}
                className="px-3 py-1.5 rounded-xl bg-apple-subtle hover:bg-apple-border/50 text-apple-text text-xs font-semibold transition flex items-center gap-1.5 self-start sm:self-auto"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${leasesLoading ? "animate-spin" : ""}`} />
                Refresh Leases
              </button>
            </div>

            {leasesError && (
              <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded-xl flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{leasesError}</span>
              </div>
            )}

            {leasesLoading ? (
              <div className="py-12 flex flex-col items-center justify-center space-y-3">
                <div className="w-8 h-8 rounded-full border-2 border-apple-blue/20 border-t-apple-blue animate-spin" />
                <span className="text-xs text-apple-secondary">Querying Redis & PostgreSQL lease fencers...</span>
              </div>
            ) : leases.length === 0 ? (
              <div className="py-12 flex flex-col items-center justify-center rounded-xl border border-dashed border-apple-border p-8 text-center bg-apple-subtle/30">
                <Unlock className="w-8 h-8 text-apple-muted mb-2" />
                <h4 className="text-xs font-semibold text-apple-text">No Active Resource Locks</h4>
                <p className="text-[11px] text-apple-secondary max-w-sm mt-1">
                  All shared mutating resources are currently released. Leases are acquired dynamically during Gate 3 action execution.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-apple-border text-apple-secondary font-semibold uppercase text-[10px] tracking-wider">
                      <th className="pb-2.5">Lease ID</th>
                      <th className="pb-2.5">Target Resource</th>
                      <th className="pb-2.5">Fencing Token</th>
                      <th className="pb-2.5">Holder Transaction</th>
                      <th className="pb-2.5">Status</th>
                      <th className="pb-2.5">TTL / Expires</th>
                      <th className="pb-2.5 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-apple-border">
                    {leases.map((lease) => (
                      <tr key={lease.lease_id} className="hover:bg-apple-subtle/40 transition">
                        <td className="py-3 font-mono font-bold text-apple-text">{lease.lease_id}</td>
                        <td className="py-3 font-mono text-apple-secondary">{lease.resource_uri}</td>
                        <td className="py-3">
                          <span className="px-2 py-0.5 rounded font-mono font-bold bg-apple-subtle text-apple-blue border border-apple-border">
                            #{lease.fencing_token}
                          </span>
                        </td>
                        <td className="py-3 font-mono text-[11px] text-apple-muted">
                          {lease.holder_transaction_id || "unassigned"}
                        </td>
                        <td className="py-3">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${
                              lease.status === "ACTIVE"
                                ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                : "bg-amber-50 text-amber-700 border border-amber-200"
                            }`}
                          >
                            {lease.status}
                          </span>
                        </td>
                        <td className="py-3 text-[11px] text-apple-secondary font-mono">
                          {lease.expires_at ? new Date(lease.expires_at).toLocaleTimeString() : "Session-scoped"}
                        </td>
                        <td className="py-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleReleaseLease(lease.lease_id, lease.fencing_token)}
                            disabled={releasingLeaseId === lease.lease_id}
                            className="px-2.5 py-1 text-[11px] font-semibold text-rose-600 hover:bg-rose-50 border border-rose-200 rounded-lg transition disabled:opacity-50"
                          >
                            {releasingLeaseId === lease.lease_id ? "Releasing..." : "Release Lock"}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* SECTION 3: TENANT SECURITY & METADATA */}
      {/* ==================================================================== */}
      {activeSection === "organization" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Identity & Attribution */}
          <div className="bg-apple-surface rounded-2xl p-5 border border-apple-border shadow-apple-card space-y-4">
            <div className="pb-3 border-b border-apple-border">
              <h3 className="text-sm font-semibold text-apple-text flex items-center gap-2">
                <UserCheck className="w-4 h-4 text-apple-blue" />
                Tenant Cryptographic Identity
              </h3>
              <p className="text-xs text-apple-secondary mt-0.5">
                Authoritative Gate 1 isolation profile and PostgreSQL Row-Level Security bound.
              </p>
            </div>

            <div className="space-y-3">
              <div className="p-3 bg-apple-subtle rounded-xl border border-apple-border">
                <span className="text-[10px] uppercase font-bold text-apple-secondary block">Tenant Identifier</span>
                <span className="font-mono text-xs font-bold text-apple-text">{tenantId || "default_tenant"}</span>
              </div>

              <div className="p-3 bg-apple-subtle rounded-xl border border-apple-border">
                <span className="text-[10px] uppercase font-bold text-apple-secondary block">Assigned RBAC Role</span>
                <span className="text-xs font-bold text-apple-blue uppercase">{role || "DEVELOPER"}</span>
              </div>

              <div className="p-3 bg-apple-subtle rounded-xl border border-apple-border">
                <span className="text-[10px] uppercase font-bold text-apple-secondary block">Isolation Layer</span>
                <span className="text-xs text-apple-text">PostgreSQL 16 Multi-Tenant RLS + Tenant Fenced Queues</span>
              </div>
            </div>
          </div>

          {/* Gate 3 Blast Radius Policy Overview */}
          <div className="bg-apple-surface rounded-2xl p-5 border border-apple-border shadow-apple-card space-y-4">
            <div className="pb-3 border-b border-apple-border">
              <h3 className="text-sm font-semibold text-apple-text flex items-center gap-2">
                <Shield className="w-4 h-4 text-apple-blue" />
                Gate 3 Blast Radius Enforcements
              </h3>
              <p className="text-xs text-apple-secondary mt-0.5">
                Execution boundaries applied before tool dispatch.
              </p>
            </div>

            <div className="space-y-3 text-xs">
              <div className="flex items-center justify-between p-2.5 bg-apple-subtle rounded-xl border border-apple-border">
                <span className="text-apple-secondary">Max Concurrency Lease TTL</span>
                <span className="font-mono font-bold text-apple-text">60 seconds</span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-apple-subtle rounded-xl border border-apple-border">
                <span className="text-apple-secondary">Two-Phase Execution Lock</span>
                <span className="font-bold text-emerald-700">Enforced (EXECUTING commit)</span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-apple-subtle rounded-xl border border-apple-border">
                <span className="text-apple-secondary">Target-Side Fencing</span>
                <span className="font-bold text-apple-text">Internal SQL Adapters</span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-apple-subtle rounded-xl border border-apple-border">
                <span className="text-apple-secondary">High-Risk Action Policy</span>
                <span className="font-bold text-amber-700">HITL Approval Required</span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
export default SettingsView;
