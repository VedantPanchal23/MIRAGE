# MIRAGE 3.0 — SDK and Integration

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document defines how developers integrate MIRAGE 3.0 into their AI applications, workflows, and agents.

---

## 1. Developer Experience Design Principles

- **Low Friction:** Provide drop-in replacements for standard LLM calls.
- **Sensible Defaults:** Secure-by-default policies that don't block development but prevent catastrophic risk.
- **Progressive Complexity:** Start with simple proxy mode, scale up to complex multi-agent governed workflows.
- **Type Safety:** Robust typing in all SDKs to catch errors at compile time.

---

## 2. Integration Modes

### 2.1 Gateway / Proxy Mode
MIRAGE acts as a transparent proxy in front of LLM APIs (e.g., OpenAI, Anthropic).
- **OpenAI-Compatible Interface:** Point existing OpenAI SDKs to MIRAGE's endpoint by simply changing the `base_url` and providing a MIRAGE API key.
- MIRAGE automatically applies Gate 1 (Input) and Gate 4 (Output) assurance seamlessly.

**Example Configuration:**
```python
from openai import OpenAI

# Transparent proxying through MIRAGE
client = OpenAI(
    base_url="https://api.mirage.ai/v1/proxy/openai",
    api_key="mirage_sk_..."
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### 2.2 Server-Side Middleware
For custom applications, MIRAGE SDKs provide interceptors and decorators for frameworks seamlessly wrapping route handlers with AI Transaction contexts.

---

## 3. SDKs

### 3.1 Python SDK (`mirage-py`)
High-level client library optimized for backend engineers.

**Detailed Example:**
```python
import mirage
from mirage.agents import GovernedAgent
from mirage.errors import PolicyViolationError

client = mirage.Client(api_key="sk-...", tenant_id="t-123")

# Define a governed tool
@client.tool(capability="db:read", risk_level="low")
def query_db(sql: str):
    return execute_sql(sql)

agent = GovernedAgent(
    client=client,
    model="gpt-4",
    autonomy_level="L3"
)

try:
    with client.transaction(intent="sales_report", budget={"max_cost": 0.5}) as tx:
        response = agent.run("Query sales and summarize", tools=[query_db])
        print(f"Assured Output: {response.content}")
except PolicyViolationError as e:
    print(f"Blocked by Policy: {e.message}")
```

### 3.2 JavaScript/TypeScript SDK Overview
Optimized for Node.js backends and Edge environments (`@mirage-ai/sdk`).
- Browser clients can *initiate* transactions and connect to SSE streams, but cannot evaluate policies or manage capabilities directly.

---

## 4. Framework Integration

MIRAGE 3.0 wraps and governs agents regardless of the framework.

- **LangChain / LangGraph:** MIRAGE provides custom Callbacks and Tool wrappers. Intercepts LangGraph node transitions to enforce Action Assurance (Gate 3).
  ```python
  from mirage.integrations.langchain import GovernedTool
  tool = GovernedTool.from_langchain_tool(search_tool, capability="web:search")
  ```
- **LlamaIndex:** Custom QueryEngine wrappers that inject Context Assurance (Gate 2).
- **AutoGen / CrewAI:** MIRAGE manages multi-agent boundaries, validating inter-agent communications and memory.

---

## 5. MCP Integration

MIRAGE supports the Model Context Protocol (MCP) in two directions:

### 5.1 Governing MCP Servers
Developers can register any third-party MCP server with MIRAGE. The SDK provides a wrapper that routes tool calls through the Action Governor.
```python
from mirage.mcp import McpToolWrapper
mcp_tool = McpToolWrapper("github_mcp", server_url="...")
```

### 5.2 MIRAGE as an MCP Server
MIRAGE can expose its verification capabilities as tools to external agents via MCP.
- Example: An external agent calls MIRAGE's MCP server to execute factual consistency checks on its own outputs.

---

## 6. Error Handling Patterns

MIRAGE uses strong error typing. Developers should handle specific exceptions:
- `PolicyViolationError`: Action blocked by Gate 1, 3, or 4.
- `BudgetExceededError`: Cost or token limits reached.
- `ApprovalRequiredError`: Action requires human intervention (Gate 3).
- `ContextPoisoningError`: Malicious input detected (Gate 2).

---

## 7. Migration from MIRAGE 2.x API

- The legacy `/verify` endpoint maps to `/v1/verify`.
- `mirage.verify(claim, evidence)` remains but executes Gate 4 logic within an AI Transaction under the hood.
- **Action Required:** Developers must migrate API keys to the new tenant-scoped RBAC model and update base URLs to `/v1/`.
