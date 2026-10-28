"""Model Context Protocol (MCP) server exposing MIRAGE factual verification tools."""

import asyncio
import json
import sys
from typing import Any

from shared.logging import get_logger
from shared.schemas import VerificationRequest
from workers.orchestrator import VerificationOrchestrator

logger = get_logger("mcp_server")


class MirageMCPServer:
    """Model Context Protocol (MCP) server for Claude Desktop, Cursor, and Antigravity."""

    def __init__(self, orchestrator: VerificationOrchestrator | None = None) -> None:
        self.orchestrator = orchestrator or VerificationOrchestrator()
        self.tools = [
            {
                "name": "verify_factual_consistency",
                "description": (
                    "Verify the factual consistency and hallucination risk of an LLM response "
                    "using MIRAGE's multi-signal verification pipeline (RAV, SCS, NLI, ICS)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The LLM response or text content to verify.",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "The original user prompt that produced the response.",
                            "default": "",
                        },
                        "tenant_id": {
                            "type": "string",
                            "description": "Tenant ID for policy enforcement and telemetry.",
                            "default": "mcp_client",
                        },
                        "knowledge_base_id": {
                            "type": "string",
                            "description": "Knowledge base collection ID for retrieval-augmented verification.",
                            "default": "default_kb",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "check_hallucination",
                "description": (
                    "Quick boolean assessment of whether an LLM completion contains factual hallucinations "
                    "or internal contradictions (HRS > 0.60)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The generated text to test for hallucinations.",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Original prompt context.",
                            "default": "",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "query_audit_logs",
                "description": (
                    "Search and query past hallucination verification sessions and audit logs "
                    "using natural language or keyword filters (e.g. 'critical risk sessions', 'contradictions')."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language query, e.g. 'Show critical risk sessions'",
                        },
                        "tenant_id": {
                            "type": "string",
                            "description": "Tenant identifier.",
                            "default": "default_tenant",
                        },
                    },
                    "required": ["query"],
                },
            },
        ]

    async def verify_factual_consistency(
        self,
        text: str,
        prompt: str = "",
        tenant_id: str = "mcp_client",
        knowledge_base_id: str = "default_kb",
    ) -> dict[str, Any]:
        """Execute full factual consistency verification tool."""
        req = VerificationRequest(
            prompt=prompt or text,
            response=text,
            tenant_id=tenant_id,
            knowledge_base_id=knowledge_base_id,
        )
        res = await self.orchestrator.verify_request(req)

        return {
            "verified_response": res.verified_response,
            "original_response": res.original_response,
            "hrs_score": res.hrs_result.hrs,
            "risk_tier": res.hrs_result.tier.value,
            "conformal_interval": {
                "lower": res.hrs_result.conformal_interval.lower,
                "upper": res.hrs_result.conformal_interval.upper,
            },
            "claims_count": res.hrs_result.claims_count,
            "contradicted_claims_count": res.hrs_result.contradicted_claims_count,
            "signal_attribution": {
                "rav": res.hrs_result.signal_attribution.rav,
                "scs": res.hrs_result.signal_attribution.scs,
                "nli": res.hrs_result.signal_attribution.nli,
                "ics": res.hrs_result.signal_attribution.ics,
                "vgs": (
                    res.hrs_result.signal_attribution.vgs if res.hrs_result.signal_attribution.vgs is not None else 0.0
                ),
            },
            "correction_applied": res.metadata.correction_applied,
            "trace_id": res.metadata.trace_id,
            "claims": [
                {
                    "claim_id": c.claim.claim_id,
                    "text": c.claim.text,
                    "type": c.claim.claim_type.value,
                    "criticality": c.claim.criticality.value,
                    "status": c.status.value,
                    "hrs_contribution": c.risk_score,
                }
                for c in res.claims
            ],
        }

    async def check_hallucination(self, text: str, prompt: str = "") -> dict[str, Any]:
        """Quick boolean risk assessment."""
        result = await self.verify_factual_consistency(text=text, prompt=prompt)
        hrs = float(result["hrs_score"])
        contradicted = int(result["contradicted_claims_count"])
        is_hallucination = hrs > 0.60 or contradicted > 0

        reason = "Output is factual and internally consistent."
        if is_hallucination:
            if contradicted > 0:
                reason = f"Identified {contradicted} direct factual contradiction(s)."
            else:
                reason = f"Elevated hallucination risk score ({hrs:.3f}) exceeds threshold (0.60)."

        return {
            "is_hallucination": is_hallucination,
            "hrs_score": hrs,
            "risk_tier": result["risk_tier"],
            "reason": reason,
        }

    async def handle_rpc_request(
        self,
        request: dict[str, Any],
        auth: Any | None = None,
    ) -> dict[str, Any]:
        """Handle JSON-RPC 2.0 protocol messages with authentication, input bounding, and tenant isolation."""
        method = request.get("method")
        msg_id = request.get("id")
        params = request.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mirage-mcp-server", "version": "3.0.0"},
                },
            }

        if method == "notifications/initialized":
            return {"jsonrpc": "2.0", "result": None}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": self.tools},
            }

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            # Resolve effective tenant strictly from authenticated context if provided
            effective_tenant = getattr(auth, "tenant_id", None) if auth else None
            req_tenant = arguments.get("tenant_id")

            # Check cross-tenant snooping
            if effective_tenant is not None and req_tenant and req_tenant != effective_tenant:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32003,
                        "message": (
                            f"Access denied: Caller belonging to tenant '{effective_tenant}' "
                            f"cannot access resources belonging to tenant '{req_tenant}'"
                        ),
                    },
                }

            tenant_to_use = effective_tenant or req_tenant or "mcp_client"

            try:
                if tool_name == "verify_factual_consistency":
                    text_input = arguments.get("text", "")
                    if len(text_input) > 50_000:
                        return {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {
                                "code": -32602,
                                "message": "Text parameter exceeds maximum allowed limit of 50,000 characters",
                            },
                        }
                    result = await self.verify_factual_consistency(
                        text=text_input,
                        prompt=arguments.get("prompt", ""),
                        tenant_id=tenant_to_use,
                        knowledge_base_id=arguments.get("knowledge_base_id", "default_kb"),
                    )
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
                    }

                if tool_name == "check_hallucination":
                    text_input = arguments.get("text", "")
                    if len(text_input) > 50_000:
                        return {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {
                                "code": -32602,
                                "message": "Text parameter exceeds maximum allowed limit of 50,000 characters",
                            },
                        }
                    result = await self.check_hallucination(
                        text=text_input,
                        prompt=arguments.get("prompt", ""),
                    )
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
                    }

                if tool_name == "query_audit_logs":
                    query_input = arguments.get("query", "")
                    if len(query_input) > 1_000:
                        return {
                            "jsonrpc": "2.0",
                            "id": msg_id,
                            "error": {
                                "code": -32602,
                                "message": "Query parameter exceeds maximum allowed limit of 1,000 characters",
                            },
                        }

                    from analytics.audit_service import AuditService

                    matches = AuditService.natural_language_query(
                        query=query_input,
                        tenant_id=tenant_to_use,
                    )
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "result": {"content": [{"type": "text", "text": json.dumps({"matches": matches}, indent=2)}]},
                    }

                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"},
                }
            except Exception as exc:
                logger.error("Error executing MCP tool '%s': %s", tool_name, exc)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32603, "message": f"Internal execution error for tool '{tool_name}'"},
                }

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method '{method}' not supported"},
        }


def stdio_server_loop(tenant_id: str = "mcp_client") -> None:
    """Standard I/O JSON-RPC 2.0 loop for Claude Desktop, Cursor, and external MCP clients."""
    server = MirageMCPServer()

    for line in sys.stdin:
        line_str = line.strip()
        if not line_str:
            continue
        try:
            req = json.loads(line_str)
            if "params" in req and isinstance(req["params"], dict) and "arguments" in req["params"]:
                req["params"]["arguments"].setdefault("tenant_id", tenant_id)
            resp = asyncio.run(server.handle_rpc_request(req))
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        except Exception as exc:
            err = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
            sys.stdout.write(json.dumps(err) + "\n")
            sys.stdout.flush()


def main() -> None:
    """CLI entry point for running Mirage MCP server as an external tool."""
    import argparse

    parser = argparse.ArgumentParser(description="MIRAGE Model Context Protocol (MCP) Server")
    parser.add_argument("--tenant-id", default="mcp_client", help="Tenant ID for assurance policy attribution")
    args = parser.parse_args()
    try:
        stdio_server_loop(tenant_id=args.tenant_id)
    except (KeyboardInterrupt, BrokenPipeError):
        pass


if __name__ == "__main__":
    main()
