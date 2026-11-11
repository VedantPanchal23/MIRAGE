"""Pluggable outcome verification adapters package.

Authoritative Specs: Reality_Verification.md §3.
"""

from .base import AdapterProbeResult, BaseOutcomeAdapter, _redact_sensitive_payload
from .database import DatabaseStateAdapter
from .event import AsyncEventAdapter
from .http import HttpResourceAdapter, SafeAsyncHTTPTransport, SafeAsyncNetworkBackend
from .observer import IndependentObserverAdapter
from .simulated import SimulatedTestAdapter

__all__ = [
    "AdapterProbeResult",
    "AsyncEventAdapter",
    "BaseOutcomeAdapter",
    "DatabaseStateAdapter",
    "HttpResourceAdapter",
    "IndependentObserverAdapter",
    "SafeAsyncHTTPTransport",
    "SafeAsyncNetworkBackend",
    "SimulatedTestAdapter",
    "_redact_sensitive_payload",
]
