"""Structured JSON logging configuration using structlog."""

import logging
import sys
from typing import Any, cast

import structlog


def configure_logging(service_name: str = "mirage", log_level: str = "INFO", json_format: bool = True) -> None:
    """Configure structured logging pipeline for application services."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Add service context processor
    def add_service_context(
        _logger: Any,
        _method_name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        event_dict["service"] = service_name
        return event_dict

    # Secret sanitizer processor
    def sanitize_secrets_processor(
        _logger: Any,
        _method_name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        import re

        cred_pattern = re.compile(r"://([^:]+):([^@]+)@")
        for key, value in list(event_dict.items()):
            if any(k in key.lower() for k in ("password", "secret", "token", "api_key", "credentials")):
                event_dict[key] = "***"
            elif isinstance(value, str):
                event_dict[key] = cred_pattern.sub(r"://\1:***@", value)
        return event_dict

    shared_processors.insert(0, sanitize_secrets_processor)
    shared_processors.insert(0, add_service_context)

    formatter_processor: structlog.types.Processor
    if json_format:
        formatter_processor = structlog.processors.JSONRenderer()
    else:
        formatter_processor = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                formatter_processor,
            ],
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))


def get_logger(name: str = "mirage") -> structlog.stdlib.BoundLogger:
    """Retrieve a bound structured logger instance."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
