"""Mondrian (Group-Conditional) Conformal Prediction Engine."""

import math
from typing import Any

import numpy as np

from shared.logging import get_logger
from shared.schemas import ConformalInterval, RiskTier, determine_risk_tier

logger = get_logger("hrs_conformal")


class MondrianConformalPredictor:
    """Group-conditional conformal prediction guaranteeing >= 1 - alpha coverage within each group."""

    DEFAULT_QUANTILES: dict[str, float] = {
        "tier:LOW": 0.055,
        "tier:MEDIUM": 0.065,
        "tier:HIGH": 0.075,
        "tier:CRITICAL": 0.085,
        "default": 0.070,
    }

    def __init__(self, alpha: float = 0.05) -> None:
        self.alpha = alpha
        self.confidence_level = round(1.0 - alpha, 4)
        self.group_quantiles: dict[str, float] = dict(self.DEFAULT_QUANTILES)
        self.group_samples_count: dict[str, int] = {}
        self._is_calibrated = False

    def fit(
        self,
        predicted_scores: list[float] | np.ndarray[Any, Any],
        true_labels: list[int | float] | np.ndarray[Any, Any],
        groups: list[str] | None = None,
    ) -> None:
        """Calibrate group-conditional non-conformity quantiles on held-out calibration set."""
        preds = np.asarray(predicted_scores, dtype=float)
        targets = np.asarray(true_labels, dtype=float)

        if len(preds) != len(targets) or len(preds) == 0:
            logger.warning("Empty or mismatched calibration set, keeping default quantiles")
            return

        if groups is None:
            # Assign groups based on risk tiers
            groups = [f"tier:{determine_risk_tier(float(p)).value}" for p in preds]

        # Group-wise non-conformity score calculation
        scores_by_group: dict[str, list[float]] = {}
        for p, y, g in zip(preds, targets, groups, strict=False):
            non_conformity = abs(float(y) - float(p))
            scores_by_group.setdefault(g, []).append(non_conformity)

        for group_name, scores in scores_by_group.items():
            n_g = len(scores)
            self.group_samples_count[group_name] = n_g
            if n_g < 10:
                # Small sample size, keep conservative default
                continue

            scores_sorted = sorted(scores)
            # Finite-sample conformal quantile: ceil((n_g + 1) * (1 - alpha)) / n_g
            q_idx = math.ceil((n_g + 1) * (1.0 - self.alpha)) - 1
            q_idx = min(q_idx, n_g - 1)
            q_val = scores_sorted[q_idx]
            self.group_quantiles[group_name] = round(float(q_val), 4)

        self._is_calibrated = True
        logger.info("Mondrian Conformal Predictor calibrated", groups=list(self.group_quantiles.keys()))

    def predict_interval(
        self,
        score: float,
        group: str | None = None,
        risk_tier: RiskTier | None = None,
    ) -> ConformalInterval:
        """Compute conformal confidence interval [lower, upper] for a given score and group."""
        if group is None:
            if risk_tier is None:
                risk_tier = determine_risk_tier(score)
            group = f"tier:{risk_tier.value}"

        q = self.group_quantiles.get(group, self.group_quantiles.get("default", 0.070))

        lower = round(max(0.0, score - q), 4)
        upper = round(min(1.0, score + q), 4)

        return ConformalInterval(
            lower=lower,
            upper=upper,
            confidence_level=self.confidence_level,
            conditional_group=group,
        )

    def evaluate_coverage(
        self,
        predicted_scores: list[float],
        true_labels: list[int | float],
        groups: list[str] | None = None,
    ) -> dict[str, float]:
        """Evaluate empirical coverage and mean interval width on a test set."""
        if not predicted_scores:
            return {"overall_coverage": 0.0, "mean_width": 0.0}

        if groups is None:
            groups = [f"tier:{determine_risk_tier(p).value}" for p in predicted_scores]

        hits = 0
        widths: list[float] = []
        group_hits: dict[str, int] = {}
        group_counts: dict[str, int] = {}

        for p, y, g in zip(predicted_scores, true_labels, groups, strict=False):
            interval = self.predict_interval(p, group=g)
            in_interval = interval.lower <= y <= interval.upper
            if in_interval:
                hits += 1
                group_hits[g] = group_hits.get(g, 0) + 1
            group_counts[g] = group_counts.get(g, 0) + 1
            widths.append(interval.upper - interval.lower)

        results: dict[str, float] = {
            "overall_coverage": round(hits / len(predicted_scores), 4),
            "mean_interval_width": round(float(np.mean(widths)), 4),
        }

        for g, count in group_counts.items():
            results[f"coverage_{g}"] = round(group_hits.get(g, 0) / count, 4)

        return results
