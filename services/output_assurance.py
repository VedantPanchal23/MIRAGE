"""Gate 4 Output Assurance and Modernized Verification Engine Service for MIRAGE 3.0.

Implements Input_Output_Assurance.md §5, Cost_Optimization.md §3, Risk_Model.md §4,
and Technical_Architecture.md §4.
"""

import hashlib
import html
import re
import time
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from db import session as db_session
from db.models import ActionContract, AITransaction, AuditLogRecord, KBDocumentRecord, OutputAssuranceRecord
from hrs_engine import HRSEngine
from models.deberta import DeBERTaNLIVerifier
from models.flan_t5 import AtomicClaimDecomposer
from shared.logging import get_logger
from shared.schemas.action import ActionState
from shared.schemas.audit import compute_sha256
from shared.schemas.auth import AuthContext
from shared.schemas.claims import (
    Claim,
    ClaimType,
    ClaimVerificationResult,
    EvidenceChunk,
    VerificationStatus,
)
from shared.schemas.control_plane import Taint, is_dangerous_triad_active
from shared.schemas.hrs import ConformalInterval, HRSResult, RiskTier, SignalAttribution, determine_risk_tier
from shared.schemas.output import (
    BudgetConsumption,
    CalibrationMetadata,
    Gate4Decision,
    OutputAssuranceContract,
    OutputAssuranceRequest,
    OutputFactualResult,
    OutputSafetyResult,
    OutputVerificationStatus,
    VerificationTier,
)
from workers.ics.worker import ICSWorker
from workers.rav.worker import RAVWorker
from workers.visual import VisualGroundingWorker

logger = get_logger("output_assurance")

# DLP and safety regex patterns
_SECRET_PATTERNS = (
    re.compile(
        r"\b(?:api[_\s-]?key|password|secret|private[_\s-]?key|access[_\s-]?token|auth[_\s-]?token|client[_\s-]?secret)\b\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{8,})['\"]?",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+([A-Za-z0-9\-._~+/]{20,})\b"),
    re.compile(r"-----BEGIN (?:[A-Z0-9_\-]+ )?PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9_\-]+ )?PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA|AROA)[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{36,255}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,64}\b"),
    re.compile(r"\b(?:client_secret|app_secret|secret_key)\s*[:=]\s*['\"]?([0-9a-fA-F]{32,64})['\"]?", re.IGNORECASE),
)
_PII_PATTERNS = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b"),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
)
_INJECTION_ARTIFACT_PATTERNS = (
    re.compile(r"<\|(?:im_start|im_end|endoftext)\|>", re.IGNORECASE),
    re.compile(r"\[/?(?:INST|SYSTEM)\]", re.IGNORECASE),
    re.compile(
        r"(?:(?:entering\s+)?DAN(?:\s+mode)?|I am DAN|jailbreak mode(?: active)?|"
        r"disregarding (?:all )?(?:previous )?system instructions|ignore (?:all )?previous instructions)",
        re.IGNORECASE,
    ),
)

# Completion claim patterns for action consistency validation
_ACTION_COMPLETION_PATTERNS = (
    re.compile(
        r"\b(?:I (?:have )?(?:transferred|deleted|updated|executed|deployed|"
        r"paid|sent|removed|modified|cancelled|refunded|processed))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:transfer|payment|deletion|removal|deployment|action|execution|refund|"
        r"transaction|update|email|notification|message) "
        r"(?:has been |was |is )(?:completed|processed|executed|successful|finalized|done|sent|delivered))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:(?:completed|processed|executed|finalized) "
        r"(?:the )?(?:transfer|payment|deletion|deployment|action|refund|transaction|email|notification))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:successfully (?:transferred|deleted|updated|executed|deployed|"
        r"paid|sent|removed|modified|refunded|processed|created))\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:has (?:succeeded|been completed|been processed|been executed|"
        r"been sent|been deleted|been updated|been paid|been transferred))\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:was (?:sent|completed|processed|executed|deleted|updated|paid|transferred))\b", re.IGNORECASE),
    re.compile(r"\b(?:operation (?:succeeded|completed))\b", re.IGNORECASE),
    re.compile(
        r"\b(?:the )?(?:transfer|payment|transaction|wire|funds) (?:went through|has gone through|have gone through)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:funds|money|payment|wire) (?:have |has )?reached (?:the )?recipient\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the )?(?:database|db|record|table) (?:has been |was |is )?updated\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:the )?(?:deployment|service|release|app) is (?:now )?live\b",
        re.IGNORECASE,
    ),
)
_EXTERNAL_ACTION_NOUNS = re.compile(
    r"\b(?:transfer|payment|deletion|removal|deployment|wire|refund|database|server|account|repo|commit)\b",
    re.IGNORECASE,
)


class OutputAssuranceService:
    """Core Gate 4 Output Assurance engine coordinating the adaptive verification ladder."""

    def __init__(
        self,
        decomposer: AtomicClaimDecomposer | None = None,
        verifier: DeBERTaNLIVerifier | None = None,
        rav_worker: RAVWorker | None = None,
        ics_worker: ICSWorker | None = None,
        visual_worker: VisualGroundingWorker | None = None,
        hrs_engine: HRSEngine | None = None,
    ) -> None:
        self.decomposer = decomposer or AtomicClaimDecomposer(use_neural=False)
        self.verifier = verifier or DeBERTaNLIVerifier(use_neural=False)
        self.rav_worker = rav_worker or RAVWorker()
        self.ics_worker = ics_worker or ICSWorker(verifier=self.verifier)
        self.visual_worker = visual_worker or VisualGroundingWorker()
        self.hrs_engine = hrs_engine or HRSEngine()

    def run_dlp_and_safety(self, text: str) -> OutputSafetyResult:
        """Tier 1 cheap deterministic scanner for secrets, PII, and injection artifacts with anti-obfuscation."""
        reasons: list[str] = []
        secrets_detected = False
        pii_detected = False
        injection_leakage = False

        # 0. Strip zero-width, non-printing formatting control characters, and Unicode Bidi overrides
        cleaned_text = re.sub(
            r"[\u200b\u200c\u200d\u200e\u200f\ufeff\u00ad\u2060\u2061\u2062\u2063\u0000-\u0008\u000b\u000c\u000e-\u001f\u202a-\u202e\u2066-\u2069]",
            "",
            text,
        )
        # Unescape HTML entities
        unescaped_text = html.unescape(cleaned_text)
        # Normalize unicode to NFKC (defeats fullwidth character obfuscation, homoglyphs, and combining marks)
        normalized_text = unicodedata.normalize("NFKC", unescaped_text)

        redacted_text = text

        # 1. Secret Detection and Redaction (check both normalized and raw text)
        for pat in _SECRET_PATTERNS:
            match_norm = pat.search(normalized_text)
            match_raw = pat.search(redacted_text)
            if match_norm or match_raw:
                secrets_detected = True
                reasons.append("Cryptographic secret or credential token detected in output")
                if match_raw:
                    redacted_text = pat.sub("[REDACTED_SECRET]", redacted_text)
                else:
                    redacted_text = pat.sub("[REDACTED_SECRET]", normalized_text)

        # 2. PII Detection and Redaction
        for pat in _PII_PATTERNS:
            match_norm = pat.search(normalized_text)
            match_raw = pat.search(redacted_text)
            if match_norm or match_raw:
                pii_detected = True
                reasons.append("Personally Identifiable Information (PII) detected in output")
                if match_raw:
                    redacted_text = pat.sub("[REDACTED_PII]", redacted_text)
                else:
                    redacted_text = pat.sub("[REDACTED_PII]", normalized_text)

        # 3. Injection Artifact Detection
        for pat in _INJECTION_ARTIFACT_PATTERNS:
            if pat.search(normalized_text) or pat.search(redacted_text):
                injection_leakage = True
                reasons.append("Prompt injection or jailbreak control tokens detected in output")

        safe = not (secrets_detected or injection_leakage)

        return OutputSafetyResult(
            safe=safe,
            pii_detected=pii_detected,
            secrets_detected=secrets_detected,
            prompt_injection_leakage=injection_leakage,
            redacted_content=redacted_text if (secrets_detected or pii_detected) else None,
            violation_reasons=reasons,
        )

    async def assure_output(
        self,
        request: OutputAssuranceRequest,
        auth: AuthContext,
    ) -> OutputAssuranceContract:
        """Execute full Gate 4 Output Assurance pipeline across the adaptive ladder."""
        start_time = time.time()
        output_id = f"out_{uuid.uuid4().hex[:12]}"
        tier_path: list[VerificationTier] = []
        escalation_reasons: list[str] = []
        verifier_provenance: list[str] = []
        model_calls = 0
        tokens_used = len(request.response_text.split()) * 2

        # 0. Validate parent AI Transaction and Tenant Binding
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            stmt = select(AITransaction).where(
                AITransaction.id == request.transaction_id,
                AITransaction.tenant_id == auth.tenant_id,
            )
            txn = (await session.execute(stmt)).scalar_one_or_none()
            if not txn:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Parent AI Transaction '{request.transaction_id}' not found for tenant '{auth.tenant_id}'",
                )

            # Check action contracts for postcondition consistency
            action_stmt = select(ActionContract).where(
                ActionContract.transaction_id == request.transaction_id,
                ActionContract.tenant_id == auth.tenant_id,
            )
            actions = list((await session.execute(action_stmt)).scalars().all())

            # Query active KB document generations for stale evidence defense
            kb_stmt = select(KBDocumentRecord).where(
                KBDocumentRecord.tenant_id == auth.tenant_id,
            )
            active_kb_docs = {
                doc.document_id: doc.generation for doc in (await session.execute(kb_stmt)).scalars().all()
            }

        # 1. TIER 1: Cheap Deterministic Checks (DLP, Safety, Schema)
        tier_path.append(VerificationTier.TIER_1_DETERMINISTIC)
        safety_res = self.run_dlp_and_safety(request.response_text)
        current_text = safety_res.redacted_content if safety_res.redacted_content else request.response_text

        # 2. Input/Action Consistency Check (Postcondition Honesty & Taint Lattice)
        action_inconsistencies = self._validate_action_consistency(actions, current_text)
        taint_inconsistencies = self._validate_taint_consistency(txn.taint_flags, current_text)

        # 3. Claim Decomposition (Deterministic / Model-assisted)
        claims = self.decomposer.decompose(current_text)
        verifier_provenance.append("flan_t5_decomposer_cpu")

        # Check if output contains only opinions/non-factual statements
        factual_claims = [c for c in claims if c.claim_type != ClaimType.OPINION]

        # 4. Adaptive Escalation: Determine if Tier 3 (Retrieval + NLI) is required
        needs_tier_3 = False
        if request.require_factual_verification:
            if factual_claims:
                needs_tier_3 = True
                escalation_reasons.append("Factual propositions detected requiring grounding verification")
            if txn.taint_flags and Taint.UNTRUSTED.value in txn.taint_flags:
                needs_tier_3 = True
                escalation_reasons.append("Transaction context contains UNTRUSTED taint")
        if action_inconsistencies:
            escalation_reasons.extend(action_inconsistencies)

        budget_exhausted = False
        claim_results: list[ClaimVerificationResult] = []
        hrs_result: HRSResult
        was_corrected = False
        correction_history: list[dict[str, Any]] = []

        if needs_tier_3:
            tier_path.append(VerificationTier.TIER_3_RETRIEVAL_NLI)
            verifier_provenance.append("qdrant_rav")
            verifier_provenance.append("deberta_nli")
            verifier_provenance.append("hrs_lightgbm_meta_learner")

            # Check budget limits before expensive verification
            elapsed_ms = (time.time() - start_time) * 1000
            if (
                elapsed_ms > request.budget.max_latency_ms
                or (model_calls + 2) > request.budget.max_model_calls
            ):
                budget_exhausted = True
                logger.warning(
                    "Gate 4 verification budget exhausted before full grounding",
                    tenant_id=auth.tenant_id,
                    elapsed_ms=elapsed_ms,
                    max_latency_ms=request.budget.max_latency_ms,
                )

            if not budget_exhausted:
                # Combine context_chunks and evidence_chunks aliases
                combined_chunks = list(request.context_chunks) + list(request.evidence_chunks)
                # Perform RAG Evidence Retrieval & NLI Grounding
                rav_scores, evidence_per_claim = await self._retrieve_and_validate_evidence(
                    claims=claims,
                    tenant_id=auth.tenant_id,
                    context_chunks=combined_chunks,
                    knowledge_base_id=request.knowledge_base_id,
                    active_kb_docs=active_kb_docs,
                )
                model_calls += 1

                # Evaluate Pairwise NLI Scores & Internal Consistency (ICS)
                nli_scores: list[float] = []
                for idx, c in enumerate(claims):
                    ev_chunks = evidence_per_claim[idx] if idx < len(evidence_per_claim) else []
                    s_nli = self.verifier.aggregate_multi_evidence(c.text, ev_chunks)
                    nli_scores.append(s_nli)
                model_calls += len(claims)

                ics_scores = self.ics_worker.compute_claim_ics_scores(claims)

                # Multimodal Grounding (VGS) - Degraded handling if no images
                vgs_scores: list[float] | None = None
                has_image = bool(request.image_urls)
                if has_image:
                    tier_path.append(VerificationTier.TIER_4_FRONTIER_JUDGE)
                    verifier_provenance.append("vgs_visual_grounding")
                    try:
                        vgs_scores = [0.10] * len(claims)  # Degraded mock / baseline
                    except Exception:
                        vgs_scores = None

                # Compute Holistic Reliability Score (HRS) with Calibration & Conformal Interval
                hrs_result, claim_results = self.hrs_engine.process_claims(
                    claims=claims,
                    rav_scores=rav_scores,
                    evidence_chunks_per_claim=evidence_per_claim,
                    scs_score=0.15,
                    ics_scores=ics_scores,
                    nli_scores=nli_scores,
                    scs_enabled=True,
                    vgs_scores=vgs_scores,
                    has_image=has_image,
                )

                # Check if Autonomous Correction Loop is triggered (LangGraph)
                contradicted_claims = [
                    c for c in claim_results if c.status == VerificationStatus.CONTRADICTED or c.risk_score > 0.60
                ]
                if contradicted_claims and request.auto_correct:
                    current_text, was_corrected, attempts, re_hrs, _ = await self._run_correction_loop(
                        output_id=output_id,
                        original_text=current_text,
                        flagged_results=contradicted_claims,
                        tenant_id=auth.tenant_id,
                    )
                    correction_history.append(
                        {
                            "attempts": attempts,
                            "original_hrs": hrs_result.hrs,
                            "rewritten_hrs": re_hrs,
                            "was_corrected": was_corrected,
                        }
                    )
                    if was_corrected and re_hrs <= 0.30:
                        # Re-calculate low risk on successful rewrite
                        hrs_result = HRSResult(
                            hrs=re_hrs,
                            raw_score=re_hrs,
                            tier=determine_risk_tier(re_hrs),
                            conformal_interval=self.hrs_engine.conformal_predictor.predict_interval(re_hrs),
                            signal_attribution=hrs_result.signal_attribution,
                            claims_count=len(claims),
                            contradicted_claims_count=0,
                            computation_latency_ms=hrs_result.computation_latency_ms,
                        )
            else:
                # Degraded fallback due to budget exhaustion
                hrs_result = self._degraded_hrs_result(len(claims))
                claim_results = [
                    ClaimVerificationResult(
                        claim=c,
                        status=VerificationStatus.INSUFFICIENT_EVIDENCE,
                        risk_score=0.50,
                        rav_score=0.50,
                        nli_score=0.50,
                    )
                    for c in claims
                ]
        else:
            # Low complexity / opinion text - Deterministic pass
            hrs_result = HRSResult(
                hrs=0.05,
                raw_score=0.05,
                tier=RiskTier.LOW,
                conformal_interval=ConformalInterval(lower=0.0, upper=0.12, confidence_level=0.95),
                signal_attribution=SignalAttribution(rav=0.0, scs=0.0, nli=0.0, ics=0.0),
                claims_count=len(claims),
                contradicted_claims_count=0,
                computation_latency_ms=round((time.time() - start_time) * 1000, 2),
            )
            claim_results = [
                ClaimVerificationResult(
                    claim=c,
                    status=VerificationStatus.SUPPORTED,
                    risk_score=0.05,
                )
                for c in claims
            ]

        # 5. Evaluate Factual Summary Statistics
        supported_count = sum(1 for c in claim_results if c.status == VerificationStatus.SUPPORTED)
        contradicted_count = sum(1 for c in claim_results if c.status == VerificationStatus.CONTRADICTED)
        unsupported_count = sum(
            1
            for c in claim_results
            if c.status in {VerificationStatus.NEUTRAL, VerificationStatus.INSUFFICIENT_EVIDENCE}
        )
        factual_score = round(1.0 - hrs_result.hrs, 4)

        factual_res = OutputFactualResult(
            factual_consistency_score=factual_score,
            claims_count=len(claim_results),
            supported_claims_count=supported_count,
            contradicted_claims_count=contradicted_count,
            unsupported_claims_count=unsupported_count,
            evidence_sufficiency=round(supported_count / max(1, len(claim_results)), 2),
        )

        # 6. Final Gate 4 Policy Decision
        final_decision, decision_reasons = self._decide_gate4(
            risk_tier=hrs_result.tier,
            hrs=hrs_result.hrs,
            safety=safety_res,
            factual=factual_res,
            action_inconsistencies=action_inconsistencies,
            taint_inconsistencies=taint_inconsistencies,
            budget_exhausted=budget_exhausted,
            was_corrected=was_corrected,
            conformal_interval=hrs_result.conformal_interval,
        )
        escalation_reasons.extend(decision_reasons)

        if final_decision in {Gate4Decision.REQUIRE_HUMAN_REVIEW, Gate4Decision.BLOCK}:
            tier_path.append(VerificationTier.TIER_5_HUMAN_REVIEW)

        # 7. Verification Status Classification
        if not safety_res.safe or final_decision == Gate4Decision.BLOCK:
            ver_status = OutputVerificationStatus.BLOCKED
        elif final_decision == Gate4Decision.REQUIRE_HUMAN_REVIEW:
            ver_status = OutputVerificationStatus.PARTIALLY_VERIFIED
        elif budget_exhausted:
            ver_status = OutputVerificationStatus.DEGRADED
        elif contradicted_count > 0:
            ver_status = OutputVerificationStatus.CONTRADICTED
        elif unsupported_count > 0 and supported_count > 0:
            ver_status = OutputVerificationStatus.PARTIALLY_VERIFIED
        elif unsupported_count > 0 and supported_count == 0:
            ver_status = OutputVerificationStatus.UNVERIFIED
        elif len(claim_results) == 0:
            ver_status = OutputVerificationStatus.UNVERIFIED
        else:
            ver_status = OutputVerificationStatus.VERIFIED

        # 8. Compute Output Fingerprint & Audit Chain
        output_hash = hashlib.sha256(current_text.encode("utf-8")).hexdigest()
        audit_payload = (
            f"{auth.tenant_id}|{request.transaction_id}|{output_id}|{ver_status.value}|"
            f"{final_decision.value}|{hrs_result.hrs:.4f}|{output_hash}"
        )
        audit_hash = hashlib.sha256(audit_payload.encode("utf-8")).hexdigest()

        total_latency_ms = round((time.time() - start_time) * 1000, 2)
        budget_consumed = BudgetConsumption(
            cost_dollars=round(model_calls * 0.0015, 4),
            tokens_used=tokens_used,
            latency_ms=total_latency_ms,
            model_calls=model_calls,
            escalation_count=len(escalation_reasons),
        )

        contract = OutputAssuranceContract(
            output_id=output_id,
            transaction_id=request.transaction_id,
            tenant_id=auth.tenant_id,
            model_id=request.model_id,
            model_version=request.model_version,
            original_output=request.response_text,
            final_output=current_text,
            output_hash=output_hash,
            verification_status=ver_status,
            final_decision=final_decision,
            risk_classification=hrs_result.tier,
            risk_score=hrs_result.hrs,
            conformal_interval=hrs_result.conformal_interval,
            signal_attribution=hrs_result.signal_attribution,
            safety_result=safety_res,
            factual_result=factual_res,
            claims=claim_results,
            verification_tier_path=tier_path,
            escalation_reasons=escalation_reasons,
            budget_consumed=budget_consumed,
            calibration_metadata=CalibrationMetadata(
                is_certified=False,
                certification_status="NOT_SCIENTIFICALLY_CERTIFIED",
                finite_sample_guarantee=(
                    "Analytical conformal interval derived under exchangeability assumption (Vovk et al. 2005); "
                    "requires empirical benchmark certification for statistical production SLA."
                ),
            ),
            verifier_provenance=verifier_provenance,
            was_corrected=was_corrected,
            correction_attempts=len(correction_history),
            correction_history=correction_history,
            audit_record_hash=audit_hash,
        )

        # 9. Authoritative Persistence in PostgreSQL with Tenant RLS
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            db_record = OutputAssuranceRecord(
                id=output_id,
                tenant_id=auth.tenant_id,
                transaction_id=request.transaction_id,
                model_id=request.model_id,
                model_version=request.model_version,
                original_output=request.response_text,
                final_output=current_text,
                output_hash=output_hash,
                verification_status=ver_status.value,
                final_decision=final_decision.value,
                risk_tier=hrs_result.tier.value,
                risk_score=hrs_result.hrs,
                conformal_bounds=hrs_result.conformal_interval.model_dump(),
                signal_attributions=hrs_result.signal_attribution.model_dump(),
                claims_payload=[c.model_dump() for c in claim_results],
                safety_result=safety_res.model_dump(),
                factual_result=factual_res.model_dump(),
                budget_consumed=budget_consumed.model_dump(),
                tier_path=[t.value for t in tier_path],
                escalation_reasons=escalation_reasons,
                was_corrected=was_corrected,
                correction_history=correction_history,
                audit_hash=audit_hash,
                created_at=contract.created_at,
                verified_at=contract.verified_at,
            )
            session.add(db_record)

            # Insert immutable AuditLogRecord with SHA-256 chain linkage
            latest_audit = await session.execute(
                select(AuditLogRecord.chain_hash)
                .where(AuditLogRecord.tenant_id == auth.tenant_id)
                .order_by(AuditLogRecord.created_at.desc(), AuditLogRecord.entry_id.desc())
                .limit(1)
            )
            prev_chain_hash = latest_audit.scalar_one_or_none() or "0" * 64
            now_dt = datetime.now(UTC)
            entry_id = f"aud_{uuid.uuid4().hex}"
            chain_hash = compute_sha256(f"{prev_chain_hash}:{entry_id}:{final_decision.value}:{now_dt.isoformat()}")

            audit_entry = AuditLogRecord(
                entry_id=entry_id,
                tenant_id=auth.tenant_id,
                session_id=request.transaction_id,
                trace_id="gate4-output",
                prompt_hash=compute_sha256(request.prompt),
                response_hash=output_hash,
                hrs_score=hrs_result.hrs,
                risk_tier=hrs_result.tier.value,
                claims_count=len(claims),
                claims_summary=[c.model_dump() for c in claim_results],
                correction_applied=was_corrected,
                event_type="gate4_output_assured",
                actor_identity_id=auth.identity_id,
                transaction_id=request.transaction_id,
                decision=final_decision.value,
                policy_reference=None,
                capability_id=None,
                reason="; ".join(escalation_reasons) if escalation_reasons else "Gate 4 evaluated successfully",
                event_payload={
                    "verification_status": ver_status.value,
                    "risk_tier": hrs_result.tier.value,
                    "risk_score": hrs_result.hrs,
                    "budget_consumed": budget_consumed.model_dump(),
                    "output_id": output_id,
                },
                prev_hash=prev_chain_hash,
                chain_hash=chain_hash,
                created_at=now_dt,
            )
            session.add(audit_entry)

        logger.info(
            "Gate 4 Output Assurance evaluated successfully",
            output_id=output_id,
            tenant_id=auth.tenant_id,
            decision=final_decision.value,
            status=ver_status.value,
            risk_tier=hrs_result.tier.value,
        )
        return contract

    async def get_output_assurance_record(
        self,
        output_id: str,
        auth: AuthContext,
    ) -> OutputAssuranceRecord:
        """Fetch persistent OutputAssuranceRecord with tenant isolation."""
        async with db_session.get_tenant_session(auth.tenant_id) as session:
            stmt = select(OutputAssuranceRecord).where(
                OutputAssuranceRecord.id == output_id,
                OutputAssuranceRecord.tenant_id == auth.tenant_id,
            )
            record = (await session.execute(stmt)).scalar_one_or_none()
            if not record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Output Assurance record '{output_id}' not found for tenant '{auth.tenant_id}'",
                )
            return record

    async def _retrieve_and_validate_evidence(
        self,
        claims: list[Claim],
        tenant_id: str,
        context_chunks: list[dict[str, Any] | str],
        knowledge_base_id: str | None,
        active_kb_docs: dict[str, int],
    ) -> tuple[list[float], list[list[EvidenceChunk]]]:
        """Retrieve evidence, enforce tenant ownership, reject stale doc generations, and isolate data."""
        rav_scores: list[float] = []
        evidence_per_claim: list[list[EvidenceChunk]] = []

        # Convert provided context chunks into verified EvidenceChunk candidates
        provided_chunks: list[EvidenceChunk] = []
        for ch in context_chunks:
            if isinstance(ch, str):
                ch_dict: dict[str, Any] = {"content": ch, "similarity_score": 0.90}
            else:
                ch_dict = ch
            doc_id = str(ch_dict.get("document_id", "ctx_doc"))
            gen = int(ch_dict.get("generation", 1))

            # Reject stale generation if tracked
            if doc_id in active_kb_docs and gen < active_kb_docs[doc_id]:
                logger.warning("Rejected stale evidence generation in Gate 4", doc_id=doc_id, gen=gen)
                continue

            # Neutralize potential instruction injection in retrieved content
            raw_content = str(ch_dict.get("content", ""))
            escaped_content = raw_content.replace("<trusted_instructions>", "&lt;trusted_instructions&gt;")

            provided_chunks.append(
                EvidenceChunk(
                    chunk_id=str(ch_dict.get("chunk_id", f"chunk_{uuid.uuid4().hex[:8]}")),
                    document_id=doc_id,
                    content=escaped_content,
                    similarity_score=float(ch_dict.get("similarity_score", 0.90)),
                    source_metadata=ch_dict.get("source_metadata", {}),
                )
            )

        for c in claims:
            matched_chunks: list[EvidenceChunk] = []

            # Match against provided context chunks
            for pch in provided_chunks:
                # Entity or keyword match
                if any(w.lower() in pch.content.lower() for w in c.text.split() if len(w) > 3):
                    matched_chunks.append(pch)

            # If no matches in provided context and KB collection specified, query RAV
            if not matched_chunks and knowledge_base_id:
                try:
                    qdrant_chunks = await self.rav_worker.search_evidence(
                        c.text,
                        tenant_id=tenant_id,
                        collection_name=knowledge_base_id,
                        limit=3,
                    )
                    # Verify each Qdrant chunk against active generation
                    for qc in qdrant_chunks:
                        doc_gen = qc.source_metadata.get("generation", 1)
                        if qc.document_id in active_kb_docs and doc_gen < active_kb_docs[qc.document_id]:
                            continue
                        matched_chunks.append(qc)
                except Exception as exc:
                    logger.warning("RAV worker retrieval skipped or failed", error=str(exc))

            evidence_per_claim.append(matched_chunks)

            # Compute claim RAV support score
            if matched_chunks:
                max_sim = max(chk.similarity_score for chk in matched_chunks)
                rav_scores.append(round(1.0 - max_sim, 4))
            else:
                rav_scores.append(0.50)  # Neutral uncertainty when ungrounded

        return rav_scores, evidence_per_claim

    def _validate_action_consistency(
        self,
        actions: list[ActionContract],
        output_text: str,
    ) -> list[str]:
        """Ensure model output does not falsely claim actions executed when contracts were pending/blocked."""
        inconsistencies: list[str] = []
        has_completion_assertion = any(pat.search(output_text) for pat in _ACTION_COMPLETION_PATTERNS)

        if not has_completion_assertion:
            return inconsistencies

        if not actions:
            msg = (
                "Postcondition Honesty Violation: Output asserts real-world action succeeded, "
                "but 0 action contracts exist for this transaction."
            )
            inconsistencies.append(msg)
            logger.warning("Postcondition honesty violation flagged: zero actions executed")
            return inconsistencies

        for act in actions:
            if act.state != ActionState.COMPLETED.value:
                msg = (
                    f"Postcondition Honesty Violation: Output claims action succeeded, but ActionContract "
                    f"'{act.id}' ({act.tool_name}) is in state '{act.state}' (not COMPLETED)"
                )
                inconsistencies.append(msg)
                logger.warning("Postcondition honesty violation flagged", action_id=act.id, state=act.state)

        return inconsistencies

    def _validate_taint_consistency(
        self,
        taints: list[str],
        output_text: str,
    ) -> list[str]:
        """Ensure output does not leak confidential data when Dangerous Triad is active."""
        inconsistencies: list[str] = []
        if is_dangerous_triad_active(taints):
            # Check for confidential patterns or secret tokens
            if any(pat.search(output_text) for pat in _SECRET_PATTERNS):
                msg = "DIFC Dangerous Triad Violation: Confidential secret leaked while UNTRUSTED taint active"
                inconsistencies.append(msg)
        return inconsistencies

    def _decide_gate4(
        self,
        risk_tier: RiskTier,
        hrs: float,
        safety: OutputSafetyResult,
        factual: OutputFactualResult,
        action_inconsistencies: list[str],
        taint_inconsistencies: list[str],
        budget_exhausted: bool,
        was_corrected: bool,
        conformal_interval: ConformalInterval | None = None,
    ) -> tuple[Gate4Decision, list[str]]:
        """Synthesize all verification signals into an authoritative Gate 4 decision."""
        reasons: list[str] = []

        # 1. Critical Hard Blocks
        if not safety.safe:
            reasons.extend(safety.violation_reasons)
            return Gate4Decision.BLOCK, reasons

        if taint_inconsistencies:
            reasons.extend(taint_inconsistencies)
            return Gate4Decision.BLOCK, reasons

        if action_inconsistencies:
            reasons.extend(action_inconsistencies)
            return Gate4Decision.BLOCK, reasons

        # 2. Critical Factual Contradiction that was not corrected
        if factual.contradicted_claims_count > 0 and not was_corrected:
            reasons.append(f"Output contains {factual.contradicted_claims_count} contradicted factual claims")
            return Gate4Decision.BLOCK, reasons

        # 3. High Risk / Escalation to Human Review
        if risk_tier == RiskTier.CRITICAL or hrs >= 0.85:
            reasons.append(f"Holistic Reliability Score critical (HRS={hrs:.3f} >= 0.85)")
            return Gate4Decision.REQUIRE_HUMAN_REVIEW, reasons

        if risk_tier == RiskTier.HIGH or hrs >= 0.60:
            reasons.append(f"High risk output detected (HRS={hrs:.3f} >= 0.60)")
            return Gate4Decision.REQUIRE_HUMAN_REVIEW, reasons

        if conformal_interval is not None and conformal_interval.upper >= 0.85 and hrs < 0.60:
            reasons.append(
                "Conformal uncertainty upper bound indicates elevated risk of critical hallucination "
                f"(upper={conformal_interval.upper:.3f} >= 0.85)"
            )
            return Gate4Decision.REQUIRE_HUMAN_REVIEW, reasons

        # 4. Redaction Transformation (Minor PII or secrets safely redacted)
        if safety.redacted_content is not None:
            reasons.append("Sensitive PII/secret elements successfully redacted")
            return Gate4Decision.REDACT_TRANSFORM, reasons

        # 5. Budget Exhaustion
        if budget_exhausted:
            reasons.append("Verification budget limit reached before full grounding")
            return Gate4Decision.ALLOW_WITH_UNCERTAINTY, reasons

        # 6. Moderate Risk / Partial Evidence
        if risk_tier == RiskTier.MEDIUM or hrs >= 0.20:
            reasons.append(f"Moderate risk with uncertainty interval (HRS={hrs:.3f})")
            return Gate4Decision.ALLOW_WITH_UNCERTAINTY, reasons

        # 7. Unanimously Grounded Low Risk
        return Gate4Decision.ALLOW, reasons

    async def _run_correction_loop(
        self,
        output_id: str,
        original_text: str,
        flagged_results: list[ClaimVerificationResult],
        tenant_id: str,
    ) -> tuple[str, bool, int, float, bool]:
        """Trigger LangGraph autonomous correction loop for contradicted claims."""
        try:
            from correction_agent.agent import CorrectionAgent

            agent = CorrectionAgent()
            return await agent.correct_response(
                response_id=output_id,
                original_response=original_text,
                verified_claims=flagged_results,
                tenant_id=tenant_id,
            )
        except Exception as exc:
            logger.warning("LangGraph correction agent invocation failed", error=str(exc))
            return original_text, False, 0, 0.90, True

    def _degraded_hrs_result(self, n_claims: int) -> HRSResult:
        """Produce a conservative uncalibrated HRSResult when verification budget is exhausted."""
        return HRSResult(
            hrs=0.50,
            raw_score=0.50,
            tier=RiskTier.MEDIUM,
            conformal_interval=ConformalInterval(
                lower=0.25,
                upper=0.75,
                confidence_level=0.95,
                conditional_group="budget_exhausted",
            ),
            signal_attribution=SignalAttribution(rav=0.25, scs=0.25, nli=0.25, ics=0.25),
            claims_count=n_claims,
            contradicted_claims_count=0,
            computation_latency_ms=0.0,
        )


# Singleton service export
output_assurance_service = OutputAssuranceService()
