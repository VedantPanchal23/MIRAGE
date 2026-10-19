"""Unit tests for Governed MCP Client, SSRF protection, and Subprocess sanitization."""

import os
from unittest.mock import patch

import pytest

from db.models import MCPServer
from services.mcp_client import (
    GovernedMCPClient,
    MCPExecutionUncertainError,
    MCPSecurityError,
    SafeSubprocessMCPClient,
    SSRFSafeMCPHttpClient,
    sanitize_subprocess_env,
)
from shared.schemas.mcp import MCPTrustStatus


def test_sanitize_subprocess_env_strips_sensitive_keys() -> None:
    """Ensure secrets (JWT, AWS, POSTGRES, DB keys) are completely purged from child process env."""
    with patch.dict(
        os.environ,
        {
            "PATH": "/usr/bin:/bin",
            "LANG": "en_US.UTF-8",
            "JWT_SECRET_KEY": "super_secret_jwt_token",
            "POSTGRES_PASSWORD": "db_password_123",
            "DATABASE_URL": "postgresql://usr:pass@localhost:5432/db",
            "AWS_SECRET_ACCESS_KEY": "aws_secret_key",
            "OPENAI_API_KEY": "sk-12345",
        },
        clear=True,
    ):
        custom = {
            "SAFE_CONFIG": "custom_value",
            "ANOTHER_SECRET_TOKEN": "forbidden_token",
        }
        clean_env = sanitize_subprocess_env(custom)

        assert "PATH" in clean_env
        assert "LANG" in clean_env
        assert "SAFE_CONFIG" in clean_env
        assert clean_env["SAFE_CONFIG"] == "custom_value"

        # None of the sensitive keys must leak
        assert "JWT_SECRET_KEY" not in clean_env
        assert "POSTGRES_PASSWORD" not in clean_env
        assert "DATABASE_URL" not in clean_env
        assert "AWS_SECRET_ACCESS_KEY" not in clean_env
        assert "OPENAI_API_KEY" not in clean_env
        assert "ANOTHER_SECRET_TOKEN" not in clean_env


def test_subprocess_client_rejects_shell_metacharacters() -> None:
    """Ensure shell metacharacters in commands or arguments raise MCPSecurityError."""
    with pytest.raises(MCPSecurityError) as exc_info:
        SafeSubprocessMCPClient(command="python; rm -rf /")
    assert "prohibited shell metacharacters" in str(exc_info.value)

    with pytest.raises(MCPSecurityError) as exc_info:
        SafeSubprocessMCPClient(command="node", args=["-e", "console.log(1) && cat /etc/passwd"])
    assert "prohibited shell metacharacters" in str(exc_info.value)

    with pytest.raises(MCPSecurityError) as exc_info:
        SafeSubprocessMCPClient(command="tool", args=["$(whoami)"])
    assert "prohibited shell metacharacters" in str(exc_info.value)


def test_subprocess_client_rejects_path_traversal() -> None:
    """Ensure path traversal in commands raises MCPSecurityError."""
    with pytest.raises(MCPSecurityError) as exc_info:
        SafeSubprocessMCPClient(command="../../bin/malicious_tool")
    assert "prohibited path traversal" in str(exc_info.value)


def test_http_client_rejects_loopback_and_metadata_ssrf() -> None:
    """Ensure loopback and metadata endpoints raise MCPSecurityError at initialization."""
    with pytest.raises(MCPSecurityError) as exc_info:
        SSRFSafeMCPHttpClient(url="http://127.0.0.1:8000/mcp")
    assert "SSRF" in str(exc_info.value)

    with pytest.raises(MCPSecurityError) as exc_info:
        SSRFSafeMCPHttpClient(url="http://169.254.169.254/latest/meta-data")
    assert "SSRF" in str(exc_info.value)

    with pytest.raises(MCPSecurityError) as exc_info:
        SSRFSafeMCPHttpClient(url="http://metadata.google.internal/computeMetadata/v1")
    assert "SSRF" in str(exc_info.value)


def test_http_client_enforces_egress_allowlist() -> None:
    """Ensure destinations outside egress allowlist raise MCPSecurityError."""
    # When egress allowlist is specified, unapproved domains are rejected
    with pytest.raises(MCPSecurityError) as exc_info:
        with patch("services.mcp_client.validate_safe_provider_url", return_value="https://untrusted-api.com/mcp"):
            SSRFSafeMCPHttpClient(
                url="https://untrusted-api.com/mcp",
                egress_allowlist=["trusted-partner.com", "*.authorized.org"],
            )
    assert "not permitted by server egress allowlist" in str(exc_info.value)


@pytest.mark.asyncio
async def test_governed_mcp_client_denies_untrusted_server() -> None:
    """Tool listing and calls are blocked if server is not TRUSTED."""
    client = GovernedMCPClient()
    untrusted_server = MCPServer(
        id="mcp_srv_pending",
        tenant_id="tenant_alpha",
        name="Pending Server",
        trust_status=MCPTrustStatus.PENDING_APPROVAL.value,
        transport_type="STDIO",
    )

    with pytest.raises(MCPSecurityError) as exc_info:
        await client.list_tools(untrusted_server)
    assert "trust status is 'PENDING_APPROVAL'" in str(exc_info.value)

    with pytest.raises(MCPSecurityError) as exc_info:
        await client.call_tool(untrusted_server, "query", {})
    assert "trust status is 'PENDING_APPROVAL'" in str(exc_info.value)


@pytest.mark.asyncio
async def test_governed_mcp_client_detects_recursion_and_circularity() -> None:
    """Client rejects tool calls exceeding MAX_RECURSION_DEPTH or attempting circular gateway re-entry."""
    client = GovernedMCPClient()
    trusted_server = MCPServer(
        id="mcp_srv_trusted",
        tenant_id="tenant_alpha",
        name="Trusted Server",
        trust_status=MCPTrustStatus.TRUSTED.value,
        transport_type="STDIO",
    )

    # Exceeded recursion depth
    with pytest.raises(MCPSecurityError) as exc_info:
        await client.call_tool(trusted_server, "query", {}, call_depth=5)
    assert "recursion depth exceeded" in str(exc_info.value)

    # Circular injection in arguments
    with pytest.raises(MCPSecurityError) as exc_info:
        await client.call_tool(
            trusted_server,
            "query",
            {"target": "http://mirage/v1/actions/execute_action"},
        )
    assert "Circular or recursive invocation detected" in str(exc_info.value)


@pytest.mark.asyncio
async def test_subprocess_tool_call_timeout_triggers_execution_uncertain() -> None:
    """Subprocess timeout during tool call terminates process and raises MCPExecutionUncertainError."""
    sub_client = SafeSubprocessMCPClient(
        command="python",
        args=["-c", "__import__('time').sleep(10)"],
        timeout_seconds=1,
    )

    with pytest.raises(MCPExecutionUncertainError) as exc_info:
        await sub_client.execute_rpc_single(
            payload={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "sleep"}},
            is_call=True,
        )
    assert "execution uncertain" in str(exc_info.value)
