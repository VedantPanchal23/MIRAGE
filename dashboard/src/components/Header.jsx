import React from "react";
import {
  ShieldCheck,
  RefreshCw,
  LogOut,
  LogIn,
  User,
  Building,
} from "lucide-react";

/**
 * Top Application Header displaying brand, session identity, and global actions.
 *
 * Displays non-authoritative identity information (user ID, tenant, role)
 * derived from the validated JWT for UX presentation only.
 */
export function Header({
  isAuthenticated,
  user,
  tenantId,
  role,
  onLogout,
  onOpenLogin,
  onRefresh,
  isRefreshing,
  lastRefreshed,
}) {
  const roleBadgeColors = {
    super_admin: "bg-purple-950 text-purple-400 border-purple-800",
    tenant_admin: "bg-indigo-950 text-indigo-400 border-indigo-800",
    operator: "bg-sky-950 text-sky-400 border-sky-800",
    viewer: "bg-emerald-950 text-emerald-400 border-emerald-800",
    api_client: "bg-slate-800 text-slate-300 border-slate-700",
  }[role] || "bg-slate-800 text-slate-300 border-slate-700";

  return (
    <header className="border-b border-slate-800/80 bg-slate-900/50 backdrop-blur sticky top-0 z-40 px-6 py-3.5 flex flex-wrap items-center justify-between gap-4">
      {/* Brand & Subtitle */}
      <div className="flex items-center space-x-3">
        <div className="w-8 h-8 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400 flex-shrink-0">
          <ShieldCheck className="w-5 h-5" aria-hidden="true" />
        </div>
        <div>
          <div className="flex items-center space-x-2">
            <h1 className="font-bold text-sm tracking-wide text-white">MIRAGE</h1>
            <span className="text-[10px] font-mono px-1.5 py-0.2 bg-sky-950 text-sky-400 border border-sky-800 rounded font-semibold">
              v2.1.0
            </span>
          </div>
          <p className="text-[11px] text-slate-400 hidden sm:block">
            Autonomous Hallucination Detection & Factual Consistency Verification
          </p>
        </div>
      </div>

      {/* Identity & Global Actions */}
      <div className="flex items-center space-x-3 flex-wrap">
        {isAuthenticated ? (
          <div className="flex items-center space-x-2 text-xs">
            {/* Read-only Tenant Badge */}
            {tenantId && (
              <div
                title="Authoritative Tenant Scope"
                className="flex items-center space-x-1 px-2.5 py-1 rounded-md bg-slate-800/80 border border-slate-700 text-slate-300 font-mono text-[11px]"
              >
                <Building className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
                <span>{tenantId}</span>
              </div>
            )}

            {/* User / Role Badge */}
            <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-slate-800/80 border border-slate-700 text-slate-300 text-[11px]">
              <User className="w-3.5 h-3.5 text-slate-400" aria-hidden="true" />
              <span className="font-medium">{user?.id || "user"}</span>
              {role && (
                <span className={`text-[10px] font-mono uppercase font-bold px-1.5 py-0.2 rounded border ${roleBadgeColors}`}>
                  {role.replace("_", " ")}
                </span>
              )}
            </div>

            {/* Logout Button */}
            <button
              onClick={onLogout}
              aria-label="Log out session"
              className="flex items-center space-x-1 px-2.5 py-1 text-xs text-rose-400 hover:text-rose-300 bg-rose-950/30 hover:bg-rose-950/60 border border-rose-900/50 rounded-md transition focus:outline-none focus:ring-2 focus:ring-rose-500"
            >
              <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
              <span>Logout</span>
            </button>
          </div>
        ) : (
          <button
            onClick={onOpenLogin}
            aria-label="Authenticate with access token"
            className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium text-sky-400 hover:text-sky-300 bg-sky-950/50 hover:bg-sky-950 border border-sky-800/80 rounded-lg transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <LogIn className="w-3.5 h-3.5" aria-hidden="true" />
            <span>Sign In</span>
          </button>
        )}

        {/* Global Refresh Button */}
        {onRefresh && (
          <button
            onClick={onRefresh}
            disabled={isRefreshing}
            aria-label={`Refresh data, last updated at ${lastRefreshed || "unknown"}`}
            className="flex items-center space-x-1.5 text-xs bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 px-3 py-1.5 rounded-lg border border-slate-700 transition focus:outline-none focus:ring-2 focus:ring-sky-500"
          >
            <RefreshCw
              className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin text-sky-400" : ""}`}
              aria-hidden="true"
            />
            <span className="hidden sm:inline">Refresh</span>
            {lastRefreshed && (
              <span className="text-[10px] text-slate-400 hidden md:inline">
                ({lastRefreshed})
              </span>
            )}
          </button>
        )}
      </div>
    </header>
  );
}

export default Header;
