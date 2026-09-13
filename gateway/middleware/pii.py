"""PII Detection Middleware: Pre-processing pattern scanner for sensitive user data.

Implements Security & Access Document §4.3 & §6:
- Non-blocking detection of common PII types: EMAIL, PHONE, SSN, CREDIT_CARD, IP_ADDRESS
- Flagging ONLY: attaches warning metadata to response headers (X-PII-Detected, X-PII-Count, X-PII-Types)
- Never blocks or redacts upstream application requests
- Never logs raw PII values (only types and counts recorded in telemetry)
"""

import re
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from shared.logging import get_logger

logger = get_logger("pii_middleware")

# Pre-compiled high-performance regular expressions for PII detection
PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"),
    "PHONE": re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "IP_ADDRESS": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
}


class PIIDetector:
    """Scans text for personal identifiable information without persisting raw tokens."""

    @classmethod
    def scan(cls, text: str) -> dict[str, Any]:
        if not text or not isinstance(text, str):
            return {"pii_detected": False, "types": [], "count": 0}

        detected_types: list[str] = []
        total_count = 0

        for pii_type, pattern in PII_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                detected_types.append(pii_type)
                total_count += len(matches)

        return {
            "pii_detected": total_count > 0,
            "types": detected_types,
            "count": total_count,
        }


class PIIDetectionMiddleware(BaseHTTPMiddleware):
    """HTTP middleware inspecting incoming request bodies for PII indicators."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Check if PII detection should be performed on verification endpoints
        path = request.url.path
        is_verification_path = any(
            path.startswith(p) for p in ["/v1/verify", "/v1/chat/completions", "/v1/knowledge-base"]
        )

        pii_detected = False
        pii_types: list[str] = []
        pii_count = 0

        if is_verification_path and request.method == "POST":
            try:
                body_bytes = await request.body()
                # Fast string scan over body payload
                body_str = body_bytes.decode("utf-8", errors="ignore")
                result = PIIDetector.scan(body_str)
                pii_detected = result["pii_detected"]
                pii_types = result["types"]
                pii_count = result["count"]

                request.state.pii_info = result

                if pii_detected:
                    logger.info(
                        "PII patterns flagged in incoming verification request",
                        types=pii_types,
                        count=pii_count,
                        path=path,
                    )
            except Exception as exc:
                logger.debug("Could not inspect request for PII", error=str(exc))

        response = await call_next(request)

        # Attach non-blocking security warning headers
        response.headers["X-PII-Detected"] = "true" if pii_detected else "false"
        if pii_detected:
            response.headers["X-PII-Count"] = str(pii_count)
            response.headers["X-PII-Types"] = ",".join(pii_types)

        return response
