"""Unit tests for Gate 4 Output Assurance, Claim Decomposition, DLP, and Policy Decision."""

import pytest

from hrs_engine.calibrator import compute_ece
from hrs_engine.conformal import MondrianConformalPredictor
from models.flan_t5 import AtomicClaimDecomposer
from services.output_assurance import OutputAssuranceService
from shared.schemas.claims import ClaimCriticality, ClaimType
from shared.schemas.hrs import RiskTier
from shared.schemas.output import (
    Gate4Decision,
    OutputFactualResult,
    OutputSafetyResult,
)


@pytest.fixture
def service() -> OutputAssuranceService:
    return OutputAssuranceService()


@pytest.fixture
def decomposer() -> AtomicClaimDecomposer:
    return AtomicClaimDecomposer(use_neural=False)


def test_claim_decomposition_taxonomy_and_spans(decomposer: AtomicClaimDecomposer) -> None:
    text = (
        "In 1928, Alexander Fleming discovered penicillin. "
        "The company reported $15 million in revenue. "
        "In my opinion, this is the best antibiotic ever made."
    )
    claims = decomposer.decompose(text)
    assert len(claims) >= 3

    types = {c.claim_type for c in claims}
    assert ClaimType.TEMPORAL in types or ClaimType.FACTUAL in types
    assert ClaimType.NUMERICAL in types
    assert ClaimType.OPINION in types

    # Opinion claims must have LOW criticality
    opinion_claims = [c for c in claims if c.claim_type == ClaimType.OPINION]
    assert all(c.criticality == ClaimCriticality.LOW for c in opinion_claims)


def test_dlp_secret_detection_and_redaction(service: OutputAssuranceService) -> None:
    unsafe_text = "Here is the production access key: api_key='sk_live_1234567890abcdef' and pass=secret123"
    safety = service.run_dlp_and_safety(unsafe_text)

    assert not safety.safe
    assert safety.secrets_detected
    assert safety.redacted_content is not None
    assert "[REDACTED_SECRET]" in safety.redacted_content
    assert "sk_live_1234567890abcdef" not in safety.redacted_content


def test_dlp_pii_detection_and_redaction(service: OutputAssuranceService) -> None:
    text_with_pii = "Contact the patient at john.doe@hospital.org or SSN 123-45-6789."
    safety = service.run_dlp_and_safety(text_with_pii)

    assert safety.pii_detected
    assert safety.redacted_content is not None
    assert "[REDACTED_PII]" in safety.redacted_content
    assert "john.doe@hospital.org" not in safety.redacted_content
    assert "123-45-6789" not in safety.redacted_content


def test_dlp_clean_payload_passes(service: OutputAssuranceService) -> None:
    clean_text = "Penicillin was discovered by Alexander Fleming at St. Mary's Hospital."
    safety = service.run_dlp_and_safety(clean_text)

    assert safety.safe
    assert not safety.secrets_detected
    assert not safety.pii_detected
    assert safety.redacted_content is None


def test_mondrian_conformal_bounds_and_coverage() -> None:
    predictor = MondrianConformalPredictor(alpha=0.05)
    # Synthetic calibration set
    preds = [0.1, 0.2, 0.3, 0.7, 0.8, 0.85, 0.9, 0.15, 0.25, 0.05, 0.65, 0.75]
    targets = [0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 1.0]

    predictor.fit(preds, targets)
    interval = predictor.predict_interval(score=0.15, risk_tier=RiskTier.LOW)

    assert interval.lower <= 0.15
    assert interval.upper >= 0.15
    assert interval.confidence_level == 0.95
    assert interval.width >= 0.0


def test_calibrator_ece_computation() -> None:
    y_true = [0, 0, 0, 0, 1, 1, 1, 1]
    y_prob = [0.1, 0.15, 0.2, 0.05, 0.85, 0.9, 0.95, 0.8]
    ece = compute_ece(y_true, y_prob, n_bins=5)
    assert 0.0 <= ece <= 0.15


def test_gate4_decision_synthesis_rules(service: OutputAssuranceService) -> None:
    # 1. Clean + low risk -> ALLOW
    clean_safety = OutputSafetyResult(safe=True)
    grounded_factual = OutputFactualResult(factual_consistency_score=0.95, claims_count=2, supported_claims_count=2)
    dec, _ = service._decide_gate4(
        risk_tier=RiskTier.LOW,
        hrs=0.08,
        safety=clean_safety,
        factual=grounded_factual,
        action_inconsistencies=[],
        taint_inconsistencies=[],
        budget_exhausted=False,
        was_corrected=False,
    )
    assert dec == Gate4Decision.ALLOW

    # 2. Contradicted claims -> BLOCK
    contra_factual = OutputFactualResult(factual_consistency_score=0.20, claims_count=2, contradicted_claims_count=1)
    dec, _ = service._decide_gate4(
        risk_tier=RiskTier.HIGH,
        hrs=0.75,
        safety=clean_safety,
        factual=contra_factual,
        action_inconsistencies=[],
        taint_inconsistencies=[],
        budget_exhausted=False,
        was_corrected=False,
    )
    assert dec == Gate4Decision.BLOCK

    # 3. Budget exhausted -> ALLOW_WITH_UNCERTAINTY
    dec, reasons = service._decide_gate4(
        risk_tier=RiskTier.MEDIUM,
        hrs=0.50,
        safety=clean_safety,
        factual=grounded_factual,
        action_inconsistencies=[],
        taint_inconsistencies=[],
        budget_exhausted=True,
        was_corrected=False,
    )
    assert dec == Gate4Decision.ALLOW_WITH_UNCERTAINTY
    assert any("budget" in r.lower() for r in reasons)

    # 4. Redaction applied -> REDACT_TRANSFORM
    redacted_safety = OutputSafetyResult(safe=True, pii_detected=True, redacted_content="Redacted [REDACTED_PII]")
    dec, _ = service._decide_gate4(
        risk_tier=RiskTier.LOW,
        hrs=0.10,
        safety=redacted_safety,
        factual=grounded_factual,
        action_inconsistencies=[],
        taint_inconsistencies=[],
        budget_exhausted=False,
        was_corrected=False,
    )
    assert dec == Gate4Decision.REDACT_TRANSFORM
