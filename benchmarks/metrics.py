"""Statistical evaluation metrics engine for MIRAGE benchmarks.

Implements formal academic evaluation metrics specified in Benchmarking_Evaluation.md:
1. Macro F1, Precision, Recall, AUROC, AUPRC.
2. Calibration: Expected Calibration Error (ECE, 15 bins), Maximum Calibration Error (MCE), Brier Score.
3. Conformal Prediction: Marginal coverage, Mondrian group-conditional coverage, mean interval width.
4. Statistical Significance: Paired bootstrap resampling (10,000 resamples), McNemar's test.
"""

import math
from collections import defaultdict
from collections.abc import Sequence

import numpy as np
from sklearn.metrics import (
    auc,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)


def compute_classification_metrics(
    y_true: Sequence[int],
    y_pred: Sequence[int],
    y_prob: Sequence[float] | None = None,
) -> dict[str, float]:
    """Compute comprehensive classification accuracy metrics.

    Args:
        y_true: Binary ground-truth labels (1 = Hallucination, 0 = Factual).
        y_pred: Binary predicted labels.
        y_prob: Continuous risk probabilities / HRS scores in [0.0, 1.0].

    Returns:
        Dictionary of accuracy, precision, recall, macro F1, and curves.
    """
    yt = np.array(y_true, dtype=int)
    yp = np.array(y_pred, dtype=int)

    acc = float(np.mean(yt == yp))
    macro_f1 = float(f1_score(yt, yp, average="macro", zero_division=0))
    prec = float(precision_score(yt, yp, average="macro", zero_division=0))
    rec = float(recall_score(yt, yp, average="macro", zero_division=0))

    # Per-class F1
    f1_factual = float(f1_score(yt, yp, pos_label=0, zero_division=0))
    f1_hallucinated = float(f1_score(yt, yp, pos_label=1, zero_division=0))

    metrics: dict[str, float] = {
        "accuracy": round(acc, 4),
        "macro_f1": round(macro_f1, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1_factual": round(f1_factual, 4),
        "f1_hallucinated": round(f1_hallucinated, 4),
    }

    if y_prob is not None and len(np.unique(yt)) > 1:
        probs = np.array(y_prob, dtype=float)
        try:
            auroc = float(roc_auc_score(yt, probs))
            metrics["auroc"] = round(auroc, 4)
        except Exception:
            metrics["auroc"] = 0.5

        try:
            p_curve, r_curve, _ = precision_recall_curve(yt, probs)
            auprc = float(auc(r_curve, p_curve))
            metrics["auprc"] = round(auprc, 4)
        except Exception:
            metrics["auprc"] = 0.0

    return metrics


def compute_calibration_metrics(
    y_true: Sequence[int],
    y_prob: Sequence[float],
    num_bins: int = 15,
) -> tuple[float, float, float, list[dict[str, float]]]:
    """Compute Expected Calibration Error (ECE), MCE, Brier Score, and reliability bins.

    Formula:
        ECE = sum_{m=1}^M (|B_m| / N) * |acc(B_m) - conf(B_m)|
        MCE = max_m |acc(B_m) - conf(B_m)|
        Brier = (1 / N) * sum_{i=1}^N (p_i - y_i)^2

    Args:
        y_true: Ground truth binary labels (0 or 1).
        y_prob: Continuous model confidence / probability in [0.0, 1.0].
        num_bins: Number of equal-width calibration bins (default 15).

    Returns:
        Tuple of (ECE, MCE, Brier score, list of per-bin reliability details).
    """
    n = len(y_true)
    if n == 0:
        return 0.0, 0.0, 0.0, []

    yt = np.array(y_true, dtype=float)
    yp = np.array(y_prob, dtype=float)

    brier = float(np.mean((yp - yt) ** 2))

    bin_boundaries = np.linspace(0.0, 1.0, num_bins + 1)
    bin_details: list[dict[str, float]] = []

    ece = 0.0
    mce = 0.0

    for i in range(num_bins):
        lower = float(bin_boundaries[i])
        upper = float(bin_boundaries[i + 1])
        center = round((lower + upper) / 2.0, 4)

        if i == num_bins - 1:
            in_bin = (yp >= lower) & (yp <= upper)
        else:
            in_bin = (yp >= lower) & (yp < upper)

        count = int(np.sum(in_bin))
        if count > 0:
            acc = float(np.mean(yt[in_bin]))
            conf = float(np.mean(yp[in_bin]))
            gap = abs(acc - conf)
            weight = count / n

            ece += weight * gap
            if gap > mce:
                mce = gap

            bin_details.append(
                {
                    "bin_id": float(i + 1),
                    "lower": round(lower, 4),
                    "upper": round(upper, 4),
                    "center": center,
                    "confidence": round(conf, 4),
                    "accuracy": round(acc, 4),
                    "count": float(count),
                    "weight": round(weight, 4),
                    "gap": round(gap, 4),
                }
            )
        else:
            bin_details.append(
                {
                    "bin_id": float(i + 1),
                    "lower": round(lower, 4),
                    "upper": round(upper, 4),
                    "center": center,
                    "confidence": center,
                    "accuracy": center,
                    "count": 0.0,
                    "weight": 0.0,
                    "gap": 0.0,
                }
            )

    return round(ece, 4), round(mce, 4), round(brier, 4), bin_details


def compute_conformal_coverage(
    y_true: Sequence[int | float],
    intervals: Sequence[tuple[float, float]],
    tolerance: float = 0.20,
) -> dict[str, float]:
    """Evaluate empirical coverage and sharpness of conformal prediction intervals.

    For continuous targets, checks low <= y <= high.
    For discrete binary labels (0 or 1), evaluates whether the prediction region covers the
    corresponding risk class (i.e. low <= tolerance for y=0, or high >= (1.0 - tolerance) for y=1).
    """
    n = len(y_true)
    if n == 0:
        return {"empirical_coverage": 1.0, "mean_interval_width": 0.0, "median_interval_width": 0.0}

    covered = 0
    widths: list[float] = []

    for y, (low, high) in zip(y_true, intervals, strict=False):
        y_val = float(y)
        if y_val == 0.0:
            is_cov = (low <= y_val <= high) or (low <= tolerance)
        elif y_val == 1.0:
            is_cov = (low <= y_val <= high) or (high >= (1.0 - tolerance))
        else:
            is_cov = low <= y_val <= high

        if is_cov:
            covered += 1
        widths.append(max(0.0, high - low))

    return {
        "empirical_coverage": round(covered / n, 4),
        "mean_interval_width": round(float(np.mean(widths)), 4),
        "median_interval_width": round(float(np.median(widths)), 4),
        "std_interval_width": round(float(np.std(widths)), 4),
    }


def compute_mondrian_coverage(
    y_true: Sequence[int | float],
    intervals: Sequence[tuple[float, float]],
    groups: Sequence[str],
) -> dict[str, float]:
    """Evaluate Mondrian group-conditional coverage across strata (e.g. Risk Tiers).

    Args:
        y_true: Ground truth targets.
        intervals: (lower, upper) intervals.
        groups: Categorical group identifier per instance (e.g. 'tier:LOW', 'tier:HIGH').

    Returns:
        Dictionary of coverage percentages per group.
    """
    grouped_data: dict[str, list[tuple[float, tuple[float, float]]]] = defaultdict(list)
    for y, interval, grp in zip(y_true, intervals, groups, strict=False):
        grouped_data[grp].append((float(y), interval))

    result: dict[str, float] = {}
    for grp, items in grouped_data.items():
        cov_info = compute_conformal_coverage([y for y, _ in items], [inv for _, inv in items])
        result[grp] = cov_info["empirical_coverage"]

    return result


def paired_bootstrap_test(
    y_true: Sequence[int],
    prob_a: Sequence[float],
    prob_b: Sequence[float],
    threshold: float = 0.50,
    n_bootstrap: int = 10000,
    seed: int = 42,
) -> dict[str, float]:
    """Conduct paired bootstrap significance test (10,000 iterations) between two model scores.

    Tests null hypothesis H0: Macro F1(A) <= Macro F1(B).

    Returns:
        dict with f1_a, f1_b, f1_diff, p_value, is_significant (at p < 0.01).
    """
    rng = np.random.default_rng(seed)
    n = len(y_true)
    yt = np.array(y_true, dtype=int)
    pa = np.array(prob_a, dtype=float)
    pb = np.array(prob_b, dtype=float)

    pred_a = (pa >= threshold).astype(int)
    pred_b = (pb >= threshold).astype(int)

    base_f1_a = float(f1_score(yt, pred_a, average="macro", zero_division=0))
    base_f1_b = float(f1_score(yt, pred_b, average="macro", zero_division=0))
    observed_diff = base_f1_a - base_f1_b

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

    return {
        "macro_f1_a": round(base_f1_a, 4),
        "macro_f1_b": round(base_f1_b, 4),
        "f1_difference": round(observed_diff, 4),
        "p_value": round(p_val, 5),
        "is_significant_p01": 1.0 if p_val < 0.01 else 0.0,
    }


def mcnemar_test(
    y_true: Sequence[int],
    pred_a: Sequence[int],
    pred_b: Sequence[int],
) -> dict[str, float]:
    """Compute McNemar's test with continuity correction for binary paired predictions.

    Formula:
        chi2 = (|b - c| - 1)^2 / (b + c)
        where b = count(A correct, B wrong), c = count(A wrong, B correct)
    """
    yt = np.array(y_true, dtype=int)
    pa = np.array(pred_a, dtype=int)
    pb = np.array(pred_b, dtype=int)

    correct_a = pa == yt
    correct_b = pb == yt

    # Contingency counts
    b = int(np.sum(correct_a & (~correct_b)))
    c = int(np.sum((~correct_a) & correct_b))

    denom = b + c
    if denom == 0:
        return {"b_only_a_correct": 0.0, "c_only_b_correct": 0.0, "chi2": 0.0, "p_value": 1.0}

    chi2 = float((abs(b - c) - 1.0) ** 2 / denom)
    # 1 degree of freedom survival function approximation
    p_val = float(math.erfc(math.sqrt(chi2) / math.sqrt(2.0)))

    return {
        "b_only_a_correct": float(b),
        "c_only_b_correct": float(c),
        "chi2": round(chi2, 4),
        "p_value": round(p_val, 5),
        "is_significant_p01": 1.0 if p_val < 0.01 else 0.0,
    }
