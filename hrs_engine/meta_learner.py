"""Meta-Learner: LightGBM gradient boosted decision tree classifier and baseline ensemble."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from shared.logging import get_logger

logger = get_logger("hrs_meta_learner")

try:
    import lightgbm as lgb

    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False


class HRSMetaLearner:
    """Predicts raw hallucination risk score from the 12-dimensional feature vector."""

    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model: Any = None
        self._is_fitted = False

        if model_path and Path(model_path).exists() and HAS_LIGHTGBM:
            try:
                self.model = lgb.Booster(model_file=str(model_path))
                self._is_fitted = True
                logger.info("Loaded pretrained LightGBM meta-learner", path=str(model_path))
            except Exception as exc:
                logger.warning("Failed to load LightGBM model from disk", error=str(exc))
                self.model = None

    def fit(self, X: Sequence[Sequence[float]], y: Sequence[int | float]) -> None:
        """Fit a LightGBM classifier on training/calibration feature vectors."""
        if not HAS_LIGHTGBM:
            logger.warning("LightGBM not available, skipping fit")
            return

        import numpy as np

        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "boosting_type": "gbdt",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 6,
            "feature_fraction": 0.8,
            "min_child_samples": 5,
            "verbose": -1,
        }

        X_arr = np.asarray(X, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        train_data = lgb.Dataset(X_arr, label=y_arr)
        self.model = lgb.train(params, train_data, num_boost_round=50)
        self._is_fitted = True
        logger.info("Fitted LightGBM meta-learner", samples=len(X))

    def predict_proba(self, features_list: list[list[float]]) -> list[float]:
        """Compute uncalibrated risk probability for each 12-dim feature vector."""
        if not features_list:
            return []

        if self._is_fitted and self.model is not None:
            try:
                import numpy as np

                preds = self.model.predict(np.asarray(features_list, dtype=float))
                return [round(float(min(1.0, max(0.0, p))), 4) for p in preds]
            except Exception as exc:
                logger.warning("LightGBM inference error, using fallback ensemble", error=str(exc))

        # Baseline non-linear parametric ensemble fallback
        predictions: list[float] = []
        for x in features_list:
            predictions.append(self._fallback_predict(x))
        return predictions

    def _fallback_predict(self, x: list[float]) -> float:
        """Non-linear signal aggregation matching Section 5.2 architecture.

        Features:
        0: rss_score (0.35)
        1: p_contra  (0.30)
        2: p_support
        3: scs_score (0.20)
        4: vgs_score
        5: ics_score (0.15)
        6: claim_type_encoded
        7: criticality_weight
        8: token_length
        9: retrieved_evidence_max_similarity
        10: total_claim_count
        11: has_image
        """
        rss = x[0]
        p_contra = x[1]
        p_support = x[2]
        scs = x[3]
        vgs = x[4]
        ics = x[5]
        has_img = x[11] > 0.5

        # Base signal weighting: RAV (0.35) + NLI (0.30) + SCS (0.20) + ICS (0.15)
        if has_img:
            # If multimodal, allocate 0.20 weight to VGS
            w_rav, w_nli, w_scs, w_ics, w_vgs = 0.25, 0.25, 0.15, 0.15, 0.20
            base_score = w_rav * rss + w_nli * p_contra + w_scs * scs + w_ics * ics + w_vgs * vgs
        else:
            w_rav, w_nli, w_scs, w_ics = 0.35, 0.30, 0.20, 0.15
            base_score = w_rav * rss + w_nli * p_contra + w_scs * scs + w_ics * ics

        # Support bonus / discount
        if p_support > 0.70 and rss < 0.25:
            base_score *= 0.60  # Substantial discount if explicitly supported

        # Non-linear interaction: high entropy combined with contradiction amplifies risk
        interaction_term = 0.12 * (scs * p_contra)
        final_score = base_score + interaction_term

        # Contradiction dominance: if evidence refutes claim or severe internal contradiction
        if p_contra > 0.80 and rss > 0.80:
            final_score = max(final_score, 0.90)
        elif p_contra > 0.80 or ics > 0.80:
            final_score = max(final_score, 0.85)

        return round(float(min(1.0, max(0.0, final_score))), 4)

    def save_model(self, save_path: str | Path) -> None:
        """Save fitted LightGBM model to disk."""
        if self.model is not None and self._is_fitted:
            self.model.save_model(str(save_path))
            logger.info("Saved LightGBM model", path=str(save_path))
