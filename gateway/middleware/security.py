"""Security headers and trace ID injection middleware."""

import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Injects enterprise-grade security headers and X-Trace-ID into all responses."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        trace_id = request.headers.get("X-Trace-ID", uuid.uuid4().hex)
        request.state.trace_id = trace_id

        response = await call_next(request)

        response.headers["X-Trace-ID"] = trace_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'none'"

        return response
