from typing import Any, Literal

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from shared.logging import get_logger

logger = get_logger("hrs_calibrator")

CalibrationMethod = Literal["isotonic", "platt", "temperature"]


def compute_ece(
    y_true: list[float] | np.ndarray[Any, Any],
    y_prob: list[float] | np.ndarray[Any, Any],
    n_bins: int = 15,
) -> float:
    """Compute Expected Calibration Error (ECE) across specified probability bins.

    Formula (Section 5.3):
        ECE = sum_{m=1}^{M} (|B_m| / N) * |acc(B_m) - conf(B_m)|
    """
    y_true_arr = np.asarray(y_true, dtype=float)
    y_prob_arr = np.asarray(y_prob, dtype=float)

    if len(y_true_arr) == 0:
        return 0.0

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = len(y_true_arr)

    for i in range(n_bins):
        bin_lower = bins[i]
        bin_upper = bins[i + 1]

        # Samples falling into current bin
        if i == n_bins - 1:
            in_bin = (y_prob_arr >= bin_lower) & (y_prob_arr <= bin_upper)
        else:
            in_bin = (y_prob_arr >= bin_lower) & (y_prob_arr < bin_upper)

        bin_count = np.sum(in_bin)
        if bin_count > 0:
            acc = float(np.mean(y_true_arr[in_bin]))
            conf = float(np.mean(y_prob_arr[in_bin]))
            ece += (bin_count / n) * abs(acc - conf)

    return round(float(ece), 5)


def compute_mce(
    y_true: list[float] | np.ndarray[Any, Any],
    y_prob: list[float] | np.ndarray[Any, Any],
    n_bins: int = 15,
) -> float:
    """Compute Maximum Calibration Error (MCE) across probability bins."""
    y_true_arr = np.asarray(y_true, dtype=float)
    y_prob_arr = np.asarray(y_prob, dtype=float)

    if len(y_true_arr) == 0:
        return 0.0

    bins = np.linspace(0.0, 1.0, n_bins + 1)
    max_err = 0.0

    for i in range(n_bins):
        bin_lower = bins[i]
        bin_upper = bins[i + 1]

        if i == n_bins - 1:
            in_bin = (y_prob_arr >= bin_lower) & (y_prob_arr <= bin_upper)
        else:
            in_bin = (y_prob_arr >= bin_lower) & (y_prob_arr < bin_upper)

        bin_count = np.sum(in_bin)
        if bin_count > 0:
            acc = float(np.mean(y_true_arr[in_bin]))
            conf = float(np.mean(y_prob_arr[in_bin]))
            diff = abs(acc - conf)
            if diff > max_err:
                max_err = diff

    return round(float(max_err), 5)


def compute_brier_score(
    y_true: list[float] | np.ndarray[Any, Any],
    y_prob: list[float] | np.ndarray[Any, Any],
) -> float:
    """Compute mean squared error between true binary outcome and predicted probability."""
    y_true_arr = np.asarray(y_true, dtype=float)
    y_prob_arr = np.asarray(y_prob, dtype=float)
    if len(y_true_arr) == 0:
        return 0.0
    return round(float(np.mean((y_true_arr - y_prob_arr) ** 2)), 5)


class Calibrator:
    """Calibrates raw risk scores using Isotonic Regression, Platt Scaling, or Temperature Scaling."""

    def __init__(self, method: CalibrationMethod = "isotonic") -> None:
        self.method = method
        self._is_fitted = False
        self._isotonic: IsotonicRegression | None = None
        self._platt: LogisticRegression | None = None
        self._temperature: float = 1.0

    def fit(self, raw_scores: list[float], true_labels: list[int | float]) -> None:
        """Fit calibration model on held-out calibration set (e.g. 1000 HaluEval samples)."""
        scores_arr = np.asarray(raw_scores, dtype=float)
        labels_arr = np.asarray(true_labels, dtype=float)

        if len(scores_arr) < 2:
            logger.warning("Insufficient samples to calibrate, skipping fit")
            return

        if self.method == "isotonic":
            self._isotonic = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            self._isotonic.fit(scores_arr, labels_arr)
            self._is_fitted = True
            logger.info("Fitted Isotonic Calibrator", n_samples=len(scores_arr))

        elif self.method == "platt":
            # Platt scaling: LogisticRegression on log-odds of scores
            eps = 1e-6
            clipped = np.clip(scores_arr, eps, 1.0 - eps)
            logits = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
            self._platt = LogisticRegression(C=1.0, solver="lbfgs")
            self._platt.fit(logits, labels_arr)
            self._is_fitted = True
            logger.info("Fitted Platt Scaling Calibrator", n_samples=len(scores_arr))

        elif self.method == "temperature":
            # Temperature scaling: optimize T to minimize NLL
            eps = 1e-6
            clipped = np.clip(scores_arr, eps, 1.0 - eps)
            logits = np.log(clipped / (1.0 - clipped))
            # Grid search for best temperature T in [0.1, 5.0]
            best_t = 1.0
            best_loss = float("inf")
            for t_candidate in np.linspace(0.2, 3.0, 50):
                scaled_probs = 1.0 / (1.0 + np.exp(-logits / t_candidate))
                nll_pos = labels_arr * np.log(np.clip(scaled_probs, eps, 1.0))
                nll_neg = (1 - labels_arr) * np.log(np.clip(1.0 - scaled_probs, eps, 1.0))
                loss = -float(np.mean(nll_pos + nll_neg))
                if loss < best_loss:
                    best_loss = loss
                    best_t = float(t_candidate)
            self._temperature = best_t
            self._is_fitted = True
            logger.info("Fitted Temperature Scaling", temperature=self._temperature)

    def calibrate(self, raw_scores: list[float]) -> list[float]:
        """Map raw score vector to calibrated probabilities."""
        if not raw_scores:
            return []

        scores_arr = np.asarray(raw_scores, dtype=float)

        if not self._is_fitted:
            # Identity fallback if calibrator has not been fitted
            return [round(float(min(1.0, max(0.0, s))), 4) for s in raw_scores]

        if self.method == "isotonic" and self._isotonic is not None:
            calibrated = self._isotonic.predict(scores_arr)
            return [round(float(min(1.0, max(0.0, s))), 4) for s in calibrated]

        if self.method == "platt" and self._platt is not None:
            eps = 1e-6
            clipped = np.clip(scores_arr, eps, 1.0 - eps)
            logits = np.log(clipped / (1.0 - clipped)).reshape(-1, 1)
            probs = self._platt.predict_proba(logits)[:, 1]
            return [round(float(min(1.0, max(0.0, p))), 4) for p in probs]

        if self.method == "temperature":
            eps = 1e-6
            clipped = np.clip(scores_arr, eps, 1.0 - eps)
            logits = np.log(clipped / (1.0 - clipped))
            scaled_probs = 1.0 / (1.0 + np.exp(-logits / self._temperature))
            return [round(float(min(1.0, max(0.0, p))), 4) for p in scaled_probs]

        return [round(float(min(1.0, max(0.0, s))), 4) for s in raw_scores]

    def calibrate_single(self, score: float) -> float:
        """Calibrate a single risk score."""
        return self.calibrate([score])[0]
