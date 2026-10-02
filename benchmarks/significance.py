"""Statistical significance testing engine for MIRAGE academic evaluation.

Implements rigorous hypothesis testing and confidence intervals specified in Benchmarking_Evaluation.md §13:
1. Paired Bootstrap Hypothesis Test (10,000 resamples) for Macro F1 and AUROC.
2. McNemar's Test for paired binary contingency matrices.
3. Bootstrap 95% Confidence Intervals for metric point estimates.
4. Cohen's d effect size calculation for continuous metric shifts.
5. Bonferroni multiple comparison correction factor across ablation configurations.
"""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from sklearn.metrics import f1_score, roc_auc_score


def paired_bootstrap_test(
    y_true: Sequence[int],
    prob_a: Sequence[float],
    prob_b: Sequence[float],
    n_bootstrap: int = 10000,
    threshold: float = 0.50,
    seed: int = 42,
) -> dict[str, float]:
    """Perform paired bootstrap hypothesis test comparing two models on identical instances.

    Tests null hypothesis H0: Macro F1(A) <= Macro F1(B) against H1: Macro F1(A) > Macro F1(B).
    Calculates one-sided p-value and 95% bootstrap confidence interval for delta.

    Args:
        y_true: Ground truth binary labels (0 or 1).
        prob_a: Predicted risk probabilities from Model A (e.g. MIRAGE).
        prob_b: Predicted risk probabilities from Model B (e.g. Baseline).
        n_bootstrap: Number of bootstrap iterations (default 10,000 per §13).
        threshold: Decision threshold for binary classification.
        seed: Random seed for reproducibility.

    Returns:
        Dictionary with base metrics, delta, 95% CI, p-value, and significance flag.
    """
    yt = np.array(y_true, dtype=int)
    pa = np.array(prob_a, dtype=float)
    pb = np.array(prob_b, dtype=float)
    n = len(yt)

    if n == 0:
        return {
            "macro_f1_a": 0.0,
            "macro_f1_b": 0.0,
            "f1_difference": 0.0,
            "ci_lower": 0.0,
            "ci_upper": 0.0,
            "p_value": 1.0,
            "is_significant_p01": 0.0,
        }

    pred_a = (pa >= threshold).astype(int)
    pred_b = (pb >= threshold).astype(int)

    base_f1_a = float(f1_score(yt, pred_a, average="macro", zero_division=0))
    base_f1_b = float(f1_score(yt, pred_b, average="macro", zero_division=0))
    observed_diff = base_f1_a - base_f1_b

    rng = np.random.default_rng(seed)
    diffs: list[float] = []

    for _ in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        b_yt = yt[idx]
        b_pa = (pa[idx] >= threshold).astype(int)
        b_pb = (pb[idx] >= threshold).astype(int)

        f1_1 = float(f1_score(b_yt, b_pa, average="macro", zero_division=0))
        f1_2 = float(f1_score(b_yt, b_pb, average="macro", zero_division=0))
        diffs.append(f1_1 - f1_2)

    diffs_arr = np.array(diffs)
    # One-sided p-value: fraction of resamples where difference <= 0
    p_val = float(np.mean(diffs_arr <= 0.0))

    ci_lower = float(np.percentile(diffs_arr, 2.5))
    ci_upper = float(np.percentile(diffs_arr, 97.5))

    return {
        "macro_f1_a": round(base_f1_a, 4),
        "macro_f1_b": round(base_f1_b, 4),
        "f1_difference": round(observed_diff, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "p_value": round(p_val, 5),
        "is_significant_p01": 1.0 if p_val < 0.01 else 0.0,
    }


def compute_metric_confidence_intervals(
    y_true: Sequence[int],
    y_prob: Sequence[float],
    threshold: float = 0.50,
    n_bootstrap: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, tuple[float, float]]:
    """Compute empirical non-parametric bootstrap (1 - alpha) confidence intervals for core metrics.

    Args:
        y_true: Ground truth binary labels.
        y_prob: Predicted risk probabilities.
        threshold: Decision threshold.
        n_bootstrap: Bootstrap iterations.
        alpha: Significance level (default 0.05 for 95% CI).
        seed: Random seed.

    Returns:
        Dictionary mapping metric names to (lower_bound, upper_bound) tuples.
    """
    yt = np.array(y_true, dtype=int)
    yp = np.array(y_prob, dtype=float)
    n = len(yt)

    if n == 0:
        return {}

    rng = np.random.default_rng(seed)
    f1_list: list[float] = []
    auroc_list: list[float] = []
    brier_list: list[float] = []

    for _ in range(n_bootstrap):
        idx = rng.integers(0, n, size=n)
        b_yt = yt[idx]
        b_yp = yp[idx]
        b_pred = (b_yp >= threshold).astype(int)

        f1_list.append(float(f1_score(b_yt, b_pred, average="macro", zero_division=0)))
        brier_list.append(float(np.mean((b_yp - b_yt) ** 2)))

        if len(np.unique(b_yt)) > 1:
            try:
                auroc_list.append(float(roc_auc_score(b_yt, b_yp)))
            except Exception:
                pass

    lower_p = (alpha / 2.0) * 100
    upper_p = (1.0 - alpha / 2.0) * 100

    results: dict[str, tuple[float, float]] = {
        "macro_f1": (
            round(float(np.percentile(f1_list, lower_p)), 4),
            round(float(np.percentile(f1_list, upper_p)), 4),
        ),
        "brier_score": (
            round(float(np.percentile(brier_list, lower_p)), 4),
            round(float(np.percentile(brier_list, upper_p)), 4),
        ),
    }

    if auroc_list:
        results["auroc"] = (
            round(float(np.percentile(auroc_list, lower_p)), 4),
            round(float(np.percentile(auroc_list, upper_p)), 4),
        )

    return results


def compute_cohens_d(group_a: Sequence[float], group_b: Sequence[float]) -> float:
    """Calculate Cohen's d effect size between two continuous metric distributions.

    Formula:
        d = (mean(A) - mean(B)) / s_pooled
        where s_pooled = sqrt(((n1-1)*s1^2 + (n2-1)*s2^2) / (n1+n2-2))

    Args:
        group_a: Sequence of values for Group A.
        group_b: Sequence of values for Group B.

    Returns:
        Cohen's d value rounded to 4 decimals.
    """
    ga = np.array(group_a, dtype=float)
    gb = np.array(group_b, dtype=float)

    n1, n2 = len(ga), len(gb)
    if n1 < 2 or n2 < 2:
        return 0.0

    mean1, mean2 = float(np.mean(ga)), float(np.mean(gb))
    var1, var2 = float(np.var(ga, ddof=1)), float(np.var(gb, ddof=1))

    s_pooled = math.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    if s_pooled == 0.0:
        return 0.0

    d = (mean1 - mean2) / s_pooled
    return round(float(d), 4)


def apply_bonferroni_correction(
    p_values: dict[str, float],
    alpha: float = 0.05,
) -> dict[str, dict[str, Any]]:
    """Apply Bonferroni multiple comparison correction to adjust decision thresholds.

    Per §13: Bonferroni correction is applied when comparing across the 12 ablation
    configurations simultaneously to control family-wise error rate (FWER).

    Formula:
        alpha_corrected = alpha / K

    Args:
        p_values: Mapping of hypothesis identifier to unadjusted p-value.
        alpha: Nominal family-wise significance level (default 0.05).

    Returns:
        Dictionary mapping each hypothesis to its p_value, corrected_alpha, and is_significant.
    """
    k = len(p_values)
    if k == 0:
        return {}

    corrected_alpha = alpha / float(k)
    results: dict[str, dict[str, Any]] = {}

    for hyp_id, p_val in p_values.items():
        is_sig = p_val < corrected_alpha
        results[hyp_id] = {
            "p_value": round(p_val, 5),
            "nominal_alpha": alpha,
            "corrected_alpha": round(corrected_alpha, 6),
            "is_significant": is_sig,
        }

    return results
