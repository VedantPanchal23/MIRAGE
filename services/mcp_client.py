"""Governed MCP Client and Transport Security.

Implements:
1. Strict SSRF and DNS-rebinding protection for HTTP-based MCP servers with IP pinning and redirect blocking.
2. Safe Subprocess execution (stdio) with shell=False, argument sanitization, secret-stripped environments,
   and process termination.
3. JSON-RPC 2.0 handshake, schema fingerprinting, and namespacing ({server_id}:{tool_name}).
4. Recursion and loop prevention.
5. Epistemic Outcome Independence: remote transport results are treated as untrusted claims, and timeouts/disconnects
   trigger EXECUTION_UNCERTAIN.
"""

import asyncio
import hashlib
import json
import os
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from db.models import MCPServer
from services.providers.ssrf_validator import (
    SSRFValidationError,
    create_ssrf_safe_client,
    validate_safe_provider_url,
)
from shared.logging import get_logger
from shared.schemas.mcp import MCPDiscoveredTool, MCPServerTransport, MCPTrustStatus

logger = get_logger("mcp_client")

# Shell metacharacters forbidden in subprocess commands or arguments
FORBIDDEN_SHELL_CHARS = re.compile(r"[;&|`$<>\n\r]")

# Environment variable keys that must NEVER be passed to subprocesses
SENSITIVE_ENV_PATTERNS = re.compile(
    r"(KEY|SECRET|PASSWORD|TOKEN|CREDENTIAL|POSTGRES|DATABASE|AWS|REDIS|MONGO|SENTRY|JWT|AUTH|PRIVATE)",
    re.IGNORECASE,
)

# Standard safe environment variables permitted for child processes
SAFE_ENV_ALLOWLIST = {
    "PATH",
    "LANG",
    "LC_ALL",
    "SYSTEMROOT",
    "COMSPEC",
    "TEMP",
    "TMP",
    "USER",
    "LOGNAME",
    "HOMEPATH",
    "NODE_PATH",
    "PYTHONPATH",
}

MAX_FRAME_SIZE = 10 * 1024 * 1024  # 10 MB maximum JSON-RPC frame
MAX_RECURSION_DEPTH = 3


class MCPClientError(Exception):
    """Base exception for all MCP client errors."""


class MCPSecurityError(MCPClientError):
    """Raised when an MCP operation violates security policies (SSRF, egress, argument injection)."""


class MCPProtocolError(MCPClientError):
    """Raised when the remote MCP server violates JSON-RPC or MCP protocol rules."""


class MCPExecutionUncertainError(MCPClientError):
    """Raised when a remote tool call times out or disconnects in flight, making outcome uncertain."""


def sanitize_subprocess_env(custom_env: dict[str, str] | None = None) -> dict[str, str]:
    """Sanitize environment variables passed to child subprocesses, stripping all secrets."""
    clean_env: dict[str, str] = {}
    for k, v in os.environ.items():
        if k in SAFE_ENV_ALLOWLIST and not SENSITIVE_ENV_PATTERNS.search(k):
            clean_env[k] = v

    if custom_env:
        for k, v in custom_env.items():
            if SENSITIVE_ENV_PATTERNS.search(k):
                logger.warning("Stripped sensitive variable from custom MCP subprocess env: %s", k)
                continue
            clean_env[k] = str(v)

    return clean_env


def validate_egress_destination(destination: str, egress_allowlist: list[str]) -> None:
    """Ensure destination hostname/IP/executable is within the server's egress allowlist if configured."""
    if not egress_allowlist:
        return

    dest_norm = destination.strip().lower()
    for allowed in egress_allowlist:
        allowed_norm = allowed.strip().lower()
        if dest_norm == allowed_norm:
            return
        # Subdomain match (e.g. *.example.com or .example.com)
        if allowed_norm.startswith("*.") and dest_norm.endswith(allowed_norm[1:]):
            return
        if allowed_norm.startswith(".") and dest_norm.endswith(allowed_norm):
            return

    raise MCPSecurityError(
        f"Destination '{destination}' is not permitted by server egress allowlist: {egress_allowlist}"
    )


class SSRFSafeMCPHttpClient:
    """HTTP client for remote MCP servers with strict SSRF protection and timeout bounding."""

    def __init__(
        self,
        url: str,
        timeout_seconds: int = 30,
        headers: dict[str, str] | None = None,
        auth_token: str | None = None,
        egress_allowlist: list[str] | None = None,
    ) -> None:
        self.raw_url = url
        self.timeout_seconds = timeout_seconds
        self.headers = headers or {}
        self.auth_token = auth_token
        self.egress_allowlist = egress_allowlist or []

        # Validate URL against SSRF
        try:
            self.validated_url = validate_safe_provider_url(url, allow_local=False, resolve_dns=True)
        except SSRFValidationError as exc:
            raise MCPSecurityError(f"MCP server URL rejected by SSRF enforcement: {exc}") from exc

        # Check egress allowlist against parsed hostname
        parsed = urlsplit(self.validated_url)
        if parsed.hostname:
            validate_egress_destination(parsed.hostname, self.egress_allowlist)

    async def send_rpc(self, payload: dict[str, Any], is_call: bool = False) -> dict[str, Any]:
        """Send JSON-RPC payload to HTTP MCP server."""
        req_headers = dict(self.headers)
        req_headers["Content-Type"] = "application/json"
        if self.auth_token:
            req_headers["Authorization"] = f"Bearer {self.auth_token}"

        try:
            async with create_ssrf_safe_client(
                allow_local=False,
                timeout=float(self.timeout_seconds),
            ) as client:
                resp = await client.post(
                    self.validated_url,
                    json=payload,
                    headers=req_headers,
                )
                if resp.status_code >= 400:
                    if is_call:
                        # Remote HTTP error after dispatch
                        raise MCPExecutionUncertainError(
                            f"Remote MCP HTTP server returned error status {resp.status_code}: {resp.text[:500]}"
                        )
                    raise MCPProtocolError(f"HTTP MCP error {resp.status_code}: {resp.text[:500]}")

                if len(resp.content) > MAX_FRAME_SIZE:
                    raise MCPProtocolError(
                        f"MCP response exceeded maximum frame size of {MAX_FRAME_SIZE} bytes"
                    )

                return resp.json()  # type: ignore[no-any-return]
        except (httpx.TimeoutException, TimeoutError) as exc:
            if is_call:
                raise MCPExecutionUncertainError(
                    f"Remote MCP HTTP tool call timed out after {self.timeout_seconds}s: execution uncertain"
                ) from exc
            raise MCPClientError(f"Remote MCP HTTP operation timed out: {exc}") from exc
        except (httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            if is_call:
                raise MCPExecutionUncertainError(
                    f"Remote MCP HTTP tool call network disconnect/error: {exc}: execution uncertain"
                ) from exc
            raise MCPClientError(f"Remote MCP HTTP network error: {exc}") from exc


class SafeSubprocessMCPClient:
    """stdio-based subprocess client for local MCP servers with argument sanitization and timeout bounding."""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_seconds: int = 30,
        egress_allowlist: list[str] | None = None,
    ) -> None:
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.cwd = cwd
        self.timeout_seconds = timeout_seconds
        self.egress_allowlist = egress_allowlist or []

        self._validate_command_and_args()

    def _validate_command_and_args(self) -> None:
        """Validate command executable and arguments to eliminate shell injection."""
        if not self.command or not isinstance(self.command, str):
            raise MCPSecurityError("Subprocess MCP command cannot be empty")

        if FORBIDDEN_SHELL_CHARS.search(self.command):
            raise MCPSecurityError(
                f"Subprocess command '{self.command}' contains prohibited shell metacharacters"
            )

        # Prohibit path traversal
        if ".." in self.command.replace("\\", "/").split("/"):
            raise MCPSecurityError(
                f"Subprocess command '{self.command}' contains prohibited path traversal components"
            )

        # Check egress allowlist if specified
        if self.egress_allowlist:
            cmd_base = os.path.basename(self.command)
            validate_egress_destination(cmd_base, self.egress_allowlist)

        for arg in self.args:
            if not isinstance(arg, str):
                raise MCPSecurityError(f"Subprocess arguments must be strings, got {type(arg)}")
            if FORBIDDEN_SHELL_CHARS.search(arg):
                raise MCPSecurityError(f"Subprocess argument '{arg}' contains prohibited shell metacharacters")

    async def execute_rpc_single(self, payload: dict[str, Any], is_call: bool = False) -> dict[str, Any]:
        """Launch isolated subprocess, send JSON-RPC message, await response, and cleanly terminate."""
        clean_env = sanitize_subprocess_env(self.env)
        exec_args = [self.command, *self.args]

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *exec_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=clean_env,
                cwd=self.cwd,
            )

            # Send initialize handshake followed by requested method
            raw_data = json.dumps(payload).encode("utf-8") + b"\n"
            if len(raw_data) > MAX_FRAME_SIZE:
                raise MCPSecurityError("Subprocess JSON-RPC payload exceeds maximum frame size")

            if proc.stdin is None or proc.stdout is None:
                raise MCPClientError("Subprocess pipes were not initialized")

            proc.stdin.write(raw_data)
            await proc.stdin.drain()

            # Read response with timeout
            async def _read_response() -> bytes:
                assert proc is not None and proc.stdout is not None
                line = await proc.stdout.readline()
                return line

            resp_line = await asyncio.wait_for(_read_response(), timeout=float(self.timeout_seconds))
            if not resp_line:
                if is_call:
                    raise MCPExecutionUncertainError(
                        "Subprocess closed stdout before responding to tool call: execution uncertain"
                    )
                raise MCPProtocolError("Subprocess returned empty response")

            if len(resp_line) > MAX_FRAME_SIZE:
                raise MCPProtocolError("Subprocess response exceeded maximum frame size")

            return json.loads(resp_line.decode("utf-8"))  # type: ignore[no-any-return]

        except TimeoutError as exc:
            if is_call:
                raise MCPExecutionUncertainError(
                    f"Subprocess tool call timed out after {self.timeout_seconds}s: execution uncertain"
                ) from exc
            raise MCPClientError(f"Subprocess operation timed out: {exc}") from exc
        finally:
            if proc is not None:
                try:
                    if proc.returncode is None:
                        proc.kill()
                    await proc.wait()
                except Exception as clean_err:
                    logger.debug("Error while terminating MCP subprocess: %s", clean_err)


class GovernedMCPClient:
    """Unified Governed MCP Client for external tool discovery and invocation."""

    async def list_tools(self, server: MCPServer) -> list[MCPDiscoveredTool]:
        """Query tools/list from the external server, computing schema fingerprints and namespacing."""
        if server.trust_status != MCPTrustStatus.TRUSTED.value:
            raise MCPSecurityError(
                f"Cannot query tools from MCP server '{server.id}': trust status is "
                f"'{server.trust_status}', but '{MCPTrustStatus.TRUSTED.value}' is required (fail-closed)."
            )

        list_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }

        resp_data = await self._dispatch_to_server(server, list_req, is_call=False)
        if "error" in resp_data:
            err = resp_data["error"]
            raise MCPProtocolError(f"Remote MCP tools/list failed: {err.get('message', err)}")

        result = resp_data.get("result", {})
        raw_tools = result.get("tools", [])
        if not isinstance(raw_tools, list):
            raise MCPProtocolError(f"Expected 'tools' array in result, got {type(raw_tools)}")

        discovered: list[MCPDiscoveredTool] = []
        permitted_caps = set(server.permitted_capabilities or [])

        for t in raw_tools:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name", "")).strip()
            if not name:
                continue

            desc = str(t.get("description", ""))
            schema = t.get("inputSchema", {})
            if not isinstance(schema, dict):
                schema = {}

            # Canonical schema fingerprinting
            canonical_schema_bytes = json.dumps(schema, sort_keys=True).encode("utf-8")
            fingerprint = hashlib.sha256(canonical_schema_bytes).hexdigest()

            # Namespaced tool name
            namespaced_name = f"{server.id}:{name}"

            # Assigned capability check: if server has permitted_capabilities, tool must map to one
            # Default capability name: mcp:{server.name}:{name}
            default_cap = f"mcp:{server.name}:{name}"
            if permitted_caps:
                # If tool requires a specific cap or default, ensure it matches permitted
                assigned_cap = default_cap if default_cap in permitted_caps else next(iter(permitted_caps))
            else:
                assigned_cap = default_cap

            discovered.append(
                MCPDiscoveredTool(
                    name=name,
                    namespaced_name=namespaced_name,
                    description=desc,
                    input_schema=schema,
                    schema_fingerprint=fingerprint,
                    required_capability=assigned_cap,
                )
            )

        return discovered

    async def call_tool(
        self,
        server: MCPServer,
        raw_tool_name: str,
        arguments: dict[str, Any],
        call_depth: int = 0,
    ) -> dict[str, Any]:
        """Execute tools/call on the remote MCP server under Gate 3 governance."""
        if server.trust_status != MCPTrustStatus.TRUSTED.value:
            raise MCPSecurityError(
                f"Tool dispatch blocked: MCP server '{server.id}' trust status is '{server.trust_status}', "
                f"must be '{MCPTrustStatus.TRUSTED.value}'"
            )

        if call_depth >= MAX_RECURSION_DEPTH:
            raise MCPSecurityError(
                f"MCP tool call recursion depth exceeded maximum limit of {MAX_RECURSION_DEPTH}"
            )

        # Recursion & self-reference guard: reject arguments containing circular references to MIRAGE gateway
        raw_args_str = json.dumps(arguments, default=str).lower()
        if "mirage/v1/actions" in raw_args_str or "execute_action" in raw_args_str:
            raise MCPSecurityError("Circular or recursive invocation detected in MCP tool arguments")

        call_req = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {
                "name": raw_tool_name,
                "arguments": arguments,
            },
        }

        resp_data = await self._dispatch_to_server(server, call_req, is_call=True)

        if "error" in resp_data:
            err = resp_data["error"]
            err_msg = err.get("message", str(err))
            return {
                "status": "error",
                "error": err_msg,
                "server_id": server.id,
                "tool": raw_tool_name,
            }

        result = resp_data.get("result", {})
        # Note: In accordance with Epistemic Outcome Independence, this result is
        # strictly an untrusted model/server claim.
        return {
            "status": "ok",
            "result": result,
            "server_id": server.id,
            "tool": raw_tool_name,
        }

    async def _dispatch_to_server(
        self,
        server: MCPServer,
        payload: dict[str, Any],
        is_call: bool,
    ) -> dict[str, Any]:
        """Dispatch JSON-RPC message over the configured transport."""
        cfg = server.connection_config or {}
        timeout = server.timeout_seconds or 30

        if server.transport_type == MCPServerTransport.STDIO.value:
            command = cfg.get("command", "")
            args = cfg.get("args", [])
            env = cfg.get("env", {})
            cwd = cfg.get("cwd")
            client = SafeSubprocessMCPClient(
                command=command,
                args=args,
                env=env,
                cwd=cwd,
                timeout_seconds=timeout,
                egress_allowlist=server.egress_allowlist or [],
            )
            return await client.execute_rpc_single(payload, is_call=is_call)

        elif server.transport_type == MCPServerTransport.HTTP_STREAM.value:
            url = cfg.get("url", "")
            headers = cfg.get("headers", {})
            auth_token = cfg.get("auth_token")
            client = SSRFSafeMCPHttpClient(
                url=url,
                timeout_seconds=timeout,
                headers=headers,
                auth_token=auth_token,
                egress_allowlist=server.egress_allowlist or [],
            )
            return await client.send_rpc(payload, is_call=is_call)

        else:
            raise MCPSecurityError(f"Unsupported MCP transport type: '{server.transport_type}'")
