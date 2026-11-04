import React, { useState, useEffect } from "react";
import {
  Code2,
  Key,
  Copy,
  Check,
  Trash2,
  Send,
  Bell,
  Globe,
  Radio,
  Plus,
  Shield,
  Layers,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export function DeveloperConsoleView() {
  const { tenantId } = useAuth();
  const [activeSection, setActiveSection] = useState("keys"); // "keys" | "webhooks" | "code"

  // --------------------------------------------------------------------------
  // API Keys State
  // --------------------------------------------------------------------------
  const [keys, setKeys] = useState([]);
  const [loadingKeys, setLoadingKeys] = useState(true);
  const [keyName, setKeyName] = useState("");
  const [keyRole, setKeyRole] = useState("admin");
  const [newlyCreatedKey, setNewlyCreatedKey] = useState(null);
  const [isCreatingKey, setIsCreatingKey] = useState(false);
  const [createKeyError, setCreateKeyError] = useState(null);

  // --------------------------------------------------------------------------
  // Webhooks State
  // --------------------------------------------------------------------------
  const [webhooks, setWebhooks] = useState([]);
  const [loadingWebhooks, setLoadingWebhooks] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [webhookDesc, setWebhookDesc] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [selectedEvents, setSelectedEvents] = useState([
    "ACTION_AWAITING_APPROVAL",
    "ACTION_BLOCKED",
    "OUTCOME_DISCREPANCY",
    "AUDIT_ALERT",
  ]);
  const [isCreatingWebhook, setIsCreatingWebhook] = useState(false);
  const [webhookError, setWebhookError] = useState(null);
  const [webhookSuccess, setWebhookSuccess] = useState(null);
  const [testingWebhookId, setTestingWebhookId] = useState(null);

  // --------------------------------------------------------------------------
  // Code Snippets State
  // --------------------------------------------------------------------------
  const [activeSnippetTab, setActiveSnippetTab] = useState("openai");
  const [copiedSnippet, setCopiedSnippet] = useState(null);

  const availableEvents = [
    { id: "ACTION_AWAITING_APPROVAL", label: "Gate 3: HITL Quorum Required", desc: "Fires when L4 action triggers human-in-the-loop review" },
    { id: "ACTION_BLOCKED", label: "Gate 3: Action Blocked", desc: "Fires when capability or blast-radius limits deny execution" },
    { id: "ACTION_COMPLETED", label: "Gate 3: Action Executed", desc: "Fires upon successful tool proxy dispatch" },
    { id: "OUTCOME_DISCREPANCY", label: "Gate 5: Reality Discrepancy", desc: "Fires when physical state diverges from model postconditions" },
    { id: "AUDIT_ALERT", label: "Gate 5: Audit & Security Alert", desc: "Fires on Merkle hash verification anomalies or system pings" },
  ];

  const loadKeys = async () => {
    try {
      const res = await api.getApiKeys();
      if (res && Array.isArray(res.keys)) {
        setKeys(res.keys);
      } else {
        setKeys([]);
      }
    } catch {
      setKeys([]);
    } finally {
      setLoadingKeys(false);
    }
  };

  const loadWebhooks = async () => {
    setLoadingWebhooks(true);
    try {
      const res = await api.listWebhooks();
      if (res && Array.isArray(res.webhooks)) {
        setWebhooks(res.webhooks);
      } else {
        setWebhooks([]);
      }
    } catch {
      setWebhooks([]);
    } finally {
      setLoadingWebhooks(false);
    }
  };

  useEffect(() => {
    loadKeys();
    loadWebhooks();
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
        throw new Error("Key created, but plaintext token was not returned.");
      }
    } catch (err) {
      setCreateKeyError(err.message || "Failed to create API key.");
    } finally {
      setIsCreatingKey(false);
    }
  };

  const handleRevokeKey = async (keyId) => {
    try {
      await api.revokeApiKey(keyId);
      setKeys((prev) => prev.filter((k) => k.id !== keyId));
    } catch (err) {
      setCreateKeyError(err.message || "Failed to revoke API key.");
    }
  };

  const handleToggleEvent = (eventId) => {
    setSelectedEvents((prev) =>
      prev.includes(eventId) ? prev.filter((e) => e !== eventId) : [...prev, eventId]
    );
  };

  const handleCreateWebhook = async (e) => {
    e.preventDefault();
    if (!webhookUrl.trim()) {
      setWebhookError("Target URL is required.");
      return;
    }
    if (selectedEvents.length === 0) {
      setWebhookError("Select at least one event type to subscribe.");
      return;
    }

    setIsCreatingWebhook(true);
    setWebhookError(null);
    setWebhookSuccess(null);

    try {
      const payload = {
        url: webhookUrl.trim(),
        description: webhookDesc.trim(),
        event_types: selectedEvents,
        secret: webhookSecret.trim() || undefined,
        active: true,
      };
      await api.createWebhook(payload);
      setWebhookSuccess("Webhook subscription registered successfully.");
      setWebhookUrl("");
      setWebhookDesc("");
      setWebhookSecret("");
      await loadWebhooks();
    } catch (err) {
      setWebhookError(err.message || "Failed to register webhook subscription.");
    } finally {
      setIsCreatingWebhook(false);
    }
  };

  const handleDeleteWebhook = async (webhookId) => {
    try {
      await api.deleteWebhook(webhookId);
      setWebhooks((prev) => prev.filter((w) => w.id !== webhookId));
    } catch (err) {
      setWebhookError(err.message || "Failed to delete webhook.");
    }
  };

  const handleTestWebhook = async (webhookId) => {
    setTestingWebhookId(webhookId);
    setWebhookError(null);
    setWebhookSuccess(null);
    try {
      await api.testWebhook(webhookId);
      setWebhookSuccess(`Test ping event dispatched to webhook ${webhookId}. Check endpoint logs.`);
    } catch (err) {
      setWebhookError(err.message || "Failed to dispatch test ping to webhook.");
    } finally {
      setTestingWebhookId(null);
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
    model="llama-3.3-70b-versatile",
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

    webhook_receiver: `# Python FastAPI: Verifying Outbound Webhook HMAC-SHA256 Signatures
import hmac
import hashlib
from fastapi import FastAPI, Request, HTTPException, Header

app = FastAPI()
WEBHOOK_SECRET = "your_webhook_secret_key"

@app.post("/mirage-events")
async def receive_mirage_webhook(
    request: Request,
    x_mirage_signature_256: str = Header(None),
    x_mirage_event: str = Header(None)
):
    body_bytes = await request.body()
    expected_sig = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(x_mirage_signature_256 or "", expected_sig):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")
        
    payload = await request.json()
    print(f"Verified Alert [{x_mirage_event}]:", payload)
    return {"status": "accepted"}`,
  };

  return (
    <div className="space-y-8 pb-12">
      {/* Header and Section Switcher */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-mirage-text">
            Developer Console &amp; Integrations
          </h1>
          <p className="text-mirage-subtext text-sm mt-1">
            Provision API keys, configure outbound security webhooks, and connect AI agents via drop-in proxies.
          </p>
        </div>

        {/* Section Tabs */}
        <div className="flex space-x-1 p-1 bg-mirage-surfaceElevated rounded border border-mirage-border self-start md:self-auto">
          <button
            type="button"
            onClick={() => setActiveSection("keys")}
            className={`flex items-center space-x-2 px-3.5 py-1.5 text-xs font-semibold rounded transition ${
              activeSection === "keys"
                ? "bg-white text-mirage-text shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
            }`}
          >
            <Key className="w-3.5 h-3.5" />
            <span>API Credentials</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveSection("webhooks")}
            className={`flex items-center space-x-2 px-3.5 py-1.5 text-xs font-semibold rounded transition ${
              activeSection === "webhooks"
                ? "bg-white text-mirage-text shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
            }`}
          >
            <Bell className="w-3.5 h-3.5" />
            <span>Outbound Webhooks</span>
            {webhooks.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full bg-mirage-cyan/10 text-mirage-cyan text-[10px] font-mono">
                {webhooks.length}
              </span>
            )}
          </button>
          <button
            type="button"
            onClick={() => setActiveSection("code")}
            className={`flex items-center space-x-2 px-3.5 py-1.5 text-xs font-semibold rounded transition ${
              activeSection === "code"
                ? "bg-white text-mirage-text shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
            }`}
          >
            <Code2 className="w-3.5 h-3.5" />
            <span>Quickstart SDK</span>
          </button>
        </div>
      </div>

      {/* SECTION 1: API KEYS */}
      {activeSection === "keys" && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: API Keys Provisioning */}
          <div className="lg:col-span-5 space-y-4">
            <div className="bg-mirage-surface rounded p-6 border border-mirage-border shadow-mirage-surface space-y-4">
              <div className="flex items-center space-x-2 pb-3 border-b border-mirage-border">
                <Key className="w-4 h-4 text-mirage-cyan" />
                <h3 className="font-semibold text-sm text-mirage-text">Provision New API Key</h3>
              </div>

              <form onSubmit={handleCreateKey} className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-mirage-text mb-1">
                    Key Description / Agent Name
                  </label>
                  <input
                    type="text"
                    value={keyName}
                    onChange={(e) => setKeyName(e.target.value)}
                    placeholder="e.g. Production Billing Agent"
                    className="w-full text-xs p-2.5 rounded bg-mirage-surfaceElevated border border-mirage-border focus:outline-none focus:border-mirage-cyan font-sans"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-mirage-text mb-1">
                    Role Assignment
                  </label>
                  <select
                    value={keyRole}
                    onChange={(e) => setKeyRole(e.target.value)}
                    className="w-full text-xs p-2.5 rounded bg-mirage-surfaceElevated border border-mirage-border focus:outline-none focus:border-mirage-cyan font-sans"
                  >
                    <option value="admin">Admin (Full 5 Gates + Governance)</option>
                    <option value="operator">Operator (Inspection &amp; Approvals)</option>
                    <option value="user">User (Verification Execution Only)</option>
                  </select>
                </div>

                <button
                  type="submit"
                  disabled={isCreatingKey || !keyName.trim()}
                  className="w-full py-2.5 rounded bg-mirage-cyan hover:bg-mirage-cyanHover text-white text-xs font-semibold shadow-sm transition disabled:opacity-50"
                >
                  {isCreatingKey ? "Generating SHA-256 Key..." : "Generate API Key"}
                </button>
              </form>

              {createKeyError && (
                <div className="p-3 rounded bg-mirage-crimson/10 border border-mirage-crimson/20 text-xs text-mirage-crimson flex items-center space-x-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  <span>{createKeyError}</span>
                </div>
              )}

              {newlyCreatedKey && (
                <div className="p-4 rounded bg-mirage-emerald/10 border border-mirage-emerald/20 space-y-2">
                  <div className="flex items-center justify-between text-xs font-semibold text-mirage-emerald">
                    <span>Secret Key Generated</span>
                    <span className="text-[10px] text-mirage-subtext">Shown once only</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <input
                      type="text"
                      readOnly
                      value={newlyCreatedKey}
                      className="w-full text-xs font-mono p-2 bg-white rounded-lg border border-mirage-emerald/30 text-mirage-text select-all"
                    />
                    <button
                      type="button"
                      onClick={() => copyToClipboard(newlyCreatedKey, "secret")}
                      className="p-2 rounded-lg bg-white border border-mirage-emerald/30 text-mirage-text hover:bg-mirage-surfaceElevated transition"
                    >
                      {copiedSnippet === "secret" ? (
                        <Check className="w-4 h-4 text-mirage-emerald" />
                      ) : (
                        <Copy className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Right Column: Active Keys List */}
          <div className="lg:col-span-7 space-y-4">
            <div className="bg-mirage-surface rounded p-6 border border-mirage-border shadow-mirage-surface space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-mirage-border">
                <h3 className="font-semibold text-sm text-mirage-text">
                  Authoritative Credentials ({keys.length})
                </h3>
                <span className="text-[11px] text-mirage-subtext font-mono">Tenant: {tenantId}</span>
              </div>

              {keys.length === 0 ? (
                <div className="p-8 border border-dashed border-mirage-border rounded text-center">
                  <Key className="w-8 h-8 text-mirage-subtext mx-auto mb-2 opacity-50" />
                  <h4 className="text-xs font-semibold text-mirage-text">No API Keys Provisioned</h4>
                  <p className="text-[11px] text-mirage-subtext mt-1">
                    Generate an API key on the left to start sending authenticated requests.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {keys.map((k) => (
                    <div
                      key={k.id}
                      className="p-4 rounded bg-mirage-surfaceElevated/50 border border-mirage-border/80 flex items-center justify-between hover:bg-mirage-surfaceElevated transition"
                    >
                      <div>
                        <div className="text-xs font-semibold text-mirage-text">{k.name}</div>
                        <div className="text-[11px] font-mono text-mirage-subtext mt-0.5">
                          Prefix: <span className="text-mirage-text font-bold">{k.key_prefix || k.id.substring(0, 12)}...</span>
                        </div>
                        <div className="text-[10px] text-mirage-muted mt-1">
                          Role: <span className="font-semibold uppercase text-mirage-cyan">{k.role}</span> &bull; Status: <span className="text-mirage-emerald font-semibold">ACTIVE</span>
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() => handleRevokeKey(k.id)}
                        title="Instantly revoke API key"
                        className="p-2 rounded text-mirage-muted hover:text-mirage-crimson hover:bg-mirage-crimson/10 transition"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* SECTION 2: OUTBOUND WEBHOOKS */}
      {activeSection === "webhooks" && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Register Webhook Form */}
          <div className="lg:col-span-5 space-y-4">
            <div className="bg-mirage-surface rounded p-6 border border-mirage-border shadow-mirage-surface space-y-4">
              <div className="flex items-center space-x-2 pb-3 border-b border-mirage-border">
                <Bell className="w-4 h-4 text-mirage-purple" />
                <h3 className="font-semibold text-sm text-mirage-text">Register Outbound Webhook</h3>
              </div>

              <form onSubmit={handleCreateWebhook} className="space-y-3">
                <div>
                  <label className="block text-xs font-semibold text-mirage-text mb-1">
                    Destination Endpoint (HTTP/HTTPS)
                  </label>
                  <input
                    type="url"
                    value={webhookUrl}
                    onChange={(e) => setWebhookUrl(e.target.value)}
                    placeholder="https://hooks.slack.com/services/... or https://api.yoursite.com/alerts"
                    className="w-full text-xs p-2.5 rounded bg-mirage-surfaceElevated border border-mirage-border focus:outline-none focus:border-mirage-cyan font-sans"
                    required
                  />
                  <span className="text-[10px] text-mirage-subtext mt-0.5 block">
                    Slack and Discord webhooks are automatically formatted as rich Block Kit / Embeds.
                  </span>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-mirage-text mb-1">
                    Description / Label
                  </label>
                  <input
                    type="text"
                    value={webhookDesc}
                    onChange={(e) => setWebhookDesc(e.target.value)}
                    placeholder="e.g. SRE Escalation Channel"
                    className="w-full text-xs p-2.5 rounded bg-mirage-surfaceElevated border border-mirage-border focus:outline-none focus:border-mirage-cyan font-sans"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-mirage-text mb-1">
                    Custom Signing Secret (Optional)
                  </label>
                  <input
                    type="text"
                    value={webhookSecret}
                    onChange={(e) => setWebhookSecret(e.target.value)}
                    placeholder="Leave empty for auto-generated 64-char hex secret"
                    className="w-full text-xs p-2.5 rounded bg-mirage-surfaceElevated border border-mirage-border focus:outline-none focus:border-mirage-cyan font-mono"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-mirage-text mb-1.5">
                    Subscribed Assurance Events
                  </label>
                  <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                    {availableEvents.map((evt) => (
                      <label
                        key={evt.id}
                        className="flex items-start space-x-2.5 p-2 rounded bg-mirage-surfaceElevated hover:bg-mirage-border/30 cursor-pointer transition text-xs"
                      >
                        <input
                          type="checkbox"
                          checked={selectedEvents.includes(evt.id)}
                          onChange={() => handleToggleEvent(evt.id)}
                          className="mt-0.5 rounded text-mirage-cyan focus:ring-mirage-cyan"
                        />
                        <div>
                          <span className="font-semibold text-mirage-text block">{evt.label}</span>
                          <span className="text-[10px] text-mirage-subtext">{evt.desc}</span>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={isCreatingWebhook || !webhookUrl.trim()}
                  className="w-full py-2.5 rounded bg-mirage-cyan hover:bg-mirage-cyanHover text-white text-xs font-semibold shadow-sm transition disabled:opacity-50"
                >
                  {isCreatingWebhook ? "Registering Subscription..." : "Register Webhook"}
                </button>
              </form>

              {webhookError && (
                <div className="p-3 rounded bg-mirage-crimson/10 border border-mirage-crimson/20 text-xs text-mirage-crimson flex items-center space-x-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  <span>{webhookError}</span>
                </div>
              )}

              {webhookSuccess && (
                <div className="p-3 rounded bg-mirage-emerald/10 border border-mirage-emerald/20 text-xs text-mirage-emerald flex items-center space-x-2">
                  <CheckCircle2 className="w-4 h-4 shrink-0" />
                  <span>{webhookSuccess}</span>
                </div>
              )}
            </div>
          </div>

          {/* Active Webhooks List */}
          <div className="lg:col-span-7 space-y-4">
            <div className="bg-mirage-surface rounded p-6 border border-mirage-border shadow-mirage-surface space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-mirage-border">
                <h3 className="font-semibold text-sm text-mirage-text">
                  Registered Outbound Subscriptions ({webhooks.length})
                </h3>
                <span className="text-[11px] text-mirage-subtext">HMAC-SHA256 Signed</span>
              </div>

              {loadingWebhooks ? (
                <div className="p-8 text-center text-xs text-mirage-subtext">Loading webhooks...</div>
              ) : webhooks.length === 0 ? (
                <div className="p-8 border border-dashed border-mirage-border rounded text-center">
                  <Radio className="w-8 h-8 text-mirage-subtext mx-auto mb-2 opacity-50" />
                  <h4 className="text-xs font-semibold text-mirage-text">No Outbound Webhooks Registered</h4>
                  <p className="text-[11px] text-mirage-subtext mt-1 max-w-sm mx-auto">
                    Subscribe a Slack, Discord, or HTTPS endpoint to receive immediate alerts when human approvals are required or reality discrepancies occur.
                  </p>
                </div>
              ) : (
                <div className="space-y-3">
                  {webhooks.map((w) => (
                    <div
                      key={w.id}
                      className="p-4 rounded bg-mirage-surfaceElevated/50 border border-mirage-border/80 space-y-2 hover:bg-mirage-surfaceElevated transition"
                    >
                      <div className="flex items-start justify-between">
                        <div>
                          <div className="text-xs font-semibold text-mirage-text flex items-center space-x-2">
                            <span>{w.description || "Webhook Endpoint"}</span>
                            <span className="px-1.5 py-0.5 rounded-full bg-mirage-emerald/10 text-mirage-emerald text-[10px] font-mono">
                              ACTIVE
                            </span>
                          </div>
                          <div className="text-[11px] font-mono text-mirage-subtext truncate max-w-md mt-0.5">
                            {w.url}
                          </div>
                        </div>

                        <div className="flex items-center space-x-2 shrink-0">
                          <button
                            type="button"
                            onClick={() => handleTestWebhook(w.id)}
                            disabled={testingWebhookId === w.id}
                            className="px-2.5 py-1 rounded-lg bg-mirage-surfaceElevated hover:bg-mirage-border border border-mirage-border text-[11px] font-semibold text-mirage-text transition disabled:opacity-50 flex items-center space-x-1"
                          >
                            <Send className="w-3 h-3 text-mirage-cyan" />
                            <span>{testingWebhookId === w.id ? "Pinging..." : "Test Ping"}</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteWebhook(w.id)}
                            title="Delete webhook subscription"
                            className="p-1.5 rounded-lg text-mirage-muted hover:text-mirage-crimson hover:bg-mirage-crimson/10 transition"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                      {/* Subscribed Event Badges */}
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {(w.event_types || []).map((evt) => (
                          <span
                            key={evt}
                            className="px-2 py-0.5 rounded-md bg-mirage-surface border border-mirage-border text-[10px] font-mono text-mirage-subtext"
                          >
                            {evt}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* SECTION 3: CODE SAMPLES */}
      {activeSection === "code" && (
        <div className="bg-mirage-surface rounded p-6 border border-mirage-border shadow-mirage-surface space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-mirage-border">
            <div className="flex items-center space-x-2">
              <Code2 className="w-4 h-4 text-mirage-cyan" />
              <h3 className="font-semibold text-sm text-mirage-text">Integration Code Samples</h3>
            </div>

            <div className="flex space-x-1 p-1 bg-mirage-surfaceElevated rounded border border-mirage-border">
              <button
                type="button"
                onClick={() => setActiveSnippetTab("openai")}
                className={`px-3 py-1 text-xs font-medium rounded-lg transition ${
                  activeSnippetTab === "openai"
                    ? "bg-white text-mirage-text shadow-sm"
                    : "text-mirage-subtext hover:text-mirage-text"
                }`}
              >
                OpenAI Proxy
              </button>
              <button
                type="button"
                onClick={() => setActiveSnippetTab("curl")}
                className={`px-3 py-1 text-xs font-medium rounded-lg transition ${
                  activeSnippetTab === "curl"
                    ? "bg-white text-mirage-text shadow-sm"
                    : "text-mirage-subtext hover:text-mirage-text"
                }`}
              >
                cURL
              </button>
              <button
                type="button"
                onClick={() => setActiveSnippetTab("mcp")}
                className={`px-3 py-1 text-xs font-medium rounded-lg transition ${
                  activeSnippetTab === "mcp"
                    ? "bg-white text-mirage-text shadow-sm"
                    : "text-mirage-subtext hover:text-mirage-text"
                }`}
              >
                Cursor / Claude MCP
              </button>
              <button
                type="button"
                onClick={() => setActiveSnippetTab("webhook_receiver")}
                className={`px-3 py-1 text-xs font-medium rounded-lg transition ${
                  activeSnippetTab === "webhook_receiver"
                    ? "bg-white text-mirage-text shadow-sm"
                    : "text-mirage-subtext hover:text-mirage-text"
                }`}
              >
                Webhook Verification
              </button>
            </div>
          </div>

          <div className="relative">
            <pre className="p-4 rounded bg-mirage-surfaceElevated/80 border border-mirage-border text-xs font-mono text-mirage-text overflow-x-auto leading-relaxed">
              {snippets[activeSnippetTab]}
            </pre>

            <button
              type="button"
              onClick={() => copyToClipboard(snippets[activeSnippetTab], activeSnippetTab)}
              className="absolute top-3 right-3 p-2 rounded bg-white/90 backdrop-blur-sm border border-mirage-border text-mirage-subtext hover:text-mirage-text shadow-sm transition"
            >
              {copiedSnippet === activeSnippetTab ? (
                <div className="flex items-center space-x-1 text-mirage-emerald text-[11px] font-sans font-medium">
                  <Check className="w-3.5 h-3.5" />
                  <span>Copied</span>
                </div>
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
            </button>
          </div>

          <div className="p-4 rounded bg-mirage-surfaceElevated/40 border border-mirage-border/70 text-xs text-mirage-subtext space-y-1">
            <div className="font-semibold text-mirage-text">Deterministic Tenant Attribution:</div>
            <p>
              Always pass the <code className="font-mono text-mirage-cyan font-bold">X-Tenant-ID</code> header with every request. MIRAGE enforces strict PostgreSQL Row-Level Security to prevent cross-tenant privilege escalation.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
