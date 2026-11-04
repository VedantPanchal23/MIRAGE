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
          <h1 className="text-2xl font-bold tracking-tight text-mirage-text flex items-center gap-2">
            <Settings className="w-6 h-6 text-mirage-cyan" />
            Governance & Organization Settings
          </h1>
          <p className="text-xs text-mirage-subtext mt-1">
            Manage tenant micro-budgets, distributed concurrency leases, and Gate 3 execution fencing policies.
          </p>
        </div>

        {/* Section Segmented Switcher */}
        <div className="flex items-center gap-1 p-1 bg-mirage-surfaceElevated rounded border border-mirage-border self-start sm:self-auto">
          <button
            type="button"
            onClick={() => setActiveSection("budgets")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 ${
              activeSection === "budgets"
                ? "bg-white text-mirage-text shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
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
                ? "bg-white text-mirage-text shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
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
                ? "bg-white text-mirage-text shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
            }`}
          >
            <Shield className="w-3.5 h-3.5" />
            Tenant Security
          </button>
        </div>
      </div>

      {/* Global Status Notifications */}
      {budgetSuccess && (
        <div className="p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs rounded flex items-center gap-2 animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{budgetSuccess}</span>
        </div>
      )}
      {budgetError && (
        <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded flex items-center gap-2 animate-in fade-in">
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
            <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-5">
              <div className="flex items-center justify-between pb-3 border-b border-mirage-border">
                <div className="flex items-center gap-2">
                  <DollarSign className="w-4 h-4 text-mirage-cyan" />
                  <span className="text-xs font-bold uppercase tracking-wider text-mirage-text">
                    Budget Headroom
                  </span>
                </div>
                <button
                  type="button"
                  onClick={loadBudget}
                  disabled={budgetLoading}
                  className="p-1 rounded-lg text-mirage-subtext hover:text-mirage-text hover:bg-mirage-surfaceElevated transition"
                  title="Refresh budget"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${budgetLoading ? "animate-spin" : ""}`} />
                </button>
              </div>

              {/* High-Level Budget Figures */}
              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 rounded bg-mirage-surfaceElevated border border-mirage-border">
                  <span className="text-[10px] uppercase font-bold text-mirage-subtext block">Total Ceiling</span>
                  <span className="text-lg font-bold text-mirage-text">{formatUsd(totalMicros)}</span>
                </div>
                <div className="p-3 rounded bg-mirage-surfaceElevated border border-mirage-border">
                  <span className="text-[10px] uppercase font-bold text-mirage-subtext block">Spent to Date</span>
                  <span className="text-lg font-bold text-mirage-text">{formatUsd(spentMicros)}</span>
                </div>
                <div className="p-3 rounded bg-mirage-surfaceElevated border border-mirage-border">
                  <span className="text-[10px] uppercase font-bold text-mirage-subtext block">In-Flight Reserved</span>
                  <span className="text-lg font-bold text-mirage-cyan">{formatUsd(reservedMicros)}</span>
                </div>
                <div className="p-3 rounded bg-mirage-surfaceElevated border border-mirage-border">
                  <span className="text-[10px] uppercase font-bold text-mirage-subtext block">Remaining Headroom</span>
                  <span className="text-lg font-bold text-emerald-600">
                    {formatUsd(Math.max(0, totalMicros - totalUsedMicros))}
                  </span>
                </div>
              </div>

              {/* Progress Visualizer */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs font-semibold">
                  <span className="text-mirage-subtext">Utilization ({usedPercent}%)</span>
                  <span className="text-mirage-text font-mono">
                    {formatUsd(totalUsedMicros)} / {formatUsd(totalMicros)}
                  </span>
                </div>
                <div className="w-full h-2.5 bg-mirage-surfaceElevated rounded-full overflow-hidden flex border border-mirage-border">
                  <div
                    className="bg-mirage-text transition-all duration-500"
                    style={{ width: `${Math.min(100, (spentMicros / (totalMicros || 1)) * 100)}%` }}
                    title={`Spent: ${formatUsd(spentMicros)}`}
                  />
                  <div
                    className="bg-mirage-cyan opacity-70 transition-all duration-500"
                    style={{ width: `${Math.min(100, (reservedMicros / (totalMicros || 1)) * 100)}%` }}
                    title={`Reserved: ${formatUsd(reservedMicros)}`}
                  />
                </div>
                <div className="flex items-center gap-4 text-[10px] text-mirage-subtext pt-1">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-mirage-text" /> Settled Spend
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-mirage-cyan" /> In-Flight Leases
                  </span>
                </div>
              </div>

              {/* Fail-Closed Policy Indicator */}
              <div className="p-3 rounded bg-mirage-surfaceElevated/50 border border-mirage-border flex items-start gap-2.5">
                <Shield className="w-4 h-4 text-mirage-cyan shrink-0 mt-0.5" />
                <div className="text-[11px] leading-relaxed text-mirage-subtext">
                  <span className="font-semibold text-mirage-text block mb-0.5">
                    {budget?.hard_limit ? "Fail-Closed Enforcement Active" : "Soft-Limit Monitoring"}
                  </span>
                  {budget?.hard_limit
                    ? "Any AI execution exceeding the micro-budget ceiling is denied automatically at Gate 1."
                    : "Overages trigger admin alerts without abruptly halting mission-critical executions."}
                </div>
              </div>

              {/* Reconcile Sweeps (SUPER_ADMIN) */}
              {role === "SUPER_ADMIN" && (
                <div className="pt-2 border-t border-mirage-border">
                  <button
                    type="button"
                    onClick={handleReconcileSweeps}
                    disabled={reconciling}
                    className="w-full py-2 px-3 rounded bg-mirage-surfaceElevated hover:bg-mirage-border/50 text-mirage-text text-xs font-semibold transition flex items-center justify-center gap-2"
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
            <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-5">
              <div className="pb-3 border-b border-mirage-border">
                <h3 className="text-sm font-semibold text-mirage-text flex items-center gap-2">
                  <Sliders className="w-4 h-4 text-mirage-cyan" />
                  Configure Spend Ceiling & Reset Bounds
                </h3>
                <p className="text-xs text-mirage-subtext mt-0.5">
                  Set enforceable execution ceilings in micro-units ($1.00 USD = 1,000,000 micros).
                </p>
              </div>

              <form onSubmit={handleSaveBudget} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-mirage-text mb-1">
                    Total Budget Ceiling (in Micros)
                  </label>
                  <div className="relative">
                    <input
                      type="number"
                      min="1000000"
                      step="1000000"
                      value={editLimitMicros}
                      onChange={(e) => setEditLimitMicros(e.target.value)}
                      className="w-full text-xs sm:text-sm p-3 bg-mirage-surfaceElevated rounded border border-mirage-border text-mirage-text focus:outline-none focus:border-mirage-cyan focus:ring-2 focus:ring-mirage-cyan/10 font-mono"
                      required
                    />
                    <div className="absolute right-3 top-3 text-xs font-mono text-mirage-subtext">
                      ≈ {formatUsd(parseInt(editLimitMicros, 10) || 0)}
                    </div>
                  </div>
                  <span className="text-[10px] text-mirage-muted mt-1 block">
                    Presets: $100 = 100,000,000 | $500 = 500,000,000 | $1,000 = 1,000,000,000 micros
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-mirage-text mb-1">
                      Reset Period Cycle
                    </label>
                    <select
                      value={editResetPeriod}
                      onChange={(e) => setEditResetPeriod(e.target.value)}
                      className="w-full text-xs p-3 bg-mirage-surfaceElevated rounded border border-mirage-border text-mirage-text font-medium focus:outline-none focus:border-mirage-cyan"
                    >
                      <option value="MONTHLY">Monthly Reset (1st of month)</option>
                      <option value="WEEKLY">Weekly Reset (Mondays)</option>
                      <option value="DAILY">Daily Rolling Window</option>
                      <option value="NEVER">Fixed Enterprise Allocation</option>
                    </select>
                  </div>

                  <div className="flex items-center justify-between p-3 bg-mirage-surfaceElevated rounded border border-mirage-border self-end">
                    <div>
                      <span className="block text-xs font-semibold text-mirage-text">Hard Limit</span>
                      <span className="text-[10px] text-mirage-muted">Block calls on ceiling</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setEditHardLimit(!editHardLimit)}
                      className={`w-9 h-5 flex items-center rounded-full p-0.5 transition ${
                        editHardLimit ? "bg-mirage-cyan justify-end" : "bg-mirage-border justify-start"
                      }`}
                    >
                      <span className="w-4 h-4 bg-white rounded-full shadow-sm" />
                    </button>
                  </div>
                </div>

                <div className="pt-2 flex justify-end">
                  <button
                    type="submit"
                    disabled={savingBudget}
                    className="px-5 py-2.5 bg-mirage-text text-white text-xs font-semibold rounded hover:bg-black transition shadow-sm flex items-center gap-2 disabled:opacity-50"
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
          <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-4">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-mirage-border">
              <div>
                <h3 className="text-sm font-semibold text-mirage-text flex items-center gap-2">
                  <Lock className="w-4 h-4 text-mirage-cyan" />
                  Active Distributed Concurrency Leases
                </h3>
                <p className="text-xs text-mirage-subtext mt-0.5">
                  Monotonic fencing tokens prevent split-brain and duplicate execution across mutating agent tools.
                </p>
              </div>
              <button
                type="button"
                onClick={loadLeases}
                disabled={leasesLoading}
                className="px-3 py-1.5 rounded bg-mirage-surfaceElevated hover:bg-mirage-border/50 text-mirage-text text-xs font-semibold transition flex items-center gap-1.5 self-start sm:self-auto"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${leasesLoading ? "animate-spin" : ""}`} />
                Refresh Leases
              </button>
            </div>

            {leasesError && (
              <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded flex items-center gap-2">
                <AlertCircle className="w-4 h-4 shrink-0" />
                <span>{leasesError}</span>
              </div>
            )}

            {leasesLoading ? (
              <div className="py-12 flex flex-col items-center justify-center space-y-3">
                <div className="w-8 h-8 rounded-full border-2 border-mirage-cyan/20 border-t-mirage-cyan animate-spin" />
                <span className="text-xs text-mirage-subtext">Querying Redis & PostgreSQL lease fencers...</span>
              </div>
            ) : leases.length === 0 ? (
              <div className="py-12 flex flex-col items-center justify-center rounded border border-dashed border-mirage-border p-8 text-center bg-mirage-surfaceElevated/30">
                <Unlock className="w-8 h-8 text-mirage-muted mb-2" />
                <h4 className="text-xs font-semibold text-mirage-text">No Active Resource Locks</h4>
                <p className="text-[11px] text-mirage-subtext max-w-sm mt-1">
                  All shared mutating resources are currently released. Leases are acquired dynamically during Gate 3 action execution.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-mirage-border text-mirage-subtext font-semibold uppercase text-[10px] tracking-wider">
                      <th className="pb-2.5">Lease ID</th>
                      <th className="pb-2.5">Target Resource</th>
                      <th className="pb-2.5">Fencing Token</th>
                      <th className="pb-2.5">Holder Transaction</th>
                      <th className="pb-2.5">Status</th>
                      <th className="pb-2.5">TTL / Expires</th>
                      <th className="pb-2.5 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-mirage-border">
                    {leases.map((lease) => (
                      <tr key={lease.lease_id} className="hover:bg-mirage-surfaceElevated/40 transition">
                        <td className="py-3 font-mono font-bold text-mirage-text">{lease.lease_id}</td>
                        <td className="py-3 font-mono text-mirage-subtext">{lease.resource_uri}</td>
                        <td className="py-3">
                          <span className="px-2 py-0.5 rounded font-mono font-bold bg-mirage-surfaceElevated text-mirage-cyan border border-mirage-border">
                            #{lease.fencing_token}
                          </span>
                        </td>
                        <td className="py-3 font-mono text-[11px] text-mirage-muted">
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
                        <td className="py-3 text-[11px] text-mirage-subtext font-mono">
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
          <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-4">
            <div className="pb-3 border-b border-mirage-border">
              <h3 className="text-sm font-semibold text-mirage-text flex items-center gap-2">
                <UserCheck className="w-4 h-4 text-mirage-cyan" />
                Tenant Cryptographic Identity
              </h3>
              <p className="text-xs text-mirage-subtext mt-0.5">
                Authoritative Gate 1 isolation profile and PostgreSQL Row-Level Security bound.
              </p>
            </div>

            <div className="space-y-3">
              <div className="p-3 bg-mirage-surfaceElevated rounded border border-mirage-border">
                <span className="text-[10px] uppercase font-bold text-mirage-subtext block">Tenant Identifier</span>
                <span className="font-mono text-xs font-bold text-mirage-text">{tenantId || "default_tenant"}</span>
              </div>

              <div className="p-3 bg-mirage-surfaceElevated rounded border border-mirage-border">
                <span className="text-[10px] uppercase font-bold text-mirage-subtext block">Assigned RBAC Role</span>
                <span className="text-xs font-bold text-mirage-cyan uppercase">{role || "DEVELOPER"}</span>
              </div>

              <div className="p-3 bg-mirage-surfaceElevated rounded border border-mirage-border">
                <span className="text-[10px] uppercase font-bold text-mirage-subtext block">Isolation Layer</span>
                <span className="text-xs text-mirage-text">PostgreSQL 16 Multi-Tenant RLS + Tenant Fenced Queues</span>
              </div>
            </div>
          </div>

          {/* Gate 3 Blast Radius Policy Overview */}
          <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-4">
            <div className="pb-3 border-b border-mirage-border">
              <h3 className="text-sm font-semibold text-mirage-text flex items-center gap-2">
                <Shield className="w-4 h-4 text-mirage-cyan" />
                Gate 3 Blast Radius Enforcements
              </h3>
              <p className="text-xs text-mirage-subtext mt-0.5">
                Execution boundaries applied before tool dispatch.
              </p>
            </div>

            <div className="space-y-3 text-xs">
              <div className="flex items-center justify-between p-2.5 bg-mirage-surfaceElevated rounded border border-mirage-border">
                <span className="text-mirage-subtext">Max Concurrency Lease TTL</span>
                <span className="font-mono font-bold text-mirage-text">60 seconds</span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-mirage-surfaceElevated rounded border border-mirage-border">
                <span className="text-mirage-subtext">Two-Phase Execution Lock</span>
                <span className="font-bold text-emerald-700">Enforced (EXECUTING commit)</span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-mirage-surfaceElevated rounded border border-mirage-border">
                <span className="text-mirage-subtext">Target-Side Fencing</span>
                <span className="font-bold text-mirage-text">Internal SQL Adapters</span>
              </div>
              <div className="flex items-center justify-between p-2.5 bg-mirage-surfaceElevated rounded border border-mirage-border">
                <span className="text-mirage-subtext">High-Risk Action Policy</span>
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
