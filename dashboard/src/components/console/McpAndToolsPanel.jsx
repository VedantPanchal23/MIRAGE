import React, { useState, useEffect } from 'react';
import { Server, ShieldAlert, Search, Wrench, AlertTriangle } from 'lucide-react';
import { api } from '../../api/client';

export function McpAndToolsPanel({ onToast = () => {} }) {
  const [servers, setServers] = useState([]);
  const [tools, setTools] = useState([]);
  const [error, setError] = useState(null);

  const [serverName, setServerName] = useState('');
  const [endpointUrl, setEndpointUrl] = useState('');

  const loadMcpAndTools = async () => {
    setError(null);
    try {
      const [srvRes, toolRes] = await Promise.all([api.listMcpServers(), api.listTools()]);
      setServers(srvRes.items || srvRes.servers || (Array.isArray(srvRes) ? srvRes : []));
      setTools(Array.isArray(toolRes) ? toolRes : toolRes.items || toolRes.tools || []);
    } catch (err) {
      setError(`Could not load MCP servers & tool registry: ${err.message}`);
    }
  };

  useEffect(() => {
    loadMcpAndTools();
  }, []);

  const handleRegisterServer = async (e) => {
    e.preventDefault();
    if (!serverName.trim() || !endpointUrl.trim()) return;
    let egressAllowlist = [];
    try {
      const parsed = new URL(endpointUrl.trim());
      if (parsed.hostname) egressAllowlist = [parsed.hostname];
    } catch (_) {}
    try {
      await api.registerMcpServer({
        name: serverName.trim(),
        transport_type: 'HTTP_STREAM',
        connection_config: { url: endpointUrl.trim() },
        egress_allowlist: egressAllowlist,
      });
      setServerName('');
      setEndpointUrl('');
      onToast('MCP server registered (pending trust approval).', 'success');
      await loadMcpAndTools();
    } catch (err) {
      onToast(`MCP server registration failed: ${err.message}`, 'violation');
    }
  };

  const handleSetTrust = async (serverId, status) => {
    try {
      await api.updateMcpTrust(serverId, status, `Operator set trust to ${status}`);
      onToast(`MCP server ${serverId} set to ${status}.`, status === 'REVOKED' ? 'violation' : 'success');
      await loadMcpAndTools();
    } catch (err) {
      onToast(`Trust update failed: ${err.message}`, 'violation');
    }
  };

  const handleDiscover = async (serverId) => {
    try {
      const res = await api.discoverMcpTools(serverId);
      onToast(`Discovered ${res.tools_registered ?? res.discovered_count ?? 0} tool(s) from server.`, 'success');
      await loadMcpAndTools();
    } catch (err) {
      onToast(`Tool discovery failed: ${err.message}`, 'violation');
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

      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-4">
          <Server className="w-4 h-4 text-slate-700" />
          <span>Governed MCP Servers</span>
        </h3>

        <form onSubmit={handleRegisterServer} className="grid grid-cols-1 sm:grid-cols-3 gap-2 mb-5">
          <label htmlFor="mcp-srv-name" className="sr-only">
            MCP Server Name
          </label>
          <input
            id="mcp-srv-name"
            type="text"
            placeholder="Server name (e.g. stripe-mcp)"
            value={serverName}
            onChange={(e) => setServerName(e.target.value)}
            className="px-3 py-2 rounded-lg border border-slate-300 text-xs text-slate-900"
          />
          <label htmlFor="mcp-srv-url" className="sr-only">
            MCP Endpoint URL
          </label>
          <input
            id="mcp-srv-url"
            type="url"
            placeholder="https://mcp.vendor.com/rpc"
            value={endpointUrl}
            onChange={(e) => setEndpointUrl(e.target.value)}
            className="px-3 py-2 rounded-lg border border-slate-300 text-xs font-mono text-slate-900"
          />
          <button
            type="submit"
            className="px-4 py-2 rounded-lg bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition-colors"
          >
            Register MCP Server
          </button>
        </form>

        <div className="space-y-3 text-xs">
          {servers.length === 0 ? (
            <p className="text-slate-500 py-4 text-center">No MCP servers registered for this tenant.</p>
          ) : (
            servers.map((srv) => (
              <div key={srv.id} className="p-4 rounded-xl border border-slate-200 bg-slate-50/60 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-bold text-slate-900">{srv.name}</div>
                  <div className="font-mono text-[11px] text-slate-600">
                    {srv.id} &bull; {srv.transport_type || srv.transport} &bull; Trust: <strong>{srv.trust_status}</strong>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => handleDiscover(srv.id)}
                    className="px-2.5 py-1.5 rounded-lg border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 text-[11px] flex items-center gap-1"
                  >
                    <Search className="w-3 h-3" />
                    <span>Discover</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSetTrust(srv.id, 'TRUSTED')}
                    className="px-2.5 py-1.5 rounded-lg bg-emerald-600 text-white hover:bg-emerald-500 text-[11px] font-semibold"
                  >
                    Approve Trust
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSetTrust(srv.id, 'REVOKED')}
                    className="px-2.5 py-1.5 rounded-lg bg-rose-600 text-white hover:bg-rose-500 text-[11px] font-semibold flex items-center gap-1"
                  >
                    <ShieldAlert className="w-3 h-3" />
                    <span>Revoke</span>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6">
        <h3 className="text-base font-bold text-slate-900 flex items-center gap-2 mb-4">
          <Wrench className="w-4 h-4 text-slate-700" />
          <span>Registered Tool Contracts ({tools.length})</span>
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
          {tools.length === 0 ? (
            <p className="text-slate-500 col-span-2 py-4 text-center">No active tools registered yet.</p>
          ) : (
            tools.map((t) => (
              <div key={t.id} className="p-3.5 rounded-xl border border-slate-200 bg-slate-50/50">
                <div className="font-bold text-slate-900 font-mono">{t.name}</div>
                <div className="text-[11px] text-slate-600 mt-1">
                  Capability: <code>{t.required_capability}</code> &bull; {t.egress_type}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
