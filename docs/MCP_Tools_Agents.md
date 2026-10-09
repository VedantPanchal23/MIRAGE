# MIRAGE 3.0 — MCP, Tools, and Agents

> **Status:** Authoritative | **Version:** 3.0.0-draft | **Date:** 2026-10-05
>
> This document defines how MIRAGE 3.0 interacts with, governs, and secures AI agents, tools, and the Model Context Protocol (MCP).

---

## 1. Introduction

In MIRAGE 3.0, agents are untrusted entities requiring governance, and tools are sensitive interfaces requiring authorization. The platform acts as an **AI Execution Assurance Platform** by strictly separating agent planning from tool execution. MIRAGE governs both directly integrated tools and MCP servers.

---

## 2. Agent Governance Model

MIRAGE controls what agents can do by intercepting their execution intents before they result in actions.

### 2.1 Agent Identity
Every agent in MIRAGE has a cryptographic identity.
- **Authentication**: Agents authenticate via mutual TLS (mTLS) or signed JWTs issued by the Identity Service.
- **Authorization**: Agents are authorized based on the tenant they belong to and the capabilities they hold.
- **Traceability**: All agent requests include the agent's unique ID, which is attached to the AI Transaction.

### 2.2 Agent Capabilities
Capabilities define what an agent is permitted to do.
- **Granting**: Capabilities are granted via the Policy Engine based on agent identity, context, and intent.
- **Scoping**: Capabilities are scoped to specific tools, resources, and operations (e.g., `github:repo:read` vs `github:repo:write`).
- **Revocation**: Capabilities can be temporarily suspended or permanently revoked at runtime.

### 2.3 Agent Lifecycle
- **Registration**: Agents are registered in the Control Plane with metadata, base capabilities, and autonomy level limits.
- **Activation**: An agent session begins, receiving a temporary capability token.
- **Monitoring**: MIRAGE observes all plans and actions in real-time.
- **Suspension**: If an agent violates policy, exceeds risk thresholds, or shows erratic behavior, its active capabilities are suspended.
- **Deactivation**: End of session, cleanup of temporary resources and memory.

---

## 3. Tool Governance

Tools are the interfaces through which agents affect the world.

### 3.1 Tool Identity, Trust, and Egress Classification
- **Tool Identity**: Each tool has a unique identifier and owner.
- **Tool Provenance**: Tools are tracked by version and origin (first-party, third-party, MCP).
- **Trust Levels**: Tools are assigned a trust level (e.g., Untrusted, Verified, Internal) which influences risk scoring and verification requirements.
- **Egress Classification**: Every tool is explicitly categorized as either:
  - `INTERNAL_ISOLATED`: Operates strictly within local VPC/isolated storage with zero external network connectivity (e.g., internal SQL read, local sandboxed math parser).
  - `EGRESS_EXTERNAL`: Initiates external network calls, emits emails, dispatches webhooks, queries third-party APIs, or pushes cloud events. Under Information Flow Control (IFC), `EGRESS_EXTERNAL` tools are automatically revoked when confidential data and untrusted content coexist in the transaction context.

### 3.2 Tool Invocation Flow
The canonical tool invocation flow is:
`AGENT → MIRAGE → CAPABILITY → POLICY → RISK → APPROVAL → TOOL/MCP → REAL SYSTEM`

1. **AGENT**: Proposes a tool call.
2. **MIRAGE**: Intercepts the request.
3. **CAPABILITY**: Checks if the agent has the capability for this tool.
4. **POLICY**: Evaluates constraints (e.g., rate limits, temporal bounds).
5. **RISK**: Assesses the blast radius and risk of the specific parameters.
6. **APPROVAL**: Checks if the autonomy level permits execution or requires human/policy approval.
7. **TOOL/MCP**: Routes the request to the tool.
8. **REAL SYSTEM**: The external system executes the action.

### 3.3 Tool Output Handling
- **Untrusted Data**: Tool outputs are treated as untrusted data.
- **Output Validation**: Outputs are validated against expected schemas.
- **Instruction Injection Prevention**: Outputs are sanitized to prevent them from containing instructions that might hijack the agent's model.
- **Taint Assignment**: Outputs from external or untrusted tools automatically append `TAINT_UNTRUSTED` to the transaction context.

### 3.4 Tool Revocation
Tools can be suspended (e.g., if the real system is down) or revoked at runtime without redeploying the agent, immediately blocking any further agent invocations.

### 3.5 Prohibition of Tool-to-Tool Ambient Escalation and Chaining
A tool or MCP server NEVER possesses ambient authority to invoke another tool directly.
- **No Direct Sockets:** Tools cannot communicate directly with peer tools over loopback or internal networks.
- **Sub-Invocation Mediation:** If a tool (e.g., an automated workflow tool) attempts to invoke a secondary tool, the sub-invocation must be routed back through the MIRAGE Tool Proxy as a distinct action.
- **Independent Authorization:** Action Assurance independently evaluates the caller's capability token and parameter schema. Tools cannot escalate privileges transitively or launder unauthorized actions.

---

## 4. MCP Integration

MIRAGE 2.x exposed MIRAGE as an MCP tool. MIRAGE 3.0 **governs other MCP tools** and acts as an MCP Governance Layer.

### 4.1 MIRAGE as an MCP Governance Layer
When an agent connects to an MCP server, MIRAGE acts as a proxy:
- It intercepts the `tools/list` request, returning only the tools the agent has capabilities for.
- It intercepts `tools/call` requests, running them through the execution gates (Action Assurance).

### 4.2 MCP Server Management
- **Registration**: MCP servers are registered as managed resources.
- **Health**: MIRAGE monitors server health and circuit-breaks if degraded.
- **Trust**: Servers are assigned trust scores based on provenance and audit history.
- **Revocation**: Specific MCP servers can be disabled globally or per-tenant.

---

## 5. Parameter Validation and Capability Scoping

- **Schema Validation**: Every tool parameter is validated against strict JSON schemas before risk assessment.
- **Capability Scoping**: Capabilities can constrain parameters. For example, a `db:query` capability might only allow `SELECT` statements, and the Action Governor will block `DROP` or `UPDATE` regardless of the tool's raw capability.

---

## 6. Multi-Agent Workflows and A2A Protocols

### 6.1 Multi-Agent Workflows
When multiple agents collaborate:
- **Trust Propagation**: MIRAGE tracks the provenance of data shared between agents.
- **Delegation**: Agents can delegate tasks, but they cannot grant capabilities they do not possess.

### 6.2 A2A Protocols (Open Decision)
*Note: The specific Agent-to-Agent communication protocol is an open architectural decision.*
MIRAGE will govern A2A by:
- Verifying identities on both sides of the communication.
- Enforcing information flow policies.
- Validating the intent of messages passed between agents.

---

## 7. Plugin and Extension Model

Third-party extensions (tools, models, policy evaluators) must:
- Be registered in the Control Plane.
- Run in isolated sandboxes or via standard network protocols (like MCP).
- Adhere to the core primitives (Identity, Tenancy, Capability).
