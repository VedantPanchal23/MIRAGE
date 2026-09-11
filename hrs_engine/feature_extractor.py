"""Feature Extractor: Standardized 12-dimensional vector extraction for HRS meta-learner."""

from typing import Any

from shared.schemas import Claim, ClaimType, EvidenceChunk

FEATURE_NAMES: list[str] = [
    "rss_score",
    "p_contra",
    "p_support",
    "scs_score",
    "vgs_score",
    "ics_score",
    "claim_type_encoded",
    "criticality_weight",
    "token_length",
    "retrieved_evidence_max_similarity",
    "total_claim_count",
    "has_image",
]

CLAIM_TYPE_MAP: dict[ClaimType, float] = {
    ClaimType.FACTUAL: 0.0,
    ClaimType.TEMPORAL: 1.0,
    ClaimType.NUMERICAL: 2.0,
    ClaimType.RELATIONAL: 3.0,
    ClaimType.IMAGE_GROUNDED: 4.0,
    ClaimType.OPINION: 5.0,
}


class FeatureExtractor:
    """Extracts 12-feature vectors from claim verification signals and metadata."""

    @staticmethod
    def extract_claim_features(
        claim: Claim,
        rav_score: float,
        scs_score: float,
        p_contra: float,
        p_support: float,
        ics_score: float,
        evidence_chunks: list[EvidenceChunk],
        total_claims_count: int,
        vgs_score: float | None = None,
        has_image: bool = False,
    ) -> list[float]:
        """Extract exact 12-dimensional feature vector for a claim.

        Order of features matches Technical Architecture Section 5.2:
        1. RSS (Retrieval Support Score, 0=fully supported, 1=unsupported)
        2. p_contra (NLI max contradiction probability)
        3. p_support (NLI max entailment probability)
        4. SCS_score (Semantic Entropy normalized score)
        5. VGS (Visual Grounding Score, 0.0 if text-only)
        6. ICS (Intra-response contradiction score)
        7. claim_type_encoded (ordinal index from CLAIM_TYPE_MAP)
        8. claim_criticality_weight (1.0 for high, 0.6 for medium, 0.3 for low)
        9. token_length of claim text
        10. retrieved_evidence_max_similarity (highest similarity of retrieved chunks)
        11. total_claim_count in response
        12. has_image (1.0 if image attached, else 0.0)
        """
        type_encoded = CLAIM_TYPE_MAP.get(claim.claim_type, 0.0)
        tokens = len(claim.text.split())
        max_sim = max((c.similarity_score for c in evidence_chunks), default=0.0)
        vgs = vgs_score if vgs_score is not None else 0.0
        img_flag = 1.0 if has_image else 0.0

        return [
            float(rav_score),
            float(p_contra),
            float(p_support),
            float(scs_score),
            float(vgs),
            float(ics_score),
            float(type_encoded),
            float(claim.criticality_weight),
            float(tokens),
            float(max_sim),
            float(total_claims_count),
            float(img_flag),
        ]

    @staticmethod
    def get_feature_names() -> list[str]:
        """Return canonical ordered list of feature names."""
        return list(FEATURE_NAMES)

    @staticmethod
    def to_dict(feature_vector: list[float]) -> dict[str, Any]:
        """Convert feature vector to a name-indexed dictionary for logging/explainability."""
        return dict(zip(FEATURE_NAMES, feature_vector, strict=False))
