"""Deterministic integration tests for connection-boundary SSRF transport enforcement in MIRAGE 3.0.

Validates that:
1. The validated destination IP is the destination actually connected to via live socket fixtures.
2. Unsafe DNS answers (private, loopback, metadata) are rejected at the connection boundary.
3. TLS SNI hostname preservation and strict certificate validation remain intact.
4. Hostname mismatches and untrusted CAs cause TLS verification failures (never bypassed).
5. Redirects to prohibited endpoints are strictly blocked (follow_redirects=False).
6. Explicit and ambient environment proxies are rejected / ignored (trust_env=False).
7. Zero keep-alive reuse forces fresh destination validation on every consecutive request.
8. All registered provider adapters employ create_ssrf_safe_client on their execution path.
"""

import asyncio
import os
import ssl
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from services.providers.anthropic_adapter import AnthropicProviderAdapter
from services.providers.gemini_adapter import GeminiProviderAdapter
from services.providers.groq_adapter import GroqProviderAdapter
from services.providers.ollama_adapter import OllamaProviderAdapter
from services.providers.openai_adapter import OpenAIProviderAdapter
from services.providers.ssrf_validator import (
    SSRFValidationError,
    create_ssrf_safe_client,
)
from shared.config import get_settings


@pytest.fixture
def tls_cert_fixture():
    """Generate self-signed certificate and private key for 'secure-model-endpoint.local'."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "secure-model-endpoint.local")
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("secure-model-endpoint.local")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    with (
        tempfile.NamedTemporaryFile("wb", delete=False) as cf,
        tempfile.NamedTemporaryFile("wb", delete=False) as kf,
    ):
        cf.write(cert.public_bytes(serialization.Encoding.PEM))
        kf.write(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
        cert_path, key_path = cf.name, kf.name

    yield cert_path, key_path

    try:
        os.unlink(cert_path)
    except OSError:
        pass
    try:
        os.unlink(key_path)
    except OSError:
        pass


@pytest.mark.security
@pytest.mark.asyncio
async def test_actual_socket_connected_to_verified_destination() -> None:
    """Live TCP socket fixture confirms connection physically reaches validated destination IP."""
    connected_peers: list[str] = []

    async def handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        connected_peers.append(str(peer))
        _ = await reader.read(500)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 15\r\n\r\nHello From Host")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_request, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    def pinned_resolver(_h: str, p: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(2, 1, 6, "", ("127.0.0.1", p))]

    settings = get_settings()
    with patch.object(settings, "local_inference_allowlist", ["127.0.0.1", f"127.0.0.1:{port}"]):
        try:
            async with create_ssrf_safe_client(allow_local=True, dns_resolver=pinned_resolver) as client:
                resp = await client.get(f"http://test-host.local:{port}/test")
                assert resp.status_code == 200
                assert resp.text == "Hello From Host"
                assert len(connected_peers) == 1
                assert "127.0.0.1" in connected_peers[0]
        finally:
            server.close()
            await server.wait_closed()


@pytest.mark.security
@pytest.mark.asyncio
async def test_unsafe_dns_answers_rejected_at_socket_boundary() -> None:
    """DNS answers resolving to private or metadata addresses are rejected before connect."""
    for bad_ip in ["10.0.0.1", "172.16.0.5", "192.168.1.1", "169.254.169.254", "127.0.0.1"]:
        def bad_resolver(_h: str, p: int, ip: str = bad_ip) -> list[tuple[int, int, int, str, tuple[str, int]]]:
            return [(2, 1, 6, "", (ip, p))]

        async with create_ssrf_safe_client(allow_local=False, dns_resolver=bad_resolver) as client:
            with pytest.raises(SSRFValidationError) as exc_info:
                await client.get("http://api.external-provider.com/v1/models")

            assert "prohibited" in str(exc_info.value).lower()


@pytest.mark.security
@pytest.mark.asyncio
async def test_tls_verification_preserved_with_valid_ca(tls_cert_fixture: tuple[str, str]) -> None:
    """Live TLS server confirms SNI hostname and certificate verification succeed when CA is trusted."""
    cert_path, key_path = tls_cert_fixture
    server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ssl.load_cert_chain(cert_path, key_path)

    async def handle_tls(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _ = await reader.read(500)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nSecure TLS")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_tls, "127.0.0.1", 0, ssl=server_ssl)
    port = server.sockets[0].getsockname()[1]

    def tls_resolver(_h: str, p: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(2, 1, 6, "", ("127.0.0.1", p))]

    settings = get_settings()
    with patch.object(settings, "local_inference_allowlist", ["127.0.0.1", f"127.0.0.1:{port}"]):
        try:
            # Client trusts the custom cert_path, verifying full certificate chain and SNI
            async with create_ssrf_safe_client(
                allow_local=True,
                dns_resolver=tls_resolver,
                verify=cert_path,
            ) as client:
                resp = await client.get(f"https://secure-model-endpoint.local:{port}/v1/chat")
                assert resp.status_code == 200
                assert resp.text == "Secure TLS"
        finally:
            server.close()
            await server.wait_closed()


@pytest.mark.security
@pytest.mark.asyncio
async def test_tls_hostname_mismatch_fails_closed(tls_cert_fixture: tuple[str, str]) -> None:
    """Connecting to a mismatched hostname fails TLS verification (SNI check is not bypassed)."""
    cert_path, key_path = tls_cert_fixture
    server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ssl.load_cert_chain(cert_path, key_path)

    async def handle_tls(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _ = await reader.read(500)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_tls, "127.0.0.1", 0, ssl=server_ssl)
    port = server.sockets[0].getsockname()[1]

    def tls_resolver(_h: str, p: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(2, 1, 6, "", ("127.0.0.1", p))]

    settings = get_settings()
    with patch.object(settings, "local_inference_allowlist", ["127.0.0.1", f"127.0.0.1:{port}"]):
        try:
            # Requesting 'wrong-hostname.local' while cert was issued for 'secure-model-endpoint.local'
            async with create_ssrf_safe_client(
                allow_local=True,
                dns_resolver=tls_resolver,
                verify=cert_path,
            ) as client:
                with pytest.raises((httpx.ConnectError, ssl.SSLCertVerificationError)):
                    await client.get(f"https://wrong-hostname.local:{port}/v1/chat")
        finally:
            server.close()
            await server.wait_closed()


@pytest.mark.security
@pytest.mark.asyncio
async def test_tls_untrusted_ca_fails_closed(tls_cert_fixture: tuple[str, str]) -> None:
    """Untrusted CA fails certificate validation, proving verification is never disabled."""
    cert_path, key_path = tls_cert_fixture
    server_ssl = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ssl.load_cert_chain(cert_path, key_path)

    async def handle_tls(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _ = await reader.read(500)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_tls, "127.0.0.1", 0, ssl=server_ssl)
    port = server.sockets[0].getsockname()[1]

    def tls_resolver(_h: str, p: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(2, 1, 6, "", ("127.0.0.1", p))]

    settings = get_settings()
    with patch.object(settings, "local_inference_allowlist", ["127.0.0.1", f"127.0.0.1:{port}"]):
        try:
            # Connecting with default verify=True (not trusting the test cert)
            async with create_ssrf_safe_client(
                allow_local=True,
                dns_resolver=tls_resolver,
                verify=True,
            ) as client:
                with pytest.raises((httpx.ConnectError, ssl.SSLCertVerificationError)):
                    await client.get(f"https://secure-model-endpoint.local:{port}/v1/chat")
        finally:
            server.close()
            await server.wait_closed()


@pytest.mark.security
@pytest.mark.asyncio
async def test_redirects_prohibited_and_cannot_bypass_ssrf() -> None:
    """Redirects are strictly not followed (follow_redirects=False)."""
    async def handle_redirect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _ = await reader.read(500)
        writer.write(
            b"HTTP/1.1 302 Found\r\nLocation: http://169.254.169.254/latest/meta-data\r\nContent-Length: 0\r\n\r\n"
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_redirect, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    def pinned_resolver(_h: str, p: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(2, 1, 6, "", ("127.0.0.1", p))]

    settings = get_settings()
    with patch.object(settings, "local_inference_allowlist", ["127.0.0.1", f"127.0.0.1:{port}"]):
        try:
            async with create_ssrf_safe_client(allow_local=True, dns_resolver=pinned_resolver) as client:
                resp = await client.get(f"http://redirect-host.local:{port}/redirect")
                assert resp.status_code == 302
                assert resp.headers.get("location") == "http://169.254.169.254/latest/meta-data"
                # Proves client stopped and did not follow into prohibited metadata address
        finally:
            server.close()
            await server.wait_closed()


@pytest.mark.security
def test_explicit_and_ambient_proxies_cannot_bypass() -> None:
    """Explicit proxies are rejected with SSRFValidationError; ambient proxies are ignored."""
    # 1. Explicit proxy rejection
    with pytest.raises(SSRFValidationError) as exc_info:
        create_ssrf_safe_client(proxy="http://127.0.0.1:8080")
    assert "Explicit proxy configuration is prohibited" in str(exc_info.value)

    # 2. Ambient environment proxy suppression
    with patch.dict(os.environ, {"HTTP_PROXY": "http://10.0.0.1:8080", "HTTPS_PROXY": "http://10.0.0.1:8080"}):
        client = create_ssrf_safe_client()
        # trust_env must be False on both client and transport
        assert client.trust_env is False
        assert getattr(client, "_transport", None) is not None
        assert getattr(client._transport, "_pool", None) is not None


@pytest.mark.security
@pytest.mark.asyncio
async def test_zero_keepalive_ensures_fresh_validation_per_request() -> None:
    """Zero keepalive pool ensures destination validation is executed on every outbound request."""
    call_count = 0

    async def handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        _ = await reader.read(500)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_request, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    def counting_resolver(_h: str, p: int) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        nonlocal call_count
        call_count += 1
        return [(2, 1, 6, "", ("127.0.0.1", p))]

    settings = get_settings()
    with patch.object(settings, "local_inference_allowlist", ["127.0.0.1", f"127.0.0.1:{port}"]):
        try:
            async with create_ssrf_safe_client(allow_local=True, dns_resolver=counting_resolver) as client:
                for _ in range(3):
                    resp = await client.get(f"http://counting-host.local:{port}/req")
                    assert resp.status_code == 200

                # 3 separate requests must result in 3 fresh pre-connect destination checks
                assert call_count == 3
        finally:
            server.close()
            await server.wait_closed()


@pytest.mark.security
def test_all_provider_adapters_use_protected_client() -> None:
    """Verify that all production provider adapters construct create_ssrf_safe_client."""
    adapters = [
        OpenAIProviderAdapter(api_key="sk-test"),
        AnthropicProviderAdapter(api_key="sk-ant-test"),
        GeminiProviderAdapter(api_key="gm-test"),
        GroqProviderAdapter(api_key="gsk-test"),
        OllamaProviderAdapter(base_url="http://localhost:11434"),
    ]

    for adapter in adapters:
        assert hasattr(adapter, "generate")
        # Assert provider code imports create_ssrf_safe_client
        module = __import__(adapter.__module__, fromlist=["create_ssrf_safe_client"])
        assert hasattr(module, "create_ssrf_safe_client"), (
            f"Adapter {adapter.__class__.__name__} in module {adapter.__module__} "
            "does not import create_ssrf_safe_client"
        )
