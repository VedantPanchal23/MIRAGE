"""OpenTelemetry distributed tracing setup with W3C Trace Context propagation."""

import hashlib
import socket
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlparse

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()


def _is_collector_reachable(endpoint: str, timeout_sec: float = 0.1) -> bool:
    """Quick socket check to verify whether OpenTelemetry collector is listening."""
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port or 4317
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except (TimeoutError, ConnectionRefusedError, OSError):
        return False


def configure_tracer(service_name: str = "mirage-gateway", otlp_endpoint: str = "http://localhost:4317") -> Tracer:
    """Initialize OpenTelemetry tracer provider with OTLP gRPC export if collector is listening."""
    resource = Resource.create(attributes={"service.name": service_name})
    provider = TracerProvider(resource=resource)

    if _is_collector_reachable(otlp_endpoint):
        try:
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
        except Exception:
            pass

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


def get_current_trace_id() -> str:
    """Retrieve current active trace ID formatted as a 32-character hex string."""
    span = trace.get_current_span()
    context = span.get_span_context()
    if context.is_valid:
        return f"{context.trace_id:032x}"
    return uuid.uuid4().hex


def get_current_span_id() -> str:
    """Retrieve current active span ID formatted as a 16-character hex string."""
    span = trace.get_current_span()
    context = span.get_span_context()
    if context.is_valid:
        return f"{context.span_id:016x}"
    return uuid.uuid4().hex[:16]


def sanitize_trace_attributes(attributes: dict[str, Any] | None) -> dict[str, Any]:
    """Sanitize span attributes ensuring compliance with Section 10.6 of Security Document.

    Raw prompts, responses, or document text are never stored in traces—only cryptographic hashes,
    latencies, metrics, and non-PII identifiers.
    """
    if not attributes:
        return {}

    sanitized: dict[str, Any] = {}
    for key, value in attributes.items():
        # Strip potential raw content keys, replacing with hash if string
        if key in ("prompt", "response", "document_text", "raw_text", "evidence_text"):
            if isinstance(value, str):
                sanitized[f"{key}_sha256"] = hashlib.sha256(value.encode("utf-8")).hexdigest()
            else:
                sanitized[f"{key}_sha256"] = "invalid_type"
        else:
            sanitized[key] = value

    return sanitized


@contextmanager
def trace_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    tracer_name: str = "mirage-tracer",
) -> Generator[Span, None, None]:
    """Context manager creating an OpenTelemetry span with sanitized operational attributes."""
    tracer = trace.get_tracer(tracer_name)
    clean_attrs = sanitize_trace_attributes(attributes)

    with tracer.start_as_current_span(name, attributes=clean_attrs) as span:
        yield span


def inject_w3c_context(carrier: dict[str, str] | None = None) -> dict[str, str]:
    """Inject W3C traceparent context into dictionary headers for cross-service propagation."""
    headers = carrier.copy() if carrier else {}
    _PROPAGATOR.inject(carrier=headers)
    return headers


def extract_w3c_context(carrier: dict[str, str]) -> None:
    """Extract W3C traceparent context from dictionary headers."""
    _PROPAGATOR.extract(carrier=carrier)
