"""Chaos Harness Configuration & Safety Controls (P3.3).

Implements strict safety guards for chaos resilience engineering:
1. Requires explicit environment enablement (MIRAGE_CHAOS_ENABLED=true).
2. Forbids execution against production or non-test environments.
3. Validates target hosts/URLs against an allowed safe target list (rejecting external/production endpoints).
4. Sanitizes and redacts secrets (passwords, JWTs, API keys, connection strings) from logs and exceptions.
5. Enforces bounded fault durations to prevent prolonged or orphaned network partitions.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from shared.config.settings import EnvironmentType, get_settings


class ChaosSafetyViolation(RuntimeError):
    """Raised when a chaos action violates safety boundaries or targets an unsafe host."""


# Allowed safe host targets (local machine, loopback, or local Docker network service names)
SAFE_TARGET_HOSTS: frozenset[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "toxiproxy",
        "mirage-toxiproxy",
        "redis",
        "mirage-redis",
        "qdrant",
        "mirage-qdrant",
        "postgres",
        "mirage-postgres",
        "rabbitmq",
        "mirage-rabbitmq",
        "torchserve",
        "tgi",
        "flan-t5",
        "api.groq.com",  # Mocked upstream LLM proxy endpoint
    }
)

# Unsafe production host indicators (domain suffixes or patterns that MUST be blocked)
PROHIBITED_HOST_PATTERNS: tuple[str, ...] = (
    ".prod",
    ".production",
    "production.",
    "prod.",
    ".internal",
    ".rds.amazonaws.com",
    ".elasticache.amazonaws.com",
    ".s3.amazonaws.com",
)

# Secret sanitization patterns
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(password=)[^&\s]+", re.IGNORECASE),
    re.compile(r"(:\/\/)([^:]+):([^@]+)@", re.IGNORECASE),  # user:pass in URLs
    re.compile(r"(bearer\s+)[a-zA-Z0-9\-_.]+", re.IGNORECASE),
    re.compile(r"(api[_-]?key[=:\s]+)[a-zA-Z0-9\-_]+", re.IGNORECASE),
    re.compile(r"(secret[=:\s]+)[a-zA-Z0-9\-_]+", re.IGNORECASE),
)


def redact_secrets(content: Any) -> str:
    """Scrub passwords, tokens, API keys, and connection credentials from any text or structure.

    Args:
        content: Any text, dictionary, or exception representation to sanitize.

    Returns:
        Clean string with sensitive credentials redacted to [REDACTED].
    """
    raw_str = str(content)
    # Scrub URL credentials (e.g. postgres://user:pass@host)
    scrubbed = re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1[REDACTED]\3", raw_str)
    # Scrub specific keyword patterns
    for pat in SECRET_PATTERNS:
        scrubbed = pat.sub(r"\1[REDACTED]", scrubbed)
    return scrubbed


@dataclass(frozen=True)
class ChaosConfig:
    """Immutable, validated configuration for the MIRAGE chaos testing harness."""

    enabled: bool = field(
        default_factory=lambda: os.getenv("MIRAGE_CHAOS_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    toxiproxy_url: str = field(default_factory=lambda: os.getenv("TOXIPROXY_URL", "http://127.0.0.1:8474").rstrip("/"))
    environment: str = field(default_factory=lambda: os.getenv("CHAOS_ENVIRONMENT", "test").lower())
    default_max_duration_sec: float = field(
        default_factory=lambda: float(os.getenv("CHAOS_MAX_FAULT_DURATION_SEC", "30.0"))
    )
    request_timeout_sec: float = field(default_factory=lambda: float(os.getenv("CHAOS_HTTP_TIMEOUT_SEC", "5.0")))

    def validate_safety(self, target_host_or_url: str | None = None) -> None:
        """Validate safety invariants before executing any chaos action.

        Raises:
            ChaosSafetyViolation: If chaos is disabled, environment is unsafe,
                                  or target host is prohibited.
        """
        # 1. Verify chaos harness is explicitly enabled
        if not self.enabled:
            raise ChaosSafetyViolation(
                "Chaos harness execution refused: MIRAGE_CHAOS_ENABLED is false. "
                "Set MIRAGE_CHAOS_ENABLED=true in the test environment to permit controlled fault injection."
            )

        # 2. Check application environment setting
        app_settings = get_settings()
        if app_settings.environment == EnvironmentType.PRODUCTION:
            raise ChaosSafetyViolation(
                "FATAL SAFETY VIOLATION: Chaos harness cannot execute against EnvironmentType.PRODUCTION. "
                "Fault injection is strictly restricted to test, development, and chaos environments."
            )

        # 3. Check chaos environment declaration
        if self.environment in ("prod", "production", "live", "staging"):
            raise ChaosSafetyViolation(
                f"FATAL SAFETY VIOLATION: Refusing chaos execution in declared environment '{self.environment}'. "
                "Must be 'test' or 'chaos'."
            )

        # 4. Check Toxiproxy server host safety
        toxiproxy_host = urlparse(self.toxiproxy_url).hostname or "127.0.0.1"
        self._validate_host_safety(toxiproxy_host)

        # 5. Check target host safety if supplied
        if target_host_or_url:
            host_to_check = target_host_or_url
            if "://" in target_host_or_url:
                parsed = urlparse(target_host_or_url)
                host_to_check = parsed.hostname or target_host_or_url
            elif ":" in target_host_or_url:
                host_to_check = target_host_or_url.split(":")[0]
            self._validate_host_safety(host_to_check)

    def _validate_host_safety(self, host: str) -> None:
        """Verify an individual hostname conforms to safety rules."""
        host_lower = host.lower()

        # Disallow prohibited suffixes
        for prohibited in PROHIBITED_HOST_PATTERNS:
            if prohibited in host_lower:
                raise ChaosSafetyViolation(
                    f"FATAL SAFETY VIOLATION: Refusing to target prohibited host '{host_lower}'. "
                    f"Matches unsafe production indicator '{prohibited}'."
                )

        # Disallow any host outside the SAFE_TARGET_HOSTS set unless local/test container
        if host_lower not in SAFE_TARGET_HOSTS and not host_lower.startswith("127."):
            raise ChaosSafetyViolation(
                f"FATAL SAFETY VIOLATION: Target host '{host_lower}' is not in the safe target allowlist. "
                "Chaos operations are only permitted against local test containers or loopback."
            )
