"""Verification Pipeline Orchestrator running parallel workers across RAV, SCS, ICS, and NLI."""

import asyncio
import time
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from correction_agent.agent import CorrectionAgent

from hrs_engine import HRSEngine
from models.deberta import DeBERTaNLIVerifier
from models.flan_t5 import AtomicClaimDecomposer
from shared.logging import get_logger
from shared.schemas import (
    ConformalInterval,
    HRSResult,
    SignalAttribution,
    VerificationMetadata,
    VerificationRequest,
    VerificationResponse,
    VerificationStatus,
    determine_risk_tier,
)
from shared.tracing import get_current_trace_id
from workers.ics.worker import ICSWorker
from workers.rav.worker import RAVWorker
from workers.scs.worker import SCSWorker

logger = get_logger("verification_orchestrator")


class VerificationOrchestrator:
    """Coordinates parallel execution of the 4 core text verification signals."""

    def __init__(
        self,
        decomposer: AtomicClaimDecomposer | None = None,
        rav_worker: RAVWorker | None = None,
        scs_worker: SCSWorker | None = None,
        ics_worker: ICSWorker | None = None,
        nli_verifier: DeBERTaNLIVerifier | None = None,
        hrs_engine: HRSEngine | None = None,
        correction_agent: "CorrectionAgent | None" = None,
    ) -> None:
        self.decomposer = decomposer or AtomicClaimDecomposer(use_neural=False)
        self.verifier = nli_verifier or DeBERTaNLIVerifier(use_neural=False)
        self.rav_worker = rav_worker or RAVWorker()
        self.scs_worker = scs_worker or SCSWorker(verifier=self.verifier)
        self.ics_worker = ics_worker or ICSWorker(verifier=self.verifier)
        self.hrs_engine = hrs_engine or HRSEngine()

        if correction_agent is None:
            from correction_agent.agent import CorrectionAgent as _CorrectionAgent

            self.correction_agent = _CorrectionAgent(graph=None)
        else:
            self.correction_agent = correction_agent

    async def verify_request(self, request: VerificationRequest) -> VerificationResponse:
        """Execute full multi-signal factual consistency verification pipeline."""
        start_time = time.time()
        trace_id = get_current_trace_id()

        # 1. Atomic claim decomposition (sub-50ms)
        claims = self.decomposer.decompose(request.response)
        if not claims:
            # Empty response or pure whitespace
            hrs_res = HRSResult(
                hrs=0.0,
                raw_score=0.0,
                tier=determine_risk_tier(0.0),
                conformal_interval=ConformalInterval(lower=0.0, upper=0.05),
                signal_attribution=SignalAttribution(),
                claims_count=0,
                contradicted_claims_count=0,
                computation_latency_ms=0.0,
            )
            return VerificationResponse(
                request_id=f"req_{uuid.uuid4().hex[:12]}",
                verified_response=request.response,
                original_response=request.response,
                hrs_result=hrs_res,
                claims=[],
                metadata=VerificationMetadata(
                    trace_id=trace_id,
                    execution_time_ms=0.0,
                    pipeline_signals_used=[],
                ),
            )

        # 2. Parallel signal execution: SCS prompt variance + ICS contradiction matrix
        scs_task = asyncio.create_task(
            self.scs_worker.compute_scs_score(
                prompt=request.prompt,
                model_id=request.model_id,
                tenant_id=request.tenant_id,
            )
        )
        ics_scores = self.ics_worker.compute_claim_ics_scores(claims)

        # 3. Parallel RAV evidence search per claim
        rav_tasks = [
            self.rav_worker.search_evidence(
                query=c.text,
                collection_name=request.knowledge_base_id or "default_kb",
            )
            for c in claims
        ]
        evidence_results = await asyncio.gather(*rav_tasks)
        scs_score, cached_scs_hit = await scs_task

        # 4. Compute per-claim RAV and NLI scores
        rav_scores: list[float] = [
            self.rav_worker.compute_rav_score(c, evidence_results[idx]) for idx, c in enumerate(claims)
        ]
        nli_scores: list[float] = [
            self.verifier.aggregate_multi_evidence(c.text, evidence_results[idx]) for idx, c in enumerate(claims)
        ]

        # 5. Synthesize calibrated HRS and Mondrian conformal intervals
        hrs_result, verified_claims = self.hrs_engine.process_claims(
            claims=claims,
            rav_scores=rav_scores,
            evidence_chunks_per_claim=evidence_results,
            scs_score=scs_score,
            ics_scores=ics_scores,
            nli_scores=nli_scores,
            scs_enabled=True,
            has_image=False,
        )

        req_id = f"req_{uuid.uuid4().hex[:12]}"
        verified_text = request.response
        correction_applied = False
        correction_iters = 0

        # 6. Trigger agentic correction loop if risk is High or Critical (> 0.60)
        has_contradiction = any(c.status == VerificationStatus.CONTRADICTED for c in verified_claims)
        if hrs_result.hrs > 0.60 or has_contradiction:
            (
                corrected_text,
                was_corrected,
                iters,
                _,
                _,
            ) = await self.correction_agent.correct_response(
                response_id=req_id,
                original_response=request.response,
                verified_claims=verified_claims,
            )
            if was_corrected:
                verified_text = corrected_text
                correction_applied = True
                correction_iters = iters

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        hrs_result.computation_latency_ms = elapsed_ms

        metadata = VerificationMetadata(
            trace_id=trace_id,
            execution_time_ms=elapsed_ms,
            pipeline_signals_used=["rav", "scs", "nli", "ics"],
            cached_scs_hit=cached_scs_hit,
            correction_applied=correction_applied,
            correction_iterations=correction_iters,
        )

        return VerificationResponse(
            request_id=req_id,
            verified_response=verified_text,
            original_response=request.response,
            hrs_result=hrs_result,
            claims=verified_claims,
            metadata=metadata,
        )
