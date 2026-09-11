"""LangGraph State Machine: Agentic multi-node correction loop with bounded retries."""

import re
from typing import Any, Literal

import httpx
from langgraph.graph import END, StateGraph

from correction_agent.prompter import CorrectionPrompter
from correction_agent.state import MirageAgentState
from models.deberta import DeBERTaNLIVerifier
from shared.config import get_settings
from shared.logging import get_logger
from workers.rav.worker import RAVWorker

logger = get_logger("correction_graph")
settings = get_settings()


class CorrectionGraph:
    """LangGraph-powered state machine for autonomous claim correction."""

    def __init__(
        self,
        rav_worker: RAVWorker | None = None,
        verifier: DeBERTaNLIVerifier | None = None,
        llm_api_url: str | None = None,
    ) -> None:
        self.rav_worker = rav_worker or RAVWorker()
        self.verifier = verifier or DeBERTaNLIVerifier(use_neural=False)
        self.llm_api_url = llm_api_url or settings.llm_upstream_url
        self._compiled_graph: Any = None
        self._build_graph()

    def _build_graph(self) -> None:
        """Construct the LangGraph state machine with nodes and conditional gates."""
        workflow = StateGraph(MirageAgentState)

        workflow.add_node("plan_correction", self._node_plan_correction)
        workflow.add_node("retrieve_evidence", self._node_retrieve_evidence)
        workflow.add_node("rewrite_claims", self._node_rewrite_claims)
        workflow.add_node("verify_rewrite", self._node_verify_rewrite)
        workflow.add_node("assemble_response", self._node_assemble_response)
        workflow.add_node("escalate", self._node_escalate)

        workflow.set_entry_point("plan_correction")
        workflow.add_edge("plan_correction", "retrieve_evidence")
        workflow.add_edge("retrieve_evidence", "rewrite_claims")
        workflow.add_edge("rewrite_claims", "verify_rewrite")

        workflow.add_conditional_edges(
            "verify_rewrite",
            self._check_gate,
            {
                "success": "assemble_response",
                "retry": "rewrite_claims",
                "escalate": "escalate",
            },
        )
        workflow.add_edge("escalate", "assemble_response")
        workflow.add_edge("assemble_response", END)

        self._compiled_graph = workflow.compile()
        logger.info("Compiled LangGraph Correction StateGraph")

    async def _node_plan_correction(self, state: MirageAgentState) -> dict[str, Any]:
        """Node 1: Prioritize claims by criticality weight and risk score."""
        flagged = list(state.get("flagged_claims", []))
        # Sort: high criticality weight first, then highest risk score
        flagged.sort(
            key=lambda c: (
                c.get("criticality_weight", 1.0),
                c.get("risk_score", 0.5),
            ),
            reverse=True,
        )
        logger.info("Prioritized claims for correction", count=len(flagged))
        return {"flagged_claims": flagged}

    async def _node_retrieve_evidence(self, state: MirageAgentState) -> dict[str, Any]:
        """Node 2: Retrieve top evidence chunks from RAV for flagged claims."""
        evidence_map = dict(state.get("evidence_map", {}))
        for claim in state.get("flagged_claims", []):
            claim_id = claim.get("claim_id", "")
            claim_text = claim.get("text", "")
            if not evidence_map.get(claim_id) and claim_text:
                chunks = await self.rav_worker.search_evidence(claim_text, limit=3)
                evidence_map[claim_id] = [c.content for c in chunks]

        return {"evidence_map": evidence_map}

    async def _node_rewrite_claims(self, state: MirageAgentState) -> dict[str, Any]:
        """Node 3: Rewrite flagged claims using strict evidence-grounded prompt."""
        rewritten = dict(state.get("rewritten_claims", {}))
        evidence_map = state.get("evidence_map", {})

        for claim in state.get("flagged_claims", []):
            cid = claim.get("claim_id", "")
            text = claim.get("text", "")
            ev_list = evidence_map.get(cid, [])

            rewritten_text = await self._call_llm_or_fallback(text, ev_list)
            rewritten[cid] = rewritten_text

        return {"rewritten_claims": rewritten}

    async def _node_verify_rewrite(self, state: MirageAgentState) -> dict[str, Any]:
        """Node 4: Fast verification pass (RAV + NLI only) on rewritten claims."""
        attempts = state.get("correction_attempts", 0) + 1
        rewritten = state.get("rewritten_claims", {})
        evidence_map = state.get("evidence_map", {})

        claim_risks: list[float] = []
        for claim in state.get("flagged_claims", []):
            cid = claim.get("claim_id", "")
            new_text = rewritten.get(cid, claim.get("text", ""))
            ev_list = evidence_map.get(cid, [])

            if ev_list:
                # Pairwise NLI: check if evidence entails the rewritten claim
                p_entail, _, p_contra = self.verifier.predict_pair(ev_list[0], new_text)
                risk = p_contra + 0.3 * (1.0 - p_entail)
                claim_risks.append(min(1.0, max(0.0, risk)))
            else:
                claim_risks.append(0.5)

        avg_hrs = round(sum(claim_risks) / max(len(claim_risks), 1), 4)
        logger.info("Re-verification pass completed", attempt=attempts, rewrite_hrs=avg_hrs)

        return {
            "rewrite_hrs": avg_hrs,
            "correction_attempts": attempts,
            "history": state.get("history", []) + [{"attempt": attempts, "hrs": avg_hrs}],
        }

    async def _node_assemble_response(self, state: MirageAgentState) -> dict[str, Any]:
        """Node 5: Assemble final response replacing original claims with rewritten text."""
        final_text = state.get("original_response", "")
        rewritten = state.get("rewritten_claims", {})

        for claim in state.get("flagged_claims", []):
            cid = claim.get("claim_id", "")
            old_text = claim.get("text", "")
            new_text = rewritten.get(cid)
            if new_text and old_text in final_text:
                final_text = final_text.replace(old_text, new_text)

        return {"final_response": final_text}

    async def _node_escalate(self, state: MirageAgentState) -> dict[str, Any]:
        """Node 6: Flag for human operator review if retries exceeded."""
        logger.warning(
            "Correction attempts exceeded threshold, escalating to human review",
            response_id=state.get("response_id"),
            attempts=state.get("correction_attempts"),
            final_hrs=state.get("rewrite_hrs"),
        )
        return {"escalated": True}

    def _check_gate(self, state: MirageAgentState) -> Literal["success", "retry", "escalate"]:
        """Conditional edge router: bounds loop to max 2 retries."""
        hrs = state.get("rewrite_hrs", 1.0)
        attempts = state.get("correction_attempts", 0)

        if hrs <= 0.30:
            return "success"
        if attempts >= 2:
            return "escalate"
        return "retry"

    async def _call_llm_or_fallback(self, original_text: str, evidence_chunks: list[str]) -> str:
        """Query LLM with evidence prompt or apply intelligent fallback grounded in evidence."""
        if not evidence_chunks:
            return original_text

        # 1. Attempt upstream LLM call if API key and URL are configured
        if settings.groq_api_key and settings.groq_api_key != "mock-groq-key":
            try:
                messages = CorrectionPrompter.build_messages(original_text, evidence_chunks)
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.post(
                        f"{self.llm_api_url}/chat/completions",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        json={
                            "model": settings.default_primary_model,
                            "messages": messages,
                            "temperature": 0.1,
                            "max_tokens": 150,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        content = data["choices"][0]["message"]["content"].strip()
                        if content:
                            return str(content)
            except Exception as exc:
                logger.debug("Upstream LLM rewrite call failed, using evidence alignment fallback", error=str(exc))

        # 2. Rule-based factual alignment fallback:
        # Replaces numerical / date discrepancies with authoritative evidence values
        top_ev = evidence_chunks[0]
        ev_nums = re.findall(r"\b\d+\b", top_ev)
        orig_nums = re.findall(r"\b\d+\b", original_text)

        if ev_nums and orig_nums and ev_nums[0] != orig_nums[0]:
            return original_text.replace(orig_nums[0], ev_nums[0])

        # If evidence contains the direct fact, ground to evidence statement
        if len(top_ev.split(".")) > 0:
            clean_first_sentence = top_ev.split(".")[0].strip()
            if len(clean_first_sentence) > 10:
                return clean_first_sentence + "."

        return original_text

    async def correct(self, initial_state: MirageAgentState) -> MirageAgentState:
        """Run the full LangGraph state machine from entry point to termination."""
        result = await self._compiled_graph.ainvoke(initial_state)
        return dict(result)  # type: ignore[return-value]
