"""Unit tests for MIRAGE 3.0 Governed MCP Enterprise Shield & Reverse Proxy."""

from mcp_server.shield import GovernedMCPShield


def test_mcp_shield_initialize() -> None:
    shield = GovernedMCPShield(tenant_id="test_tenant")
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = shield.handle_request(req)
    assert resp is not None
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "mirage-mcp-shield"
    assert "protocolVersion" in resp["result"]


def test_mcp_shield_tools_list() -> None:
    shield = GovernedMCPShield(tenant_id="test_tenant")
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = shield.handle_request(req)
    assert resp is not None
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "governed_bash" in tool_names
    assert "governed_sql_query" in tool_names
    assert "governed_http_fetch" in tool_names


def test_mcp_shield_safe_execution() -> None:
    shield = GovernedMCPShield(tenant_id="test_tenant")
    req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "governed_bash",
            "arguments": {"command": "ls -la /var/log"},
        },
    }
    resp = shield.handle_request(req)
    assert resp is not None
    assert resp["result"]["isError"] is False
    content_text = resp["result"]["content"][0]["text"]
    assert "SIMULATED_STDOUT" in content_text
    assert "GATE 5 VERIFIED" in content_text


def test_mcp_shield_blocks_dangerous_command() -> None:
    shield = GovernedMCPShield(tenant_id="test_tenant")
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "governed_bash",
            "arguments": {"command": "rm -rf /data/production"},
        },
    }
    resp = shield.handle_request(req)
    assert resp is not None
    assert resp["result"]["isError"] is True
    content_text = resp["result"]["content"][0]["text"]
    assert "MIRAGE GATE 3 BLOCKED" in content_text
    assert "Dangerous pattern detected" in content_text


def test_mcp_shield_blocks_ssrf_metadata_attack() -> None:
    shield = GovernedMCPShield(tenant_id="test_tenant")
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "governed_http_fetch",
            "arguments": {"url": "http://169.254.169.254/latest/meta-data/"},
        },
    }
    resp = shield.handle_request(req)
    assert resp is not None
    assert resp["result"]["isError"] is True
    content_text = resp["result"]["content"][0]["text"]
    assert "MIRAGE GATE 3 BLOCKED" in content_text
    assert "SSRF Defense" in content_text


def test_mcp_shield_unknown_method() -> None:
    shield = GovernedMCPShield(tenant_id="test_tenant")
    req = {"jsonrpc": "2.0", "id": 6, "method": "unknown/method", "params": {}}
    resp = shield.handle_request(req)
    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32601
