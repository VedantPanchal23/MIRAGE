"""Model unit tests for the FLAN-T5 atomic claim decomposer."""

import time

import pytest

from models.flan_t5 import AtomicClaimDecomposer
from shared.schemas import ClaimCriticality, ClaimType


@pytest.fixture
def decomposer() -> AtomicClaimDecomposer:
    """Instantiate standard CPU heuristic claim decomposer."""
    return AtomicClaimDecomposer(use_neural=False)


@pytest.mark.model_unit
class TestFLANT5Decomposer:
    def test_decompose_simple_sentence(self, decomposer: AtomicClaimDecomposer) -> None:
        text = "Penicillin was discovered in 1928 by Alexander Fleming."
        claims = decomposer.decompose(text)
        assert len(claims) >= 1
        claim = claims[0]
        assert claim.claim_id == "c_01"
        assert "1928" in claim.text
        assert claim.claim_type == ClaimType.TEMPORAL
        assert claim.criticality == ClaimCriticality.HIGH
        assert claim.criticality_weight == 1.0

    def test_decompose_compound_sentences(self, decomposer: AtomicClaimDecomposer) -> None:
        text = (
            "The company achieved $50 million in revenue during 2023. "
            "Furthermore, Paris is the capital of France and also has a high population."
        )
        claims = decomposer.decompose(text)
        assert len(claims) >= 2
        claim_types = [c.claim_type for c in claims]
        assert ClaimType.NUMERICAL in claim_types or ClaimType.TEMPORAL in claim_types

    def test_decompose_empty_text(self, decomposer: AtomicClaimDecomposer) -> None:
        assert decomposer.decompose("") == []
        assert decomposer.decompose("   \n\t  ") == []

    def test_taxonomy_classification(self, decomposer: AtomicClaimDecomposer) -> None:
        assert decomposer.classify_claim_type("In 1945, World War II ended.") == ClaimType.TEMPORAL
        assert decomposer.classify_claim_type("Sales increased by 15.8 percent.") == ClaimType.NUMERICAL
        assert (
            decomposer.classify_claim_type("The diagram displays the neural architecture.") == ClaimType.IMAGE_GROUNDED
        )
        assert decomposer.classify_claim_type("In my opinion, this was the best movie.") == ClaimType.OPINION
        assert decomposer.classify_claim_type("Mount Everest is the highest mountain.") == ClaimType.FACTUAL

    def test_criticality_assignment(self, decomposer: AtomicClaimDecomposer) -> None:
        # Opinion -> LOW (0.3)
        crit_op, wt_op = decomposer.assign_criticality("This is arguably fine.", ClaimType.OPINION)
        assert crit_op == ClaimCriticality.LOW
        assert wt_op == 0.3

        # Temporal / Numerical -> HIGH (1.0)
        crit_num, wt_num = decomposer.assign_criticality("Revenue is $10M.", ClaimType.NUMERICAL)
        assert crit_num == ClaimCriticality.HIGH
        assert wt_num == 1.0

        # Medical high-stakes -> HIGH (1.0)
        crit_med, wt_med = decomposer.assign_criticality(
            "Dosage is contraindicated for renal patients.", ClaimType.FACTUAL
        )
        assert crit_med == ClaimCriticality.HIGH
        assert wt_med == 1.0

    def test_sub_50ms_cpu_latency(self, decomposer: AtomicClaimDecomposer) -> None:
        text = (
            "Albert Einstein published his theory of special relativity in 1905. "
            "It revolutionized theoretical physics and astronomy during the 20th century. "
            "The equation E=mc^2 indicates that mass and energy are equivalent."
        )
        # Warm-up
        decomposer.decompose(text)

        # Benchmark 50 iterations
        times = []
        for _ in range(50):
            t0 = time.perf_counter()
            decomposer.decompose(text)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000)

        avg_latency_ms = sum(times) / len(times)
        max_latency_ms = max(times)
        assert avg_latency_ms < 10.0, f"Average latency was {avg_latency_ms:.2f}ms (must be < 10ms on CPU)"
        assert max_latency_ms < 50.0, f"Max latency was {max_latency_ms:.2f}ms (must be < 50ms on CPU)"

    def test_json_validation_and_fallback(self, decomposer: AtomicClaimDecomposer) -> None:
        valid_json = '[{"text": "Earth orbits the Sun in 365 days."}, {"text": "Mars has two moons."}]'
        parsed = decomposer.validate_claims_json(valid_json)
        assert parsed is not None
        assert len(parsed) == 2
        assert parsed[0].claim_id == "c_01"

        malformed_json = '{"corrupted": true, broken}'
        assert decomposer.validate_claims_json(malformed_json) is None
