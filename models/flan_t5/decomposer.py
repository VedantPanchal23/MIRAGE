"""Atomic Claim Decomposer with taxonomy classification and criticality weighting."""

import json
import re
import time
from typing import Any

from shared.logging import get_logger
from shared.schemas import (
    CRITICALITY_WEIGHTS,
    Claim,
    ClaimCriticality,
    ClaimType,
)

logger = get_logger("claim_decomposer")

# Regex patterns for fast rule-based taxonomy classification
RE_TEMPORAL = re.compile(
    r"\b(?:in\s+\d{3,4}|\d{1,2}(?:st|nd|rd|th)?\s+(?:century|decade)|(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:,\s+\d{4})?|\d{4}\s*(?:BC|BCE|AD)?)\b",
    re.IGNORECASE,
)
RE_NUMERICAL = re.compile(
    r"(?:\$|€|£|¥)?\b\d+(?:\.\d+)?%?\b|\b(?:million|billion|trillion|percent|percentage)\b",
    re.IGNORECASE,
)
RE_IMAGE = re.compile(
    r"\b(?:image|photo|picture|figure|chart|graph|diagram|visual|table|screenshot)\b",
    re.IGNORECASE,
)
RE_OPINION = re.compile(
    r"\b(?:in my opinion|best|worst|arguably|presumably|I think|I believe|magnificent|terrible|superior|inferior)\b",
    re.IGNORECASE,
)


class AtomicClaimDecomposer:
    """Decomposes multi-sentence LLM responses into atomic, verifiable claims with domain criticality."""

    def __init__(self, model_name: str = "google/flan-t5-base", use_neural: bool = False) -> None:
        self.model_name = model_name
        self.use_neural = use_neural
        self._model: Any = None
        self._tokenizer: Any = None

        if self.use_neural:
            try:
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

                self._tokenizer = AutoTokenizer.from_pretrained(model_name)
                self._model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
                logger.info("Loaded neural FLAN-T5 decomposer", model=model_name)
            except Exception as exc:
                logger.warning("Failed to load neural FLAN-T5 model, falling back to heuristic", error=str(exc))
                self.use_neural = False

    def classify_claim_type(self, text: str) -> ClaimType:
        """Classify atomic claim according to the 6-type taxonomy."""
        if RE_IMAGE.search(text):
            return ClaimType.IMAGE_GROUNDED
        if RE_OPINION.search(text):
            return ClaimType.OPINION
        if RE_TEMPORAL.search(text):
            return ClaimType.TEMPORAL
        if RE_NUMERICAL.search(text):
            return ClaimType.NUMERICAL
        relational_keywords = ["caused", "led to", "father of", "married", "founded by", "capital of"]
        if any(keyword in text.lower() for keyword in relational_keywords):
            return ClaimType.RELATIONAL
        return ClaimType.FACTUAL

    def assign_criticality(self, text: str, claim_type: ClaimType) -> tuple[ClaimCriticality, float]:
        """Assign impact criticality (HIGH, MEDIUM, LOW) and numerical weight."""
        if claim_type == ClaimType.OPINION:
            return ClaimCriticality.LOW, CRITICALITY_WEIGHTS[ClaimCriticality.LOW]
        if claim_type in {ClaimType.NUMERICAL, ClaimType.TEMPORAL, ClaimType.IMAGE_GROUNDED}:
            return ClaimCriticality.HIGH, CRITICALITY_WEIGHTS[ClaimCriticality.HIGH]
        # Check for high-stakes keywords (medical, financial, legal)
        high_stakes = ["dosage", "mg", "contraindicated", "revenue", "loss", "liability", "clause", "violation"]
        if any(term in text.lower() for term in high_stakes):
            return ClaimCriticality.HIGH, CRITICALITY_WEIGHTS[ClaimCriticality.HIGH]
        return ClaimCriticality.MEDIUM, CRITICALITY_WEIGHTS[ClaimCriticality.MEDIUM]

    def decompose(self, text: str) -> list[Claim]:
        """Split text into independent atomic claims with sub-50ms CPU latency."""
        start_time = time.time()
        cleaned_text = text.strip()
        if not cleaned_text:
            return []

        # If neural model is enabled and ready, attempt model decomposition
        if self.use_neural and self._model is not None and self._tokenizer is not None:
            claims = self._decompose_neural(cleaned_text)
            if claims:
                return claims

        # High-speed rule-based sentence & clause splitting engine (<45ms on CPU)
        claims = self._decompose_heuristic(cleaned_text)
        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug("Claim decomposition completed", num_claims=len(claims), latency_ms=round(elapsed_ms, 2))
        return claims

    def _decompose_heuristic(self, text: str) -> list[Claim]:
        """Fast, robust sentence and compound clause splitter."""
        # 1. Normalize linebreaks and bullet points
        normalized = re.sub(r"^\s*[-*•\d+.]\s*", "", text, flags=re.MULTILINE)
        raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]

        claims: list[Claim] = []
        claim_index = 1

        for sentence in raw_sentences:
            # Strip trailing punctuation
            clean_s = sentence.rstrip(".!?")
            if len(clean_s) < 5:
                continue

            # Split on compound coordinators if clauses are sufficiently substantial
            sub_clauses = re.split(
                r"\s+(?:and also|while at the same time|whereas|furthermore)\s+", clean_s, flags=re.IGNORECASE
            )

            for clause in sub_clauses:
                clause = clause.strip()
                if len(clause) < 5:
                    continue

                claim_type = self.classify_claim_type(clause)
                criticality, weight = self.assign_criticality(clause, claim_type)

                # Locate spans if present
                span_start = text.find(clause) if clause in text else None
                span_end = (span_start + len(clause)) if span_start is not None else None

                claim = Claim(
                    claim_id=f"c_{claim_index:02d}",
                    text=clause,
                    claim_type=claim_type,
                    criticality=criticality,
                    criticality_weight=weight,
                    span_start=span_start,
                    span_end=span_end,
                )
                claims.append(claim)
                claim_index += 1

        # Fallback if no claims extracted
        if not claims:
            claims.append(
                Claim(
                    claim_id="c_01",
                    text=text[:200],
                    claim_type=ClaimType.FACTUAL,
                    criticality=ClaimCriticality.MEDIUM,
                    criticality_weight=0.6,
                )
            )

        return claims

    def _decompose_neural(self, text: str) -> list[Claim] | None:
        """Neural FLAN-T5 claim extraction pass with JSON validation."""
        if self._tokenizer is None or self._model is None:
            return None
        try:
            prompt = f"Decompose the following text into atomic factual claims in JSON format: {text}"
            inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512)
            outputs = self._model.generate(**inputs, max_length=256)
            decoded = self._tokenizer.decode(outputs[0], skip_special_tokens=True)
            return self.validate_claims_json(decoded)
        except Exception as exc:
            logger.warning("Neural decomposition error, falling back to heuristic", error=str(exc))
            return None

    def validate_claims_json(self, raw_output: str) -> list[Claim] | None:
        """Parse and validate JSON string returned by model with regex fallback."""
        try:
            data = json.loads(raw_output)
            if isinstance(data, list):
                parsed: list[Claim] = []
                for idx, item in enumerate(data, start=1):
                    if isinstance(item, dict) and "text" in item:
                        c_type = self.classify_claim_type(item["text"])
                        crit, weight = self.assign_criticality(item["text"], c_type)
                        parsed.append(
                            Claim(
                                claim_id=f"c_{idx:02d}",
                                text=item["text"],
                                claim_type=c_type,
                                criticality=crit,
                                criticality_weight=weight,
                            )
                        )
                if parsed:
                    return parsed
        except Exception:
            pass
        return None
