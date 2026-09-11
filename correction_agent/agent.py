"""Correction Agent: High-level interface to the LangGraph autonomous correction loop."""

from correction_agent.graph import CorrectionGraph
from correction_agent.state import MirageAgentState
from shared.logging import get_logger
from shared.schemas import ClaimVerificationResult, VerificationStatus

logger = get_logger("correction_agent")


class CorrectionAgent:
    """High-level facade orchestrating factual correction of hallucinated completions."""

    def __init__(self, graph: CorrectionGraph | None = None) -> None:
        self.graph = graph or CorrectionGraph()

    async def correct_response(
        self,
        response_id: str,
        original_response: str,
        verified_claims: list[ClaimVerificationResult],
    ) -> tuple[str, bool, int, float, bool]:
        """Trigger autonomous correction for contradicted or high-risk claims.

        Returns:
            Tuple of:
            - final_text (str): rewritten response
            - was_corrected (bool): True if any claim was successfully rewritten
            - attempts (int): number of correction attempts made
            - final_hrs (float): HRS of rewritten claims
            - escalated (bool): True if max retries exceeded
        """
        flagged: list[dict[str, object]] = []
        evidence_map: dict[str, list[str]] = {}

        for c in verified_claims:
            if c.status == VerificationStatus.CONTRADICTED or c.risk_score > 0.60:
                flagged.append(
                    {
                        "claim_id": c.claim.claim_id,
                        "text": c.claim.text,
                        "criticality_weight": c.claim.criticality_weight,
                        "risk_score": c.risk_score,
                    }
                )
                evidence_map[c.claim.claim_id] = [chunk.content for chunk in c.evidence_chunks]

        if not flagged:
            # No claims require correction
            return original_response, False, 0, 0.0, False

        logger.info(
            "Initiating LangGraph correction loop",
            response_id=response_id,
            flagged_claims_count=len(flagged),
        )

        initial_state: MirageAgentState = {
            "response_id": response_id,
            "original_response": original_response,
            "flagged_claims": flagged,
            "evidence_map": evidence_map,
            "rewritten_claims": {},
            "rewrite_hrs": 1.0,
            "correction_attempts": 0,
            "escalated": False,
            "final_response": original_response,
            "history": [],
        }

        final_state = await self.graph.correct(initial_state)

        final_text = final_state.get("final_response", original_response)
        attempts = final_state.get("correction_attempts", 0)
        final_hrs = final_state.get("rewrite_hrs", 0.0)
        escalated = final_state.get("escalated", False)
        was_corrected = final_text != original_response

        logger.info(
            "LangGraph correction completed",
            response_id=response_id,
            was_corrected=was_corrected,
            attempts=attempts,
            final_hrs=final_hrs,
            escalated=escalated,
        )

        return final_text, was_corrected, attempts, final_hrs, escalated
