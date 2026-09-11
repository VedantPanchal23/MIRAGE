"""Unit and integration tests for Phase 4 multi-signal verification workers."""

import pytest

from models.deberta.verifier import DeBERTaNLIVerifier
from shared.schemas import (
    Claim,
    ClaimCriticality,
    ClaimType,
    EvidenceChunk,
    VerificationRequest,
    VerificationStatus,
)
from workers.ics.worker import ICSWorker
from workers.orchestrator import VerificationOrchestrator
from workers.rav.worker import RAVWorker
from workers.scs.worker import SCSWorker


@pytest.mark.unit
class TestDeBERTaNLIVerifier:
    def test_predict_pair_entailment(self) -> None:
        verifier = DeBERTaNLIVerifier(use_neural=False)
        premise = "Alexander Fleming discovered penicillin in 1928 at St Mary's Hospital."
        hypothesis = "Penicillin was discovered in 1928."
        p_entail, _, p_contra = verifier.predict_pair(premise, hypothesis)
        assert p_entail > 0.60
        assert p_contra < 0.20

    def test_predict_pair_numerical_contradiction(self) -> None:
        verifier = DeBERTaNLIVerifier(use_neural=False)
        premise = "Alexander Fleming discovered penicillin in 1928."
        hypothesis = "Alexander Fleming discovered penicillin in 1985."
        _, _, p_contra = verifier.predict_pair(premise, hypothesis)
        assert p_contra > 0.80

    def test_predict_pair_polarity_contradiction(self) -> None:
        verifier = DeBERTaNLIVerifier(use_neural=False)
        premise = "The clinical trial showed the vaccine is safe."
        hypothesis = "The clinical trial showed the vaccine is not safe."
        _, _, p_contra = verifier.predict_pair(premise, hypothesis)
        assert p_contra > 0.80

    def test_bidirectional_entailment_clustering(self) -> None:
        verifier = DeBERTaNLIVerifier(use_neural=False)
        t1 = "Water boils at 100 degrees Celsius under standard atmospheric pressure."
        t2 = "At standard pressure, water reaches boiling point at 100 degrees Celsius."
        assert verifier.are_bidirectionally_entailed(t1, t2) is True

        t3 = "Water freezes at 0 degrees Celsius."
        assert verifier.are_bidirectionally_entailed(t1, t3) is False

    def test_aggregate_multi_evidence(self) -> None:
        verifier = DeBERTaNLIVerifier(use_neural=False)
        supporting_chunk = EvidenceChunk(
            chunk_id="c1",
            document_id="d1",
            content="The capital of Germany is Berlin, which is also its largest city.",
            similarity_score=0.95,
        )
        risk_supported = verifier.aggregate_multi_evidence(
            claim_text="Berlin is the capital of Germany",
            evidence_chunks=[supporting_chunk],
        )
        assert risk_supported < 0.20

        refuting_chunk = EvidenceChunk(
            chunk_id="c2",
            document_id="d2",
            content="The capital of Germany is Berlin.",
            similarity_score=0.90,
        )
        risk_refuted = verifier.aggregate_multi_evidence(
            claim_text="Munich is the capital of Germany in 2024",
            evidence_chunks=[refuting_chunk],
        )
        assert risk_refuted > 0.70


@pytest.mark.unit
class TestRAVWorker:
    @pytest.mark.asyncio
    async def test_rav_search_and_score(self) -> None:
        rav = RAVWorker()
        rav.add_mock_document(
            chunk_id="chk_hist_01",
            content="Apollo 11 landed on the Moon in July 1969 with Neil Armstrong and Buzz Aldrin.",
        )

        claim = Claim(
            claim_id="c_01",
            text="Apollo 11 landed on the Moon in 1969.",
            claim_type=ClaimType.TEMPORAL,
            criticality=ClaimCriticality.HIGH,
        )

        chunks = await rav.search_evidence(claim.text)
        assert len(chunks) >= 1
        score = rav.compute_rav_score(claim, chunks)
        assert score < 0.25

    def test_rav_empty_evidence_penalty(self) -> None:
        rav = RAVWorker()
        claim = Claim(claim_id="c_02", text="Unrecorded assertion without documentation.")
        score = rav.compute_rav_score(claim, [])
        assert score >= 0.80


@pytest.mark.unit
class TestSCSWorker:
    def test_semantic_entropy_calculation(self) -> None:
        scs = SCSWorker()
        # Case 1: 5 completions in 1 cluster -> 0.0 entropy
        single_cluster = [["comp1", "comp2", "comp3", "comp4", "comp5"]]
        se_zero = scs.compute_semantic_entropy(single_cluster, total_samples=5)
        assert se_zero == 0.0

        # Case 2: 5 completions in 5 separate clusters -> maximum entropy (1.0)
        diverse_clusters = [["c1"], ["c2"], ["c3"], ["c4"], ["c5"]]
        se_max = scs.compute_semantic_entropy(diverse_clusters, total_samples=5)
        assert se_max == 1.0

    @pytest.mark.asyncio
    async def test_scs_caching_behavior(self) -> None:
        scs = SCSWorker()
        prompt = "What is photosynthesis?"
        score1, hit1 = await scs.compute_scs_score(prompt, model_id="llama-3.1", tenant_id="t1")
        assert hit1 is False

        # Second call with identical prompt and tenant must hit cache
        score2, hit2 = await scs.compute_scs_score(prompt, model_id="llama-3.1", tenant_id="t1")
        assert hit2 is True
        assert score1 == score2


@pytest.mark.unit
class TestICSWorker:
    def test_ics_intra_response_contradiction(self) -> None:
        ics = ICSWorker()
        claim1 = Claim(claim_id="c_01", text="The company generated $50 million in revenue during 2023.")
        claim2 = Claim(claim_id="c_02", text="The company generated $5 million in revenue during 2023.")

        matrix = ics.build_contradiction_matrix([claim1, claim2])
        assert matrix[0][1] > 0.80
        assert matrix[1][0] == matrix[0][1]

        resp_ics = ics.compute_response_ics_score([claim1, claim2])
        assert resp_ics > 0.80


@pytest.mark.unit
class TestVerificationOrchestrator:
    @pytest.mark.asyncio
    async def test_orchestrator_full_pipeline(self) -> None:
        orchestrator = VerificationOrchestrator()
        orchestrator.rav_worker.add_mock_document(
            chunk_id="chk_med_1",
            content="Alexander Fleming discovered penicillin in 1928.",
        )

        req = VerificationRequest(
            prompt="Who discovered penicillin and when?",
            response="Alexander Fleming discovered penicillin in 1928. It is used to treat bacterial infections.",
            tenant_id="tenant_research",
        )

        response = await orchestrator.verify_request(req)
        assert response.hrs_result.hrs <= 0.35
        assert len(response.claims) >= 1

        # Check that all 4 signals were computed
        for c in response.claims:
            assert c.rav_score is not None
            assert c.scs_score is not None
            assert c.nli_score is not None
            assert c.ics_score is not None
            assert "rav" in c.signal_attribution
            assert "nli" in c.signal_attribution

    @pytest.mark.asyncio
    async def test_orchestrator_contradicted_claim(self) -> None:
        orchestrator = VerificationOrchestrator()
        orchestrator.rav_worker.add_mock_document(
            chunk_id="chk_med_2",
            content="Penicillin was discovered in 1928.",
        )

        req = VerificationRequest(
            prompt="When was penicillin discovered?",
            response="Alexander Fleming discovered penicillin in 1999.",
            tenant_id="tenant_research",
        )

        response = await orchestrator.verify_request(req)
        # Contradicted year should lead to elevated risk
        contra_claims = [c for c in response.claims if c.status == VerificationStatus.CONTRADICTED]
        assert len(contra_claims) >= 1 or response.hrs_result.hrs > 0.30
