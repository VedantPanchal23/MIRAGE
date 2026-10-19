import React, { useState, useEffect, useCallback, useContext } from "react";
import {
  Building,
  Key,
  ShieldAlert,
  ShieldCheck,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  RefreshCw,
  Plus,
  Trash2,
  Copy,
  Check,
  Search,
  Filter,
  Lock,
  Unlock,
  AlertCircle,
  X,
  RotateCw,
} from "lucide-react";
import {
  listTenants,
  createTenant,
  suspendTenant,
  reactivateTenant,
  offboardTenant,
} from "../api/tenants";
import {
  listApiKeys,
  createApiKey,
  rotateApiKey,
  revokeApiKey,
} from "../api/apikeys";
import { AuthContext, ROLES } from "../context/AuthContext";

/**
 * Format ISO datetime string for display.
 */
function formatDate(dateStr) {
  if (!dateStr) return "Never";
  try {
    const d = new Date(dateStr);
    return d.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

/**
 * Status badge for Tenants.
 */
function TenantStatusBadge({ status }) {
  const s = (status || "").toUpperCase();
  if (s === "ACTIVE") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-950 text-emerald-400 border border-emerald-800">
        <CheckCircle className="w-3 h-3" />
        ACTIVE
      </span>
    );
  }
  if (s === "SUSPENDED") {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-950 text-amber-400 border border-amber-800">
        <AlertTriangle className="w-3 h-3" />
        SUSPENDED
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-900 text-slate-400 border border-slate-700">
      <XCircle className="w-3 h-3" />
      {s || "OFFBOARDED"}
    </span>
  );
}

/**
 * Status badge for API Keys.
 */
function ApiKeyStatusBadge({ keyItem }) {
  if (keyItem.revoked_at) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-950 text-rose-400 border border-rose-800">
        <XCircle className="w-3 h-3" />
        Revoked
      </span>
    );
  }
  if (keyItem.expires_at && new Date(keyItem.expires_at) < new Date()) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-950 text-amber-400 border border-amber-800">
        <Clock className="w-3 h-3" />
        Expired
      </span>
    );
  }
  if (keyItem.is_active) {
    return (
      <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-950 text-emerald-400 border border-emerald-800">
        <CheckCircle className="w-3 h-3" />
        Active
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-900 text-slate-400 border border-slate-700">
      Inactive
    </span>
  );
}

/**
 * Tenants and API Keys Lifecycle Administration View.
 */
export function TenantsView({ isRefreshing, onDataLoaded }) {
  const { role, tenantId: currentTenantId } = useContext(AuthContext);
  const isSuperAdmin = role === ROLES.SUPER_ADMIN;

  const [activeSubTab, setActiveSubTab] = useState("tenants");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  // Tenants state
  const [tenants, setTenants] = useState([]);
  const [tenantStatusFilter, setTenantStatusFilter] = useState("ALL");
  const [tenantSearchQuery, setTenantSearchQuery] = useState("");

  // API Keys state
  const [apiKeys, setApiKeys] = useState([]);
  const [keySearchQuery, setKeySearchQuery] = useState("");

  // Modals state
  const [showCreateTenantModal, setShowCreateTenantModal] = useState(false);
  const [newTenantData, setNewTenantData] = useState({
    id: "",
    name: "",
    environment: "production",
    monthly_budget: 1000.0,
  });

  const [showSuspendModal, setShowSuspendModal] = useState(false);
  const [tenantToSuspend, setTenantToSuspend] = useState(null);
  const [suspensionReason, setSuspensionReason] = useState("");

  const [showOffboardModal, setShowOffboardModal] = useState(false);
  const [tenantToOffboard, setTenantToOffboard] = useState(null);
  const [offboardConfirmId, setOffboardConfirmId] = useState("");

  const [showCreateKeyModal, setShowCreateKeyModal] = useState(false);
  const [newKeyData, setNewKeyData] = useState({
    name: "",
    tenant_id: "",
    scopes: "*",
    expires_in_days: 30,
  });

  const [showRotateKeyModal, setShowRotateKeyModal] = useState(false);
  const [keyToRotate, setKeyToRotate] = useState(null);
  const [rotateImmediate, setRotateImmediate] = useState(true);
  const [rotateGracePeriod, setRotateGracePeriod] = useState(0);

  // One-time Plaintext Secret Display Modal
  // INVARIANT: This secret is held ONLY in transient state and wiped on dismissal.
  const [revealedSecretModal, setRevealedSecretModal] = useState(null); // { keyName, secret, keyPrefix }
  const [copiedSecret, setCopiedSecret] = useState(false);

  // Fetch tenants
  const fetchTenants = useCallback(async () => {
    try {
      const filter = tenantStatusFilter === "ALL" ? undefined : tenantStatusFilter;
      const res = await listTenants({ status: filter, limit: 100 });
      setTenants(res.items || []);
    } catch (err) {
      setError(`Failed to load tenants: ${err.message}`);
    }
  }, [tenantStatusFilter]);

  // Fetch API keys
  const fetchApiKeys = useCallback(async () => {
    try {
      const res = await listApiKeys({ limit: 100 });
      setApiKeys(res.items || []);
    } catch (err) {
      setError(`Failed to load API keys: ${err.message}`);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([fetchTenants(), fetchApiKeys()]);
      if (onDataLoaded) {
        onDataLoaded(new Date().toLocaleTimeString());
      }
    } finally {
      setLoading(false);
    }
  }, [fetchTenants, fetchApiKeys, onDataLoaded]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  useEffect(() => {
    if (isRefreshing) {
      refreshAll();
    }
  }, [isRefreshing, refreshAll]);

  // Copy secret to clipboard
  const handleCopySecret = async (secret) => {
    try {
      await navigator.clipboard.writeText(secret);
      setCopiedSecret(true);
      setTimeout(() => setCopiedSecret(false), 2500);
    } catch {
      // Fallback
    }
  };

  // Dismiss one-time secret modal
  const handleDismissSecret = () => {
    setRevealedSecretModal(null);
    setCopiedSecret(false);
  };

  // Tenant Handlers
  const handleCreateTenant = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      await createTenant({
        id: newTenantData.id.trim(),
        name: newTenantData.name.trim(),
        environment: newTenantData.environment,
        monthly_budget: parseFloat(newTenantData.monthly_budget) || 1000.0,
      });
      setShowCreateTenantModal(false);
      setNewTenantData({
        id: "",
        name: "",
        environment: "production",
        monthly_budget: 1000.0,
      });
      setSuccessMessage("Tenant provisioned successfully.");
      setTimeout(() => setSuccessMessage(null), 3000);
      await fetchTenants();
    } catch (err) {
      setError(`Failed to provision tenant: ${err.message}`);
    }
  };

  const handleSuspendTenant = async () => {
    if (!tenantToSuspend) return;
    setError(null);
    try {
      await suspendTenant(tenantToSuspend.id, {
        reason: suspensionReason.trim() || undefined,
      });
      setShowSuspendModal(false);
      setTenantToSuspend(null);
      setSuspensionReason("");
      setSuccessMessage("Tenant suspended.");
      setTimeout(() => setSuccessMessage(null), 3000);
      await fetchTenants();
    } catch (err) {
      setError(`Failed to suspend tenant: ${err.message}`);
    }
  };

  const handleReactivateTenant = async (t) => {
    setError(null);
    try {
      await reactivateTenant(t.id);
      setSuccessMessage("Tenant reactivated.");
      setTimeout(() => setSuccessMessage(null), 3000);
      await fetchTenants();
    } catch (err) {
      setError(`Failed to reactivate tenant: ${err.message}`);
    }
  };

  const handleOffboardTenant = async () => {
    if (!tenantToOffboard) return;
    if (offboardConfirmId !== tenantToOffboard.id) {
      setError("Confirmation ID does not match.");
      return;
    }
    setError(null);
    try {
      await offboardTenant(tenantToOffboard.id);
      setShowOffboardModal(false);
      setTenantToOffboard(null);
      setOffboardConfirmId("");
      setSuccessMessage("Tenant offboarded.");
      setTimeout(() => setSuccessMessage(null), 3000);
      await fetchTenants();
    } catch (err) {
      setError(`Failed to offboard tenant: ${err.message}`);
    }
  };

  // API Key Handlers
  const handleCreateApiKey = async (e) => {
    e.preventDefault();
    setError(null);
    try {
      const scopesArray = newKeyData.scopes
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

      const payload = {
        name: newKeyData.name.trim(),
        scopes: scopesArray.length > 0 ? scopesArray : ["*"],
        expires_in_days: newKeyData.expires_in_days ? parseInt(newKeyData.expires_in_days, 10) : null,
      };
      if (isSuperAdmin && newKeyData.tenant_id.trim()) {
        payload.tenant_id = newKeyData.tenant_id.trim();
      }

      const res = await createApiKey(payload);
      setShowCreateKeyModal(false);
      setNewKeyData({
        name: "",
        tenant_id: "",
        scopes: "*",
        expires_in_days: 30,
      });

      // Show one-time secret disclosure
      setRevealedSecretModal({
        keyName: res.name,
        keyPrefix: res.key_prefix,
        secret: res.key_secret,
      });

      await fetchApiKeys();
    } catch (err) {
      setError(`Failed to create API key: ${err.message}`);
    }
  };

  const handleRotateApiKey = async () => {
    if (!keyToRotate) return;
    setError(null);
    try {
      const res = await rotateApiKey(keyToRotate.id, {
        immediate_revocation: rotateImmediate,
        grace_period_seconds: rotateImmediate ? 0 : parseInt(rotateGracePeriod, 10) || 0,
      });
      setShowRotateKeyModal(false);
      setKeyToRotate(null);

      // Show one-time secret disclosure for new rotated key
      setRevealedSecretModal({
        keyName: res.name,
        keyPrefix: res.key_prefix,
        secret: res.key_secret,
      });

      await fetchApiKeys();
    } catch (err) {
      setError(`Failed to rotate API key: ${err.message}`);
    }
  };

  const handleRevokeApiKey = async (k) => {
    if (!window.confirm(`Revoke API key "${k.name}"? This action cannot be undone.`)) return;
    setError(null);
    try {
      await revokeApiKey(k.id);
      setSuccessMessage("API key revoked.");
      setTimeout(() => setSuccessMessage(null), 3000);
      await fetchApiKeys();
    } catch (err) {
      setError(`Failed to revoke API key: ${err.message}`);
    }
  };

  // Filtered lists
  const filteredTenants = tenants.filter((t) => {
    if (!tenantSearchQuery) return true;
    const q = tenantSearchQuery.toLowerCase();
    return (
      (t.id && t.id.toLowerCase().includes(q)) ||
      (t.name && t.name.toLowerCase().includes(q)) ||
      (t.environment && t.environment.toLowerCase().includes(q))
    );
  });

  const filteredKeys = apiKeys.filter((k) => {
    if (!keySearchQuery) return true;
    const q = keySearchQuery.toLowerCase();
    return (
      (k.name && k.name.toLowerCase().includes(q)) ||
      (k.key_prefix && k.key_prefix.toLowerCase().includes(q)) ||
      (k.tenant_id && k.tenant_id.toLowerCase().includes(q))
    );
  });

  return (
    <div className="space-y-6">
      {/* Header and Subtabs */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Building className="w-6 h-6 text-sky-400" />
            SaaS Control Plane & Security
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Manage multi-tenant lifecycle, administrative isolation boundaries, and cryptographically hashed API keys.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={refreshAll}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg bg-slate-900 border border-slate-700 hover:bg-slate-800 text-slate-200 transition-colors disabled:opacity-50"
            title="Refresh All"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin text-sky-400" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Alert Banners */}
      {error && (
        <div className="p-4 rounded-lg bg-rose-950/60 border border-rose-800/80 text-rose-200 flex items-start justify-between gap-3">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-5 h-5 text-rose-400 mt-0.5 shrink-0" />
            <div>
              <p className="font-semibold text-sm">Operation Failed</p>
              <p className="text-xs text-rose-300 mt-0.5">{error}</p>
            </div>
          </div>
          <button onClick={() => setError(null)} className="text-rose-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {successMessage && (
        <div className="p-3 rounded-lg bg-emerald-950/60 border border-emerald-800/80 text-emerald-200 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <CheckCircle className="w-4 h-4 text-emerald-400 shrink-0" />
            <span>{successMessage}</span>
          </div>
          <button onClick={() => setSuccessMessage(null)} className="text-emerald-400 hover:text-white">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Navigation Sub-Tabs */}
      <div className="flex items-center gap-2 border-b border-slate-800">
        <button
          onClick={() => setActiveSubTab("tenants")}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeSubTab === "tenants"
              ? "border-sky-500 text-sky-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Building className="w-4 h-4" />
          Tenants Directory
          <span className="ml-1 text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
            {tenants.length}
          </span>
        </button>

        <button
          onClick={() => setActiveSubTab("apikeys")}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            activeSubTab === "apikeys"
              ? "border-sky-500 text-sky-400"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Key className="w-4 h-4" />
          API Credentials
          <span className="ml-1 text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
            {apiKeys.length}
          </span>
        </button>
      </div>

      {/* ========================================================================= */}
      {/* SUBTAB 1: TENANTS LIFECYCLE */}
      {/* ========================================================================= */}
      {activeSubTab === "tenants" && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            {/* Search and Filter */}
            <div className="flex items-center gap-2 flex-1 max-w-md">
              <div className="relative flex-1">
                <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
                <input
                  type="text"
                  placeholder="Search by ID, name, environment..."
                  value={tenantSearchQuery}
                  onChange={(e) => setTenantSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                />
              </div>

              <select
                value={tenantStatusFilter}
                onChange={(e) => setTenantStatusFilter(e.target.value)}
                className="bg-slate-900 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              >
                <option value="ALL">All Statuses</option>
                <option value="ACTIVE">Active Only</option>
                <option value="SUSPENDED">Suspended</option>
                <option value="OFFBOARDED">Offboarded</option>
              </select>
            </div>

            {/* Create Tenant Action */}
            {isSuperAdmin && (
              <button
                onClick={() => setShowCreateTenantModal(true)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition-colors shrink-0"
              >
                <Plus className="w-4 h-4" />
                Provision Tenant
              </button>
            )}
          </div>

          {/* Tenants Table */}
          <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/40">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/80 text-slate-400 uppercase font-semibold border-b border-slate-800">
                <tr>
                  <th className="px-4 py-3">Tenant ID</th>
                  <th className="px-4 py-3">Name</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Environment</th>
                  <th className="px-4 py-3">Created</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {filteredTenants.length === 0 ? (
                  <tr>
                    <td colSpan="6" className="px-4 py-8 text-center text-slate-500 font-sans">
                      No tenants found matching criteria.
                    </td>
                  </tr>
                ) : (
                  filteredTenants.map((t) => (
                    <tr key={t.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 font-semibold text-white">{t.id}</td>
                      <td className="px-4 py-3 font-sans text-slate-200">{t.name}</td>
                      <td className="px-4 py-3 font-sans">
                        <TenantStatusBadge status={t.status} />
                        {t.status === "SUSPENDED" && t.suspension_reason && (
                          <span className="block text-[10px] text-amber-400/80 font-sans mt-0.5 max-w-xs truncate" title={t.suspension_reason}>
                            Reason: {t.suspension_reason}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[11px]">
                          {t.environment}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-400">{formatDate(t.created_at)}</td>
                      <td className="px-4 py-3 text-right font-sans space-x-2">
                        {isSuperAdmin && t.status === "ACTIVE" && (
                          <button
                            onClick={() => {
                              setTenantToSuspend(t);
                              setShowSuspendModal(true);
                            }}
                            className="px-2 py-1 rounded text-xs font-medium bg-amber-950/60 hover:bg-amber-900 text-amber-300 border border-amber-800 transition-colors"
                          >
                            Suspend
                          </button>
                        )}

                        {isSuperAdmin && t.status === "SUSPENDED" && (
                          <button
                            onClick={() => handleReactivateTenant(t)}
                            className="px-2 py-1 rounded text-xs font-medium bg-emerald-950/60 hover:bg-emerald-900 text-emerald-300 border border-emerald-800 transition-colors"
                          >
                            Reactivate
                          </button>
                        )}

                        {isSuperAdmin && t.status !== "OFFBOARDED" && (
                          <button
                            onClick={() => {
                              setTenantToOffboard(t);
                              setShowOffboardModal(true);
                            }}
                            className="px-2 py-1 rounded text-xs font-medium bg-rose-950/60 hover:bg-rose-900 text-rose-300 border border-rose-800 transition-colors"
                          >
                            Offboard
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* SUBTAB 2: API KEYS LIFECYCLE */}
      {/* ========================================================================= */}
      {activeSubTab === "apikeys" && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            {/* Search */}
            <div className="relative flex-1 max-w-md">
              <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
              <input
                type="text"
                placeholder="Search keys by label, prefix, tenant..."
                value={keySearchQuery}
                onChange={(e) => setKeySearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 bg-slate-900 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>

            {/* Create API Key Button */}
            <button
              onClick={() => setShowCreateKeyModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition-colors shrink-0"
            >
              <Plus className="w-4 h-4" />
              Generate API Key
            </button>
          </div>

          {/* API Keys Table */}
          <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/40">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/80 text-slate-400 uppercase font-semibold border-b border-slate-800">
                <tr>
                  <th className="px-4 py-3">Label / Name</th>
                  <th className="px-4 py-3">Key Prefix</th>
                  <th className="px-4 py-3">Tenant ID</th>
                  <th className="px-4 py-3">Scopes</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Last Used</th>
                  <th className="px-4 py-3">Expires</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60 font-mono">
                {filteredKeys.length === 0 ? (
                  <tr>
                    <td colSpan="8" className="px-4 py-8 text-center text-slate-500 font-sans">
                      No API credentials found.
                    </td>
                  </tr>
                ) : (
                  filteredKeys.map((k) => (
                    <tr key={k.id} className="hover:bg-slate-800/40 transition-colors">
                      <td className="px-4 py-3 font-sans font-medium text-white">{k.name}</td>
                      <td className="px-4 py-3 text-sky-400">
                        {k.key_prefix}...
                      </td>
                      <td className="px-4 py-3 text-slate-300">{k.tenant_id}</td>
                      <td className="px-4 py-3">
                        <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300 text-[11px]">
                          {(k.scopes || []).join(", ")}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-sans">
                        <ApiKeyStatusBadge keyItem={k} />
                      </td>
                      <td className="px-4 py-3 text-slate-400">{formatDate(k.last_used_at)}</td>
                      <td className="px-4 py-3 text-slate-400">{formatDate(k.expires_at)}</td>
                      <td className="px-4 py-3 text-right font-sans space-x-2">
                        {k.is_active && (
                          <>
                            <button
                              onClick={() => {
                                setKeyToRotate(k);
                                setRotateImmediate(true);
                                setRotateGracePeriod(0);
                                setShowRotateKeyModal(true);
                              }}
                              className="px-2 py-1 rounded text-xs font-medium bg-sky-950/60 hover:bg-sky-900 text-sky-300 border border-sky-800 transition-colors"
                              title="Rotate Key"
                            >
                              Rotate
                            </button>
                            <button
                              onClick={() => handleRevokeApiKey(k)}
                              className="px-2 py-1 rounded text-xs font-medium bg-rose-950/60 hover:bg-rose-900 text-rose-300 border border-rose-800 transition-colors"
                              title="Revoke Key"
                            >
                              Revoke
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 1: PROVISION TENANT */}
      {/* ========================================================================= */}
      {showCreateTenantModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                <Building className="w-5 h-5 text-sky-400" />
                Provision New Tenant
              </h3>
              <button
                onClick={() => setShowCreateTenantModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateTenant} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Tenant Identifier <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. acme-corp"
                  value={newTenantData.id}
                  onChange={(e) =>
                    setNewTenantData({ ...newTenantData, id: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-sky-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Organization / Workspace Name <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Acme Corporation"
                  value={newTenantData.name}
                  onChange={(e) =>
                    setNewTenantData({ ...newTenantData, name: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-sky-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Environment
                </label>
                <select
                  value={newTenantData.environment}
                  onChange={(e) =>
                    setNewTenantData({ ...newTenantData, environment: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-sky-500"
                >
                  <option value="production">Production</option>
                  <option value="staging">Staging</option>
                  <option value="development">Development</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Monthly USD Budget
                </label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={newTenantData.monthly_budget}
                  onChange={(e) =>
                    setNewTenantData({
                      ...newTenantData,
                      monthly_budget: e.target.value,
                    })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-sky-500 font-mono"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowCreateTenantModal(false)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition-colors"
                >
                  Provision
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 2: SUSPEND TENANT */}
      {/* ========================================================================= */}
      {showSuspendModal && tenantToSuspend && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="bg-slate-900 border border-amber-800/80 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-center gap-3 text-amber-400 pb-3 border-b border-slate-800">
              <AlertTriangle className="w-6 h-6 shrink-0" />
              <div>
                <h3 className="text-base font-semibold text-white">Suspend Tenant</h3>
                <p className="text-xs text-slate-400 font-mono">{tenantToSuspend.id}</p>
              </div>
            </div>

            <p className="text-xs text-slate-300 my-4">
              Suspending this tenant will immediately terminate all active sessions, block incoming API authentication calls at the database boundary, and reject background execution leases.
            </p>

            <div className="mb-4">
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Reason for Suspension (required)
              </label>
              <textarea
                rows="3"
                value={suspensionReason}
                onChange={(e) => setSuspensionReason(e.target.value)}
                placeholder="e.g., Billing delinquent / security incident investigation"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-amber-500"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowSuspendModal(false);
                  setTenantToSuspend(null);
                }}
                className="px-3 py-1.5 text-xs font-medium rounded-lg text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSuspendTenant}
                className="px-4 py-2 text-xs font-semibold rounded-lg bg-amber-600 hover:bg-amber-500 text-white transition-colors"
              >
                Confirm Suspension
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 3: OFFBOARD TENANT */}
      {/* ========================================================================= */}
      {showOffboardModal && tenantToOffboard && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="bg-slate-900 border border-rose-800/80 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-center gap-3 text-rose-400 pb-3 border-b border-slate-800">
              <ShieldAlert className="w-6 h-6 shrink-0" />
              <div>
                <h3 className="text-base font-semibold text-white">Permanent Offboarding</h3>
                <p className="text-xs text-slate-400 font-mono">{tenantToOffboard.id}</p>
              </div>
            </div>

            <p className="text-xs text-rose-300/90 my-4">
              Offboarding terminates the tenant lifecycle permanently. All credentials will be invalidated and resource allocations frozen.
            </p>

            <div className="mb-4">
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Type <span className="font-mono text-rose-400 font-semibold">{tenantToOffboard.id}</span> to confirm:
              </label>
              <input
                type="text"
                value={offboardConfirmId}
                onChange={(e) => setOffboardConfirmId(e.target.value)}
                placeholder={tenantToOffboard.id}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white focus:outline-none focus:border-rose-500 font-mono"
              />
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowOffboardModal(false);
                  setTenantToOffboard(null);
                  setOffboardConfirmId("");
                }}
                className="px-3 py-1.5 text-xs font-medium rounded-lg text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={offboardConfirmId !== tenantToOffboard.id}
                onClick={handleOffboardTenant}
                className="px-4 py-2 text-xs font-semibold rounded-lg bg-rose-600 hover:bg-rose-500 text-white transition-colors disabled:opacity-50"
              >
                Permanently Offboard
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 4: GENERATE API KEY */}
      {/* ========================================================================= */}
      {showCreateKeyModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-base font-semibold text-white flex items-center gap-2">
                <Key className="w-5 h-5 text-sky-400" />
                Generate API Key
              </h3>
              <button
                onClick={() => setShowCreateKeyModal(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateApiKey} className="space-y-4 mt-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Key Label / Name <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. CI/CD Ingestion Worker"
                  value={newKeyData.name}
                  onChange={(e) =>
                    setNewKeyData({ ...newKeyData, name: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-sky-500"
                />
              </div>

              {isSuperAdmin && (
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Target Tenant ID (leave empty for caller tenant)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. acme-corp"
                    value={newKeyData.tenant_id}
                    onChange={(e) =>
                      setNewKeyData({ ...newKeyData, tenant_id: e.target.value })
                    }
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-sky-500 font-mono"
                  />
                </div>
              )}

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Scopes (comma-separated)
                </label>
                <input
                  type="text"
                  placeholder="* or verify:read, verify:write"
                  value={newKeyData.scopes}
                  onChange={(e) =>
                    setNewKeyData({ ...newKeyData, scopes: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-sky-500 font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">
                  Validity Period (Days)
                </label>
                <input
                  type="number"
                  min="1"
                  max="365"
                  value={newKeyData.expires_in_days}
                  onChange={(e) =>
                    setNewKeyData({ ...newKeyData, expires_in_days: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-sm text-white focus:outline-none focus:border-sky-500 font-mono"
                />
              </div>

              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowCreateKeyModal(false)}
                  className="px-3 py-1.5 text-xs font-medium rounded-lg text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition-colors"
                >
                  Generate Key
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 5: ROTATE API KEY */}
      {/* ========================================================================= */}
      {showRotateKeyModal && keyToRotate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="bg-slate-900 border border-slate-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <div className="flex items-center gap-3 text-sky-400 pb-3 border-b border-slate-800">
              <RotateCw className="w-6 h-6 shrink-0" />
              <div>
                <h3 className="text-base font-semibold text-white">Rotate API Key</h3>
                <p className="text-xs text-slate-400">{keyToRotate.name} ({keyToRotate.key_prefix}...)</p>
              </div>
            </div>

            <p className="text-xs text-slate-300 my-4">
              Rotating creates a new high-entropy secret. You can invalidate the previous key immediately or configure a temporary grace period.
            </p>

            <div className="space-y-4 mb-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={rotateImmediate}
                  onChange={(e) => setRotateImmediate(e.target.checked)}
                  className="rounded bg-slate-950 border-slate-700 text-sky-600 focus:ring-0"
                />
                <span className="text-xs font-medium text-slate-200">
                  Revoke previous key immediately
                </span>
              </label>

              {!rotateImmediate && (
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">
                    Grace Period (seconds)
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="86400"
                    value={rotateGracePeriod}
                    onChange={(e) => setRotateGracePeriod(e.target.value)}
                    className="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-xs text-white font-mono focus:outline-none focus:border-sky-500"
                  />
                </div>
              )}
            </div>

            <div className="flex items-center justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => {
                  setShowRotateKeyModal(false);
                  setKeyToRotate(null);
                }}
                className="px-3 py-1.5 text-xs font-medium rounded-lg text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRotateApiKey}
                className="px-4 py-2 text-xs font-semibold rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition-colors"
              >
                Rotate Now
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 6: ONE-TIME PLAINTEXT SECRET DISCLOSURE */}
      {/* INVARIANT: Secret is cleared immediately upon dismissal */}
      {/* ========================================================================= */}
      {revealedSecretModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-4 backdrop-blur-md">
          <div className="bg-slate-900 border border-amber-500/80 rounded-xl max-w-lg w-full p-6 shadow-2xl space-y-4">
            <div className="flex items-center gap-3 text-amber-400 pb-3 border-b border-slate-800">
              <ShieldAlert className="w-6 h-6 shrink-0 text-amber-400" />
              <div>
                <h3 className="text-base font-bold text-white">Save Your API Key Secret</h3>
                <p className="text-xs text-slate-400">{revealedSecretModal.keyName}</p>
              </div>
            </div>

            <div className="p-3 rounded-lg bg-amber-950/60 border border-amber-800/80 text-amber-200 text-xs flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <span>
                <strong>Warning:</strong> This plaintext secret is displayed <strong>ONLY ONCE</strong>.
                It will NEVER be retrievable again. Store it securely in your secrets manager or environment configuration.
              </span>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-slate-400 font-medium">Plaintext API Secret</label>
              <div className="flex items-center gap-2 p-2.5 rounded-lg bg-slate-950 border border-slate-700 font-mono text-xs text-emerald-400 select-all overflow-x-auto">
                <span className="flex-1 break-all">{revealedSecretModal.secret}</span>
                <button
                  type="button"
                  onClick={() => handleCopySecret(revealedSecretModal.secret)}
                  className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 flex items-center gap-1 shrink-0 transition-colors"
                  title="Copy Key to Clipboard"
                >
                  {copiedSecret ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-400" />
                      <span className="text-[11px] text-emerald-400">Copied!</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5" />
                      <span className="text-[11px]">Copy</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            <div className="pt-3 border-t border-slate-800 flex justify-end">
              <button
                type="button"
                onClick={handleDismissSecret}
                className="px-4 py-2 text-xs font-semibold rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white transition-colors"
              >
                I have saved this key safely
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default TenantsView;
