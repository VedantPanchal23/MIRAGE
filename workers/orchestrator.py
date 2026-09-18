"""Verification Pipeline Orchestrator running parallel workers across RAV, SCS, ICS, and NLI."""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from correction_agent.agent import CorrectionAgent

from analytics.store import default_session_store
from db.mongo import MongoDuplicateTraceError, MongoTraceService, default_mongo_trace_service
from db.persistence import (
    AmbiguousPostgresCommitError,
    DatabasePersistenceError,
    DefinitivePostgresPersistenceError,
    DuplicateSessionError,
    PostgresPersistenceService,
    default_persistence_service,
)
from gateway.middleware.pii import PIIDetector
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
from shared.telemetry import record_verification_metrics, time_module
from shared.tracing import get_current_trace_id, trace_span
from workers.ics.worker import ICSWorker
from workers.rav.worker import RAVWorker
from workers.scs.worker import SCSWorker
from workers.visual import VisualGroundingWorker

logger = get_logger("verification_orchestrator")


class VerificationOrchestrator:
    """Coordinates parallel execution of the verification signals across RAV, SCS, ICS, NLI, and VGS."""

    def __init__(
        self,
        decomposer: AtomicClaimDecomposer | None = None,
        rav_worker: RAVWorker | None = None,
        scs_worker: SCSWorker | None = None,
        ics_worker: ICSWorker | None = None,
        nli_verifier: DeBERTaNLIVerifier | None = None,
        hrs_engine: HRSEngine | None = None,
        correction_agent: "CorrectionAgent | None" = None,
        visual_worker: VisualGroundingWorker | None = None,
        persistence_service: PostgresPersistenceService | None = default_persistence_service,
        mongo_service: MongoTraceService | None = default_mongo_trace_service,
    ) -> None:
        self.decomposer = decomposer or AtomicClaimDecomposer(use_neural=False)
        self.verifier = nli_verifier or DeBERTaNLIVerifier(use_neural=False)
        self.rav_worker = rav_worker or RAVWorker()
        self.scs_worker = scs_worker or SCSWorker(verifier=self.verifier)
        self.ics_worker = ics_worker or ICSWorker(verifier=self.verifier)
        self.hrs_engine = hrs_engine or HRSEngine()
        self.visual_worker = visual_worker or VisualGroundingWorker()
        self.persistence_service = persistence_service
        self.mongo_service = mongo_service

        if correction_agent is None:
            from correction_agent.agent import CorrectionAgent as _CorrectionAgent

            self.correction_agent = _CorrectionAgent(graph=None)
        else:
            self.correction_agent = correction_agent

    async def verify_request(self, request: VerificationRequest) -> VerificationResponse:
        """Execute full multi-signal factual consistency verification pipeline."""
        start_time = time.time()
        trace_id = get_current_trace_id()

        with trace_span(
            "mirage.pipeline_execution",
            attributes={
                "tenant_id": request.tenant_id,
                "model_id": request.model_id,
                "prompt": request.prompt,  # will be hashed by sanitize_trace_attributes
                "response": request.response,  # will be hashed by sanitize_trace_attributes
            },
        ):
            # 1. Atomic claim decomposition (sub-50ms)
            with trace_span("mirage.claim_decomposition"), time_module("flan_t5"):
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
                record_verification_metrics(
                    tenant_id=request.tenant_id,
                    model_id=request.model_id,
                    hrs=0.0,
                    tier="LOW",
                    ci_width=0.05,
                    latency_seconds=0.0,
                    cached_scs_hit=None,
                    correction_applied=False,
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

            images = request.all_images
            has_image = bool(images)
            signals_used: list[str] = ["rav", "scs", "nli", "ics"]

            # 2. Parallel signal execution: SCS prompt variance + ICS contradiction matrix + Visual Grounding
            visual_task: asyncio.Task[Any] | None = None
            if has_image:
                visual_task = asyncio.create_task(
                    self.visual_worker.verify_claims(
                        claims=claims,
                        images=images,
                    )
                )

            with trace_span("mirage.scs_and_ics_signals"):
                with time_module("scs"):
                    scs_task = asyncio.create_task(
                        self.scs_worker.compute_scs_score(
                            prompt=request.prompt,
                            model_id=request.model_id,
                            tenant_id=request.tenant_id,
                        )
                    )
                with time_module("ics"):
                    ics_scores = self.ics_worker.compute_claim_ics_scores(claims)

            # 3. Parallel RAV evidence search per claim
            with trace_span("mirage.rav_retrieval"), time_module("rav"):
                rav_tasks = [
                    self.rav_worker.search_evidence(
                        query=c.text,
                        collection_name=request.knowledge_base_id or "default_kb",
                    )
                    for c in claims
                ]
                evidence_results = await asyncio.gather(*rav_tasks)
                scs_score, cached_scs_hit = await scs_task

            # 4. Compute per-claim RAV and NLI scores (+ gather Visual Grounding if multimodal)
            with trace_span("mirage.nli_scoring"), time_module("nli"):
                rav_scores: list[float] = [
                    self.rav_worker.compute_rav_score(c, evidence_results[idx]) for idx, c in enumerate(claims)
                ]
                nli_scores: list[float] = [
                    self.verifier.aggregate_multi_evidence(c.text, evidence_results[idx])
                    for idx, c in enumerate(claims)
                ]

            vgs_scores: list[float] | None = None
            if visual_task is not None:
                with trace_span("mirage.visual_grounding"), time_module("visual"):
                    visual_results = await visual_task
                    vgs_scores = [vr[0] for vr in visual_results]
                    signals_used.append("vgs")

            # 5. Synthesize calibrated HRS and Mondrian conformal intervals
            with trace_span("mirage.hrs_synthesis"), time_module("hrs_engine"):
                hrs_result, verified_claims = self.hrs_engine.process_claims(
                    claims=claims,
                    rav_scores=rav_scores,
                    evidence_chunks_per_claim=evidence_results,
                    scs_score=scs_score,
                    ics_scores=ics_scores,
                    nli_scores=nli_scores,
                    vgs_scores=vgs_scores,
                    scs_enabled=True,
                    has_image=has_image,
                )

            req_id = request.session_id or f"req_{uuid.uuid4().hex[:12]}"
            verified_text = request.response
            correction_applied = False
            correction_iters = 0

            # 6. Trigger agentic correction loop if risk is High or Critical (> 0.60)
            has_contradiction = any(c.status == VerificationStatus.CONTRADICTED for c in verified_claims)
            if hrs_result.hrs > 0.60 or has_contradiction:
                with trace_span("mirage.agentic_correction"), time_module("correction"):
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
            ci_width = round(hrs_result.conformal_interval.upper - hrs_result.conformal_interval.lower, 4)

            # Record metrics & audit session
            record_verification_metrics(
                tenant_id=request.tenant_id,
                model_id=request.model_id,
                hrs=hrs_result.hrs,
                tier=hrs_result.tier.value,
                ci_width=ci_width,
                latency_seconds=elapsed_ms / 1000.0,
                cached_scs_hit=cached_scs_hit,
                correction_applied=correction_applied,
                correction_success=correction_applied and verified_text != request.response,
            )

            # Store session in analytics store
            claims_dicts: list[dict[str, Any]] = [
                {
                    "claim_id": c.claim.claim_id,
                    "text": c.claim.text,
                    "type": c.claim.claim_type.value,
                    "criticality": c.claim.criticality.value,
                    "status": c.status.value,
                    "hrs_contribution": c.risk_score,
                }
                for c in verified_claims
            ]

            attribution_dict: dict[str, float] = {
                "rav": hrs_result.signal_attribution.rav,
                "scs": hrs_result.signal_attribution.scs,
                "nli": hrs_result.signal_attribution.nli,
                "ics": hrs_result.signal_attribution.ics,
                "vgs": hrs_result.signal_attribution.vgs if hrs_result.signal_attribution.vgs is not None else 0.0,
            }

            # 7. Coordinated Cross-Database Dual-Write (Best-Effort Dual-Write with Compensation)
            # Consistency Model: Best-effort coordinated dual-write (NOT an atomic 2PC distributed transaction).
            # Failure Windows:
            # - Window 1 (Mongo fails first): Aborts before PG. 0 records in both. Returns HTTP 503.
            # - Window 2 (PG fails after Mongo): PG rolls back; compensating delete cleans Mongo. Returns HTTP 503.
            # - Window 3 (Crash after PG commit): Both durable on disk; client observes connection drop (never 200).
            # - Window 4 (PG commit outcome ambiguous): Network drop during commit ACK. If PG committed,
            #   compensating delete would drop Mongo trace leaving PG orphan. Cannot guarantee atomicity.
            # - Window 5 (Compensating delete fails): PG rolled back; Mongo delete fails -> unrecoverable orphan
            #   remains in Mongo until TTL or reconciliation. Re-raises PG error -> Returns HTTP 503.
            # - Window 6 (Request retry): Duplicate session_id fails fast via unique indexes (Mongo unique session_id,
            #   PG primary key).

            # Scan prompt and response for PII indicators (Security_Access.md §4.3)
            # Flagging only: records detected types and counts in metadata; never extracts/logs raw PII strings.
            prompt_pii = PIIDetector.scan(request.prompt)
            resp_pii = PIIDetector.scan(request.response)
            pii_flagged = bool(prompt_pii["pii_detected"] or resp_pii["pii_detected"])
            detected_types = sorted(set(prompt_pii["types"] + resp_pii["types"]))
            total_pii_count = int(prompt_pii["count"] + resp_pii["count"])

            # Step 1: Persist deep unstructured execution trace to MongoDB
            if self.mongo_service is not None:
                trace_doc: dict[str, Any] = {
                    "session_id": req_id,
                    "tenant_id": request.tenant_id,
                    "trace_id": trace_id,
                    "model_id": request.model_id,
                    "raw_prompt": request.prompt,
                    "raw_response": request.response,
                    "verified_response": verified_text,
                    "hrs_result": hrs_result.model_dump() if hasattr(hrs_result, "model_dump") else {},
                    "claims": [
                        {
                            "claim_id": getattr(getattr(vc, "claim", vc), "claim_id", getattr(vc, "id", "")),
                            "text": getattr(getattr(vc, "claim", vc), "text", getattr(vc, "claim_text", "")),
                            "type": getattr(getattr(getattr(vc, "claim", vc), "claim_type", None), "value", "factual"),
                            "criticality": getattr(
                                getattr(getattr(vc, "claim", vc), "criticality", None), "value", "medium"
                            ),
                            "status": getattr(getattr(vc, "status", None), "value", "SUPPORTED"),
                            "risk_score": float(getattr(vc, "risk_score", 0.0)),
                            "signal_scores": getattr(vc, "signal_scores", {}),
                        }
                        for vc in verified_claims
                    ],
                    "evidence_chunks": [
                        {
                            "claim_index": idx,
                            "claim_text": c.text,
                            "chunks": [
                                ch.model_dump()
                                if hasattr(ch, "model_dump")
                                else (ch.__dict__ if hasattr(ch, "__dict__") else ch)
                                for ch in (evidence_results[idx] if idx < len(evidence_results) else [])
                            ],
                        }
                        for idx, c in enumerate(claims)
                    ],
                    "correction_metadata": {
                        "correction_applied": correction_applied,
                        "iterations": correction_iters,
                    },
                    "execution_metadata": {
                        "execution_time_ms": elapsed_ms,
                        "pipeline_signals_used": signals_used,
                        "cached_scs_hit": cached_scs_hit,
                    },
                    "pii_metadata": {
                        "pii_flagged": pii_flagged,
                        "detected_types": detected_types,
                        "total_count": total_pii_count,
                    },
                    "created_at": datetime.now(UTC),
                }
                try:
                    await self.mongo_service.persist_verification_trace(
                        tenant_id=request.tenant_id,
                        trace_data=trace_doc,
                    )
                except MongoDuplicateTraceError:
                    logger.info(
                        "Trace document already exists in MongoDB for session; preserving existing trace",
                        session_id=req_id,
                        tenant_id=request.tenant_id,
                    )

            # Step 2: Persist authoritative relational transaction to PostgreSQL
            if self.persistence_service is not None:
                try:
                    await self.persistence_service.persist_verification_transaction(
                        session_id=req_id,
                        tenant_id=request.tenant_id,
                        trace_id=trace_id,
                        model_id=request.model_id,
                        prompt=request.prompt,
                        response=request.response,
                        hrs_score=hrs_result.hrs,
                        risk_tier=hrs_result.tier.value,
                        verified_claims=verified_claims,
                        correction_applied=correction_applied,
                    )
                except DuplicateSessionError:
                    # Idempotent duplicate delivery: PostgreSQL already committed this session.
                    # Do NOT delete from MongoDB; return cleanly without appending a duplicate audit log.
                    logger.info(
                        "Idempotent duplicate session detected in PostgreSQL; preserving existing record",
                        session_id=req_id,
                        tenant_id=request.tenant_id,
                    )
                except DefinitivePostgresPersistenceError as def_exc:
                    # Case A: Definitive PostgreSQL failure/rollback before COMMIT.
                    # We know with certainty that PostgreSQL has 0 records and no audit hash chain was updated.
                    # Therefore, compensating MongoDB delete is SAFE and REQUIRED.
                    logger.info(
                        "Definitive PostgreSQL failure before commit; executing compensating MongoDB delete",
                        session_id=req_id,
                        tenant_id=request.tenant_id,
                        error=str(def_exc),
                    )
                    if self.mongo_service is not None:
                        try:
                            await self.mongo_service.delete_trace(
                                tenant_id=request.tenant_id,
                                session_id=req_id,
                            )
                        except Exception as del_exc:
                            logger.critical(
                                "Compensating MongoDB delete failed! Orphaned trace document requires reconciliation",
                                session_id=req_id,
                                tenant_id=request.tenant_id,
                                error=str(del_exc),
                                orphan_state="mongodb_unreconciled",
                            )
                    raise
                except AmbiguousPostgresCommitError as amb_exc:
                    # Case B: Ambiguous PostgreSQL COMMIT outcome (network timeout / connection drop during commit).
                    # DO NOT blindly delete Mongo trace! PostgreSQL may have already committed the session and
                    # the immutable audit hash chain. Deleting Mongo trace would permanently orphan the audit record.
                    # Preserving the trace ensures trace data exists for subsequent reconciliation.
                    logger.critical(
                        "Ambiguous PostgreSQL commit outcome! PRESERVING MongoDB trace for reconciliation",
                        session_id=req_id,
                        tenant_id=request.tenant_id,
                        trace_id=trace_id,
                        error=str(amb_exc),
                        orphan_state="postgres_commit_ambiguous",
                        reconciliation_required=True,
                    )
                    raise
                except DatabasePersistenceError as db_exc:
                    # Generic / unknown database persistence error: default to safe preservation
                    logger.critical(
                        "Unclassified PostgreSQL persistence error! Preserving MongoDB trace for safety",
                        session_id=req_id,
                        tenant_id=request.tenant_id,
                        trace_id=trace_id,
                        error=str(db_exc),
                        orphan_state="unclassified_persistence_error",
                    )
                    raise

            # Step 3: Record in-memory session cache (only reached upon mutual persistence success)
            default_session_store.record_session(
                session_id=req_id,
                tenant_id=request.tenant_id,
                trace_id=trace_id,
                model_id=request.model_id,
                prompt=request.prompt,
                response=request.response,
                hrs_score=hrs_result.hrs,
                risk_tier=hrs_result.tier.value,
                ci_lower=hrs_result.conformal_interval.lower,
                ci_upper=hrs_result.conformal_interval.upper,
                correction_applied=correction_applied,
                claims_count=len(verified_claims),
                contradicted_count=sum(1 for c in verified_claims if c.status == VerificationStatus.CONTRADICTED),
                claims=claims_dicts,
                signal_attribution=attribution_dict,
            )

            metadata = VerificationMetadata(
                trace_id=trace_id,
                execution_time_ms=elapsed_ms,
                pipeline_signals_used=signals_used,
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
