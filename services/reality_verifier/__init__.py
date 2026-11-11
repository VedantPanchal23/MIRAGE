"""Gate 5 Outcome Assurance and Reality Verification Service Package.

Authoritative module for real-world state verification, epistemic observability,
monotonic state transitions, and cryptographic ActionContract binding.
"""

from db import session as db_session

from .adapters import (
    AdapterProbeResult,
    AsyncEventAdapter,
    BaseOutcomeAdapter,
    DatabaseStateAdapter,
    HttpResourceAdapter,
    IndependentObserverAdapter,
    SafeAsyncHTTPTransport,
    SafeAsyncNetworkBackend,
    SimulatedTestAdapter,
    _redact_sensitive_payload,
)
from .reconciliation import (
    VALID_OUTCOME_TRANSITIONS,
    _extract_clauses,
    _normalize_text,
    _strip_quotes_and_citations,
    reconcile_output_with_outcome,
)
from .service import (
    RealityVerifierService,
    reality_verifier_service,
)

__all__ = [
    "AdapterProbeResult",
    "AsyncEventAdapter",
    "BaseOutcomeAdapter",
    "DatabaseStateAdapter",
    "HttpResourceAdapter",
    "IndependentObserverAdapter",
    "RealityVerifierService",
    "SafeAsyncHTTPTransport",
    "SafeAsyncNetworkBackend",
    "SimulatedTestAdapter",
    "VALID_OUTCOME_TRANSITIONS",
    "_extract_clauses",
    "_normalize_text",
    "_redact_sensitive_payload",
    "_strip_quotes_and_citations",
    "db_session",
    "reconcile_output_with_outcome",
    "reality_verifier_service",
]
