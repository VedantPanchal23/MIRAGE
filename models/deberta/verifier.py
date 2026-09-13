"""DeBERTa-v3-large NLI Verifier and Multi-Evidence Aggregator."""

import re
from typing import Any

from shared.logging import get_logger
from shared.schemas import EvidenceChunk

logger = get_logger("deberta_verifier")


class DeBERTaNLIVerifier:
    """Natural Language Inference model predicting Entailment, Neutral, and Contradiction probabilities."""

    def __init__(self, model_name: str = "microsoft/deberta-v3-large", use_neural: bool = False) -> None:
        self.model_name = model_name
        self.use_neural = use_neural
        self._tokenizer: Any = None
        self._model: Any = None

        if self.use_neural:
            try:
                import torch
                from transformers import AutoModelForSequenceClassification, AutoTokenizer

                self._tokenizer = AutoTokenizer.from_pretrained(model_name)
                self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._model.to(device)
                self._model.eval()
                logger.info("Loaded neural DeBERTa verifier", model=model_name, device=device)
            except Exception as exc:
                logger.warning("Failed to load neural DeBERTa verifier, using heuristic logic", error=str(exc))
                self.use_neural = False

    def predict_pair(self, premise: str, hypothesis: str) -> tuple[float, float, float]:
        """Return (p_entailment, p_neutral, p_contradiction) for a premise-hypothesis pair."""
        p_clean = premise.strip()
        h_clean = hypothesis.strip()
        if not p_clean or not h_clean:
            return 0.0, 1.0, 0.0

        if self.use_neural and self._model is not None and self._tokenizer is not None:
            return self._predict_neural(p_clean, h_clean)

        return self._predict_heuristic(p_clean, h_clean)

    def are_bidirectionally_entailed(self, text_a: str, text_b: str, threshold: float = 0.5) -> bool:
        """Check if text_a and text_b mutually entail each other (Kuhn et al., 2023 semantic clustering)."""
        p_ab, _, c_ab = self.predict_pair(text_a, text_b)
        p_ba, _, c_ba = self.predict_pair(text_b, text_a)
        # Mutually entailed and neither contradicts
        return (p_ab >= threshold and p_ba >= threshold) and (c_ab < 0.3 and c_ba < 0.3)

    def aggregate_multi_evidence(
        self,
        claim_text: str,
        evidence_chunks: list[EvidenceChunk],
        support_penalty_lambda: float = 0.3,
    ) -> float:
        """Compute multi-evidence NLI risk score: s_nli = max(contra) + lambda * (1 - max(entail))."""
        if not evidence_chunks:
            # Without evidence, default to neutral uncertainty
            return 0.50

        max_contra = 0.0
        max_entail = 0.0

        for chunk in evidence_chunks:
            p_entail, _, p_contra = self.predict_pair(chunk.content, claim_text)
            if p_contra > max_contra:
                max_contra = p_contra
            if p_entail > max_entail:
                max_entail = p_entail

        # Formula: max contradiction + penalty for lack of strong entailment
        raw_risk = max_contra + support_penalty_lambda * (1.0 - max_entail)
        return round(min(1.0, max(0.0, raw_risk)), 4)

    def _predict_heuristic(self, premise: str, hypothesis: str) -> tuple[float, float, float]:
        """Fast logical heuristic predicting entailment/contradiction based on entity and negation overlap."""
        p_lower = premise.lower()
        h_lower = hypothesis.lower()

        # Check for explicit negation clashes (e.g. "is" vs "is not", "cures" vs "does not cure")
        neg_words = [
            " not ",
            " never ",
            " no ",
            " cannot ",
            " false ",
            "isn't",
            "wasn't",
            "aren't",
            " zero ",
            " none ",
            " without ",
        ]
        has_negation_p = any(neg in p_lower for neg in neg_words)
        has_negation_h = any(neg in h_lower for neg in neg_words)

        p_words = set(re.findall(r"\b\w{3,}\b", p_lower))
        h_words = set(re.findall(r"\b\w{3,}\b", h_lower))

        if not h_words:
            return 0.1, 0.8, 0.1

        stopwords = {
            "the",
            "a",
            "an",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "by",
            "with",
            "is",
            "was",
            "are",
            "were",
            "be",
            "been",
            "being",
            "has",
            "have",
            "had",
            "do",
            "does",
            "did",
            "and",
            "or",
            "but",
            "so",
            "as",
            "from",
            "that",
            "this",
            "which",
            "also",
            "its",
            "it",
        }

        p_content = p_words - stopwords
        h_content = h_words - stopwords
        shared_content = p_content.intersection(h_content)
        shared = p_words.intersection(h_words)
        overlap = len(shared) / len(h_words)

        # Check for numeric or date mismatch
        p_nums = set(re.findall(r"\b\d+\b", p_lower))
        h_nums = set(re.findall(r"\b\d+\b", h_lower))
        if h_nums and p_nums and not h_nums.issubset(p_nums) and (overlap >= 0.20 or len(shared_content) >= 1):
            # Shared context but numbers contradict (e.g., 1999 vs 1928)
            return 0.02, 0.08, 0.90

        if has_negation_p != has_negation_h and (
            len(shared_content) >= 2 or (h_content and len(shared_content) / len(h_content) > 0.40)
        ):
            # Direct polarity flip
            return 0.01, 0.09, 0.90

        # Direct entailment if hypothesis content words are a subset of premise content words
        if h_content and h_content.issubset(p_content):
            return 0.92, 0.06, 0.02

        # Check for entity / attribute conflict with shared relational context
        # e.g., "The capital of Germany is Berlin" vs "Munich is the capital of Germany"
        p_conflict = p_content - h_content
        h_conflict = h_content - p_content
        if len(shared) >= 2 and p_conflict and h_conflict:
            relation_indicators = {
                "capital",
                "discovered",
                "invented",
                "founded",
                "born",
                "died",
                "president",
                "author",
                "authored",
                "created",
                "largest",
                "smallest",
                "cure",
                "cured",
                "causes",
                "caused",
                "located",
                "headquarters",
            }
            if any(rel in shared for rel in relation_indicators):
                return 0.02, 0.08, 0.90

        if overlap > 0.65:
            # High semantic overlap and aligned polarity
            return 0.85, 0.12, 0.03
        if overlap > 0.35:
            # Moderate overlap
            return 0.50, 0.45, 0.05

        return 0.10, 0.80, 0.10

    def _predict_neural(self, premise: str, hypothesis: str) -> tuple[float, float, float]:
        """Run DeBERTa inference on PyTorch model."""
        import torch

        inputs = self._tokenizer(
            premise,
            hypothesis,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        device = next(self._model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            logits = self._model(**inputs).logits
            probs = torch.softmax(logits, dim=-1)[0].cpu().tolist()

        # DeBERTa order: [entailment, neutral, contradiction]
        return float(probs[0]), float(probs[1]), float(probs[2])
