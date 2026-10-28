"""MIRAGE 3.0 Official Developer CLI Utility.

Provides terminal commands for:
- Environment & gateway health inspection
- Automated developer sandbox quickstart
- Factual consistency verification (Gate 4 Output Assurance)
- Governed MCP stdio server execution
- Governed tool registry inspection
"""

import argparse
import os
import sys
from typing import Any

VERSION = "3.0.0"
DEFAULT_BASE_URL = os.environ.get("MIRAGE_BASE_URL", "http://localhost:8000")


def _get_api_key(explicit_key: str | None = None) -> str | None:
    if explicit_key:
        return explicit_key
    if os.environ.get("MIRAGE_API_KEY"):
        return os.environ.get("MIRAGE_API_KEY")

    # Check .env.local if present
    if os.path.exists(".env.local"):
        try:
            with open(".env.local", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MIRAGE_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            pass
    return None


def cmd_health(args: argparse.Namespace) -> int:
    """Check MIRAGE Gateway health status."""
    import httpx

    base_url = args.base_url or DEFAULT_BASE_URL
    print(f"Inspecting MIRAGE Gateway at {base_url}...")
    try:
        resp = httpx.get(f"{base_url}/v1/health", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[HEALTHY] Gateway status: {data.get('status')} (version: {data.get('version', VERSION)})")
            return 0
        print(f"[UNHEALTHY] Gateway returned HTTP {resp.status_code}: {resp.text}")
        return 1
    except Exception as exc:
        print(f"[UNREACHABLE] Could not connect to gateway: {exc}")
        return 1


def cmd_quickstart(args: argparse.Namespace) -> int:
    """Run automated developer onboarding and 5-gate pipeline test."""
    from scripts.quickstart import main as quickstart_main

    base_url = args.base_url or DEFAULT_BASE_URL
    os.environ["MIRAGE_BASE_URL"] = base_url
    try:
        quickstart_main()
        return 0
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 1
    except Exception as exc:
        print(f"[ERROR] Quickstart failed: {exc}")
        return 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify factual consistency of a candidate text (Gate 4 Output Assurance)."""
    import httpx

    base_url = args.base_url or DEFAULT_BASE_URL
    api_key = _get_api_key(args.api_key)

    if not api_key:
        print("[ERROR] No API key provided. Set MIRAGE_API_KEY, use --api-key, or run 'mirage quickstart'.")
        return 1

    prompt = args.prompt or args.text
    response = args.text

    print(f"Submitting text for Gate 4 factual verification to {base_url}...")
    headers = {"X-API-Key": api_key}
    payload = {
        "prompt": prompt,
        "response": response,
        "model_id": args.model or "allam-2-7b",
    }

    try:
        resp = httpx.post(f"{base_url}/v1/verify", json=payload, headers=headers, timeout=args.timeout)
        if resp.status_code != 200:
            print(f"[FAIL] Verification returned HTTP {resp.status_code}: {resp.text}")
            return 1

        data = resp.json()
        hrs = data.get("hrs_result", {})
        ci = hrs.get("conformal_interval", {})

        print("\n" + "=" * 60)
        print("  MIRAGE GATE 4 OUTPUT ASSURANCE REPORT")
        print("=" * 60)
        print(f"Request ID:         {data.get('request_id')}")
        print(f"Verified Response:  {data.get('verified_response')}")
        print(f"Hallucination Risk: {hrs.get('hrs', 0):.4f} (Tier: {hrs.get('tier')})")
        print(f"95% Conformal CI:   [{ci.get('lower', 0):.4f}, {ci.get('upper', 0):.4f}]")
        print(f"Claims Evaluated:   {hrs.get('claims_count', 0)}")
        print(f"Latency:            {hrs.get('computation_latency_ms', 0):.2f} ms")

        claims = data.get("claims", [])
        if claims:
            print("\nClaims Breakdown:")
            for idx, c in enumerate(claims, 1):
                claim_obj = c.get("claim", {})
                status_str = c.get("status")
                risk_val = c.get("risk_score", 0)
                print(f"  [{idx}] '{claim_obj.get('text')}' -> Status: {status_str} (Risk: {risk_val:.3f})")
        print("=" * 60 + "\n")
        return 0
    except Exception as exc:
        print(f"[ERROR] Verification failed: {exc}")
        return 1


def cmd_mcp(args: argparse.Namespace) -> int:
    """Launch the Governed Model Context Protocol (MCP) stdio server."""
    from mcp_server.server import main as mcp_main

    sys.argv = ["mcp_server", "--tenant-id", args.tenant_id]
    mcp_main()
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    """List registered tools under tenant Gate 3 registry."""
    import httpx

    base_url = args.base_url or DEFAULT_BASE_URL
    api_key = _get_api_key(args.api_key)

    if not api_key:
        print("[ERROR] No API key provided. Set MIRAGE_API_KEY, use --api-key, or run 'mirage quickstart'.")
        return 1

    headers = {"X-API-Key": api_key}
    try:
        resp = httpx.get(f"{base_url}/v1/tools", headers=headers, timeout=10.0)
        if resp.status_code != 200:
            print(f"[FAIL] Could not list tools: HTTP {resp.status_code}: {resp.text}")
            return 1
        tools: list[dict[str, Any]] = resp.json()
        print(f"\nRegistered Gate 3 Tools ({len(tools)} total):")
        for t in tools:
            meta_str = f"Type: {t.get('tool_type')}, Egress: {t.get('egress_type')}, Active: {t.get('active')}"
            print(f"  - {t.get('name')} ({meta_str})")
            print(f"    Capability Required: {t.get('required_capability')}")
            print(f"    Description:         {t.get('description')}")
        print()
        return 0
    except Exception as exc:
        print(f"[ERROR] Tool listing failed: {exc}")
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="mirage",
        description=f"MIRAGE {VERSION} - AI Execution Assurance Platform CLI",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # health
    p_health = subparsers.add_parser("health", help="Check gateway status and health")
    p_health.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Gateway base URL")
    p_health.set_defaults(func=cmd_health)

    # quickstart
    p_qs = subparsers.add_parser("quickstart", help="Auto-onboard local sandbox tenant and run 5-gate assurance test")
    p_qs.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Gateway base URL")
    p_qs.set_defaults(func=cmd_quickstart)

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify factual consistency of a response (Gate 4)")
    p_verify.add_argument("text", help="Response text to verify")
    p_verify.add_argument("--prompt", default="", help="Prompt that produced the response")
    p_verify.add_argument("--model", default="allam-2-7b", help="Model identifier")
    p_verify.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Gateway base URL")
    p_verify.add_argument("--api-key", default=None, help="Mirage API Key")
    p_verify.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
    p_verify.set_defaults(func=cmd_verify)

    # mcp
    p_mcp = subparsers.add_parser("mcp", help="Run the Governed MCP stdio server")
    p_mcp.add_argument("--tenant-id", default="mcp_client", help="Tenant ID for tenant isolation")
    p_mcp.set_defaults(func=cmd_mcp)

    # tools
    p_tools = subparsers.add_parser("tools", help="List registered Gate 3 tools")
    p_tools.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Gateway base URL")
    p_tools.add_argument("--api-key", default=None, help="Mirage API Key")
    p_tools.set_defaults(func=cmd_tools)

    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
