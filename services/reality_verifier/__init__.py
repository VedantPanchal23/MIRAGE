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
from .audit_verifier import (
    acquire_audit_chain_state,
    append_audit_trail_entry,
    extract_result_records,
    validate_audit_correlation,
    validate_chain_record_fields_and_hash,
    verify_record_against_audit_trail,
)
from .evaluator import (
    evaluate_outcome_status_and_confidence,
    record_to_contract,
    validate_outcome_transition,
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
    "acquire_audit_chain_state",
    "append_audit_trail_entry",
    "db_session",
    "evaluate_outcome_status_and_confidence",
    "extract_result_records",
    "reality_verifier_service",
    "reconcile_output_with_outcome",
    "record_to_contract",
    "validate_audit_correlation",
    "validate_chain_record_fields_and_hash",
    "validate_outcome_transition",
    "verify_record_against_audit_trail",
]
