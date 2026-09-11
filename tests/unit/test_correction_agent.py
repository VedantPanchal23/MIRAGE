"""Unit and graph execution tests for Phase 6 LangGraph Agentic Correction Loop."""

import pytest

from correction_agent.agent import CorrectionAgent
from correction_agent.graph import CorrectionGraph
from correction_agent.prompter import CorrectionPrompter
from correction_agent.state import MirageAgentState
from shared.schemas import (
    Claim,
    ClaimCriticality,
    ClaimType,
    ClaimVerificationResult,
    EvidenceChunk,
    VerificationRequest,
    VerificationStatus,
)
from workers.orchestrator import VerificationOrchestrator


@pytest.mark.unit
class TestCorrectionPrompter:
    def test_prompt_formatting_with_evidence(self) -> None:
        claim = "Albert Einstein was born in 1945."
        evidence = [
            "Albert Einstein was born on 14 March 1879 in Ulm, Germany.",
            "He was a German-born theoretical physicist.",
        ]
        user_msg = CorrectionPrompter.format_user_prompt(claim, evidence)
        assert "ORIGINAL CLAIM: Albert Einstein was born in 1945." in user_msg
        assert "Albert Einstein was born on 14 March 1879" in user_msg
        assert "CORRECTED CLAIM:" in user_msg

        messages = CorrectionPrompter.build_messages(claim, evidence)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_prompt_formatting_empty_evidence(self) -> None:
        user_msg = CorrectionPrompter.format_user_prompt("Unfounded claim", [])
        assert "No authoritative evidence available." in user_msg


@pytest.mark.unit
class TestCorrectionGraph:
    @pytest.mark.asyncio
    async def test_correction_state_machine_flow(self) -> None:
        graph = CorrectionGraph()
        initial_state: MirageAgentState = {
            "response_id": "resp_001",
            "original_response": "Penicillin was discovered in 1999 by Alexander Fleming.",
            "flagged_claims": [
                {
                    "claim_id": "c1",
                    "text": "Penicillin was discovered in 1999",
                    "criticality_weight": 1.0,
                    "risk_score": 0.85,
                }
            ],
            "evidence_map": {"c1": ["Penicillin was discovered in 1928 by Alexander Fleming."]},
            "rewritten_claims": {},
            "rewrite_hrs": 1.0,
            "correction_attempts": 0,
            "escalated": False,
            "final_response": "Penicillin was discovered in 1999 by Alexander Fleming.",
            "history": [],
        }

        final_state = await graph.correct(initial_state)

        # 1. Rewritten claim should have the corrected year 1928
        assert "1928" in final_state["final_response"]
        assert "1999" not in final_state["final_response"]
        # 2. Correction attempts should be bounded (>=1 and <= 2)
        assert 1 <= final_state["correction_attempts"] <= 2
        # 3. Not escalated since rewrite succeeded
        assert final_state["escalated"] is False

    @pytest.mark.asyncio
    async def test_bounded_loop_escalation(self) -> None:
        graph = CorrectionGraph()
        # Initial state with simulated uncorrectable claim without evidence
        initial_state: MirageAgentState = {
            "response_id": "resp_002",
            "original_response": "The phantom galaxy has 500 million moons.",
            "flagged_claims": [
                {
                    "claim_id": "c2",
                    "text": "The phantom galaxy has 500 million moons",
                    "criticality_weight": 1.0,
                    "risk_score": 0.95,
                }
            ],
            "evidence_map": {"c2": []},
            "rewritten_claims": {},
            "rewrite_hrs": 1.0,
            "correction_attempts": 0,
            "escalated": False,
            "final_response": "The phantom galaxy has 500 million moons.",
            "history": [],
        }

        final_state = await graph.correct(initial_state)
        # Bounded loop must cut off at attempt 2 and escalate
        assert final_state["correction_attempts"] == 2
        assert final_state["escalated"] is True


@pytest.mark.unit
class TestCorrectionAgent:
    @pytest.mark.asyncio
    async def test_correct_response_contradicted(self) -> None:
        agent = CorrectionAgent()
        claim = Claim(
            claim_id="c_fleming",
            text="Alexander Fleming discovered penicillin in 1999",
            claim_type=ClaimType.TEMPORAL,
            criticality=ClaimCriticality.HIGH,
            criticality_weight=1.0,
        )
        chunk = EvidenceChunk(
            chunk_id="chk_fl",
            document_id="doc_fl",
            content="Penicillin was discovered in 1928 by Scottish physician Alexander Fleming.",
            similarity_score=0.95,
        )
        verified_claim = ClaimVerificationResult(
            claim=claim,
            status=VerificationStatus.CONTRADICTED,
            risk_score=0.88,
            rav_score=0.10,
            scs_score=0.05,
            nli_score=0.90,
            ics_score=0.00,
            signal_attribution={"rav": 0.1, "scs": 0.1, "nli": 0.8, "ics": 0.0},
            evidence_chunks=[chunk],
            explanation="Contradicted year",
        )

        (
            final_text,
            was_corrected,
            attempts,
            final_hrs,
            escalated,
        ) = await agent.correct_response(
            response_id="test_resp_1",
            original_response="Alexander Fleming discovered penicillin in 1999 at St Mary's Hospital.",
            verified_claims=[verified_claim],
        )

        assert was_corrected is True
        assert "1928" in final_text
        assert "1999" not in final_text
        assert attempts >= 1
        assert escalated is False

    @pytest.mark.asyncio
    async def test_orchestrator_end_to_end_with_correction(self) -> None:
        orchestrator = VerificationOrchestrator()
        orchestrator.rav_worker.add_mock_document(
            chunk_id="chk_germany",
            content="Berlin is the capital and largest city of Germany.",
        )

        # Request containing an inaccurate capital statement
        req = VerificationRequest(
            prompt="What is the capital of Germany?",
            response="Munich is the capital of Germany.",
            tenant_id="tenant_enterprise",
        )

        resp = await orchestrator.verify_request(req)
        # Contradiction should trigger the correction loop
        assert resp.metadata.correction_applied is True
        assert resp.metadata.correction_iterations >= 1
        assert "Berlin" in resp.verified_response
        assert resp.original_response == "Munich is the capital of Germany."
