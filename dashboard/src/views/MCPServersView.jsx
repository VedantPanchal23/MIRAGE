import React, { useState, useEffect, useCallback, useContext } from "react";
import {
  Server,
  ShieldCheck,
  AlertTriangle,
  CheckCircle,
  XCircle,
  RefreshCw,
  Plus,
  Terminal,
  Globe,
  Lock,
  Search,
  Clock,
  Layers,
  X,
  RotateCw,
} from "lucide-react";
import {
  listMCPServers,
  registerMCPServer,
  updateMCPServerTrust,
  discoverMCPTools,
} from "../api/mcp";
import { AuthContext, ROLES } from "../context/AuthContext";

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
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

export function MCPServersView() {
  const { role } = useContext(AuthContext);
  const isSuperOrTenantAdmin = role === ROLES.SUPER_ADMIN || role === ROLES.TENANT_ADMIN;

  const [servers, setServers] = useState([]);
  const [totalServers, setTotalServers] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  // Search & Filter
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");

  // Registration Modal State
  const [isRegisterOpen, setIsRegisterOpen] = useState(false);
  const [regData, setRegData] = useState({
    name: "",
    description: "",
    transport_type: "STDIO",
    command: "python",
    args: "",
    url: "",
    auth_token: "",
    permitted_capabilities: "",
    egress_allowlist: "",
    timeout_seconds: 30,
  });

  // Trust Status Transition Modal
  const [trustModal, setTrustModal] = useState({
    isOpen: false,
    server: null,
    targetStatus: "",
    reason: "",
  });

  // Discovery Result Modal
  const [discoveryModal, setDiscoveryModal] = useState({
    isOpen: false,
    server: null,
    result: null,
    loading: false,
  });

  const fetchServers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listMCPServers({ limit: 100, offset: 0 });
      setServers(res.items || []);
      setTotalServers(res.total || 0);
    } catch (err) {
      setError(err?.message || "Failed to load MCP servers");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchServers();
  }, [fetchServers]);

  const handleRegisterSubmit = async (e) => {
    e.preventDefault();
    setError(null);

    let connection_config = {};
    if (regData.transport_type === "STDIO") {
      const argsList = regData.args
        .split(",")
        .map((a) => a.trim())
        .filter(Boolean);
      connection_config = {
        command: regData.command.trim(),
        args: argsList,
      };
    } else {
      connection_config = {
        url: regData.url.trim(),
      };
      if (regData.auth_token.trim()) {
        connection_config.auth_token = regData.auth_token.trim();
      }
    }

    const permittedCaps = regData.permitted_capabilities
      .split(",")
      .map((c) => c.trim())
      .filter(Boolean);

    const egressList = regData.egress_allowlist
      .split(",")
      .map((e) => e.trim())
      .filter(Boolean);

    try {
      await registerMCPServer({
        name: regData.name.trim(),
        description: regData.description.trim(),
        transport_type: regData.transport_type,
        connection_config,
        permitted_capabilities: permittedCaps,
        egress_allowlist: egressList,
        timeout_seconds: Number(regData.timeout_seconds) || 30,
      });

      setSuccessMsg(`Server '${regData.name}' registered successfully in PENDING_APPROVAL status.`);
      setIsRegisterOpen(false);
      setRegData({
        name: "",
        description: "",
        transport_type: "STDIO",
        command: "python",
        args: "",
        url: "",
        auth_token: "",
        permitted_capabilities: "",
        egress_allowlist: "",
        timeout_seconds: 30,
      });
      await fetchServers();
    } catch (err) {
      setError(err?.message || "Registration failed");
    }
  };

  const handleTrustSubmit = async (e) => {
    e.preventDefault();
    if (!trustModal.server || !trustModal.targetStatus) return;

    try {
      await updateMCPServerTrust(trustModal.server.id, {
        trust_status: trustModal.targetStatus,
        reason: trustModal.reason || "Manual status change via dashboard operator console",
      });

      setSuccessMsg(
        `Server '${trustModal.server.name}' status transitioned to ${trustModal.targetStatus}.`
      );
      setTrustModal({ isOpen: false, server: null, targetStatus: "", reason: "" });
      await fetchServers();
    } catch (err) {
      setError(err?.message || "Trust transition failed");
    }
  };

  const handleDiscoverTools = async (server) => {
    setDiscoveryModal({
      isOpen: true,
      server,
      result: null,
      loading: true,
    });

    try {
      const res = await discoverMCPTools(server.id);
      setDiscoveryModal({
        isOpen: true,
        server,
        result: res,
        loading: false,
      });
      await fetchServers();
    } catch (err) {
      setError(err?.message || "Tool discovery failed");
      setDiscoveryModal({
        isOpen: false,
        server: null,
        result: null,
        loading: false,
      });
    }
  };

  // Filtered servers
  const filteredServers = servers.filter((srv) => {
    const matchesSearch =
      srv.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      srv.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (srv.description || "").toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === "ALL" || srv.trust_status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header Banner */}
      <div className="bg-white border border-gray-200 rounded-lg p-6 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-indigo-50 rounded-md">
              <Server className="h-6 w-6 text-indigo-600" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">Governed MCP Server Registry</h1>
              <p className="text-sm text-gray-500">
                Register external MCP servers, control execution boundaries, and synchronize tools under Gate 3 governance.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-3">
          <button
            onClick={fetchServers}
            disabled={loading}
            className="inline-flex items-center px-3 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 disabled:opacity-50"
          >
            <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          {isSuperOrTenantAdmin && (
            <button
              onClick={() => setIsRegisterOpen(true)}
              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700"
            >
              <Plus className="h-4 w-4 mr-2" />
              Register Server
            </button>
          )}
        </div>
      </div>

      {/* Notifications */}
      {error && (
        <div className="p-4 bg-red-50 border-l-4 border-red-500 rounded-r-md flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <AlertTriangle className="h-5 w-5 text-red-600" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
          <button onClick={() => setError(null)} className="text-red-500 hover:text-red-700">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {successMsg && (
        <div className="p-4 bg-green-50 border-l-4 border-green-500 rounded-r-md flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <CheckCircle className="h-5 w-5 text-green-600" />
            <p className="text-sm text-green-800">{successMsg}</p>
          </div>
          <button onClick={() => setSuccessMsg(null)} className="text-green-500 hover:text-green-700">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row gap-4 justify-between items-center bg-gray-50 p-4 rounded-lg border border-gray-200">
        <div className="relative w-full sm:w-96">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
          <input
            type="text"
            placeholder="Search servers by name, ID, or description..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-9 pr-4 py-2 text-sm border border-gray-300 rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <div className="flex items-center space-x-2 w-full sm:w-auto">
          <label className="text-xs font-medium text-gray-500">Status:</label>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-sm border border-gray-300 rounded-md py-1.5 px-3 bg-white focus:outline-none focus:ring-1 focus:ring-indigo-500"
          >
            <option value="ALL">All Statuses ({totalServers})</option>
            <option value="PENDING_APPROVAL">Pending Approval</option>
            <option value="TRUSTED">Trusted</option>
            <option value="SUSPENDED">Suspended</option>
            <option value="REVOKED">Revoked</option>
          </select>
        </div>
      </div>

      {/* Servers Table */}
      <div className="bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Server & Transport
              </th>
              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Trust Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Bound Tools
              </th>
              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Timeout
              </th>
              <th className="px-6 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Registered At
              </th>
              <th className="px-6 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider">
                Governance Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {loading && servers.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-12 text-center text-sm text-gray-500">
                  <RefreshCw className="h-6 w-6 animate-spin mx-auto text-indigo-500 mb-2" />
                  Loading MCP servers...
                </td>
              </tr>
            ) : filteredServers.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-12 text-center text-sm text-gray-500">
                  No MCP servers match the specified criteria.
                </td>
              </tr>
            ) : (
              filteredServers.map((srv) => (
                <tr key={srv.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div className="flex items-center space-x-3">
                      {srv.transport_type === "STDIO" ? (
                        <Terminal className="h-5 w-5 text-gray-500 flex-shrink-0" />
                      ) : (
                        <Globe className="h-5 w-5 text-blue-500 flex-shrink-0" />
                      )}
                      <div>
                        <div className="text-sm font-medium text-gray-900">{srv.name}</div>
                        <div className="text-xs text-gray-500 font-mono">{srv.id}</div>
                        {srv.description && (
                          <div className="text-xs text-gray-400 mt-0.5">{srv.description}</div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {srv.trust_status === "TRUSTED" && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        <CheckCircle className="h-3 w-3 mr-1" />
                        TRUSTED
                      </span>
                    )}
                    {srv.trust_status === "PENDING_APPROVAL" && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
                        <Clock className="h-3 w-3 mr-1" />
                        PENDING APPROVAL
                      </span>
                    )}
                    {srv.trust_status === "SUSPENDED" && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
                        <AlertTriangle className="h-3 w-3 mr-1" />
                        SUSPENDED
                      </span>
                    )}
                    {srv.trust_status === "REVOKED" && (
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                        <XCircle className="h-3 w-3 mr-1" />
                        REVOKED
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center space-x-1.5 text-sm text-gray-700">
                      <Layers className="h-4 w-4 text-gray-400" />
                      <span>{srv.tool_count} tools</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {srv.timeout_seconds}s
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {formatDate(srv.created_at)}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
                    {/* Discover Tools */}
                    <button
                      onClick={() => handleDiscoverTools(srv)}
                      disabled={srv.trust_status !== "TRUSTED"}
                      title={
                        srv.trust_status !== "TRUSTED"
                          ? "Server must be TRUSTED before tools can be discovered"
                          : "Synchronize remote tools"
                      }
                      className="inline-flex items-center px-2.5 py-1 text-xs font-medium rounded text-indigo-700 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <RotateCw className="h-3 w-3 mr-1" />
                      Discover Tools
                    </button>

                    {/* Trust transitions */}
                    {isSuperOrTenantAdmin && srv.trust_status === "PENDING_APPROVAL" && (
                      <button
                        onClick={() =>
                          setTrustModal({
                            isOpen: true,
                            server: srv,
                            targetStatus: "TRUSTED",
                            reason: "Approved by tenant administrator",
                          })
                        }
                        className="inline-flex items-center px-2.5 py-1 text-xs font-medium rounded text-green-700 bg-green-50 hover:bg-green-100"
                      >
                        <ShieldCheck className="h-3 w-3 mr-1" />
                        Approve
                      </button>
                    )}

                    {isSuperOrTenantAdmin && srv.trust_status === "TRUSTED" && (
                      <button
                        onClick={() =>
                          setTrustModal({
                            isOpen: true,
                            server: srv,
                            targetStatus: "SUSPENDED",
                            reason: "Operator initiated temporary suspension",
                          })
                        }
                        className="inline-flex items-center px-2.5 py-1 text-xs font-medium rounded text-orange-700 bg-orange-50 hover:bg-orange-100"
                      >
                        <Lock className="h-3 w-3 mr-1" />
                        Suspend
                      </button>
                    )}

                    {isSuperOrTenantAdmin && srv.trust_status === "SUSPENDED" && (
                      <button
                        onClick={() =>
                          setTrustModal({
                            isOpen: true,
                            server: srv,
                            targetStatus: "TRUSTED",
                            reason: "Operator unsuspended server",
                          })
                        }
                        className="inline-flex items-center px-2.5 py-1 text-xs font-medium rounded text-green-700 bg-green-50 hover:bg-green-100"
                      >
                        <ShieldCheck className="h-3 w-3 mr-1" />
                        Re-Trust
                      </button>
                    )}

                    {isSuperOrTenantAdmin && srv.trust_status !== "REVOKED" && (
                      <button
                        onClick={() =>
                          setTrustModal({
                            isOpen: true,
                            server: srv,
                            targetStatus: "REVOKED",
                            reason: "Permanent operator revocation",
                          })
                        }
                        className="inline-flex items-center px-2.5 py-1 text-xs font-medium rounded text-red-700 bg-red-50 hover:bg-red-100"
                      >
                        <XCircle className="h-3 w-3 mr-1" />
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Registration Modal */}
      {isRegisterOpen && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-black bg-opacity-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg max-w-lg w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-lg font-bold text-gray-900">Register External MCP Server</h3>
              <button
                onClick={() => setIsRegisterOpen(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleRegisterSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700">Server Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. production-database-mcp"
                  value={regData.name}
                  onChange={(e) => setRegData({ ...regData, name: e.target.value })}
                  className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700">Description</label>
                <input
                  type="text"
                  placeholder="Purpose of this external MCP server..."
                  value={regData.description}
                  onChange={(e) => setRegData({ ...regData, description: e.target.value })}
                  className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700">Transport Type</label>
                <select
                  value={regData.transport_type}
                  onChange={(e) => setRegData({ ...regData, transport_type: e.target.value })}
                  className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm bg-white focus:ring-indigo-500 focus:border-indigo-500"
                >
                  <option value="STDIO">STDIO (Local Subprocess)</option>
                  <option value="HTTP_STREAM">HTTP_STREAM (Remote SSE/Streamable HTTP)</option>
                </select>
              </div>

              {regData.transport_type === "STDIO" ? (
                <>
                  <div>
                    <label className="block text-xs font-medium text-gray-700">Command Executable *</label>
                    <input
                      type="text"
                      required
                      placeholder="e.g. python, node, /usr/bin/mcp-server"
                      value={regData.command}
                      onChange={(e) => setRegData({ ...regData, command: e.target.value })}
                      className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm font-mono focus:ring-indigo-500 focus:border-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700">Arguments (comma separated)</label>
                    <input
                      type="text"
                      placeholder="-m, my_mcp_package, --port, 8080"
                      value={regData.args}
                      onChange={(e) => setRegData({ ...regData, args: e.target.value })}
                      className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm font-mono focus:ring-indigo-500 focus:border-indigo-500"
                    />
                  </div>
                </>
              ) : (
                <>
                  <div>
                    <label className="block text-xs font-medium text-gray-700">Remote Server URL *</label>
                    <input
                      type="url"
                      required
                      placeholder="https://mcp.external-service.com/rpc"
                      value={regData.url}
                      onChange={(e) => setRegData({ ...regData, url: e.target.value })}
                      className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm font-mono focus:ring-indigo-500 focus:border-indigo-500"
                    />
                    <p className="text-xs text-gray-400 mt-1">
                      Private subnets, loopbacks, and cloud metadata (169.254.169.254) are strictly blocked.
                    </p>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700">Bearer Auth Token (Optional)</label>
                    <input
                      type="password"
                      placeholder="Remote authentication token"
                      value={regData.auth_token}
                      onChange={(e) => setRegData({ ...regData, auth_token: e.target.value })}
                      className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                    />
                  </div>
                </>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700">Permitted Capabilities</label>
                  <input
                    type="text"
                    placeholder="db:read, db:write"
                    value={regData.permitted_capabilities}
                    onChange={(e) => setRegData({ ...regData, permitted_capabilities: e.target.value })}
                    className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700">Timeout (Seconds)</label>
                  <input
                    type="number"
                    min="1"
                    max="300"
                    value={regData.timeout_seconds}
                    onChange={(e) => setRegData({ ...regData, timeout_seconds: e.target.value })}
                    className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-700">Egress Allowlist (Optional)</label>
                <input
                  type="text"
                  placeholder="api.external.com, *.trusted.org"
                  value={regData.egress_allowlist}
                  onChange={(e) => setRegData({ ...regData, egress_allowlist: e.target.value })}
                  className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>

              <div className="pt-3 flex justify-end space-x-3 border-t">
                <button
                  type="button"
                  onClick={() => setIsRegisterOpen(false)}
                  className="px-4 py-2 border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-indigo-600 border border-transparent rounded-md text-sm font-medium text-white hover:bg-indigo-700 shadow-sm"
                >
                  Submit Registration
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Trust Status Transition Modal */}
      {trustModal.isOpen && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-black bg-opacity-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg max-w-md w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b pb-3">
              <h3 className="text-lg font-bold text-gray-900">
                Transition Server Trust to {trustModal.targetStatus}
              </h3>
              <button
                onClick={() => setTrustModal({ isOpen: false, server: null, targetStatus: "", reason: "" })}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <p className="text-sm text-gray-600">
              Are you sure you want to transition server{" "}
              <strong className="text-gray-900">{trustModal.server?.name}</strong> to{" "}
              <strong className="text-indigo-600">{trustModal.targetStatus}</strong>?
            </p>

            {trustModal.targetStatus === "REVOKED" && (
              <div className="p-3 bg-red-50 border border-red-200 rounded text-xs text-red-700">
                <strong>Warning:</strong> Revocation is permanent. All bound tools will be immediately deactivated and cannot be un-revoked.
              </div>
            )}

            {trustModal.targetStatus === "SUSPENDED" && (
              <div className="p-3 bg-orange-50 border border-orange-200 rounded text-xs text-orange-700">
                <strong>Notice:</strong> All tools provided by this server will be immediately marked inactive until re-trusted.
              </div>
            )}

            <form onSubmit={handleTrustSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700">Audit Justification *</label>
                <textarea
                  required
                  rows={3}
                  placeholder="Enter explicit operational rationale for this trust transition..."
                  value={trustModal.reason}
                  onChange={(e) => setTrustModal({ ...trustModal, reason: e.target.value })}
                  className="mt-1 w-full border border-gray-300 rounded-md p-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                />
              </div>

              <div className="pt-3 flex justify-end space-x-3 border-t">
                <button
                  type="button"
                  onClick={() => setTrustModal({ isOpen: false, server: null, targetStatus: "", reason: "" })}
                  className="px-4 py-2 border border-gray-300 rounded-md text-sm text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className={`px-4 py-2 border border-transparent rounded-md text-sm font-medium text-white shadow-sm ${
                    trustModal.targetStatus === "REVOKED"
                      ? "bg-red-600 hover:bg-red-700"
                      : "bg-indigo-600 hover:bg-indigo-700"
                  }`}
                >
                  Confirm Transition
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Discovery Result Modal */}
      {discoveryModal.isOpen && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-black bg-opacity-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg max-w-2xl w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b pb-3">
              <div>
                <h3 className="text-lg font-bold text-gray-900">
                  Tool Discovery: {discoveryModal.server?.name}
                </h3>
                <p className="text-xs text-gray-500">
                  Synchronized and registered remote tools in Gate 3 Tool Registry
                </p>
              </div>
              <button
                onClick={() =>
                  setDiscoveryModal({ isOpen: false, server: null, result: null, loading: false })
                }
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {discoveryModal.loading ? (
              <div className="py-12 text-center text-sm text-gray-500">
                <RefreshCw className="h-8 w-8 animate-spin mx-auto text-indigo-500 mb-2" />
                Querying tools/list from remote MCP server...
              </div>
            ) : discoveryModal.result ? (
              <div className="space-y-4">
                <div className="flex justify-between items-center p-3 bg-indigo-50 rounded-md border border-indigo-100 text-sm">
                  <span className="text-indigo-900 font-medium">
                    Total Discovered: {discoveryModal.result.tools_discovered?.length || 0}
                  </span>
                  <span className="text-indigo-900 font-medium">
                    New Registered: {discoveryModal.result.tools_registered || 0}
                  </span>
                </div>

                <div className="max-h-96 overflow-y-auto space-y-3">
                  {(discoveryModal.result.tools_discovered || []).map((t, idx) => (
                    <div key={idx} className="p-3 border rounded-md bg-gray-50 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-semibold font-mono text-gray-900">
                          {t.namespaced_name}
                        </span>
                        <span className="px-2 py-0.5 rounded text-xs bg-gray-200 text-gray-800 font-mono">
                          {t.required_capability}
                        </span>
                      </div>
                      {t.description && <p className="text-xs text-gray-600">{t.description}</p>}
                      <div className="text-[11px] text-gray-400 font-mono">
                        Fingerprint: {t.schema_fingerprint}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="pt-3 flex justify-end border-t">
                  <button
                    onClick={() =>
                      setDiscoveryModal({ isOpen: false, server: null, result: null, loading: false })
                    }
                    className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700"
                  >
                    Close
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-500">No tools found.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default MCPServersView;
