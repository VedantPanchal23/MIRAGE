import React, { useState, useEffect } from "react";
import {
  Code2,
  Key,
  Copy,
  Check,
  Trash2,
  Plus,
  Terminal,
  FileCode,
  Shield,
  Layers,
  AlertTriangle,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export function DeveloperConsoleView() {
  const { tenantId } = useAuth();
  const [keys, setKeys] = useState([]);
  const [loading, setLoading] = useState(true);

  // New Key Form State
  const [keyName, setKeyName] = useState("");
  const [keyRole, setKeyRole] = useState("admin");
  const [newlyCreatedKey, setNewlyCreatedKey] = useState(null);
  const [isCreatingKey, setIsCreatingKey] = useState(false);
  const [copiedSnippet, setCopiedSnippet] = useState(null);

  // Active Code Snippet Tab
  const [activeSnippetTab, setActiveSnippetTab] = useState("openai");
  const [createKeyError, setCreateKeyError] = useState(null);

  const loadKeys = async () => {
    try {
      const res = await api.getApiKeys();
      if (res && Array.isArray(res.keys) && res.keys.length > 0) {
        setKeys(res.keys);
      } else {
        setKeys([]);
      }
    } catch {
      setKeys([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadKeys();
  }, [tenantId]);

  const handleCreateKey = async (e) => {
    e.preventDefault();
    if (!keyName.trim()) return;
    setIsCreatingKey(true);
    setCreateKeyError(null);

    try {
      const res = await api.createApiKey(keyName.trim(), "", keyRole);
      if (res && res.plaintext_key) {
        setNewlyCreatedKey(res.plaintext_key);
        await loadKeys();
        setKeyName("");
      } else {
        throw new Error("Key created, but token was not returned.");
      }
    } catch (err) {
      setCreateKeyError(err.message || "Failed to create API key in database.");
    } finally {
      setIsCreatingKey(false);
    }
  };

  const handleRevokeKey = async (keyId) => {
    try {
      await api.revokeApiKey(keyId);
      setKeys((prev) => prev.filter((k) => k.id !== keyId));
    } catch (err) {
      setCreateKeyError(err.message || "Failed to revoke API key in database.");
    }
  };

  const copyToClipboard = (text, id) => {
    navigator.clipboard.writeText(text);
    setCopiedSnippet(id);
    setTimeout(() => setCopiedSnippet(null), 2000);
  };

  const snippets = {
    openai: `# Python: OpenAI SDK Drop-in Proxy
from openai import OpenAI

# Simply point base_url to MIRAGE. Every completion traverses the 5 Gates.
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your_mirage_api_key_here",
    default_headers={"X-Tenant-ID": "${tenantId}"}
)

response = client.chat.completions.create(
    model="allam-2-7b",
    messages=[
        {"role": "system", "content": "You are a governed enterprise assistant."},
        {"role": "user", "content": "Execute vendor disbursement #INV-992"}
    ]
)
print("Assured Output:", response.choices[0].message.content)`,

    curl: `# cURL: Direct Verification Endpoint
curl -X POST http://localhost:8000/v1/verify \\
  -H "Content-Type: application/json" \\
  -H "X-Tenant-ID: ${tenantId}" \\
  -H "Authorization: Bearer your_mirage_api_key_here" \\
  -d '{
    "prompt": "Recommended pediatric loading dose of amoxicillin?",
    "response": "The standard dose is 80 to 90 mg/kg/day divided Q12H.",
    "model_id": "meta-llama/llama-3.3-70b-instruct",
    "auto_correct": true
  }'`,

    mcp: `// Cursor & Claude Desktop Governed MCP Server Configuration
// Add this block to your claude_desktop_config.json:
{
  "mcpServers": {
    "mirage-governed-tools": {
      "command": "python",
      "args": ["-m", "mcp_server.main"],
      "env": {
        "MIRAGE_GATEWAY_URL": "http://localhost:8000",
        "MIRAGE_TENANT_ID": "${tenantId}",
        "MIRAGE_API_KEY": "your_mirage_api_key_here"
      }
    }
  }
}`,
  };

  return (
    <div className="space-y-8 pb-12">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-apple-text">
          Developer Console & Integrations
        </h1>
        <p className="text-apple-secondary text-sm mt-1">
          Issue high-entropy API credentials, manage lifecycle revocation, and connect your LLM agents via drop-in OpenAI proxies or governed MCP servers.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: API Keys Provisioning */}
        <div className="lg:col-span-5 space-y-4">
          <div className="bg-apple-surface rounded-3xl p-6 border border-apple-border shadow-apple-card space-y-4">
            <div className="flex items-center space-x-2 pb-3 border-b border-apple-border">
              <Key className="w-4 h-4 text-apple-blue" />
              <h3 className="font-semibold text-sm text-apple-text">Provision API Key</h3>
            </div>

            <form onSubmit={handleCreateKey} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-apple-text mb-1">
                  Key Description / Agent Name
                </label>
                <input
                  type="text"
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                  placeholder="e.g. Production Billing Agent"
                  className="w-full text-xs p-2.5 rounded-xl bg-apple-subtle border border-apple-border focus:outline-none focus:border-apple-blue font-sans"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-apple-text mb-1">
                  Role Assignment
                </label>
                <select
                  value={keyRole}
                  onChange={(e) => setKeyRole(e.target.value)}
                  className="w-full text-xs p-2.5 rounded-xl bg-apple-subtle border border-apple-border focus:outline-none focus:border-apple-blue font-sans"
                >
                  <option value="admin">Admin (Full 5 Gates + Governance)</option>
                  <option value="operator">Operator (Inspection & Approvals)</option>
                  <option value="user">User (Verification Execution Only)</option>
                </select>
              </div>

              <button
                type="submit"
                disabled={isCreatingKey || !keyName.trim()}
                className="w-full py-2.5 rounded-xl bg-apple-blue hover:bg-apple-blueHover text-white text-xs font-semibold shadow-apple-sm transition disabled:opacity-50"
              >
                {isCreatingKey ? "Generating SHA-256 Key..." : "Generate API Key"}
              </button>
            </form>

            {createKeyError && (
              <div className="p-3 rounded-xl bg-apple-red/10 border border-apple-red/20 text-xs text-apple-red flex items-center space-x-2">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{createKeyError}</span>
              </div>
            )}

            {newlyCreatedKey && (
              <div className="p-4 rounded-2xl bg-apple-green/10 border border-apple-green/20 space-y-2">
                <div className="flex items-center justify-between text-xs font-semibold text-apple-green">
                  <span>Secret Key Generated</span>
                  <span className="text-[10px] text-apple-secondary">Shown once only</span>
                </div>
                <div className="flex items-center space-x-2">
                  <input
                    type="text"
                    readOnly
                    value={newlyCreatedKey}
                    className="w-full text-xs font-mono p-2 bg-white rounded-lg border border-apple-green/30 text-apple-text select-all"
                  />
                  <button
                    type="button"
                    onClick={() => copyToClipboard(newlyCreatedKey, "secret")}
                    className="p-2 rounded-lg bg-white border border-apple-green/30 text-apple-text hover:bg-apple-subtle transition"
                  >
                    {copiedSnippet === "secret" ? (
                      <Check className="w-4 h-4 text-apple-green" />
                    ) : (
                      <Copy className="w-4 h-4" />
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Active Keys List */}
          <div className="space-y-2.5">
            <span className="text-xs font-semibold text-apple-secondary uppercase tracking-wider px-1">
              Active Credentials ({keys.length})
            </span>
            {keys.length === 0 ? (
              <div className="bg-apple-surface rounded-2xl p-6 border border-apple-border text-center">
                <Key className="w-8 h-8 text-apple-secondary mx-auto mb-2 opacity-60" />
                <h4 className="text-xs font-semibold text-apple-text">No API Keys Provisioned</h4>
                <p className="text-[11px] text-apple-secondary mt-1 max-w-xs mx-auto">
                  Generate an API key above to authenticate AI agents and SDK requests.
                </p>
              </div>
            ) : (
              keys.map((k) => (
                <div
                  key={k.id}
                  className="p-3.5 rounded-2xl bg-apple-surface border border-apple-border shadow-apple-sm flex items-center justify-between hover:shadow-apple-card transition"
                >
                  <div>
                    <div className="text-xs font-semibold text-apple-text">{k.name}</div>
                    <div className="text-[11px] font-mono text-apple-secondary mt-0.5">
                      {k.key_prefix || k.id}
                    </div>
                    <div className="text-[10px] text-apple-muted mt-1">
                      Role: <span className="font-semibold uppercase">{k.role}</span>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleRevokeKey(k.id)}
                    title="Instantly revoke API key"
                    className="p-2 rounded-xl text-apple-muted hover:text-apple-red hover:bg-apple-red/10 transition"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Right Column: Copyable Integration Snippets */}
        <div className="lg:col-span-7 bg-apple-surface rounded-3xl p-6 border border-apple-border shadow-apple-card space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-apple-border">
            <div className="flex items-center space-x-2">
              <Code2 className="w-4 h-4 text-apple-blue" />
              <h3 className="font-semibold text-sm text-apple-text">Integration Code Samples</h3>
            </div>

            <div className="flex space-x-1 p-1 bg-apple-subtle rounded-xl border border-apple-border">
              <button
                type="button"
                onClick={() => setActiveSnippetTab("openai")}
                className={`px-3 py-1 text-xs font-medium rounded-lg transition ${
                  activeSnippetTab === "openai"
                    ? "bg-white text-apple-text shadow-apple-sm"
                    : "text-apple-secondary hover:text-apple-text"
                }`}
              >
                OpenAI Proxy
              </button>
              <button
                type="button"
                onClick={() => setActiveSnippetTab("curl")}
                className={`px-3 py-1 text-xs font-medium rounded-lg transition ${
                  activeSnippetTab === "curl"
                    ? "bg-white text-apple-text shadow-apple-sm"
                    : "text-apple-secondary hover:text-apple-text"
                }`}
              >
                cURL
              </button>
              <button
                type="button"
                onClick={() => setActiveSnippetTab("mcp")}
                className={`px-3 py-1 text-xs font-medium rounded-lg transition ${
                  activeSnippetTab === "mcp"
                    ? "bg-white text-apple-text shadow-apple-sm"
                    : "text-apple-secondary hover:text-apple-text"
                }`}
              >
                Cursor / Claude MCP
              </button>
            </div>
          </div>

          <div className="relative">
            <pre className="p-4 rounded-2xl bg-apple-subtle/80 border border-apple-border text-xs font-mono text-apple-text overflow-x-auto leading-relaxed">
              {snippets[activeSnippetTab]}
            </pre>

            <button
              type="button"
              onClick={() => copyToClipboard(snippets[activeSnippetTab], activeSnippetTab)}
              className="absolute top-3 right-3 p-2 rounded-xl bg-white/90 backdrop-blur-sm border border-apple-border text-apple-secondary hover:text-apple-text shadow-apple-sm transition"
            >
              {copiedSnippet === activeSnippetTab ? (
                <div className="flex items-center space-x-1 text-apple-green text-[11px] font-sans font-medium">
                  <Check className="w-3.5 h-3.5" />
                  <span>Copied</span>
                </div>
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
            </button>
          </div>

          <div className="p-4 rounded-2xl bg-apple-subtle/40 border border-apple-border/70 text-xs text-apple-secondary space-y-1">
            <div className="font-semibold text-apple-text">Deterministic Tenant Attribution:</div>
            <p>
              Always pass the <code className="font-mono text-apple-blue font-bold">X-Tenant-ID</code> header with every request. MIRAGE enforces strict tenant binding to prevent IDOR and cross-tenant privilege escalation.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
