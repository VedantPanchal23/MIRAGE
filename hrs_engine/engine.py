"""HRS Engine: Core orchestrator for multi-signal aggregation, calibration, uncertainty, and explainability."""

import time
from typing import Any

from hrs_engine.calibrator import Calibrator
from hrs_engine.conformal import MondrianConformalPredictor
from hrs_engine.feature_extractor import FeatureExtractor
from hrs_engine.meta_learner import HRSMetaLearner
from hrs_engine.shap_explainer import TreeSHAPExplainer
from shared.logging import get_logger
from shared.schemas import (
    Claim,
    ClaimVerificationResult,
    EvidenceChunk,
    HRSResult,
    SignalAttribution,
    VerificationStatus,
    determine_risk_tier,
)

logger = get_logger("hrs_engine")


class HRSEngine:
    """Unified engine for Hallucination Risk Score calculation and uncertainty quantification."""

    def __init__(
        self,
        meta_learner: HRSMetaLearner | None = None,
        calibrator: Calibrator | None = None,
        conformal_predictor: MondrianConformalPredictor | None = None,
        shap_explainer: TreeSHAPExplainer | None = None,
    ) -> None:
        self.meta_learner = meta_learner or HRSMetaLearner()
        self.calibrator = calibrator or Calibrator(method="isotonic")
        self.conformal_predictor = conformal_predictor or MondrianConformalPredictor(alpha=0.05)
        self.shap_explainer = shap_explainer or TreeSHAPExplainer(model=self.meta_learner.model)

    def process_claims(
        self,
        claims: list[Claim],
        rav_scores: list[float],
        evidence_chunks_per_claim: list[list[EvidenceChunk]],
        scs_score: float,
        ics_scores: dict[str, float],
        nli_scores: list[float] | None = None,
        scs_enabled: bool = True,
        vgs_scores: list[float] | None = None,
        has_image: bool = False,
    ) -> tuple[HRSResult, list[ClaimVerificationResult]]:
        """Process claims through feature extraction, meta-learner, calibrator, conformal prediction, and SHAP.

        Returns:
            Tuple of (response_level_HRSResult, list_of_ClaimVerificationResult).
        """
        start_time = time.time()
        n_claims = len(claims)

        if n_claims == 0:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            empty_interval = self.conformal_predictor.predict_interval(0.0)
            return (
                HRSResult(
                    hrs=0.0,
                    raw_score=0.0,
                    tier=determine_risk_tier(0.0),
                    conformal_interval=empty_interval,
                    signal_attribution=SignalAttribution(),
                    claims_count=0,
                    contradicted_claims_count=0,
                    computation_latency_ms=elapsed_ms,
                ),
                [],
            )

        # 1. Feature extraction per claim
        feature_vectors: list[list[float]] = []
        effective_scs = scs_score if scs_enabled else 0.0

        for idx, claim in enumerate(claims):
            chunks = evidence_chunks_per_claim[idx] if idx < len(evidence_chunks_per_claim) else []
            s_rav = rav_scores[idx] if idx < len(rav_scores) else 0.5
            s_ics = ics_scores.get(claim.claim_id, 0.0)
            s_vgs = vgs_scores[idx] if vgs_scores and idx < len(vgs_scores) else None
            s_nli = nli_scores[idx] if nli_scores and idx < len(nli_scores) else None

            max_support = 0.0
            if chunks:
                max_support = max((c.similarity_score for c in chunks), default=0.0)

            if s_nli is not None:
                max_contra = s_nli
            elif chunks:
                max_contra = max(0.0, s_rav - 0.20) if s_rav > 0.40 else 0.05
            else:
                max_contra = 0.10

            feat = FeatureExtractor.extract_claim_features(
                claim=claim,
                rav_score=s_rav,
                scs_score=effective_scs,
                p_contra=max_contra,
                p_support=max_support,
                ics_score=s_ics,
                evidence_chunks=chunks,
                total_claims_count=n_claims,
                vgs_score=s_vgs,
                has_image=has_image,
            )
            feature_vectors.append(feat)

        # 2. Raw score inference via meta-learner
        raw_scores = self.meta_learner.predict_proba(feature_vectors)

        # 3. Dynamic weight re-normalization if SCS is disabled
        if not scs_enabled:
            # Re-normalize: divide out SCS weight
            w_rav, w_nli, w_ics = 0.35, 0.30, 0.15
            denom = w_rav + w_nli + w_ics  # 0.80
            scale = 1.0 / denom
            raw_scores = [min(1.0, s * scale) for s in raw_scores]

        # 4. Calibration via Isotonic Regression
        calibrated_scores = self.calibrator.calibrate(raw_scores)

        # 5. Explainability & Claim Verification Result Synthesis
        claim_results: list[ClaimVerificationResult] = []
        weighted_risk_sum = 0.0
        max_claim_risk = 0.0
        all_attributions: list[SignalAttribution] = []

        for idx, claim in enumerate(claims):
            c_raw = raw_scores[idx]
            c_calibrated = calibrated_scores[idx]
            chunks = evidence_chunks_per_claim[idx] if idx < len(evidence_chunks_per_claim) else []
            s_rav = rav_scores[idx] if idx < len(rav_scores) else 0.5
            s_ics = ics_scores.get(claim.claim_id, 0.0)

            # TreeSHAP attribution
            attribution_obj = self.shap_explainer.explain_claim(
                feature_vectors[idx],
                has_vgs=has_image,
            )
            all_attributions.append(attribution_obj)

            # Determine verification status
            s_nli = nli_scores[idx] if nli_scores and idx < len(nli_scores) else c_raw
            if s_nli > 0.65 or s_ics > 0.70 or c_calibrated > 0.60:
                status = VerificationStatus.CONTRADICTED
                explanation = "Contradiction detected by NLI logic or intra-response consistency check."
            elif c_calibrated < 0.25 and s_rav < 0.20:
                status = VerificationStatus.SUPPORTED
                explanation = "Claim is strongly supported by retrieved knowledge base evidence."
            elif not chunks:
                status = VerificationStatus.INSUFFICIENT_EVIDENCE
                explanation = "No authoritative evidence chunks found in configured knowledge base."
            else:
                status = VerificationStatus.NEUTRAL
                explanation = "Claim has neutral evidence alignment."

            attribution_dict: dict[str, Any] = {
                "rav": attribution_obj.rav,
                "scs": attribution_obj.scs if scs_enabled else 0.0,
                "nli": attribution_obj.nli,
                "ics": attribution_obj.ics,
            }
            if attribution_obj.vgs is not None:
                attribution_dict["vgs"] = attribution_obj.vgs

            claim_results.append(
                ClaimVerificationResult(
                    claim=claim,
                    status=status,
                    risk_score=c_calibrated,
                    rav_score=s_rav,
                    scs_score=effective_scs,
                    nli_score=s_nli,
                    ics_score=s_ics,
                    vgs_score=vgs_scores[idx] if vgs_scores and idx < len(vgs_scores) else None,
                    signal_attribution=attribution_dict,
                    evidence_chunks=chunks,
                    explanation=explanation,
                )
            )

            weighted_risk_sum += c_calibrated * claim.criticality_weight
            if c_calibrated > max_claim_risk:
                max_claim_risk = c_calibrated

        # 6. Response-Level Aggregation with Critical Hallucination Lower Bound
        # Formula (Section 2.8): HRS_resp = sum(w_crit * HRS(c_i)) / sum(w_crit)
        # If max_i HRS(c_i) > 0.80, HRS_resp is bounded from below by 0.80 * max_i HRS(c_i)
        weight_sum = sum(c.criticality_weight for c in claims) or 1.0
        aggregated_hrs = weighted_risk_sum / weight_sum

        if max_claim_risk > 0.80:
            critical_lower_bound = 0.80 * max_claim_risk
            if aggregated_hrs < critical_lower_bound:
                aggregated_hrs = critical_lower_bound

        final_hrs = round(min(1.0, max(0.0, aggregated_hrs)), 4)
        response_tier = determine_risk_tier(final_hrs)

        # 7. Mondrian Conformal Prediction Interval for Response
        conformal_int = self.conformal_predictor.predict_interval(
            score=final_hrs,
            risk_tier=response_tier,
        )

        # Aggregate signal attributions for response level
        avg_rav = round(sum(a.rav for a in all_attributions) / n_claims, 3)
        avg_scs = round(sum(a.scs for a in all_attributions) / n_claims, 3) if scs_enabled else 0.0
        avg_nli = round(sum(a.nli for a in all_attributions) / n_claims, 3)
        avg_ics = round(sum(a.ics for a in all_attributions) / n_claims, 3)
        avg_vgs = round(sum(a.vgs for a in all_attributions if a.vgs is not None) / n_claims, 3) if has_image else None

        response_attribution = SignalAttribution(
            rav=avg_rav,
            scs=avg_scs,
            nli=avg_nli,
            ics=avg_ics,
            vgs=avg_vgs,
        )

        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        contradicted_count = sum(1 for c in claim_results if c.status == VerificationStatus.CONTRADICTED)

        hrs_result = HRSResult(
            hrs=final_hrs,
            raw_score=final_hrs,
            tier=response_tier,
            conformal_interval=conformal_int,
            signal_attribution=response_attribution,
            claims_count=n_claims,
            contradicted_claims_count=contradicted_count,
            computation_latency_ms=elapsed_ms,
        )

        return hrs_result, claim_results
