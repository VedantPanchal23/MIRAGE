"""3-Way calibration benchmarking and cross-domain generalization engine.

Implements the formal calibration evaluation protocol from Benchmarking_Evaluation.md §6:
1. Compares Isotonic Regression, Platt Scaling, and Temperature Scaling.
2. Generates 15-bin calibration reliability diagrams (accuracy vs. confidence).
3. Evaluates ECE, MCE, and Brier Score before and after calibration.
4. Validates cross-benchmark transfer from HaluEval validation split to TruthfulQA and FActScore zero-shot.
"""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from benchmarks.evaluator import BenchmarkCase, BenchmarkOutput
from benchmarks.metrics import compute_calibration_metrics


@dataclass
class CalibrationMethodResult:
    """Evaluation summary for a specific calibration method."""

    method_name: str
    ece_before: float
    ece_after: float
    mce_before: float
    mce_after: float
    brier_before: float
    brier_after: float
    reliability_bins_after: list[dict[str, float]]
    target_ece_met: bool  # ECE < 0.035 on in-domain, < 0.050 on cross-domain

    def to_dict(self) -> dict[str, Any]:
        """Serialize method result to dictionary."""
        return asdict(self)


@dataclass
class CrossDomainTransferResult:
    """Evaluation of calibration generalization under distribution shift."""

    source_domain: str
    target_domain: str
    calibrator: str
    sample_count: int
    uncalibrated_ece: float
    transfer_ece: float
    transfer_mce: float
    transfer_brier: float
    transfer_generalization_target_met: bool  # ECE < 0.050 per §17

    def to_dict(self) -> dict[str, Any]:
        """Serialize cross-domain result to dictionary."""
        return asdict(self)


class ThreeWayCalibrationBenchmark:
    """Fits and benchmarks Isotonic Regression, Platt Scaling, and Temperature Scaling."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed
        self.isotonic_model: IsotonicRegression | None = None
        self.platt_model: LogisticRegression | None = None
        self.temperature: float = 1.0

    def fit_calibrators(self, raw_scores: Sequence[float], y_true: Sequence[int]) -> None:
        """Fit all three post-hoc calibrators on calibration dataset.

        Args:
            raw_scores: Uncalibrated continuous scores / logits.
            y_true: Binary ground-truth labels (0 or 1).
        """
        x = np.array(raw_scores, dtype=float).reshape(-1, 1)
        y = np.array(y_true, dtype=int)

        # 1. Isotonic Regression (piecewise non-decreasing constant)
        self.isotonic_model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self.isotonic_model.fit(x.ravel(), y)

        # 2. Platt Scaling (Logistic Regression on raw scores)
        self.platt_model = LogisticRegression(C=1.0, solver="lbfgs", random_state=self.seed)
        self.platt_model.fit(x, y)

        # 3. Temperature Scaling: optimize T to minimize negative log-likelihood
        # For probabilities in (0, 1), convert to logit z = log(p / (1 - p))
        eps = 1e-6
        clipped_p = np.clip(x.ravel(), eps, 1.0 - eps)
        logits = np.log(clipped_p / (1.0 - clipped_p))

        best_t = 1.0
        best_nll = float("inf")
        # Grid search over T in [0.2, 5.0]
        for t_candidate in np.linspace(0.2, 5.0, 50):
            scaled_logits = logits / t_candidate
            scaled_p = 1.0 / (1.0 + np.exp(-scaled_logits))
            scaled_p = np.clip(scaled_p, eps, 1.0 - eps)
            nll = -float(np.mean(y * np.log(scaled_p) + (1 - y) * np.log(1 - scaled_p)))
            if nll < best_nll:
                best_nll = nll
                best_t = float(t_candidate)

        self.temperature = best_t

    def calibrate(self, method: str, raw_scores: Sequence[float]) -> list[float]:
        """Apply a fitted calibration method to new raw scores."""
        x = np.array(raw_scores, dtype=float)

        if method == "isotonic":
            if self.isotonic_model is None:
                raise RuntimeError("Isotonic model not fitted yet.")
            calibrated = self.isotonic_model.predict(x)
            return [float(p) for p in np.clip(calibrated, 0.0, 1.0)]

        elif method == "platt":
            if self.platt_model is None:
                raise RuntimeError("Platt model not fitted yet.")
            probs = self.platt_model.predict_proba(x.reshape(-1, 1))[:, 1]
            return [float(p) for p in probs]

        elif method == "temperature":
            eps = 1e-6
            clipped_p = np.clip(x, eps, 1.0 - eps)
            logits = np.log(clipped_p / (1.0 - clipped_p))
            scaled_logits = logits / max(self.temperature, 0.01)
            scaled_p = 1.0 / (1.0 + np.exp(-scaled_logits))
            return [float(p) for p in scaled_p]

        else:
            raise ValueError(f"Unknown calibration method: {method}")

    def evaluate_methods(
        self,
        raw_scores: Sequence[float],
        y_true: Sequence[int],
    ) -> list[CalibrationMethodResult]:
        y_list = list(y_true)
        raw_list = list(raw_scores)

        ece_b, mce_b, brier_b, _ = compute_calibration_metrics(y_list, raw_list, num_bins=15)
        results: list[CalibrationMethodResult] = []

        for m_name in ["isotonic", "platt", "temperature"]:
            cal_scores = self.calibrate(m_name, raw_list)
            ece_a, mce_a, brier_a, bins_a = compute_calibration_metrics(y_list, cal_scores, num_bins=15)

            results.append(
                CalibrationMethodResult(
                    method_name=m_name,
                    ece_before=round(ece_b, 4),
                    ece_after=round(ece_a, 4),
                    mce_before=round(mce_b, 4),
                    mce_after=round(mce_a, 4),
                    brier_before=round(brier_b, 4),
                    brier_after=round(brier_a, 4),
                    reliability_bins_after=bins_a,
                    target_ece_met=bool(ece_a <= 0.035 if m_name == "isotonic" else ece_a <= 0.050),
                )
            )

        return results

    def evaluate_cross_domain_transfer(
        self,
        target_name: str,
        target_cases: Sequence[BenchmarkCase],
        target_outputs: Sequence[BenchmarkOutput],
    ) -> CrossDomainTransferResult:
        """Evaluate zero-shot transfer of the fitted Isotonic calibrator on an out-of-domain dataset."""
        y_true = [c.ground_truth_label for c in target_cases]
        raw_scores = [o.predicted_hrs for o in target_outputs]

        ece_uncal, _, _, _ = compute_calibration_metrics(y_true, raw_scores, num_bins=15)

        # Apply Isotonic calibrator fitted on source domain (HaluEval)
        calibrated_scores = self.calibrate("isotonic", raw_scores)
        ece_cal, mce_cal, brier_cal, _ = compute_calibration_metrics(y_true, calibrated_scores, num_bins=15)

        return CrossDomainTransferResult(
            source_domain="HaluEval (Validation Split)",
            target_domain=target_name,
            calibrator="Isotonic Regression",
            sample_count=len(target_cases),
            uncalibrated_ece=round(ece_uncal, 4),
            transfer_ece=round(ece_cal, 4),
            transfer_mce=round(mce_cal, 4),
            transfer_brier=round(brier_cal, 4),
            transfer_generalization_target_met=bool(ece_cal <= 0.050),
        )
