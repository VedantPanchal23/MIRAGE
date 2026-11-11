"""Hardened HTTP GET/HEAD verification probe checking external REST endpoints.

Enforces deep anti-SSRF defenses, DNS rebinding prevention, redirect re-validation,
and ActionContract target host binding.

Authoritative Specs: Reality_Verification.md §3.2, Security.md §5.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse
from collections.abc import Callable
from typing import Any

import httpcore
import httpx

from db.models import ActionContract
from shared.schemas.outcome import OutcomeVerificationRequest

from .base import AdapterProbeResult, BaseOutcomeAdapter


class SafeAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Network backend intercepting TCP socket connections to enforce IP allowlist at the connection boundary.

    Defends against Time-of-Check to Time-of-Use (TOCTOU) DNS rebinding attacks where an adversarial
    domain returns a valid public IP during preflight check but resolves to an internal loopback
    or cloud metadata IP (e.g. 127.0.0.1, 169.254.169.254) at socket connection time.
    """

    def __init__(self, is_ip_allowed_fn: Callable[[str], bool], allow_local: bool = False) -> None:
        self._backend = httpcore.AnyIOBackend()
        self._is_ip_allowed_fn = is_ip_allowed_fn
        self._allow_local = allow_local

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        stream = await self._backend.connect_tcp(
            host, port, timeout=timeout, local_address=local_address, socket_options=socket_options
        )
        if not self._allow_local:
            server_addr = stream.get_extra_info("server_addr")
            if not server_addr:
                await stream.aclose()
                raise httpcore.ConnectError(
                    "SSRF / DNS rebinding security block: unable to verify peer address at connection boundary"
                )
            peer_ip = str(server_addr[0])
            if not self._is_ip_allowed_fn(peer_ip):
                await stream.aclose()
                raise httpcore.ConnectError(
                    f"SSRF / DNS rebinding security block: connection to peer IP '{peer_ip}' is forbidden"
                )
        return stream

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> httpcore.AsyncNetworkStream:
        _ = (path, timeout, socket_options)
        raise httpcore.ConnectError("Unix domain sockets forbidden for outcome verification probes")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class SafeAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """Hardened AsyncHTTPTransport binding SafeAsyncNetworkBackend to prevent DNS rebinding and SSRF."""

    def __init__(
        self,
        is_ip_allowed_fn: Callable[[str], bool],
        allow_local: bool = False,
        **kwargs: Any,
    ) -> None:
        kwargs["trust_env"] = False
        super().__init__(**kwargs)
        backend = SafeAsyncNetworkBackend(is_ip_allowed_fn, allow_local=allow_local)
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=self._pool._ssl_context,
            network_backend=backend,
            http1=True,
            http2=False,
            max_keepalive_connections=0,
            keepalive_expiry=0.0,
        )


class HttpResourceAdapter(BaseOutcomeAdapter):
    """Hardened HTTP GET/HEAD verification probe checking external REST endpoints."""

    def _is_ip_allowed(self, host: str) -> bool:
        """SSRF defense: prevent connecting to private/loopback IP addresses or cloud metadata services."""
        clean_host = host.lower().strip()
        if (
            clean_host in ("localhost", "127.0.0.1", "::1", "metadata.google.internal", "169.254.169.254")
            or clean_host.endswith(".local")
            or clean_host.endswith(".internal")
        ):
            return False

        try:
            ip = ipaddress.ip_address(clean_host)
            return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
        except ValueError:
            try:
                addr_info = socket.getaddrinfo(clean_host, None, proto=socket.IPPROTO_TCP)
                if not addr_info:
                    return False
                for _family, _, _, _, sockaddr in addr_info:
                    ip_str = sockaddr[0]
                    ip = ipaddress.ip_address(ip_str)
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                        return False
                return True
            except Exception:
                return False

    async def verify(
        self,
        action: ActionContract,
        request: OutcomeVerificationRequest,
        tenant_id: str,
    ) -> AdapterProbeResult:
        config = request.adapter_config
        expected = request.expected_postconditions
        discrepancies: list[str] = []
        observed_state: dict[str, Any] = {}
        evidence: dict[str, Any] = {
            "adapter": "HttpResourceAdapter",
            "action_id": action.id,
            "tenant_id": tenant_id,
        }

        target_url = config.get("verification_url") or (
            action.target_resource if action.target_resource.startswith("http") else None
        )
        if not target_url:
            discrepancies.append("HttpResourceAdapter requires 'verification_url' for readback verification")
            return AdapterProbeResult(
                observed_state=action.observed_result or {},
                evidence_payload={"note": "No verification_url provided"},
                discrepancies=discrepancies,
                is_simulated=False,
                adapter_name="HttpResourceAdapter",
                success_indicated=False,
            )

        parsed = urllib.parse.urlparse(target_url)
        if parsed.scheme not in ("http", "https"):
            discrepancies.append(f"Unsupported URI scheme '{parsed.scheme}' (only http/https permitted)")
            return AdapterProbeResult(
                observed_state={},
                evidence_payload=evidence,
                discrepancies=discrepancies,
                is_simulated=False,
                adapter_name="HttpResourceAdapter",
                success_indicated=False,
            )

        if parsed.username or parsed.password:
            discrepancies.append("URI contains userinfo credentials; rejected for security")
            return AdapterProbeResult(
                observed_state={},
                evidence_payload=evidence,
                discrepancies=discrepancies,
                is_simulated=False,
                adapter_name="HttpResourceAdapter",
                success_indicated=False,
            )

        if action.target_resource.startswith("http"):
            auth_parsed = urllib.parse.urlparse(action.target_resource)
            if auth_parsed.hostname and parsed.hostname and auth_parsed.hostname.lower() != parsed.hostname.lower():
                discrepancies.append(
                    f"Target resource mismatch: verification host '{parsed.hostname}' "
                    f"does not match authorized ActionContract host '{auth_parsed.hostname}'"
                )
                return AdapterProbeResult(
                    observed_state={},
                    evidence_payload=evidence,
                    discrepancies=discrepancies,
                    is_simulated=False,
                    adapter_name="HttpResourceAdapter",
                    success_indicated=False,
                )

        allow_local = config.get("allow_localhost_for_tests", False)
        if not allow_local and not self._is_ip_allowed(parsed.hostname or ""):
            discrepancies.append(f"SSRF violation: target host '{parsed.hostname}' is a forbidden private address")
            return AdapterProbeResult(
                observed_state={},
                evidence_payload=evidence,
                discrepancies=discrepancies,
                is_simulated=False,
                adapter_name="HttpResourceAdapter",
                success_indicated=False,
            )

        expected_status = config.get("expected_status", 200)

        try:
            transport = SafeAsyncHTTPTransport(self._is_ip_allowed, allow_local=allow_local)
            async with httpx.AsyncClient(
                transport=transport,
                timeout=request.timeout_seconds,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                resp = await client.get(target_url)
                evidence["http_status"] = resp.status_code
                evidence["headers"] = dict(resp.headers)
                observed_state["status_code"] = resp.status_code

                if resp.is_redirect:
                    redir_loc = resp.headers.get("location")
                    if not redir_loc:
                        discrepancies.append("Redirect response missing Location header")
                    else:
                        redir_parsed = urllib.parse.urlparse(urllib.parse.urljoin(target_url, redir_loc))
                        if not allow_local and not self._is_ip_allowed(redir_parsed.hostname or ""):
                            discrepancies.append(
                                f"Redirect SSRF violation: redirect target '{redir_parsed.hostname}' "
                                f"is a forbidden address"
                            )
                        else:
                            resp = await client.get(redir_parsed.geturl())
                            evidence["redirect_http_status"] = resp.status_code
                            observed_state["status_code"] = resp.status_code

                if resp.status_code != expected_status:
                    discrepancies.append(
                        f"HTTP status code mismatch: expected {expected_status}, received {resp.status_code}"
                    )

                try:
                    body_json = resp.json()
                    observed_state["body"] = body_json
                    for key, val in expected.items():
                        if isinstance(body_json, dict) and body_json.get(key) != val:
                            discrepancies.append(
                                f"Response body mismatch on '{key}': expected '{val}', got '{body_json.get(key)}'"
                            )
                except Exception:
                    observed_state["body_text"] = resp.text[:500]

        except Exception as exc:
            discrepancies.append(f"HTTP verification probe failed: {exc!s}")

        return AdapterProbeResult(
            observed_state=observed_state,
            evidence_payload=evidence,
            discrepancies=discrepancies,
            is_simulated=False,
            adapter_name="HttpResourceAdapter",
            success_indicated=(len(discrepancies) == 0),
        )
