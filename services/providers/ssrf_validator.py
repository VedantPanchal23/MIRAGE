"""Comprehensive SSRF and Destination Enforcement for MIRAGE 3.0 Providers.

Enforces:
1. URL parsing, scheme restriction (HTTP/HTTPS only), and rejection of embedded credentials.
2. IP normalization (IPv4, IPv6, IPv4-mapped IPv6, octal/hex representations, trailing dots).
3. Complete DNS resolution with validation of every resolved address against prohibited CIDRs
   (loopback, link-local, private, CGNAT, multicast, reserved, and cloud metadata).
4. Explicit local inference allowlisting (Ollama/on-prem): arbitrary private IPs are prohibited.
5. Strict redirect prohibition (follow_redirects=False) across all provider HTTP clients.
6. Connection-boundary socket-level enforcement: custom SSRFSafeNetworkBackend intercepts
   outbound TCP connections at socket connect time, eliminating DNS rebinding (TOCTOU) vectors.
"""

import ipaddress
import socket
import ssl
from collections.abc import Callable, Iterable
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx

from shared.config import get_settings


class SSRFValidationError(Exception):
    """Raised when an endpoint URL violates SSRF destination policies."""

    pass


# Canonical prohibited IPv4 & IPv6 CIDR blocks
PROHIBITED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),  # Current network (only valid as source)
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918 private
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 Shared Address Space / CGNAT (includes 100.100.100.200)
    ipaddress.ip_network("127.0.0.0/8"),  # RFC 1122 Loopback
    ipaddress.ip_network("169.254.0.0/16"),  # RFC 3927 Link Local (includes 169.254.169.254)
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918 private
    ipaddress.ip_network("192.0.0.0/24"),  # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918 private
    ipaddress.ip_network("198.18.0.0/15"),  # Benchmarking
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),  # Multicast
    ipaddress.ip_network("240.0.0.0/4"),  # Reserved
    ipaddress.ip_network("255.255.255.255/32"),  # Broadcast
    # IPv6 blocks
    ipaddress.ip_network("::/128"),  # Unspecified
    ipaddress.ip_network("::1/128"),  # Loopback
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
    ipaddress.ip_network("100::/64"),  # Discard prefix
    ipaddress.ip_network("2001:db8::/32"),  # Documentation
    ipaddress.ip_network("fc00::/7"),  # Unique Local (ULA private)
    ipaddress.ip_network("fe80::/10"),  # Link-local
    ipaddress.ip_network("ff00::/8"),  # Multicast
]

PROHIBITED_METADATA_HOSTS = {
    "169.254.169.254",
    "100.100.100.200",
    "metadata.google.internal",
    "instance-data",
}

DEFAULT_LOCAL_HOST_ALLOWLIST = {
    "localhost",
    "127.0.0.1",
    "::1",
}

DEFAULT_LOCAL_PORT_ALLOWLIST = {11434, 8000, 8080}


def _validate_local_endpoint(raw_host: str, host_lower: str, port: int, url_clean: str) -> str:
    """Validate that local endpoint host and port are strictly approved."""
    settings = get_settings()
    extra_allowed = [h.lower() for h in (getattr(settings, "local_inference_allowlist", []) or [])]

    # 1. Host check
    if host_lower not in DEFAULT_LOCAL_HOST_ALLOWLIST and host_lower not in extra_allowed:
        allowed_hosts_str = ", ".join(sorted(DEFAULT_LOCAL_HOST_ALLOWLIST))
        raise SSRFValidationError(
            f"Local inference host '{raw_host}' is not in approved local allowlist [{allowed_hosts_str}]"
        )

    # 2. Port check: protect internal infrastructure services (e.g. Redis 6379, Postgres 5432)
    allowed_ports = set(DEFAULT_LOCAL_PORT_ALLOWLIST)
    for item in extra_allowed:
        if ":" in item:
            try:
                allowed_ports.add(int(item.split(":")[-1]))
            except ValueError:
                pass
    if port not in allowed_ports:
        raise SSRFValidationError(
            f"Local inference port {port} is not in approved port allowlist {sorted(allowed_ports)}"
        )
    return url_clean


def _check_ip_prohibited(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if IP belongs to any prohibited network or special range."""
    # Check if IPv6 address is IPv4-mapped
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _check_ip_prohibited(ip.ipv4_mapped)

    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return True

    for net in PROHIBITED_NETWORKS:
        if ip in net:
            return True

    return False


def validate_safe_provider_url(
    url: str,
    allow_local: bool = False,
    resolve_dns: bool = True,
) -> str:
    """Validate provider endpoint URL against SSRF and unauthorized network egress.

    Args:
        url: The provider base URL to inspect.
        allow_local: Whether strictly allowlisted local inference endpoints (e.g. Ollama) are permitted.
        resolve_dns: Whether to perform DNS resolution and check every resolved address.

    Returns:
        The validated URL.

    Raises:
        SSRFValidationError: If the destination violates SSRF or network isolation policy.
    """
    if not url or not isinstance(url, str):
        raise SSRFValidationError("Provider endpoint URL cannot be empty")

    url_clean = url.strip()
    parsed = urlsplit(url_clean)

    # 1. Scheme validation
    if parsed.scheme.lower() not in ("http", "https"):
        raise SSRFValidationError(f"Invalid URL scheme '{parsed.scheme}'; only http and https are allowed")

    # 2. Reject embedded credentials
    if parsed.username or parsed.password:
        raise SSRFValidationError("URLs with embedded user credentials (username/password) are prohibited")

    # 3. Hostname normalization
    raw_host = (parsed.hostname or "").strip().rstrip(".")
    if not raw_host:
        raise SSRFValidationError("Provider URL authority/hostname is missing or empty")

    host_lower = raw_host.lower()

    # 4. Explicit cloud metadata host names
    if host_lower in PROHIBITED_METADATA_HOSTS or any(host_lower.endswith(f".{m}") for m in PROHIBITED_METADATA_HOSTS):
        raise SSRFValidationError(f"Destination '{raw_host}' is a prohibited cloud metadata endpoint")

    # 5. Check if host is an IP literal
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    is_ip_literal = False
    ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    try:
        ip_obj = ipaddress.ip_address(raw_host.strip("[]"))
        is_ip_literal = True
    except ValueError:
        is_ip_literal = False

    if is_ip_literal and ip_obj is not None:
        if allow_local:
            return _validate_local_endpoint(raw_host, str(ip_obj), port, url_clean)
        else:
            if _check_ip_prohibited(ip_obj):
                raise SSRFValidationError(
                    f"Destination IP '{ip_obj}' is prohibited (loopback, private, link-local, or metadata)"
                )
        return url_clean

    # 6. Hostname handling for local inference
    if allow_local:
        return _validate_local_endpoint(raw_host, host_lower, port, url_clean)

    # 7. For non-local destinations: reject literal localhost names
    if host_lower in ("localhost", "ip6-localhost", "ip6-loopback") or host_lower.endswith(".localhost"):
        raise SSRFValidationError(f"Loopback hostname '{raw_host}' is prohibited for cloud providers")

    # 8. DNS Resolution and validation of every returned address
    if resolve_dns:
        try:
            addr_info = socket.getaddrinfo(raw_host, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as dns_err:
            raise SSRFValidationError(f"DNS resolution failed for provider host '{raw_host}': {dns_err}") from dns_err

        if not addr_info:
            raise SSRFValidationError(f"DNS resolution returned no addresses for host '{raw_host}'")

        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            try:
                resolved_ip = ipaddress.ip_address(ip_str)
            except ValueError as ip_err:
                raise SSRFValidationError(f"Invalid resolved IP '{ip_str}' from host '{raw_host}'") from ip_err

            if _check_ip_prohibited(resolved_ip):
                raise SSRFValidationError(
                    f"Host '{raw_host}' resolved to prohibited address '{resolved_ip}' "
                    "(loopback, private, link-local, or cloud metadata)"
                )

    return url_clean


class SSRFSafeNetworkBackend(httpcore.AnyIOBackend):
    """Custom network backend enforcing destination SSRF checks at the socket connection boundary.

    Prevents DNS rebinding / TOCTOU attacks by resolving DNS and verifying every resolved IP address
    immediately prior to TCP connect, then pinning the connection to the verified IP.
    """

    def __init__(
        self,
        allow_local: bool = False,
        dns_resolver: Callable[[str, int], list[Any]] | None = None,
    ) -> None:
        super().__init__()
        self.allow_local = allow_local
        self._dns_resolver = dns_resolver

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> Any:
        raw_host = (host or "").strip().rstrip(".")
        if not raw_host:
            raise SSRFValidationError("Outbound connection host is empty")

        host_lower = raw_host.lower()

        # Cloud metadata hostname check
        if host_lower in PROHIBITED_METADATA_HOSTS or any(
            host_lower.endswith(f".{m}") for m in PROHIBITED_METADATA_HOSTS
        ):
            raise SSRFValidationError(f"Outbound connection to cloud metadata host '{raw_host}' is blocked")

        # Check if host is an IP literal
        is_ip = False
        ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
        try:
            ip_obj = ipaddress.ip_address(raw_host.strip("[]"))
            is_ip = True
        except ValueError:
            is_ip = False

        if is_ip and ip_obj is not None:
            if self.allow_local:
                _validate_local_endpoint(raw_host, str(ip_obj), port, f"http://{raw_host}:{port}")
            else:
                if _check_ip_prohibited(ip_obj):
                    raise SSRFValidationError(
                        f"Outbound connection to prohibited IP '{ip_obj}' is blocked (loopback/private/metadata)"
                    )
            pinned_ip = str(ip_obj)
        else:
            # Hostname: check localhost string if local not allowed
            if not self.allow_local and (
                host_lower in ("localhost", "ip6-localhost", "ip6-loopback") or host_lower.endswith(".localhost")
            ):
                raise SSRFValidationError(f"Outbound loopback host '{raw_host}' is blocked")

            # Resolve DNS immediately before connecting to defeat DNS rebinding
            resolver = self._dns_resolver or (lambda h, p: socket.getaddrinfo(h, p, proto=socket.IPPROTO_TCP))
            try:
                addr_info = resolver(raw_host, port)
            except Exception as dns_err:
                raise SSRFValidationError(f"DNS resolution failed for '{raw_host}': {dns_err}") from dns_err

            if not addr_info:
                raise SSRFValidationError(f"DNS resolution returned no addresses for host '{raw_host}'")

            verified_safe_ip: str | None = None
            for entry in addr_info:
                sockaddr = entry[4]
                ip_str = str(sockaddr[0])
                try:
                    resolved_ip = ipaddress.ip_address(ip_str)
                except ValueError as ip_err:
                    raise SSRFValidationError(f"Invalid resolved IP '{ip_str}' for host '{raw_host}'") from ip_err

                if self.allow_local:
                    _validate_local_endpoint(raw_host, ip_str, port, f"http://{raw_host}:{port}")
                else:
                    if _check_ip_prohibited(resolved_ip):
                        raise SSRFValidationError(
                            f"Host '{raw_host}' resolved to prohibited address '{resolved_ip}' "
                            "(DNS rebinding / private egress blocked)"
                        )

                if verified_safe_ip is None:
                    verified_safe_ip = ip_str

            assert verified_safe_ip is not None
            pinned_ip = verified_safe_ip

        # Connect directly to the verified safe IP to defeat DNS rebinding
        return await super().connect_tcp(
            pinned_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> Any:
        raise SSRFValidationError("Unix domain sockets are prohibited for outbound LLM provider connections")


class SSRFProtectedTransport(httpx.AsyncHTTPTransport):
    """Async HTTP transport enforcing connection-boundary SSRF safety, proxy denial, and zero keepalive reuse.

    Dependency Compatibility Boundary:
    - httpx >= 0.27.0
    - httpcore >= 1.0.0
    Constructs an explicit httpcore.AsyncConnectionPool with a custom network_backend and zero keep-alive
    reuse without relying on private httpx/httpcore attributes.
    """

    def __init__(
        self,
        allow_local: bool = False,
        dns_resolver: Callable[[str, int], list[Any]] | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if kwargs.get("proxy") is not None or kwargs.get("proxies") is not None:
            raise SSRFValidationError(
                "Explicit proxy configuration is prohibited for outbound LLM provider connections"
            )

        # Disable ambient environment proxies
        kwargs["trust_env"] = False

        verify = kwargs.get("verify", True)
        cert = kwargs.get("cert")
        if isinstance(verify, ssl.SSLContext):
            ssl_context = verify
        else:
            ssl_context = httpx.create_ssl_context(verify=verify, cert=cert, trust_env=False)

        super().__init__(*args, **kwargs)

        backend = SSRFSafeNetworkBackend(
            allow_local=allow_local,
            dns_resolver=dns_resolver,
        )
        # Bind through official AsyncConnectionPool network_backend constructor argument
        # Enforce zero keep-alive connections so every request performs immediate pre-connect verification
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            network_backend=backend,
            http1=kwargs.get("http1", True),
            http2=kwargs.get("http2", False),
            max_connections=50,
            max_keepalive_connections=0,
            keepalive_expiry=0.0,
        )


def create_ssrf_safe_transport(
    allow_local: bool = False,
    dns_resolver: Callable[[str, int], list[Any]] | None = None,
    **kwargs: Any,
) -> httpx.AsyncHTTPTransport:
    """Create an AsyncHTTPTransport wired with connection-boundary SSRF enforcement."""
    return SSRFProtectedTransport(
        allow_local=allow_local,
        dns_resolver=dns_resolver,
        **kwargs,
    )


def create_ssrf_safe_client(
    allow_local: bool = False,
    timeout: float = 30.0,
    dns_resolver: Callable[[str, int], list[Any]] | None = None,
    **kwargs: Any,
) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient enforcing connection-boundary SSRF safety and redirect blocking."""
    if "proxy" in kwargs or "proxies" in kwargs:
        raise SSRFValidationError("Explicit proxy configuration is prohibited for outbound LLM provider connections")
    kwargs["trust_env"] = False
    verify = kwargs.pop("verify", True)
    cert = kwargs.pop("cert", None)
    transport = create_ssrf_safe_transport(
        allow_local=allow_local,
        dns_resolver=dns_resolver,
        verify=verify,
        cert=cert,
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=False,
        verify=verify,
        cert=cert,
        **kwargs,
    )
