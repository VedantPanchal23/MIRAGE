"""Unit tests for structured logging and distributed tracing utilities."""

import pytest

from shared.logging import configure_logging, get_logger
from shared.tracing import configure_tracer, get_current_trace_id


@pytest.mark.unit
class TestLoggingAndTracing:
    def test_logger_configuration(self) -> None:
        configure_logging(service_name="test-service", log_level="DEBUG", json_format=False)
        logger = get_logger("test")
        assert logger is not None
        # Logging an event should not raise
        logger.info("Test log event", tenant_id="tenant_xyz")

    def test_trace_id_generation(self) -> None:
        configure_tracer(service_name="test-tracer")
        trace_id = get_current_trace_id()
        assert isinstance(trace_id, str)
        assert len(trace_id) == 32
