"""Output and Outcome consistency reconciliation engine.

Prevents models from falsely asserting completion or physical state transitions
when reality verification was not established.

Authoritative Specs: Reality_Verification.md §4, Input_Output_Assurance.md §6.
"""

from __future__ import annotations

import re
import unicodedata

from shared.schemas.outcome import (
    OutcomeReconciliationResult,
    OutcomeStatus,
    OutcomeVerificationContract,
)

# Completion claim patterns for Output <-> Outcome consistency reconciliation
_COMPLETION_ASSERTION_PATTERNS = (
    re.compile(
        r"\b(?:I (?:have )?(?:transferred|deleted|updated|executed|deployed|"
        r"paid|sent|removed|modified|cancelled|refunded|processed))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:transfer|payment|deletion|removal|deployment|action|execution|refund|"
        r"transaction|update|email|notification|message|item|items|batch|task|tasks|order|orders) "
        r"(?:has been |have been |was |were |is |are )"
        r"(?:completed|processed|executed|successful|finalized|done|sent|delivered))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:completed|processed|executed|finalized) "
        r"(?:the |all )?"
        r"(?:transfer|payment|deletion|deployment|action|refund|transaction|email|notification|items|batch|tasks))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:successfully (?:transferred|deleted|updated|executed|deployed|"
        r"paid|sent|removed|modified|refunded|processed|created|finished|completed))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:transferred|deleted|updated|executed|deployed|"
        r"paid|sent|removed|modified|refunded|processed|created|finished|completed) successfully)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:has|have) (?:succeeded|been completed|been processed|been executed|"
        r"been sent|been deleted|been updated|been paid|been transferred))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the )?(?:transfer|payment|transaction|wire|funds) (?:went through|has gone through|have gone through)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:funds|money|payment|wire) (?:have |has )?reached (?:the )?recipient\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the )?(?:database|db|record|table) (?:has been |was |is )?updated\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the )?(?:deployment|service|release|app) is (?:now )?live\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:the|first|second|this) )?(?:[a-z0-9_]+ )?"
        r"(?:transfer|payment|order|orders|action|transaction|operation|update|task) (?:has )?succeeded\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:it|this) has (?:now )?(?:completed|finished|succeeded)\b",
        re.IGNORECASE,
    ),
)


def _normalize_text(text: str) -> str:
    """Normalize unicode, whitespace, and typographic quotes to standard ASCII."""
    norm = unicodedata.normalize("NFKC", text)
    norm = re.sub(r"[\u200B-\u200D\uFEFF]", "", norm)
    norm = norm.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def _strip_quotes_and_citations(text: str) -> str:
    """Strip text inside quotation marks and markdown blockquotes so quotations are not treated as agent assertions."""
    text = re.sub(r"^\s*>.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r'"[^"\n]*"', " ", text)
    text = re.sub(r"(?:^|\s)'(?:[^'\n]|'')*'(?:\s|$)", " ", text)
    return text


def _extract_clauses(text: str) -> list[str]:
    """Split text into independent clauses using sentence terminators and contrastive conjunctions."""
    sentences = re.split(r"[.!?;\n]+", text)
    clauses: list[str] = []
    contrastive_re = re.compile(r"\b(?:but|however|although|though|yet|nevertheless|whereas|while)\b", re.IGNORECASE)
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        subparts = contrastive_re.split(s)
        for part in subparts:
            part = part.strip()
            if part:
                clauses.append(part)
    return clauses


# Canonical monotonic outcome state machine transition rules
VALID_OUTCOME_TRANSITIONS: dict[OutcomeStatus, set[OutcomeStatus]] = {
    OutcomeStatus.PENDING_VERIFICATION: {
        OutcomeStatus.PENDING_VERIFICATION,
        OutcomeStatus.VERIFIED_SUCCESS,
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        OutcomeStatus.PARTIAL_ACHIEVEMENT,
        OutcomeStatus.PARTIAL,
        OutcomeStatus.VERIFIED_FAILURE,
        OutcomeStatus.FAILED,
        OutcomeStatus.UNKNOWN,
        OutcomeStatus.UNVERIFIABLE,
        OutcomeStatus.UNOBSERVABLE,
        OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
    },
    OutcomeStatus.UNKNOWN: {
        OutcomeStatus.UNKNOWN,
        OutcomeStatus.VERIFIED_SUCCESS,
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        OutcomeStatus.PARTIAL_ACHIEVEMENT,
        OutcomeStatus.PARTIAL,
        OutcomeStatus.VERIFIED_FAILURE,
        OutcomeStatus.FAILED,
        OutcomeStatus.UNVERIFIABLE,
        OutcomeStatus.UNOBSERVABLE,
        OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
    },
    OutcomeStatus.ACKNOWLEDGED_UNVERIFIED: {
        OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
        OutcomeStatus.VERIFIED_SUCCESS,
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        OutcomeStatus.PARTIAL_ACHIEVEMENT,
        OutcomeStatus.PARTIAL,
        OutcomeStatus.VERIFIED_FAILURE,
        OutcomeStatus.FAILED,
    },
    OutcomeStatus.PARTIAL: {
        OutcomeStatus.PARTIAL,
        OutcomeStatus.PARTIAL_ACHIEVEMENT,
        OutcomeStatus.VERIFIED_SUCCESS,
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.VERIFIED_FAILURE,
        OutcomeStatus.FAILED,
    },
    OutcomeStatus.PARTIAL_ACHIEVEMENT: {
        OutcomeStatus.PARTIAL_ACHIEVEMENT,
        OutcomeStatus.PARTIAL,
        OutcomeStatus.VERIFIED_SUCCESS,
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.VERIFIED_FAILURE,
        OutcomeStatus.FAILED,
    },
    OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED: {
        OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        OutcomeStatus.VERIFIED_SUCCESS,
        OutcomeStatus.SUCCESS_CONFIRMED,
    },
    OutcomeStatus.SUCCESS_CONFIRMED: {
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.VERIFIED_SUCCESS,
    },
    OutcomeStatus.VERIFIED_SUCCESS: {
        OutcomeStatus.VERIFIED_SUCCESS,
        OutcomeStatus.SUCCESS_CONFIRMED,
    },
    OutcomeStatus.FAILED: {
        OutcomeStatus.FAILED,
        OutcomeStatus.VERIFIED_FAILURE,
    },
    OutcomeStatus.VERIFIED_FAILURE: {
        OutcomeStatus.VERIFIED_FAILURE,
        OutcomeStatus.FAILED,
    },
    OutcomeStatus.UNOBSERVABLE: {
        OutcomeStatus.UNOBSERVABLE,
        OutcomeStatus.UNVERIFIABLE,
        OutcomeStatus.VERIFIED_FAILURE,
        OutcomeStatus.FAILED,
    },
    OutcomeStatus.UNVERIFIABLE: {
        OutcomeStatus.UNVERIFIABLE,
        OutcomeStatus.UNOBSERVABLE,
        OutcomeStatus.VERIFIED_FAILURE,
        OutcomeStatus.FAILED,
    },
}


def reconcile_output_with_outcome(
    response_text: str,
    outcome_contract: OutcomeVerificationContract,
    transaction_id: str | None = None,
    action_id: str | None = None,
    auth_tenant_id: str | None = None,
) -> OutcomeReconciliationResult:
    """Verify Output <-> Outcome consistency: prevent models from falsely claiming verified success."""
    if auth_tenant_id is not None:
        if not auth_tenant_id.strip() or outcome_contract.tenant_id != auth_tenant_id.strip():
            return OutcomeReconciliationResult(
                is_consistent=False,
                epistemic_conflict_detected=True,
                conflict_reasons=[
                    f"Cross-tenant outcome violation: outcome tenant '{outcome_contract.tenant_id}' "
                    f"does not match authenticated tenant '{auth_tenant_id}'"
                ],
                recommended_disposition="REJECT",
            )

    if transaction_id is not None:
        if not transaction_id.strip() or outcome_contract.transaction_id != transaction_id.strip():
            return OutcomeReconciliationResult(
                is_consistent=False,
                epistemic_conflict_detected=True,
                conflict_reasons=[
                    f"Transaction correlation mismatch: outcome belongs to '{outcome_contract.transaction_id}', "
                    f"caller specified '{transaction_id}'"
                ],
                recommended_disposition="REJECT",
            )

    if action_id is not None:
        if not action_id.strip() or outcome_contract.action_id != action_id.strip():
            return OutcomeReconciliationResult(
                is_consistent=False,
                epistemic_conflict_detected=True,
                conflict_reasons=[
                    f"Action correlation mismatch: outcome belongs to action '{outcome_contract.action_id}', "
                    f"caller specified '{action_id}'"
                ],
                recommended_disposition="REJECT",
            )

    norm_text = _normalize_text(response_text)
    unquoted = _strip_quotes_and_citations(norm_text)
    clauses = _extract_clauses(unquoted)

    claims_completion = False
    has_explicit_failure = False
    conflict_reasons: list[str] = []

    for clause in clauses:
        clause_lower = clause.lower()
        if any(
            u in clause_lower
            for u in [
                "cannot confirm",
                "could not confirm",
                "unclear whether",
                "unable to confirm",
                "unable to verify",
                "not confirmed",
                "failed to confirm",
                "no confirmation that",
                "no evidence that",
            ]
        ):
            continue

        if any(
            f in clause_lower
            for f in [
                "operation failed",
                "action failed",
                "failed, so",
                "failed to execute",
                "execution failed",
                "failed completely",
                "was unsuccessful",
                "did not succeed",
            ]
        ):
            has_explicit_failure = True

        for pat in _COMPLETION_ASSERTION_PATTERNS:
            for m in pat.finditer(clause):
                start_idx = max(0, m.start() - 35)
                prefix = clause[start_idx : m.start()].lower()
                negated = any(
                    neg in prefix
                    for neg in [
                        "not ",
                        "never ",
                        "failed to ",
                        "unable to ",
                        "could not ",
                        "did not ",
                        "was not ",
                        "were not ",
                        "has not ",
                        "have not ",
                        "is not ",
                        "are not ",
                    ]
                )
                if not negated:
                    claims_completion = True
                    break
            if claims_completion:
                break

    status_val = outcome_contract.outcome_status

    if not claims_completion:
        if status_val in (
            OutcomeStatus.FAILED,
            OutcomeStatus.VERIFIED_FAILURE,
            OutcomeStatus.UNKNOWN,
            OutcomeStatus.UNOBSERVABLE,
            OutcomeStatus.UNVERIFIABLE,
            OutcomeStatus.PARTIAL,
            OutcomeStatus.PARTIAL_ACHIEVEMENT,
            OutcomeStatus.ACKNOWLEDGED_UNVERIFIED,
            OutcomeStatus.PENDING_VERIFICATION,
        ):
            return OutcomeReconciliationResult(
                is_consistent=True,
                epistemic_conflict_detected=False,
                conflict_reasons=[],
                recommended_disposition="PERMIT",
            )

        if status_val in (
            OutcomeStatus.SUCCESS_CONFIRMED,
            OutcomeStatus.VERIFIED_SUCCESS,
            OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
        ):
            if has_explicit_failure:
                return OutcomeReconciliationResult(
                    is_consistent=False,
                    epistemic_conflict_detected=True,
                    conflict_reasons=[
                        "Contradiction: Output claims action failure, but Gate 5 reality verification "
                        "confirmed successful state transition."
                    ],
                    recommended_disposition="REWRITE_WITH_CAVEAT",
                )
            return OutcomeReconciliationResult(
                is_consistent=True,
                epistemic_conflict_detected=False,
                conflict_reasons=[],
                recommended_disposition="PERMIT",
            )

    if outcome_contract.is_simulated:
        conflict_reasons.append(
            "Epistemic Invariant Violation: Output asserts real-world success, but verification evidence "
            "is simulated (SimulatedTestAdapter). Simulation evidence cannot prove physical real-world execution."
        )
        return OutcomeReconciliationResult(
            is_consistent=False,
            epistemic_conflict_detected=True,
            conflict_reasons=conflict_reasons,
            recommended_disposition="REWRITE_WITH_CAVEAT",
        )

    if status_val in (
        OutcomeStatus.SUCCESS_CONFIRMED,
        OutcomeStatus.VERIFIED_SUCCESS,
        OutcomeStatus.SUCCESS_EVENTUALLY_OBSERVED,
    ):
        return OutcomeReconciliationResult(
            is_consistent=True,
            epistemic_conflict_detected=False,
            conflict_reasons=[],
            recommended_disposition="PERMIT",
        )

    conflict_msg = (
        f"Epistemic Invariant Violation: Output claims successful action completion, but Gate 5 "
        f"reality status is '{status_val.value}' with confidence {outcome_contract.epistemic_confidence}. "
    )
    if status_val == OutcomeStatus.PENDING_VERIFICATION:
        conflict_msg += "Action outcome verification is still PENDING_VERIFICATION; real-world success is unconfirmed."
    elif status_val == OutcomeStatus.ACKNOWLEDGED_UNVERIFIED:
        conflict_msg += "Transport acknowledgment alone does not prove destination state change."
    elif status_val in (OutcomeStatus.UNOBSERVABLE, OutcomeStatus.UNVERIFIABLE):
        conflict_msg += "Target resource is write-only/unobservable; physical state confirmation is impossible."
    elif status_val in (OutcomeStatus.FAILED, OutcomeStatus.VERIFIED_FAILURE):
        conflict_msg += "State verification observed explicit invariant failure."
    elif status_val in (OutcomeStatus.PARTIAL, OutcomeStatus.PARTIAL_ACHIEVEMENT):
        conflict_msg += "Outcome is PARTIAL: subset of actions failed in batch; output cannot claim complete success."
    elif status_val == OutcomeStatus.UNKNOWN:
        conflict_msg += "State verification timed out or was indeterminate."

    conflict_reasons.append(conflict_msg)

    disposition = (
        "REJECT" if status_val in (OutcomeStatus.FAILED, OutcomeStatus.VERIFIED_FAILURE) else "REWRITE_WITH_CAVEAT"
    )
    return OutcomeReconciliationResult(
        is_consistent=False,
        epistemic_conflict_detected=True,
        conflict_reasons=conflict_reasons,
        recommended_disposition=disposition,
    )
