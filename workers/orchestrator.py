"""Verification Pipeline Orchestrator running parallel workers across RAV, SCS, ICS, and NLI."""

import asyncio
import time
import uuid

from models.deberta.verifier import DeBERTaNLIVerifier
from models.flan_t5.decomposer import AtomicClaimDecomposer
from shared.logging import get_logger
from shared.schemas import (
    ClaimVerificationResult,
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
    ) -> None:
        self.decomposer = decomposer or AtomicClaimDecomposer(use_neural=False)
        self.verifier = nli_verifier or DeBERTaNLIVerifier(use_neural=False)
        self.rav_worker = rav_worker or RAVWorker()
        self.scs_worker = scs_worker or SCSWorker(verifier=self.verifier)
        self.ics_worker = ics_worker or ICSWorker(verifier=self.verifier)

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

        # 4. Synthesize per-claim verification results
        verified_claims: list[ClaimVerificationResult] = []
        weighted_claim_risk_sum = 0.0

        for idx, claim in enumerate(claims):
            chunks = evidence_results[idx]
            s_rav = self.rav_worker.compute_rav_score(claim, chunks)
            s_nli = self.verifier.aggregate_multi_evidence(claim.text, chunks)
            s_ics = ics_scores.get(claim.claim_id, 0.0)

            # Signal weighting: RAV (0.35) + SCS (0.20) + NLI (0.30) + ICS (0.15)
            w_rav, w_scs, w_nli, w_ics = 0.35, 0.20, 0.30, 0.15
            claim_risk = round(
                w_rav * s_rav + w_scs * scs_score + w_nli * s_nli + w_ics * s_ics,
                4,
            )

            # Determine claim status
            if s_nli > 0.65 or s_ics > 0.70 or claim_risk > 0.60:
                status = VerificationStatus.CONTRADICTED
                explanation = "Contradiction detected by NLI logic or intra-response consistency check."
            elif claim_risk < 0.25 and s_rav < 0.20:
                status = VerificationStatus.SUPPORTED
                explanation = "Claim is strongly supported by retrieved knowledge base evidence."
            elif not chunks:
                status = VerificationStatus.INSUFFICIENT_EVIDENCE
                explanation = "No authoritative evidence chunks found in configured knowledge base."
            else:
                status = VerificationStatus.NEUTRAL
                explanation = "Claim has neutral evidence alignment."

            attribution = {
                "rav": round(w_rav * s_rav / max(claim_risk, 0.01), 3),
                "scs": round(w_scs * scs_score / max(claim_risk, 0.01), 3),
                "nli": round(w_nli * s_nli / max(claim_risk, 0.01), 3),
                "ics": round(w_ics * s_ics / max(claim_risk, 0.01), 3),
            }

            verified_claims.append(
                ClaimVerificationResult(
                    claim=claim,
                    status=status,
                    risk_score=claim_risk,
                    rav_score=s_rav,
                    scs_score=scs_score,
                    nli_score=s_nli,
                    ics_score=s_ics,
                    signal_attribution=attribution,
                    evidence_chunks=chunks,
                    explanation=explanation,
                )
            )
            weighted_claim_risk_sum += claim_risk * claim.criticality_weight

        # 5. Criticality-weighted response HRS aggregation
        weight_sum = sum(c.criticality_weight for c in claims) or 1.0
        response_hrs = round(min(1.0, max(0.0, weighted_claim_risk_sum / weight_sum)), 4)
        tier = determine_risk_tier(response_hrs)
        elapsed_ms = round((time.time() - start_time) * 1000, 2)

        hrs_result = HRSResult(
            hrs=response_hrs,
            raw_score=response_hrs,
            tier=tier,
            conformal_interval=ConformalInterval(
                lower=max(0.0, round(response_hrs - 0.06, 4)),
                upper=min(1.0, round(response_hrs + 0.06, 4)),
                confidence_level=0.95,
                conditional_group=f"tier:{tier.value}",
            ),
            signal_attribution=SignalAttribution(rav=0.35, scs=0.20, nli=0.30, ics=0.15),
            claims_count=len(claims),
            contradicted_claims_count=sum(1 for c in verified_claims if c.status == VerificationStatus.CONTRADICTED),
            computation_latency_ms=elapsed_ms,
        )

        metadata = VerificationMetadata(
            trace_id=trace_id,
            execution_time_ms=elapsed_ms,
            pipeline_signals_used=["rav", "scs", "nli", "ics"],
            cached_scs_hit=cached_scs_hit,
            correction_applied=False,
        )

        return VerificationResponse(
            request_id=f"req_{uuid.uuid4().hex[:12]}",
            verified_response=request.response,
            original_response=request.response,
            hrs_result=hrs_result,
            claims=verified_claims,
            metadata=metadata,
        )
