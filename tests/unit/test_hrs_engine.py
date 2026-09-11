"""Unit and statistical validation tests for Phase 5 HRS Engine and uncertainty quantification."""

import numpy as np
import pytest

from hrs_engine.calibrator import (
    Calibrator,
    compute_brier_score,
    compute_ece,
    compute_mce,
)
from hrs_engine.conformal import MondrianConformalPredictor
from hrs_engine.engine import HRSEngine
from hrs_engine.feature_extractor import FeatureExtractor
from hrs_engine.meta_learner import HRSMetaLearner
from hrs_engine.shap_explainer import TreeSHAPExplainer
from shared.schemas import (
    Claim,
    ClaimCriticality,
    ClaimType,
    EvidenceChunk,
    RiskTier,
    VerificationStatus,
)


@pytest.mark.unit
class TestFeatureExtractor:
    def test_extract_12_features(self) -> None:
        claim = Claim(
            claim_id="c_test_01",
            text="The speed of light in vacuum is approximately 300,000 km/s.",
            claim_type=ClaimType.NUMERICAL,
            criticality=ClaimCriticality.HIGH,
            criticality_weight=1.0,
        )
        chunk = EvidenceChunk(
            chunk_id="chk_1",
            document_id="doc_1",
            content="Light travels at roughly 299,792 km/s in vacuum.",
            similarity_score=0.92,
        )
        features = FeatureExtractor.extract_claim_features(
            claim=claim,
            rav_score=0.10,
            scs_score=0.05,
            p_contra=0.02,
            p_support=0.92,
            ics_score=0.00,
            evidence_chunks=[chunk],
            total_claims_count=1,
            vgs_score=None,
            has_image=False,
        )

        assert len(features) == 12
        assert features[0] == 0.10  # rss_score
        assert features[1] == 0.02  # p_contra
        assert features[2] == 0.92  # p_support
        assert features[3] == 0.05  # scs_score
        assert features[4] == 0.00  # vgs_score
        assert features[5] == 0.00  # ics_score
        assert features[6] == 2.00  # numerical type encoded
        assert features[7] == 1.00  # criticality weight
        assert features[9] == 0.92  # max similarity
        assert features[10] == 1.0  # total claim count
        assert features[11] == 0.0  # has_image

    def test_feature_names_and_dict(self) -> None:
        names = FeatureExtractor.get_feature_names()
        assert len(names) == 12
        vec = [0.1] * 12
        fdict = FeatureExtractor.to_dict(vec)
        assert len(fdict) == 12
        assert "rss_score" in fdict
        assert "has_image" in fdict


@pytest.mark.unit
class TestHRSMetaLearner:
    def test_fallback_prediction_range(self) -> None:
        learner = HRSMetaLearner()
        features = [
            [0.1, 0.05, 0.90, 0.02, 0.0, 0.0, 0.0, 1.0, 10.0, 0.90, 1.0, 0.0],
            [0.8, 0.90, 0.05, 0.70, 0.0, 0.6, 0.0, 1.0, 10.0, 0.20, 1.0, 0.0],
        ]
        probs = learner.predict_proba(features)
        assert len(probs) == 2
        assert 0.0 <= probs[0] < 0.25  # strongly supported
        assert 0.70 <= probs[1] <= 1.0  # heavily contradicted + high entropy

    def test_fit_and_predict_lightgbm(self) -> None:
        learner = HRSMetaLearner()
        # Create synthetic training set
        np.random.seed(42)
        X = np.random.rand(100, 12).tolist()
        y = [1 if (row[0] > 0.5 or row[1] > 0.5) else 0 for row in X]
        learner.fit(X, y)
        test_samples = np.random.rand(10, 12).tolist()
        preds = learner.predict_proba(test_samples)
        assert len(preds) == 10
        assert all(0.0 <= p <= 1.0 for p in preds)


@pytest.mark.unit
class TestCalibrator:
    def test_isotonic_calibration_monotonicity(self) -> None:
        calibrator = Calibrator(method="isotonic")
        raw = [0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95]
        labels = [0, 0, 0, 1, 1, 1, 1]
        calibrator.fit(raw, labels)
        calibrated = calibrator.calibrate([0.15, 0.4, 0.7, 0.9])
        assert len(calibrated) == 4
        # Monotonicity check
        assert calibrated[0] <= calibrated[1] <= calibrated[2] <= calibrated[3]

    def test_platt_scaling(self) -> None:
        calibrator = Calibrator(method="platt")
        raw = [0.1, 0.2, 0.4, 0.6, 0.8, 0.9]
        labels = [0, 0, 0, 1, 1, 1]
        calibrator.fit(raw, labels)
        calibrated = calibrator.calibrate([0.15, 0.85])
        assert calibrated[0] < calibrated[1]

    def test_temperature_scaling(self) -> None:
        calibrator = Calibrator(method="temperature")
        raw = [0.1, 0.3, 0.7, 0.9]
        labels = [0, 0, 1, 1]
        calibrator.fit(raw, labels)
        calibrated = calibrator.calibrate([0.2, 0.8])
        assert calibrated[0] < calibrated[1]

    def test_ece_and_mce_computation(self) -> None:
        y_true = [0, 0, 0, 1, 1, 1]
        y_prob = [0.1, 0.15, 0.2, 0.85, 0.9, 0.95]
        ece = compute_ece(y_true, y_prob, n_bins=5)
        mce = compute_mce(y_true, y_prob, n_bins=5)
        brier = compute_brier_score(y_true, y_prob)

        assert 0.0 <= ece < 0.15
        assert 0.0 <= mce < 0.25
        assert 0.0 <= brier < 0.05


@pytest.mark.unit
class TestMondrianConformalPredictor:
    def test_conformal_interval_guarantees(self) -> None:
        predictor = MondrianConformalPredictor(alpha=0.05)
        # Verify default intervals across risk tiers
        int_low = predictor.predict_interval(0.15, risk_tier=RiskTier.LOW)
        assert int_low.lower <= 0.15 <= int_low.upper
        assert int_low.confidence_level == 0.95
        assert int_low.conditional_group == "tier:LOW"
        assert (int_low.upper - int_low.lower) < 0.20

        int_crit = predictor.predict_interval(0.88, risk_tier=RiskTier.CRITICAL)
        assert int_crit.lower <= 0.88 <= int_crit.upper
        assert int_crit.upper <= 1.0
        assert int_crit.conditional_group == "tier:CRITICAL"

    def test_conformal_calibration_fit_and_coverage(self) -> None:
        predictor = MondrianConformalPredictor(alpha=0.05)
        # Synthetic calibration set
        np.random.seed(42)
        true_labels = [0] * 50 + [1] * 50
        predicted_scores = [np.random.uniform(0.0, 0.25) for _ in range(50)] + [
            np.random.uniform(0.75, 1.0) for _ in range(50)
        ]
        predictor.fit(predicted_scores, true_labels)

        eval_res = predictor.evaluate_coverage(predicted_scores, true_labels)
        assert eval_res["overall_coverage"] >= 0.90
        assert eval_res["mean_interval_width"] < 0.35


@pytest.mark.unit
class TestTreeSHAPExplainer:
    def test_analytic_shapley_sum_to_one(self) -> None:
        explainer = TreeSHAPExplainer()
        features = [0.4, 0.8, 0.1, 0.3, 0.0, 0.5, 0.0, 1.0, 12.0, 0.7, 2.0, 0.0]
        attribution = explainer.explain_claim(features, has_vgs=False)
        total = attribution.rav + attribution.scs + attribution.nli + attribution.ics
        assert abs(total - 1.0) <= 0.02  # exact local accuracy sum within rounding
        assert attribution.nli > 0.20  # highest signal should have highest attribution
        assert attribution.vgs is None

    def test_multimodal_vgs_attribution(self) -> None:
        explainer = TreeSHAPExplainer()
        features = [0.2, 0.1, 0.8, 0.1, 0.9, 0.0, 4.0, 1.0, 8.0, 0.5, 1.0, 1.0]
        attribution = explainer.explain_claim(features, has_vgs=True)
        assert attribution.vgs is not None
        assert attribution.vgs > 0.30
        total = attribution.rav + attribution.scs + attribution.nli + attribution.ics + attribution.vgs
        assert abs(total - 1.0) <= 0.02


@pytest.mark.unit
class TestHRSEngine:
    def test_process_claims_supported(self) -> None:
        engine = HRSEngine()
        claim = Claim(
            claim_id="c1",
            text="Berlin is the capital of Germany.",
            claim_type=ClaimType.FACTUAL,
            criticality=ClaimCriticality.HIGH,
            criticality_weight=1.0,
        )
        evidence = EvidenceChunk(
            chunk_id="chk_1",
            document_id="doc_1",
            content="Berlin is the capital and largest city of Germany.",
            similarity_score=0.95,
        )

        hrs_res, claim_res = engine.process_claims(
            claims=[claim],
            rav_scores=[0.05],
            evidence_chunks_per_claim=[[evidence]],
            scs_score=0.02,
            ics_scores={"c1": 0.0},
            nli_scores=[0.02],
            scs_enabled=True,
        )

        assert hrs_res.tier == RiskTier.LOW
        assert hrs_res.hrs < 0.25
        assert len(claim_res) == 1
        assert claim_res[0].status == VerificationStatus.SUPPORTED

    def test_critical_hallucination_lower_bound_rule(self) -> None:
        engine = HRSEngine()
        # 3 claims: 2 completely supported, 1 critical hallucination
        c1 = Claim(claim_id="c1", text="Supported claim 1", criticality_weight=1.0)
        c2 = Claim(claim_id="c2", text="Supported claim 2", criticality_weight=1.0)
        c3 = Claim(claim_id="c3", text="Deadly hallucinated claim", criticality_weight=1.0)

        hrs_res, _ = engine.process_claims(
            claims=[c1, c2, c3],
            rav_scores=[0.05, 0.05, 0.95],
            evidence_chunks_per_claim=[[], [], []],
            scs_score=0.05,
            ics_scores={"c1": 0.0, "c2": 0.0, "c3": 0.95},
            nli_scores=[0.05, 0.05, 0.95],
            scs_enabled=True,
        )

        # Critical lower bound rule: max claim > 0.80 => response HRS bounded below by 0.80 * max
        assert hrs_res.hrs >= 0.70
        assert hrs_res.contradicted_claims_count == 1

    def test_scs_weight_renormalization_when_disabled(self) -> None:
        engine = HRSEngine()
        c = Claim(claim_id="c1", text="Sample factual claim", criticality_weight=1.0)
        hrs_res, claim_res = engine.process_claims(
            claims=[c],
            rav_scores=[0.30],
            evidence_chunks_per_claim=[[]],
            scs_score=0.80,  # Should be ignored because scs_enabled=False
            ics_scores={"c1": 0.20},
            nli_scores=[0.25],
            scs_enabled=False,
        )

        # SCS attribution must be 0.0 when disabled
        assert hrs_res.signal_attribution.scs == 0.0
        assert claim_res[0].scs_score == 0.0
