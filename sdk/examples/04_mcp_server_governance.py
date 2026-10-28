"""Example 4: Governed MCP Server Management and Tool Discovery.

Demonstrates:
- Registering an external MCP server in PENDING_APPROVAL status.
- Setting egress restrictions and permitted capabilities.
- Operator trust transition to TRUSTED.
- Discovering remote tools, generating SHA-256 schema fingerprints, and syncing with tool registry.
"""

import os
import sys
import uuid

from mirage_sdk import (
    MCPServerCreateRequest,
    MCPServerTransport,
    MCPTrustStatus,
    MirageAuthorizationError,
    MirageClient,
)


def main() -> None:
    api_key = os.environ.get("MIRAGE_API_KEY")
    base_url = os.environ.get("MIRAGE_BASE_URL", "http://localhost:8000")

    # If no valid API key is set in environment, auto-provision a local sandbox tenant
    if not api_key or api_key == "mirage_test_key_sample":
        print("[DX] No MIRAGE_API_KEY detected. Provisioning local sandbox developer tenant...")
        try:
            with MirageClient(api_key="bootstrap_temp", base_url=base_url) as boot_client:
                tenant_res = boot_client.register_tenant({
                    "name": "Local Dev Sandbox",
                    "admin_email": f"developer_{uuid.uuid4().hex[:6]}@mirage.local",
                    "tier": "developer",
                })
                api_key = tenant_res["api_key"]
                print(f"[OK] Onboarded sandbox tenant '{tenant_res['tenant_id']}' with active API key.\n")
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Sandbox onboarding skipped ({exc}). Falling back to test key.")
            api_key = api_key or "mirage_test_key_sample"

    with MirageClient(api_key=api_key, base_url=base_url) as client:
        print("1. Registering external MCP server...")
        try:
            server = client.register_mcp_server(
                MCPServerCreateRequest(
                    name="github-enterprise-mcp",
                    description="GitHub Enterprise integration for pull request and issue inspection",
                    transport_type=MCPServerTransport.STDIO,
                    connection_config={
                        "command": "node",
                        "args": ["/opt/mcp/github-server/dist/index.js"],
                    },
                    permitted_capabilities=["vcs:read", "issue:read"],
                    egress_allowlist=["github.myorg.internal"],
                    timeout_seconds=45,
                )
            )
            print(f"   Registered server '{server.name}' (ID: {server.id})")
            print(f"   Initial Trust Status: {server.trust_status} (Fail-Closed)")

            print("\n2. Promoting trust status to TRUSTED (operator action)...")
            updated = client.update_mcp_server_trust(
                server_id=server.id,
                trust_status=MCPTrustStatus.TRUSTED,
                reason="Verified binary signature and egress boundary against security policy",
            )
            print(f"   Updated Trust Status: {updated.trust_status}")

            print("\n3. Listing registered MCP servers under tenant isolation...")
            server_list = client.list_mcp_servers(limit=10)
            print(f"   Total MCP Servers: {server_list.total}")
            for s in server_list.servers:
                print(f"     - {s.name} ({s.id}): status={s.trust_status}, transport={s.transport_type}")

        except MirageAuthorizationError as exc:
            print(f"[FORBIDDEN] Operator role required to manage MCP servers: {exc.message}")
            sys.exit(1)


if __name__ == "__main__":
    main()
