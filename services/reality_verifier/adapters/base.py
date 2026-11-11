"""Base classes and utility functions for reality verification adapters.

Authoritative Specs: Reality_Verification.md §3, Technical_Architecture.md §8.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from db.models import ActionContract
from shared.schemas.outcome import OutcomeVerificationRequest


class AdapterProbeResult:
    """Standardized result returned by an outcome verification adapter."""

    def __init__(
        self,
        observed_state: dict[str, Any],
        evidence_payload: dict[str, Any],
        discrepancies: list[str],
        is_simulated: bool,
        adapter_name: str,
        success_indicated: bool = True,
        reconciliation_notes: list[str] | None = None,
    ) -> None:
        self.observed_state = observed_state
        self.evidence_payload = evidence_payload
        self.discrepancies = discrepancies
        self.is_simulated = is_simulated
        self.adapter_name = adapter_name
        self.success_indicated = success_indicated
        self.reconciliation_notes = reconciliation_notes or []


class BaseOutcomeAdapter(ABC):
    """Abstract base class for pluggable reality verification adapters."""

    @abstractmethod
    async def verify(
        self,
        action: ActionContract,
        request: OutcomeVerificationRequest,
        tenant_id: str,
    ) -> AdapterProbeResult:
        """Execute reality verification probe against target system."""
        pass


_REDACT_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)sk-[a-zA-Z0-9_\-]{16,}"), "[REDACTED_SECRET]"),
    (re.compile(r"(?i)ghp_[a-zA-Z0-9]{20,}"), "[REDACTED_SECRET]"),
    (re.compile(r"(://[^:]+:)([^@]+)(@)"), r"\1[REDACTED]\3"),
    (
        re.compile(r"(?i)(password|secret|token|api_key|apikey|private_key)\s*[:=]\s*['\"]?([^'\"\s,]+)['\"]?"),
        r"\1=[REDACTED]",
    ),
]
_SENSITIVE_KEY_NAMES = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_token",
    "private_key",
    "auth",
    "authorization",
    "credentials",
    "client_secret",
}


def _redact_sensitive_payload(val: Any) -> Any:
    """Recursively scrub credentials, tokens, and secrets from observation and evidence payloads."""
    if isinstance(val, str):
        result = val
        for pat, repl in _REDACT_PATTERNS:
            result = pat.sub(repl, result)
        return result
    elif isinstance(val, dict):
        redacted_dict: dict[str, Any] = {}
        for k, v in val.items():
            if str(k).lower() in _SENSITIVE_KEY_NAMES:
                redacted_dict[k] = "[REDACTED]"
            else:
                redacted_dict[k] = _redact_sensitive_payload(v)
        return redacted_dict
    elif isinstance(val, list):
        return [_redact_sensitive_payload(item) for item in val]
    return val
