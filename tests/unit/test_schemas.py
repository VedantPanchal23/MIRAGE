"""Unit tests for shared Pydantic data schemas and validation logic."""

import pytest
from pydantic import ValidationError

from shared.schemas import (
    CRITICALITY_WEIGHTS,
    AuditLogEntry,
    Claim,
    ClaimCriticality,
    ClaimType,
    ClaimVerificationResult,
    ConformalInterval,
    EvidenceChunk,
    HRSResult,
    RiskTier,
    SignalAttribution,
    VerificationMetadata,
    VerificationRequest,
    VerificationResponse,
    VerificationStatus,
    compute_sha256,
    determine_risk_tier,
)


@pytest.mark.unit
class TestClaimSchemas:
    def test_claim_creation_defaults(self) -> None:
        claim = Claim(claim_id="c_01", text="Penicillin was discovered in 1928 by Alexander Fleming.")
        assert claim.claim_id == "c_01"
        assert claim.claim_type == ClaimType.FACTUAL
        assert claim.criticality == ClaimCriticality.MEDIUM
        assert claim.criticality_weight == 0.6
        assert claim.span_start is None

    def test_claim_immutability(self) -> None:
        claim = Claim(claim_id="c_02", text="Water boils at 100 degrees Celsius.")
        with pytest.raises(ValidationError):
            # Model is frozen
            claim.text = "New text"

    def test_criticality_weights_mapping(self) -> None:
        assert CRITICALITY_WEIGHTS[ClaimCriticality.HIGH] == 1.0
        assert CRITICALITY_WEIGHTS[ClaimCriticality.MEDIUM] == 0.6
        assert CRITICALITY_WEIGHTS[ClaimCriticality.LOW] == 0.3

    def test_claim_verification_result_with_signals(self) -> None:
        claim = Claim(
            claim_id="c_03",
            text="The French Revolution began in 1789.",
            claim_type=ClaimType.TEMPORAL,
            criticality=ClaimCriticality.HIGH,
            criticality_weight=1.0,
        )
        evidence = EvidenceChunk(
            chunk_id="chk_101",
            document_id="doc_history",
            content="In 1789, the French Revolution began with the Storming of the Bastille.",
            similarity_score=0.92,
            source_metadata={"page": 14},
        )
        result = ClaimVerificationResult(
            claim=claim,
            status=VerificationStatus.SUPPORTED,
            risk_score=0.03,
            rav_score=0.08,
            scs_score=0.02,
            nli_score=0.01,
            ics_score=0.00,
            signal_attribution={"rav": 0.45, "nli": 0.55},
            evidence_chunks=[evidence],
            explanation="Claim is strongly supported by historical evidence chunk chk_101.",
        )
        assert result.status == VerificationStatus.SUPPORTED
        assert result.risk_score == 0.03
        assert len(result.evidence_chunks) == 1
        assert result.signal_attribution["rav"] == 0.45


@pytest.mark.unit
class TestHRSSchemas:
    def test_determine_risk_tier_boundaries(self) -> None:
        assert determine_risk_tier(0.00) == RiskTier.LOW
        assert determine_risk_tier(0.19) == RiskTier.LOW
        assert determine_risk_tier(0.20) == RiskTier.MEDIUM
        assert determine_risk_tier(0.59) == RiskTier.MEDIUM
        assert determine_risk_tier(0.60) == RiskTier.HIGH
        assert determine_risk_tier(0.84) == RiskTier.HIGH
        assert determine_risk_tier(0.85) == RiskTier.CRITICAL
        assert determine_risk_tier(1.00) == RiskTier.CRITICAL

    def test_conformal_interval_valid(self) -> None:
        interval = ConformalInterval(lower=0.10, upper=0.25, confidence_level=0.95, conditional_group="tier:LOW")
        assert interval.lower == 0.10
        assert interval.upper == 0.25
        assert interval.width == 0.15

    def test_conformal_interval_invalid_bounds(self) -> None:
        with pytest.raises(ValidationError):
            ConformalInterval(lower=0.80, upper=0.20)

    def test_hrs_result_serialization(self) -> None:
        hrs_res = HRSResult(
            hrs=0.12,
            raw_score=0.15,
            tier=RiskTier.LOW,
            conformal_interval=ConformalInterval(lower=0.08, upper=0.18),
            signal_attribution=SignalAttribution(rav=0.4, scs=0.2, nli=0.3, ics=0.1),
            claims_count=4,
            contradicted_claims_count=0,
            computation_latency_ms=145.2,
        )
        assert hrs_res.tier == RiskTier.LOW
        assert hrs_res.hrs == 0.12
        assert hrs_res.signal_attribution.rav == 0.4


@pytest.mark.unit
class TestVerificationPayloads:
    def test_verification_request_valid(self) -> None:
        req = VerificationRequest(
            prompt="Who discovered penicillin?",
            response="Alexander Fleming discovered penicillin in 1928.",
            tenant_id="tenant_hospital_a",
            knowledge_base_id="med_docs",
        )
        assert req.tenant_id == "tenant_hospital_a"
        assert req.auto_correct is True

    def test_verification_request_empty_prompt_fails(self) -> None:
        with pytest.raises(ValidationError):
            VerificationRequest(prompt="", response="Some response")

    def test_verification_response_roundtrip(self) -> None:
        resp = VerificationResponse(
            verified_response="Verified text",
            original_response="Original text",
            hrs_result=HRSResult(
                hrs=0.05,
                raw_score=0.06,
                tier=RiskTier.LOW,
                conformal_interval=ConformalInterval(lower=0.02, upper=0.10),
                signal_attribution=SignalAttribution(rav=0.5, nli=0.5),
                claims_count=1,
                contradicted_claims_count=0,
                computation_latency_ms=88.5,
            ),
            claims=[],
            metadata=VerificationMetadata(
                trace_id="trace_abc123",
                execution_time_ms=120.0,
                pipeline_signals_used=["rav", "nli", "scs", "ics"],
            ),
        )
        json_str = resp.model_dump_json()
        deserialized = VerificationResponse.model_validate_json(json_str)
        assert deserialized.request_id.startswith("req_")
        assert deserialized.hrs_result.hrs == 0.05


@pytest.mark.unit
class TestAuditLogIntegrity:
    def test_sha256_computation(self) -> None:
        h1 = compute_sha256("test string")
        assert len(h1) == 64

    def test_audit_entry_hash_chain_and_verification(self) -> None:
        entry1 = AuditLogEntry.create(
            entry_id="entry_01",
            tenant_id="tenant_fintech",
            session_id="sess_01",
            trace_id="trc_01",
            prompt="What is the interest rate?",
            response="The interest rate is 5.5%.",
            hrs_score=0.02,
            risk_tier="LOW",
            claims_count=1,
            claims_summary=[{"claim": "The interest rate is 5.5%", "status": "SUPPORTED"}],
            correction_applied=False,
            prev_hash="0" * 64,
        )
        assert entry1.verify_integrity() is True
        assert entry1.verify_integrity(expected_prev_hash="0" * 64) is True
        assert entry1.verify_integrity(expected_prev_hash="wrong_hash") is False

        # Build chained entry 2
        entry2 = AuditLogEntry.create(
            entry_id="entry_02",
            tenant_id="tenant_fintech",
            session_id="sess_02",
            trace_id="trc_02",
            prompt="What is the mortgage fee?",
            response="The mortgage fee is $500.",
            hrs_score=0.04,
            risk_tier="LOW",
            claims_count=1,
            claims_summary=[{"claim": "The mortgage fee is $500", "status": "SUPPORTED"}],
            correction_applied=False,
            prev_hash=entry1.chain_hash,
        )
        assert entry2.verify_integrity(expected_prev_hash=entry1.chain_hash) is True

    def test_audit_entry_tamper_detection(self) -> None:
        entry = AuditLogEntry.create(
            entry_id="entry_tamper",
            tenant_id="tenant_a",
            session_id="sess_a",
            trace_id="trc_a",
            prompt="Test prompt",
            response="Test response",
            hrs_score=0.10,
            risk_tier="LOW",
            claims_count=1,
            claims_summary=[],
            correction_applied=False,
        )
        assert entry.verify_integrity() is True

        # Simulate adversarial payload tampering
        tampered = entry.model_copy(update={"hrs_score": 0.99})
        assert tampered.verify_integrity() is False
