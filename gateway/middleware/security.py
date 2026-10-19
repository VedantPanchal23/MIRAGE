"""Security headers, trace/correlation ID injection, and header sanitization middleware."""

import re
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

_HEADER_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{8,64}$")


def _sanitize_header_id(raw_val: str | None, default_generator: Callable[[], str]) -> str:
    """Validate and sanitize external tracing identifiers to prevent log and header injection attacks."""
    if not raw_val or not isinstance(raw_val, str):
        return default_generator()
    cleaned = raw_val.strip()
    if not _HEADER_ID_REGEX.match(cleaned):
        return default_generator()
    return cleaned


class HeaderSanitizationMiddleware:
    """Strips untrusted client-supplied identity headers at the ASGI boundary.

    Implements Security & Access Document §2.2:
    Headers specifying roles are ignored and stripped before downstream application logic.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            # Identity is established exclusively by a credential plus control-plane lookup.
            prohibited = {b"x-role", b"x-tenant-id", b"x-agent-id", b"x-identity-id", b"x-capability"}
            sanitized_headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() not in prohibited]
            scope["headers"] = sanitized_headers
        await self.app(scope, receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects enterprise-grade security headers, X-Trace-ID, and X-Correlation-ID into all responses."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        trace_id = _sanitize_header_id(request.headers.get("X-Trace-ID"), lambda: uuid.uuid4().hex)
        correlation_id = _sanitize_header_id(request.headers.get("X-Correlation-ID"), lambda: trace_id)

        request.state.trace_id = trace_id
        request.state.correlation_id = correlation_id

        # Bind tracing context to structlog contextvars for correlated logging across all modules
        structlog.contextvars.bind_contextvars(
            trace_id=trace_id,
            correlation_id=correlation_id,
        )

        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'none'"

        return response
