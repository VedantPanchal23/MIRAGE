"""Model unit tests for the DeBERTa-v3-large NLI Verifier and Multi-Evidence Aggregator."""

import pytest

from models.deberta.verifier import DeBERTaNLIVerifier
from shared.schemas import EvidenceChunk


@pytest.fixture
def deberta_verifier() -> DeBERTaNLIVerifier:
    """Instantiate DeBERTa NLI verifier in CPU/heuristic mode for fast deterministic unit tests."""
    return DeBERTaNLIVerifier(use_neural=False)


@pytest.mark.model_unit
class TestDeBERTaModel:
    """Test suite verifying DeBERTa NLI scoring, distribution, and evidence aggregation."""

    def test_three_class_distribution_properties(self, deberta_verifier: DeBERTaNLIVerifier) -> None:
        """Verify output is a 3-class tuple (p_entail, p_neutral, p_contra) summing to ~1.0."""
        premise = "The new drug received FDA approval after extensive phase 3 clinical trials."
        hypothesis = "The drug was approved by the FDA."

        p_entail, p_neutral, p_contra = deberta_verifier.predict_pair(premise, hypothesis)

        # Check range bounds
        assert 0.0 <= p_entail <= 1.0
        assert 0.0 <= p_neutral <= 1.0
        assert 0.0 <= p_contra <= 1.0

        # Check probability sum close to 1.0
        prob_sum = p_entail + p_neutral + p_contra
        assert pytest.approx(prob_sum, abs=0.01) == 1.0

    def test_known_answer_strong_entailment(self, deberta_verifier: DeBERTaNLIVerifier) -> None:
        """Verify known entailed premise-hypothesis pairs produce high entailment probability."""
        pairs = [
            (
                "Alexander Fleming discovered penicillin in 1928 at St. Mary's Hospital.",
                "Penicillin was discovered by Alexander Fleming in 1928.",
            ),
            (
                "The patient showed zero symptoms of respiratory distress during observation.",
                "The patient showed zero symptoms of respiratory distress.",
            ),
        ]
        for premise, hypothesis in pairs:
            p_entail, p_neutral, p_contra = deberta_verifier.predict_pair(premise, hypothesis)
            assert p_entail > p_contra, f"Entailment should exceed contradiction for: {hypothesis}"
            assert p_entail >= 0.50

    def test_known_answer_direct_contradiction(self, deberta_verifier: DeBERTaNLIVerifier) -> None:
        """Verify negation or direct opposition produces high contradiction probability."""
        pairs = [
            (
                "The clinical trial demonstrated no significant side effects in adult participants.",
                "The clinical trial demonstrated severe side effects in adult participants.",
            ),
            (
                "The product is strictly not intended for pediatric usage.",
                "The product is intended for pediatric usage.",
            ),
        ]
        for premise, hypothesis in pairs:
            p_entail, p_neutral, p_contra = deberta_verifier.predict_pair(premise, hypothesis)
            assert p_contra > p_entail, f"Contradiction should exceed entailment for: {hypothesis}"
            assert p_contra >= 0.50

    def test_known_answer_neutral_unrelated(self, deberta_verifier: DeBERTaNLIVerifier) -> None:
        """Verify unrelated premise-hypothesis pairs produce high neutral probability."""
        premise = "Photosynthesis requires sunlight, carbon dioxide, and water."
        hypothesis = "The Tokyo stock exchange closed higher on Tuesday morning."

        p_entail, p_neutral, p_contra = deberta_verifier.predict_pair(premise, hypothesis)
        assert p_neutral >= p_entail
        assert p_neutral >= p_contra

    def test_empty_string_edge_cases(self, deberta_verifier: DeBERTaNLIVerifier) -> None:
        """Verify empty premise or hypothesis safely defaults to (0.0, 1.0, 0.0)."""
        assert deberta_verifier.predict_pair("", "Some hypothesis") == (0.0, 1.0, 0.0)
        assert deberta_verifier.predict_pair("Some premise", "   ") == (0.0, 1.0, 0.0)
        assert deberta_verifier.predict_pair("", "") == (0.0, 1.0, 0.0)

    def test_bidirectional_entailment(self, deberta_verifier: DeBERTaNLIVerifier) -> None:
        """Verify semantic clustering bidirectional entailment check (Kuhn et al., 2023)."""
        text_a = "Alexander Fleming discovered penicillin in 1928."
        text_b = "Penicillin was discovered in 1928 by Alexander Fleming."
        text_c = "Albert Einstein formulated the theory of general relativity."

        # Mutual entailment
        assert deberta_verifier.are_bidirectionally_entailed(text_a, text_b, threshold=0.5) is True
        # Completely different facts
        assert deberta_verifier.are_bidirectionally_entailed(text_a, text_c, threshold=0.5) is False

    def test_multi_evidence_aggregation_empty(self, deberta_verifier: DeBERTaNLIVerifier) -> None:
        """Without evidence, aggregate_multi_evidence defaults to 0.50 (neutral uncertainty)."""
        risk = deberta_verifier.aggregate_multi_evidence("Any claim text", [])
        assert risk == 0.50

    def test_multi_evidence_aggregation_supporting(self, deberta_verifier: DeBERTaNLIVerifier) -> None:
        """Supporting evidence yields low risk score."""
        claim = "Penicillin was discovered in 1928 by Alexander Fleming."
        evidence = [
            EvidenceChunk(
                chunk_id="chk_01",
                document_id="doc_med_01",
                content="Alexander Fleming discovered penicillin in 1928 at St Mary's Hospital London.",
                similarity_score=0.92,
                source_metadata={"source": "medical_history.pdf"},
            )
        ]
        risk = deberta_verifier.aggregate_multi_evidence(claim, evidence)
        assert risk < 0.40, f"Expected low risk for supported claim, got {risk}"

    def test_multi_evidence_aggregation_contradicting(self, deberta_verifier: DeBERTaNLIVerifier) -> None:
        """Contradicting evidence yields high risk score."""
        claim = "The patient showed severe respiratory distress."
        evidence = [
            EvidenceChunk(
                chunk_id="chk_02",
                document_id="doc_notes_01",
                content="The patient showed zero symptoms of respiratory distress during observation.",
                similarity_score=0.91,
                source_metadata={"source": "chart_notes.txt"},
            )
        ]
        risk = deberta_verifier.aggregate_multi_evidence(claim, evidence)
        assert risk > 0.60, f"Expected elevated risk for contradicted claim, got {risk}"
