"""ICS Worker: Intra-response pairwise claim contradiction matrix and consistency scoring."""

from models.deberta.verifier import DeBERTaNLIVerifier
from shared.logging import get_logger
from shared.schemas import Claim

logger = get_logger("ics_worker")


class ICSWorker:
    """Evaluates self-contradictory logic, arithmetic conflicts, and chronological
    paradoxes within a single response.
    """

    def __init__(self, verifier: DeBERTaNLIVerifier | None = None) -> None:
        self.verifier = verifier or DeBERTaNLIVerifier()

    def build_contradiction_matrix(self, claims: list[Claim]) -> list[list[float]]:
        """Construct symmetric pairwise contradiction probability matrix M[i][j]."""
        n = len(claims)
        matrix: list[list[float]] = [[0.0 for _ in range(n)] for _ in range(n)]

        for i in range(n):
            for j in range(i + 1, n):
                text_i = claims[i].text
                text_j = claims[j].text

                # Evaluate both directional pairs
                _, _, c_ij = self.verifier.predict_pair(text_i, text_j)
                _, _, c_ji = self.verifier.predict_pair(text_j, text_i)

                max_contra = round(max(c_ij, c_ji), 4)
                matrix[i][j] = max_contra
                matrix[j][i] = max_contra

        return matrix

    def compute_claim_ics_scores(self, claims: list[Claim]) -> dict[str, float]:
        """Compute per-claim maximum intra-response contradiction score."""
        n = len(claims)
        if n <= 1:
            return {c.claim_id: 0.0 for c in claims}

        matrix = self.build_contradiction_matrix(claims)
        scores: dict[str, float] = {}

        for i in range(n):
            c_id = claims[i].claim_id
            max_c = max((matrix[i][j] for j in range(n) if i != j), default=0.0)
            scores[c_id] = max_c

        return scores

    def compute_response_ics_score(self, claims: list[Claim]) -> float:
        """Compute aggregate response-level ICS score: max_{i != j} M[i][j]."""
        if len(claims) <= 1:
            return 0.0

        claim_scores = self.compute_claim_ics_scores(claims)
        return max(claim_scores.values(), default=0.0)
