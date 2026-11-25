import React, { useState, useEffect } from 'react';
import { Key, UserPlus, RefreshCw, Ban, Copy, Check, AlertTriangle } from 'lucide-react';
import { api } from '../../api/client';

export function AccessAndKeysPanel({ onToast = () => {} }) {
  const [keys, setKeys] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [newKeyName, setNewKeyName] = useState('');
  const [createdSecret, setCreatedSecret] = useState(null);
  const [copiedSecret, setCopiedSecret] = useState(false);

  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteName, setInviteName] = useState('');
  const [inviteRole, setInviteRole] = useState('operator');

  const loadAccess = async () => {
    setLoading(true);
    setError(null);
    try {
      const [keyRes, userRes] = await Promise.all([api.listApiKeys(), api.listTeamUsers()]);
      setKeys(keyRes.keys || []);
      setUsers(userRes.users || []);
    } catch (err) {
      setError(`Could not load API keys and team access: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAccess();
  }, []);

  const handleCreateKey = async (e) => {
    e.preventDefault();
    if (!newKeyName.trim()) return;
    try {
      const created = await api.createApiKey({ name: newKeyName.trim() });
      const secret = created.raw_key || created.key_secret || created.api_key;
      const keyLabel = created.key_metadata?.name || created.name || newKeyName.trim();
      setCreatedSecret(secret);
      setNewKeyName('');
      onToast(`API key '${keyLabel}' provisioned.`, 'success');
      await loadAccess();
    } catch (err) {
      onToast(`Failed creating API key: ${err.message}`, 'violation');
    }
  };

  const handleRevokeKey = async (keyId) => {
    try {
      await api.revokeApiKey(keyId);
      onToast(`API key ${keyId} revoked immediately.`, 'violation');
      await loadAccess();
    } catch (err) {
      onToast(`Failed revoking API key: ${err.message}`, 'violation');
    }
  };

  const handleRotateKey = async (keyId) => {
    try {
      const rotated = await api.rotateApiKey(keyId);
      const secret = rotated.raw_key || rotated.key_secret || rotated.api_key;
      setCreatedSecret(secret);
      onToast(`Key rotated. Copy the new credential now.`, 'success');
      await loadAccess();
    } catch (err) {
      onToast(`Key rotation failed: ${err.message}`, 'violation');
    }
  };

  const handleProvisionUser = async (e) => {
    e.preventDefault();
    if (!inviteEmail.trim() || !inviteName.trim()) return;
    try {
      const created = await api.createTeamUser({
        email: inviteEmail.trim(),
        displayName: inviteName.trim(),
        role: inviteRole,
      });
      setCreatedSecret(created.api_key);
      setInviteEmail('');
      setInviteName('');
      onToast(`Provisioned ${created.external_subject} (${created.role}).`, 'success');
      await loadAccess();
    } catch (err) {
      onToast(`Failed provisioning user: ${err.message}`, 'violation');
    }
  };

  return (
    <div className="space-y-6">
      {error && (
        <div role="alert" className="p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {createdSecret && (
        <div role="status" className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-900 text-xs">
          <div className="font-bold mb-1">One-Time Plaintext Credential (store securely now):</div>
          <div className="flex items-center justify-between gap-2 bg-white border border-emerald-300 rounded-lg p-2.5 font-mono">
            <span className="break-all select-all">{createdSecret}</span>
            <button
              type="button"
              onClick={() => {
                navigator.clipboard?.writeText(createdSecret);
                setCopiedSecret(true);
                setTimeout(() => setCopiedSecret(false), 2000);
              }}
              aria-label="Copy plaintext API secret"
              className="px-2.5 py-1 rounded bg-slate-900 text-white text-[11px] flex items-center gap-1 shrink-0"
            >
              {copiedSecret ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copiedSecret ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
              <Key className="w-4 h-4 text-slate-700" />
              <span>Tenant API Keys</span>
            </h3>
            <button
              type="button"
              onClick={loadAccess}
              className="text-xs text-slate-600 hover:text-slate-900 flex items-center gap-1"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
          </div>

          <form onSubmit={handleCreateKey} className="flex gap-2 mb-4">
            <label htmlFor="new-api-key-name" className="sr-only">
              API Key Name
            </label>
            <input
              id="new-api-key-name"
              type="text"
              placeholder="e.g. production-langchain-worker"
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              className="flex-1 px-3 py-2 rounded-lg border border-slate-300 text-xs text-slate-900"
            />
            <button
              type="submit"
              className="px-3.5 py-2 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition-colors"
            >
              Create Key
            </button>
          </form>

          <div className="space-y-2.5 text-xs">
            {keys.length === 0 ? (
              <p className="text-slate-500 py-4 text-center">No active API keys listed for this view.</p>
            ) : (
              keys.map((k) => {
                const isKeyActive = k.is_active ?? k.active ?? false;
                return (
                <div key={k.id} className="p-3 rounded-xl border border-slate-200 bg-slate-50/60 flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-semibold text-slate-900 truncate">{k.name}</div>
                    <div className="font-mono text-[11px] text-slate-600">
                      {k.key_prefix}*** &bull; {isKeyActive ? 'ACTIVE' : 'REVOKED'}
                    </div>
                  </div>
                  {isKeyActive && (
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        type="button"
                        onClick={() => handleRotateKey(k.id)}
                        className="px-2.5 py-1 rounded border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 text-[11px]"
                      >
                        Rotate
                      </button>
                      <button
                        type="button"
                        onClick={() => handleRevokeKey(k.id)}
                        className="px-2.5 py-1 rounded border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100 text-[11px] flex items-center gap-1"
                      >
                        <Ban className="w-3 h-3" />
                        <span>Revoke</span>
                      </button>
                    </div>
                  )}
                </div>
                );
              })
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-4">
            <UserPlus className="w-4 h-4 text-slate-700" />
            <span>Team Members &amp; RBAC</span>
          </h3>

          <form onSubmit={handleProvisionUser} className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-4">
            <label htmlFor="team-invite-name" className="sr-only">
              Display Name
            </label>
            <input
              id="team-invite-name"
              type="text"
              placeholder="Full Name"
              value={inviteName}
              onChange={(e) => setInviteName(e.target.value)}
              className="px-3 py-2 rounded-lg border border-slate-300 text-xs text-slate-900"
            />
            <label htmlFor="team-invite-email" className="sr-only">
              Work Email
            </label>
            <input
              id="team-invite-email"
              type="email"
              placeholder="teammate@company.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              className="px-3 py-2 rounded-lg border border-slate-300 text-xs text-slate-900"
            />
            <div className="flex gap-2">
              <label htmlFor="team-invite-role" className="sr-only">
                RBAC Role
              </label>
              <select
                id="team-invite-role"
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="flex-1 px-2.5 py-2 rounded-lg border border-slate-300 text-xs text-slate-900 bg-white"
              >
                <option value="operator">Operator</option>
                <option value="viewer">Auditor / Viewer (Read-Only)</option>
                <option value="tenant_admin">Tenant Admin</option>
                <option value="api_client">Service API Client</option>
              </select>
              <button
                type="submit"
                className="px-3 py-2 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition-colors"
              >
                Provision
              </button>
            </div>
          </form>

          <div className="space-y-2.5 text-xs">
            {users.length === 0 ? (
              <p className="text-slate-500 py-4 text-center">No provisioned team members found.</p>
            ) : (
              users.map((u) => (
                <div key={u.id} className="p-3 rounded-xl border border-slate-200 bg-slate-50/60 flex items-center justify-between gap-2">
                  <div>
                    <div className="font-semibold text-slate-900">{u.display_name}</div>
                    <div className="font-mono text-[11px] text-slate-600">{u.external_subject}</div>
                  </div>
                  <span className="px-2 py-0.5 rounded bg-white border border-slate-200 font-mono text-[11px] font-semibold text-slate-800 uppercase">
                    {u.role}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
