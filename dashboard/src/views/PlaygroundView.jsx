import React, { useState, useEffect } from "react";
import {
  Play,
  RotateCcw,
  CheckCircle,
  AlertTriangle,
  XCircle,
  Shield,
  Layers,
  Sparkles,
  Cpu,
  Sliders,
  Check,
  Terminal,
  Server,
  Activity,
  Code,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export function PlaygroundView() {
  const { tenantId } = useAuth();
  const [activeTab, setActiveTab] = useState("output"); // "output" | "action" | "mcp"

  // --------------------------------------------------------------------------
  // Tab 1: Gate 4 Output Assurance & HRS State
  // --------------------------------------------------------------------------
  const presets = [
    {
      id: "financial",
      title: "FinTech Wire Transfer",
      prompt: "Execute an immediate wire transfer of $75,000 to routing transit 021000021 account 99887766 for vendor invoice #INV-2026-99.",
      response: "Wire transfer dispatched: $75,000 sent to Acme Supplier with authorization code TX-99214. The transaction settled instantly on the Fedwire network.",
      model: "llama-3.3-70b-versatile",
    },
    {
      id: "medical",
      title: "Clinical Dosage Guidance",
      prompt: "What is the recommended pediatric loading dose of amoxicillin for a 22kg child with acute otitis media?",
      response: "The standard pediatric loading dose of amoxicillin is 120mg/kg daily split into single bolus injections every 2 hours, requiring 2640mg at once.",
      model: "llama-3.3-70b-versatile",
    },
    {
      id: "policy",
      title: "Corporate Expense Policy",
      prompt: "Can employees expense first-class international flights under standard travel guidelines?",
      response: "According to company travel policy, all flights over 4 hours automatically qualify for first-class international bookings without prior managerial authorization.",
      model: "llama-3.3-70b-versatile",
    },
  ];

  const [prompt, setPrompt] = useState(presets[0].prompt);
  const [response, setResponse] = useState(presets[0].response);
  const [modelId, setModelId] = useState("llama-3.3-70b-versatile");
  const [autoCorrect, setAutoCorrect] = useState(true);
  const [streamMode, setStreamMode] = useState(true);
  const [streamingStatus, setStreamingStatus] = useState(null);
  const [streamingClaims, setStreamingClaims] = useState([]);
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const handleApplyPreset = (p) => {
    setPrompt(p.prompt);
    setResponse(p.response);
    setModelId(p.model);
    setResult(null);
    setError(null);
    setStreamingClaims([]);
    setStreamingStatus(null);
  };

  const handleExecuteAssurance = async () => {
    if (!prompt.trim() || !response.trim()) {
      setError("Both prompt and model response are required for assurance verification.");
      return;
    }

    setIsRunning(true);
    setError(null);
    setResult(null);

    if (streamMode) {
      setStreamingStatus("Connecting to assurance pipeline...");
      setStreamingClaims([]);
      const claimsAcc = [];

      try {
        await api.verifyCompletionStream(
          {
            prompt,
            response,
            tenant_id: tenantId,
            model_id: modelId,
            auto_correct: autoCorrect,
            knowledge_base_id: "default_kb",
          },
          {
            onEvent: (event, data) => {
              if (event === "connected") {
                setStreamingStatus("Connected. Decomposing atomic claims...");
              } else if (event === "claims_extracted") {
                setStreamingStatus(`Evaluating ${data.claims_count} extracted propositions in parallel...`);
              } else if (event === "claim_verified") {
                claimsAcc.push(data);
                setStreamingClaims([...claimsAcc]);
              } else if (event === "verification_complete") {
                setStreamingStatus("Verification complete.");
                setResult({
                  request_id: data.request_id,
                  verified_response: data.verified_response,
                  hrs_result: {
                    hrs: data.hrs_score,
                    tier: data.risk_tier,
                    conformal_interval: data.conformal_interval,
                    claims_count: data.claims_count,
                    contradicted_claims_count: data.contradicted_claims_count,
                  },
                  claims: claimsAcc.map((c) => ({
                    claim: { claim_id: c.claim_id, text: c.text },
                    status: c.status,
                    risk_score: c.risk_score,
                    rav_score: c.attribution?.rav,
                    scs_score: c.attribution?.scs,
                    nli_score: c.attribution?.nli,
                    ics_score: c.attribution?.ics,
                  })),
                });
              }
            },
            onError: (err) => {
              console.warn("Streaming verification error:", err);
              setError(err?.message || "Streaming verification failed.");
              setIsRunning(false);
              setStreamingStatus(null);
            },
            onComplete: () => {
              setIsRunning(false);
              setStreamingStatus(null);
            },
          }
        );
      } catch (err) {
        console.warn("Assurance stream exception:", err);
        setError(err?.message || "Streaming failed.");
        setIsRunning(false);
        setStreamingStatus(null);
      }
    } else {
      try {
        const res = await api.verifyCompletion({
          prompt,
          response,
          tenant_id: tenantId,
          model_id: modelId,
          auto_correct: autoCorrect,
          knowledge_base_id: "default_kb",
        });
        setResult(res);
      } catch (err) {
        console.warn("Assurance verification error:", err);
        setError(err?.message || "Verification failed. Check backend connection and model parameters.");
        setResult(null);
      } finally {
        setIsRunning(false);
      }
    }
  };

  // --------------------------------------------------------------------------
  // Tab 2: Gate 3 & Gate 5 Governed Action & Reality Verification State
  // --------------------------------------------------------------------------
  const [actionTool, setActionTool] = useState("database.update_order_status");
  const [actionParams, setActionParams] = useState(JSON.stringify({ order_id: "ord_9981", status: "COMPLETED" }, null, 2));
  const [actionDecision, setActionDecision] = useState(null);
  const [actionExecResult, setActionExecResult] = useState(null);
  const [outcomeResult, setOutcomeResult] = useState(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState(null);

  const handleProposeAction = async () => {
    setActionLoading(true);
    setActionDecision(null);
    setActionExecResult(null);
    setOutcomeResult(null);
    setActionError(null);
    try {
      const parsedParams = JSON.parse(actionParams);
      const res = await api.proposeAction({
        transaction_id: `tx_${Date.now()}`,
        tool_name: actionTool,
        action_type: "WRITE",
        target_resource: `orders:${parsedParams.order_id || "default"}`,
        parameters: parsedParams,
        idempotency_key: `idem_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`,
        postconditions: [
          {
            assertion: "STATUS_EQUALS",
            target: `orders:${parsedParams.order_id || "default"}.status`,
            expected_value: "COMPLETED",
            description: "Target database row status must be COMPLETED",
          },
        ],
        blast_radius: {
          resource_scope: "ORDERS",
          estimated_dollar_cost: 100.0,
          reversibility: "REVERSIBLE",
          target_environment: "DEV",
        },
      });
      setActionDecision(res);
    } catch (err) {
      setActionError(err?.message || "Gate 3 Action Proposal rejected.");
      setActionDecision(null);
    } finally {
      setActionLoading(false);
    }
  };

  const handleExecuteAction = async () => {
    if (!actionDecision?.action_id) return;
    setActionLoading(true);
    setActionError(null);
    try {
      const res = await api.executeAction(actionDecision.action_id);
      setActionExecResult(res);
    } catch (err) {
      setActionError(err?.message || "Action execution failed.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleVerifyOutcome = async () => {
    if (!actionDecision?.action_id) return;
    setActionLoading(true);
    setActionError(null);
    try {
      const parsedParams = JSON.parse(actionParams);
      const res = await api.verifyOutcome({
        transaction_id: `tx_live`,
        action_id: actionDecision.action_id,
        expected_postconditions: { status: "COMPLETED" },
        observation: {
          observation_id: `obs_${Date.now()}`,
          source_id: "DATABASE",
          target_resource: `orders:${parsedParams.order_id}`,
          observed_state: { status: "COMPLETED", order_id: parsedParams.order_id },
        },
      });
      setOutcomeResult(res);
    } catch (err) {
      setActionError(err?.message || "Gate 5 Outcome Verification failed.");
    } finally {
      setActionLoading(false);
    }
  };

  // --------------------------------------------------------------------------
  // Tab 3: Governed MCP Tool Explorer State
  // --------------------------------------------------------------------------
  const [mcpTools, setMcpTools] = useState([]);
  const [selectedMcpTool, setSelectedMcpTool] = useState(null);
  const [mcpInputArgs, setMcpInputArgs] = useState("{}");
  const [mcpRpcOutput, setMcpRpcOutput] = useState(null);
  const [mcpLoading, setMcpLoading] = useState(false);

  useEffect(() => {
    if (activeTab === "mcp" && mcpTools.length === 0) {
      loadMcpTools();
    }
  }, [activeTab]);

  const loadMcpTools = async () => {
    setMcpLoading(true);
    try {
      const res = await api.executeMcpRpc({
        jsonrpc: "2.0",
        id: "mcp-list-1",
        method: "tools/list",
        params: {},
      });
      const tools = res?.result?.tools || [];
      setMcpTools(tools);
      if (tools.length > 0) {
        setSelectedMcpTool(tools[0]);
        setMcpInputArgs(JSON.stringify({ text: "Water boils at 100 degrees Celsius." }, null, 2));
      }
    } catch (err) {
      setMcpTools([]);
    } finally {
      setMcpLoading(false);
    }
  };

  const handleExecuteMcpTool = async () => {
    if (!selectedMcpTool) return;
    setMcpLoading(true);
    setMcpRpcOutput(null);
    try {
      const parsedArgs = JSON.parse(mcpInputArgs);
      const res = await api.executeMcpRpc({
        jsonrpc: "2.0",
        id: `rpc-${Date.now()}`,
        method: "tools/call",
        params: {
          name: selectedMcpTool.name,
          arguments: parsedArgs,
        },
      });
      setMcpRpcOutput(res);
    } catch (err) {
      setMcpRpcOutput({
        jsonrpc: "2.0",
        id: "err-1",
        error: { code: -32603, message: err?.message || "RPC Call failed" },
      });
    } finally {
      setMcpLoading(false);
    }
  };

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-mirage-text">
            Assurance Playground
          </h1>
          <p className="text-mirage-subtext text-sm mt-1">
            Interactive multi-gate testbench: evaluate completions, govern tool actions, and explore MCP servers.
          </p>
        </div>

        {/* Tab Selector */}
        <div className="flex p-1 bg-mirage-surfaceElevated border border-mirage-border rounded w-fit">
          <button
            type="button"
            onClick={() => setActiveTab("output")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 ${
              activeTab === "output"
                ? "bg-white text-mirage-text shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
            }`}
          >
            <Shield className="w-3.5 h-3.5" />
            Gate 4: Output & HRS
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("action")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 ${
              activeTab === "action"
                ? "bg-white text-mirage-text shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
            }`}
          >
            <Activity className="w-3.5 h-3.5" />
            Gate 3 & 5: Action & Reality
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("mcp")}
            className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition flex items-center gap-1.5 ${
              activeTab === "mcp"
                ? "bg-white text-mirage-text shadow-sm"
                : "text-mirage-subtext hover:text-mirage-text"
            }`}
          >
            <Server className="w-3.5 h-3.5" />
            Governed MCP Explorer
          </button>
        </div>
      </div>

      {/* ==================================================================== */}
      {/* TAB 1: GATE 4 OUTPUT ASSURANCE */}
      {/* ==================================================================== */}
      {activeTab === "output" && (
        <div className="space-y-6">
          {/* Preset Test Scenarios */}
          <div className="space-y-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-mirage-subtext">
              Verification Scenarios
            </label>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => handleApplyPreset(p)}
                  className="p-3 text-left rounded bg-mirage-surface hover:bg-mirage-surfaceElevated border border-mirage-border shadow-sm transition group"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-xs text-mirage-text group-hover:text-mirage-cyan transition">
                      {p.title}
                    </span>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-mirage-surfaceElevated text-mirage-subtext border border-mirage-border">
                      {p.model}
                    </span>
                  </div>
                  <p className="text-[11px] text-mirage-muted mt-1 line-clamp-1">{p.prompt}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Workbench Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-6 space-y-4">
              <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-mirage-text mb-1.5">
                    Prompt (User / Agent Input)
                  </label>
                  <textarea
                    rows={3}
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Enter user prompt or agent execution instruction..."
                    className="w-full text-xs sm:text-sm p-3 bg-mirage-surfaceElevated/50 rounded border border-mirage-border focus:outline-none focus:border-mirage-cyan focus:ring-2 focus:ring-mirage-cyan/10 transition resize-none font-sans"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-mirage-text mb-1.5">
                    Target Model Completion (To be verified)
                  </label>
                  <textarea
                    rows={4}
                    value={response}
                    onChange={(e) => setResponse(e.target.value)}
                    placeholder="Enter the LLM generated response to evaluate..."
                    className="w-full text-xs sm:text-sm p-3 bg-mirage-surfaceElevated/50 rounded border border-mirage-border focus:outline-none focus:border-mirage-cyan focus:ring-2 focus:ring-mirage-cyan/10 transition resize-none font-mono text-mirage-text"
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
                  <div>
                    <label className="block text-xs font-semibold text-mirage-subtext mb-1">
                      Pipeline Model
                    </label>
                    <select
                      value={modelId}
                      onChange={(e) => setModelId(e.target.value)}
                      className="w-full text-xs p-2.5 bg-mirage-surfaceElevated rounded border border-mirage-border font-medium text-mirage-text focus:outline-none focus:border-mirage-cyan"
                    >
                      <option value="allam-2-7b">Allam-2 7B</option>
                      <option value="meta-llama/llama-3.3-70b-instruct">Llama 3.3 70B</option>
                      <option value="qwen/qwen-2.5-72b-instruct">Qwen 2.5 72B</option>
                    </select>
                  </div>

                  <div className="flex items-center justify-between p-2.5 bg-mirage-surfaceElevated rounded border border-mirage-border">
                    <div>
                      <span className="block text-xs font-semibold text-mirage-text">Auto-Correct</span>
                      <span className="text-[10px] text-mirage-muted">LangGraph repair</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setAutoCorrect(!autoCorrect)}
                      className={`w-9 h-5 flex items-center rounded-full p-0.5 transition ${
                        autoCorrect ? "bg-mirage-cyan justify-end" : "bg-mirage-border justify-start"
                      }`}
                    >
                      <span className="w-4 h-4 bg-white rounded-full shadow-sm" />
                    </button>
                  </div>

                  <div className="flex items-center justify-between p-2.5 bg-mirage-surfaceElevated rounded border border-mirage-border">
                    <div>
                      <span className="block text-xs font-semibold text-mirage-text">SSE Stream</span>
                      <span className="text-[10px] text-mirage-muted">Live event feed</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => setStreamMode(!streamMode)}
                      className={`w-9 h-5 flex items-center rounded-full p-0.5 transition ${
                        streamMode ? "bg-mirage-cyan justify-end" : "bg-mirage-border justify-start"
                      }`}
                    >
                      <span className="w-4 h-4 bg-white rounded-full shadow-sm" />
                    </button>
                  </div>
                </div>

                {error && (
                  <div className="p-3 bg-rose-50 border border-rose-200 text-rose-700 text-xs rounded flex items-center gap-2">
                    <XCircle className="w-4 h-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}

                <div className="flex items-center justify-between pt-2">
                  <button
                    type="button"
                    onClick={() => {
                      setPrompt("");
                      setResponse("");
                      setResult(null);
                      setError(null);
                    }}
                    className="px-3 py-2 text-xs font-semibold text-mirage-subtext hover:text-mirage-text rounded hover:bg-mirage-surfaceElevated transition flex items-center gap-1.5"
                  >
                    <RotateCcw className="w-3.5 h-3.5" />
                    Reset
                  </button>

                  <button
                    type="button"
                    onClick={handleExecuteAssurance}
                    disabled={isRunning}
                    className="px-5 py-2.5 bg-mirage-text text-white text-xs font-semibold rounded hover:bg-black shadow-sm transition flex items-center gap-2 disabled:opacity-50"
                  >
                    {isRunning ? (
                      <>
                        <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        Evaluating...
                      </>
                    ) : (
                      <>
                        <Play className="w-3.5 h-3.5 fill-current" />
                        Execute Gate 4 Assurance
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>

            {/* Right Column: Results */}
            <div className="lg:col-span-6 space-y-4">
              {result ? (
                <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-4">
                  <div className="flex items-center justify-between pb-3 border-b border-mirage-border">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold uppercase tracking-wider text-mirage-subtext">
                        Verification Status
                      </span>
                      <span
                        className={`text-xs px-2.5 py-1 rounded-full font-bold uppercase ${
                          result?.hrs_result?.tier === "LOW"
                            ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                            : result?.hrs_result?.tier === "CRITICAL"
                            ? "bg-rose-50 text-rose-700 border border-rose-200"
                            : "bg-amber-50 text-amber-700 border border-amber-200"
                        }`}
                      >
                        {result?.hrs_result?.tier || "EVALUATED"}
                      </span>
                    </div>
                    <span className="text-[11px] font-mono text-mirage-muted">
                      Score: {result?.hrs_result?.hrs?.toFixed(4) || "0.0000"}
                    </span>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-mirage-subtext mb-1">
                      Verified Response
                    </label>
                    <div className="p-3 bg-mirage-surfaceElevated/70 rounded border border-mirage-border text-xs text-mirage-text font-mono leading-relaxed">
                      {result.verified_response || result.response}
                    </div>
                  </div>

                  {result.claims && result.claims.length > 0 && (
                    <div>
                      <label className="block text-xs font-semibold text-mirage-subtext mb-1.5">
                        Extracted Claims & Entailment
                      </label>
                      <div className="space-y-2">
                        {result.claims.map((c, i) => (
                          <div key={i} className="p-2.5 rounded bg-mirage-surfaceElevated border border-mirage-border text-xs space-y-1">
                            <div className="flex items-center justify-between">
                              <span className="font-semibold text-mirage-text">{c.claim?.text || c.claim_text}</span>
                              <span
                                className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                  c.status === "SUPPORTED" || c.status === "VERIFIED_TRUE"
                                    ? "bg-emerald-100 text-emerald-800"
                                    : "bg-rose-100 text-rose-800"
                                }`}
                              >
                                {c.status}
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : isRunning && streamMode ? (
                <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-4">
                  <div className="flex items-center justify-between pb-3 border-b border-mirage-border">
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-full bg-mirage-cyan animate-pulse" />
                      <span className="text-xs font-bold uppercase tracking-wider text-mirage-text">
                        Real-Time SSE Stream
                      </span>
                    </div>
                    <span className="text-[11px] font-mono text-mirage-subtext animate-pulse">
                      {streamingStatus || "Processing stream..."}
                    </span>
                  </div>

                  {streamingClaims.length > 0 ? (
                    <div className="space-y-3">
                      <label className="block text-xs font-semibold text-mirage-subtext">
                        Progressive Claims Evaluated ({streamingClaims.length})
                      </label>
                      <div className="space-y-2">
                        {streamingClaims.map((c, i) => (
                          <div
                            key={i}
                            className="p-3 rounded bg-mirage-surfaceElevated border border-mirage-border text-xs space-y-1.5 transition-all"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-mirage-text">{c.text}</span>
                              <span
                                className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                                  c.status === "SUPPORTED" || c.status === "VERIFIED_TRUE"
                                    ? "bg-emerald-100 text-emerald-800"
                                    : "bg-rose-100 text-rose-800"
                                }`}
                              >
                                {c.status}
                              </span>
                            </div>
                            {c.attribution && (
                              <div className="flex items-center gap-2 text-[10px] font-mono text-mirage-muted pt-1 border-t border-mirage-border/50">
                                <span>RAV: {(c.attribution.rav ?? 0).toFixed(2)}</span>
                                <span>•</span>
                                <span>SCS: {(c.attribution.scs ?? 0).toFixed(2)}</span>
                                <span>•</span>
                                <span>NLI: {(c.attribution.nli ?? 0).toFixed(2)}</span>
                                <span>•</span>
                                <span>ICS: {(c.attribution.ics ?? 0).toFixed(2)}</span>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="py-12 flex flex-col items-center justify-center text-center space-y-3">
                      <div className="w-8 h-8 rounded-full border-2 border-mirage-cyan/20 border-t-mirage-cyan animate-spin" />
                      <p className="text-xs text-mirage-subtext font-medium">
                        {streamingStatus || "Awaiting initial stream events..."}
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="h-full min-h-[380px] flex flex-col items-center justify-center rounded border-2 border-dashed border-mirage-border p-8 text-center bg-mirage-surfaceElevated/20">
                  <div className="w-12 h-12 rounded bg-mirage-surfaceElevated text-mirage-muted flex items-center justify-center mb-3">
                    <Layers className="w-6 h-6" />
                  </div>
                  <h3 className="text-sm font-semibold text-mirage-text">Ready for Output Assurance</h3>
                  <p className="text-xs text-mirage-subtext max-w-sm mt-1">
                    Select a scenario or enter a custom prompt and candidate response, then click Execute.
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* TAB 2: GATE 3 & GATE 5 ACTION & REALITY VERIFICATION */}
      {/* ==================================================================== */}
      {activeTab === "action" && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-6 space-y-4">
            <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-4">
              <div>
                <label className="block text-xs font-semibold text-mirage-text mb-1.5">
                  Governed Tool Name
                </label>
                <select
                  value={actionTool}
                  onChange={(e) => setActionTool(e.target.value)}
                  className="w-full text-xs sm:text-sm p-3 bg-mirage-surfaceElevated rounded border border-mirage-border font-mono text-mirage-text focus:outline-none focus:border-mirage-cyan"
                >
                  <option value="database.update_order_status">database.update_order_status (Internal SQL)</option>
                  <option value="quickstart.payment_capture">quickstart.payment_capture (Payment Bridge)</option>
                  <option value="iam.assign_role">iam.assign_role (Access Management)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-mirage-text mb-1.5">
                  Action Parameters (JSON)
                </label>
                <textarea
                  rows={4}
                  value={actionParams}
                  onChange={(e) => setActionParams(e.target.value)}
                  className="w-full text-xs p-3 bg-mirage-surfaceElevated/70 rounded border border-mirage-border font-mono text-mirage-text focus:outline-none focus:border-mirage-cyan"
                />
              </div>

              <div className="flex flex-wrap gap-2 pt-2">
                <button
                  type="button"
                  onClick={handleProposeAction}
                  disabled={actionLoading}
                  className="px-4 py-2 bg-mirage-text text-white text-xs font-semibold rounded hover:bg-black transition flex items-center gap-1.5 disabled:opacity-50"
                >
                  1. Propose Action (Gate 3)
                </button>
                <button
                  type="button"
                  onClick={handleExecuteAction}
                  disabled={actionLoading || !actionDecision}
                  className="px-4 py-2 bg-mirage-cyan text-white text-xs font-semibold rounded hover:bg-blue-600 transition flex items-center gap-1.5 disabled:opacity-40"
                >
                  2. Execute via Tool Proxy
                </button>
                <button
                  type="button"
                  onClick={handleVerifyOutcome}
                  disabled={actionLoading || !actionExecResult}
                  className="px-4 py-2 bg-emerald-600 text-white text-xs font-semibold rounded hover:bg-emerald-700 transition flex items-center gap-1.5 disabled:opacity-40"
                >
                  3. Verify Reality (Gate 5)
                </button>
              </div>

              {actionError && (
                <div className="p-3 rounded bg-mirage-crimson/10 border border-mirage-crimson/20 text-xs text-mirage-crimson flex items-center space-x-2">
                  <AlertTriangle className="w-4 h-4 shrink-0" />
                  <span>{actionError}</span>
                </div>
              )}
            </div>
          </div>

          <div className="lg:col-span-6 space-y-4">
            <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-4">
              <h3 className="text-xs font-bold uppercase tracking-wider text-mirage-subtext">
                Assurance Lifecycle Trace
              </h3>

              {/* Step 1: Proposal Decision */}
              <div className="p-3 bg-mirage-surfaceElevated rounded border border-mirage-border text-xs space-y-1.5">
                <div className="flex items-center justify-between font-semibold">
                  <span className="text-mirage-text">Gate 3 Action Contract:</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    actionDecision?.decision === "ALLOW" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"
                  }`}>
                    {actionDecision?.decision || "NOT PROPOSED"}
                  </span>
                </div>
                {actionDecision && (
                  <div className="font-mono text-[11px] text-mirage-muted space-y-0.5">
                    <p>Action ID: {actionDecision.action_id}</p>
                    <p>Risk Score: {actionDecision.risk_score} | Fencing Token: {actionDecision.fencing_token || "None"}</p>
                  </div>
                )}
              </div>

              {/* Step 2: Tool Execution */}
              <div className="p-3 bg-mirage-surfaceElevated rounded border border-mirage-border text-xs space-y-1.5">
                <div className="flex items-center justify-between font-semibold">
                  <span className="text-mirage-text">Governed Tool Proxy Dispatch:</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    actionExecResult?.state === "EXECUTED" ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700"
                  }`}>
                    {actionExecResult?.state || "NOT EXECUTED"}
                  </span>
                </div>
                {actionExecResult?.observed_output && (
                  <pre className="p-2 bg-white rounded-lg border border-mirage-border font-mono text-[10px] text-mirage-text overflow-x-auto">
                    {JSON.stringify(actionExecResult.observed_output, null, 2)}
                  </pre>
                )}
              </div>

              {/* Step 3: Reality Verification */}
              <div className="p-3 bg-mirage-surfaceElevated rounded border border-mirage-border text-xs space-y-1.5">
                <div className="flex items-center justify-between font-semibold">
                  <span className="text-mirage-text">Gate 5 Reality Verification:</span>
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    outcomeResult?.outcome_status === "VERIFIED_SUCCESS" ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700"
                  }`}>
                    {outcomeResult?.outcome_status || "UNVERIFIED"}
                  </span>
                </div>
                {outcomeResult && (
                  <div className="font-mono text-[11px] text-mirage-muted space-y-0.5">
                    <p>Epistemic Confidence: {(outcomeResult.epistemic_confidence * 100).toFixed(1)}%</p>
                    <p>Discrepancies: {outcomeResult.discrepancies?.length || 0}</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ==================================================================== */}
      {/* TAB 3: GOVERNED MCP TOOL EXPLORER */}
      {/* ==================================================================== */}
      {activeTab === "mcp" && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <div className="lg:col-span-5 space-y-4">
            <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider text-mirage-subtext">
                  Discovered MCP Tools
                </h3>
                <button
                  type="button"
                  onClick={loadMcpTools}
                  disabled={mcpLoading}
                  className="text-xs text-mirage-cyan hover:underline font-medium"
                >
                  Refresh
                </button>
              </div>

              <div className="space-y-2">
                {mcpTools.map((t) => (
                  <button
                    key={t.name}
                    type="button"
                    onClick={() => {
                      setSelectedMcpTool(t);
                      setMcpInputArgs(JSON.stringify({ text: "Water boils at 100 degrees Celsius." }, null, 2));
                    }}
                    className={`w-full p-3 rounded border text-left transition ${
                      selectedMcpTool?.name === t.name
                        ? "bg-mirage-cyan/5 border-mirage-cyan text-mirage-text"
                        : "bg-mirage-surfaceElevated/50 border-mirage-border text-mirage-subtext hover:text-mirage-text"
                    }`}
                  >
                    <span className="font-mono text-xs font-semibold block">{t.name}</span>
                    <span className="text-[11px] text-mirage-muted line-clamp-1 mt-0.5">{t.description}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="lg:col-span-7 space-y-4">
            <div className="bg-mirage-surface rounded p-5 border border-mirage-border shadow-mirage-surface space-y-4">
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-mirage-subtext mb-1">
                  JSON-RPC 2.0 Invocation ({selectedMcpTool?.name || "No tool selected"})
                </h3>
                <textarea
                  rows={4}
                  value={mcpInputArgs}
                  onChange={(e) => setMcpInputArgs(e.target.value)}
                  className="w-full text-xs p-3 bg-mirage-surfaceElevated/70 rounded border border-mirage-border font-mono text-mirage-text focus:outline-none focus:border-mirage-cyan"
                  placeholder="Enter arguments JSON..."
                />
              </div>

              <button
                type="button"
                onClick={handleExecuteMcpTool}
                disabled={mcpLoading || !selectedMcpTool}
                className="px-4 py-2 bg-mirage-text text-white text-xs font-semibold rounded hover:bg-black transition flex items-center gap-2 disabled:opacity-50"
              >
                {mcpLoading ? "Calling MCP RPC..." : "Execute via POST /v1/mcp/rpc"}
              </button>

              {mcpRpcOutput && (
                <div>
                  <label className="block text-xs font-semibold text-mirage-subtext mb-1">
                    JSON-RPC 2.0 Response
                  </label>
                  <pre className="p-3 bg-mirage-surfaceElevated/80 rounded border border-mirage-border font-mono text-[11px] text-mirage-text overflow-x-auto max-h-[300px]">
                    {JSON.stringify(mcpRpcOutput, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
