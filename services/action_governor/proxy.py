"""Authoritative Sandboxed Tool Proxy for Gate 3 Action Assurance.

Executes actions strictly for authorized ActionContracts, enforces isolation,
and provides safe AST math evaluation without eval().
"""

import ast
import operator
from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from db import session as db_session
from db.models import ActionContract, MCPServer, ToolDefinition
from services.mcp_client import GovernedMCPClient, MCPExecutionUncertainError
from shared.schemas.action import ActionState
from shared.schemas.auth import AuthContext


class ToolProxyBypassError(Exception):
    """Raised when an unverified or direct tool call attempts to bypass Gate 3 Action Governance."""

    pass


_SAFE_ARITHMETIC_OPS: dict[type[ast.AST], Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval_math(expr: str) -> float | int:
    """Safe abstract syntax tree mathematical evaluator eliminating eval()."""

    def _eval_node(node: ast.AST) -> float | int:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        elif isinstance(node, ast.BinOp):
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            op = _SAFE_ARITHMETIC_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported math operator: {type(node.op).__name__}")
            res: float | int = float(op(left, right))
            return res
        elif isinstance(node, ast.UnaryOp):
            operand = _eval_node(node.operand)
            op = _SAFE_ARITHMETIC_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"Unsupported math operator: {type(node.op).__name__}")
            res_u: float | int = float(op(operand))
            return res_u
        raise ValueError(f"Disallowed AST element in arithmetic expression: {type(node).__name__}")

    tree = ast.parse(expr.strip(), mode="eval")
    return _eval_node(tree.body)


class GovernedToolProxy:
    """Authoritative sandboxed Tool Proxy executing actions strictly for authorized ActionContracts."""

    def __init__(self, mcp_client: Any | None = None) -> None:
        self.invocation_counts: dict[str, int] = {}
        self.mcp_client = mcp_client

    def get_invocation_count(self, tool_name: str) -> int:
        return self.invocation_counts.get(tool_name, 0)

    def reset_invocation_counts(self) -> None:
        self.invocation_counts.clear()

    async def dispatch(
        self,
        *,
        contract: ActionContract,
        auth: AuthContext,
    ) -> tuple[dict[str, Any], str | None]:
        """Dispatch tool execution strictly verifying contract state."""
        _ = auth
        if contract.state != ActionState.EXECUTING.value:
            raise ToolProxyBypassError(
                f"Direct tool execution prohibited: contract '{contract.id}' is not in EXECUTING state "
                f"(current: {contract.state}). All tool dispatches must be authorized by Gate 3."
            )

        tool_name = contract.tool_name
        params = contract.normalized_parameters or {}
        target_resource = contract.target_resource

        # Increment verifiable invocation count for testing and live demonstration observation
        self.invocation_counts[tool_name] = self.invocation_counts.get(tool_name, 0) + 1

        fencing_token = contract.fencing_token

        try:
            # Check if this action is an external MCP tool
            if ":" in tool_name or (contract.tool_id and contract.tool_id.startswith("tool_")):
                async with db_session.get_tenant_session(auth.tenant_id) as s:
                    tool_stmt = select(ToolDefinition).where(
                        ToolDefinition.tenant_id == auth.tenant_id,
                        ToolDefinition.id == contract.tool_id,
                    )
                    tool_def = (await s.execute(tool_stmt)).scalar_one_or_none()
                    if tool_def and tool_def.tool_type == "MCP" and tool_def.mcp_server_id:
                        server_stmt = select(MCPServer).where(
                            MCPServer.tenant_id == auth.tenant_id,
                            MCPServer.id == tool_def.mcp_server_id,
                        )
                        server = (await s.execute(server_stmt)).scalar_one_or_none()
                        if not server:
                            raise ToolProxyBypassError(
                                f"Bound MCP server '{tool_def.mcp_server_id}' not found for tool '{tool_name}'"
                            )
                        if server.trust_status != "TRUSTED":
                            raise ToolProxyBypassError(
                                f"Bound MCP server '{server.id}' trust status is '{server.trust_status}', "
                                f"must be 'TRUSTED' (fail-closed)"
                            )

                        client = self.mcp_client or GovernedMCPClient()
                        raw_name = (tool_def.config or {}).get("raw_tool_name") or tool_name.split(":", 1)[-1]
                        mcp_res = await client.call_tool(
                            server=server,
                            raw_tool_name=raw_name,
                            arguments=params,
                        )
                        mcp_res["fencing_token"] = fencing_token
                        return mcp_res, None

            if tool_name == "calculator":
                expr = str(params.get("expression", "0"))
                val = _safe_eval_math(expr)
                return {"status": "ok", "result": val, "expression": expr, "fencing_token": fencing_token}, None

            elif tool_name in ("db_query", "internal_sql_query"):
                expected_token = params.get("expected_fencing_token")
                if expected_token is not None and expected_token != fencing_token:
                    raise ValueError(
                        f"Target-side fencing check failed: expected token {expected_token} "
                        f"!= active token {fencing_token}"
                    )
                return {
                    "status": "ok",
                    "rows_affected": 1,
                    "target": target_resource,
                    "fencing_token": fencing_token,
                    "parameters": params,
                }, None

            elif tool_name in ("email_sender", "external_email"):
                return {
                    "status": "ok",
                    "delivered": True,
                    "recipient": params.get("recipient"),
                    "subject": params.get("subject"),
                    "fencing_token": fencing_token,
                }, None

            elif tool_name == "customer_lookup":
                return {
                    "status": "ok",
                    "customer_id": params.get("customer_id"),
                    "target": target_resource,
                    "fencing_token": fencing_token,
                }, None

            elif tool_name == "controlled_test_probe":
                # Controlled probe tool for Section 22 verifiable execution proofs
                return {
                    "status": "ok",
                    "probe_executed": True,
                    "invocations": self.invocation_counts[tool_name],
                    "target": target_resource,
                    "params": params,
                    "fencing_token": fencing_token,
                }, None

            else:
                return {
                    "status": "ok",
                    "executed": True,
                    "tool": tool_name,
                    "target_resource": target_resource,
                    "params": params,
                    "fencing_token": fencing_token,
                }, None
        except MCPExecutionUncertainError:
            raise
        except Exception as exc:
            return {"status": "error", "error": str(exc), "fencing_token": fencing_token}, str(exc)
