"""HRS Engine: Hallucination Risk Score aggregation, calibration, and uncertainty quantification."""

from hrs_engine.calibrator import Calibrator, compute_ece
from hrs_engine.conformal import MondrianConformalPredictor
from hrs_engine.engine import HRSEngine
from hrs_engine.feature_extractor import FeatureExtractor
from hrs_engine.meta_learner import HRSMetaLearner
from hrs_engine.shap_explainer import TreeSHAPExplainer

__all__ = [
    "Calibrator",
    "FeatureExtractor",
    "HRSEngine",
    "HRSMetaLearner",
    "MondrianConformalPredictor",
    "TreeSHAPExplainer",
    "compute_ece",
]
