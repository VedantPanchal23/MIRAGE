"""OpenTelemetry distributed tracing setup with W3C Trace Context propagation."""

import uuid

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Tracer


def configure_tracer(service_name: str = "mirage-gateway", otlp_endpoint: str = "http://localhost:4317") -> Tracer:
    """Initialize OpenTelemetry tracer provider with OTLP gRPC export."""
    resource = Resource.create(attributes={"service.name": service_name})
    provider = TracerProvider(resource=resource)

    try:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
    except Exception:
        # Fallback to in-memory/noop if collector unavailable in dev/test
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
