import React from "react";
import { ShieldAlert } from "lucide-react";

/**
 * AccessDenied component displayed when a user lacks the UX permission to view an area.
 *
 * SECURITY NOTE:
 * This component is for UX gating only. The backend API is the sole authority
 * enforcing authorization and tenant isolation on all requests.
 */
export function AccessDenied({
  title = "Access Denied",
  requiredPermission,
  userRole,
}) {
  return (
    <section
      role="alert"
      aria-labelledby="access-denied-heading"
      className="bg-slate-900 border border-rose-900/60 rounded-xl p-8 max-w-xl mx-auto my-12 text-center shadow-xl"
    >
      <div className="w-12 h-12 rounded-full bg-rose-500/10 border border-rose-500/30 flex items-center justify-center mx-auto text-rose-400 mb-4">
        <ShieldAlert className="w-6 h-6" aria-hidden="true" />
      </div>
      <h2 id="access-denied-heading" className="text-lg font-bold text-white mb-2">
        {title}
      </h2>
      <p className="text-sm text-slate-300 leading-relaxed mb-4">
        Your authenticated role <span className="font-mono text-rose-300 font-semibold">{userRole || "unknown"}</span> lacks the
        required UX permission {requiredPermission && <span className="font-mono text-rose-300 font-semibold">({requiredPermission})</span>} to
        inspect this area.
      </p>
      <div className="text-xs text-slate-400 bg-slate-950/80 border border-slate-800 rounded-lg p-3">
        Client-side role gating is for interface presentation only. All API requests are strictly
        and authoritatively validated by the MIRAGE Gateway RBAC engine.
      </div>
    </section>
  );
}

export default AccessDenied;
