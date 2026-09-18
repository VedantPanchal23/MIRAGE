"""Longitudinal Hallucination Risk Score (HRS) drift detection and stability analysis engine."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from scipy.stats import ks_2samp


class DriftStatus(StrEnum):
    """Statistical drift classification based on Population Stability Index (PSI)."""

    STABLE = "stable"
    MODERATE_DRIFT = "moderate_drift"
    SIGNIFICANT_DRIFT = "significant_drift"


@dataclass
class DriftReport:
    """Comprehensive statistical drift report comparing baseline and current HRS distributions."""

    psi: float
    ks_statistic: float
    ks_pvalue: float
    status: DriftStatus
    alert_triggered: bool
    alert_reason: str | None
    baseline_sample_count: int
    current_sample_count: int
    baseline_mean_hrs: float
    current_mean_hrs: float
    rolling_7d_delta: float | None
    bin_proportions_baseline: list[float] = field(default_factory=list)
    bin_proportions_current: list[float] = field(default_factory=list)


def calculate_psi(
    baseline_samples: Sequence[float],
    current_samples: Sequence[float],
    num_bins: int = 10,
    epsilon: float = 1e-4,
) -> tuple[float, list[float], list[float]]:
    """Compute Population Stability Index (PSI) across uniform probability bins in [0.0, 1.0].

    Formula:
        PSI = sum((Actual_b - Expected_b) * ln((Actual_b + eps) / (Expected_b + eps)))

    Args:
        baseline_samples: Reference/calibration distribution (Expected).
        current_samples: Monitored target distribution (Actual).
        num_bins: Number of probability bins (default 10).
        epsilon: Smoothing constant preventing log(0) or division by zero.

    Returns:
        Tuple of (psi_value, baseline_proportions, current_proportions).
    """
    if not baseline_samples or not current_samples:
        return 0.0, [], []

    base_arr = np.clip(np.asarray(baseline_samples, dtype=float), 0.0, 1.0)
    curr_arr = np.clip(np.asarray(current_samples, dtype=float), 0.0, 1.0)

    # Define bins over [0.0, 1.0]
    bin_edges = np.linspace(0.0, 1.0, num_bins + 1)

    # Compute histogram frequencies
    base_counts, _ = np.histogram(base_arr, bins=bin_edges)
    curr_counts, _ = np.histogram(curr_arr, bins=bin_edges)

    # Convert to proportions (sums to 1.0)
    base_prop = (base_counts / len(base_arr)).tolist()
    curr_prop = (curr_counts / len(curr_arr)).tolist()

    psi_total = 0.0
    for b_prop, c_prop in zip(base_prop, curr_prop, strict=True):
        b_adj = b_prop + epsilon
        c_adj = c_prop + epsilon
        bin_psi = (c_prop - b_prop) * np.log(c_adj / b_adj)
        psi_total += float(bin_psi)

    return float(np.round(max(0.0, psi_total), 5)), base_prop, curr_prop


def calculate_ks_test(
    baseline_samples: Sequence[float],
    current_samples: Sequence[float],
) -> tuple[float, float]:
    """Perform two-sample Kolmogorov-Smirnov test to evaluate distributional shift.

    Returns:
        Tuple of (ks_statistic, p_value).
    """
    if len(baseline_samples) < 2 or len(current_samples) < 2:
        return 0.0, 1.0

    res = ks_2samp(baseline_samples, current_samples)
    return float(res.statistic), float(res.pvalue)


def check_rolling_spikes(
    prior_7d_samples: Sequence[float],
    current_7d_samples: Sequence[float],
    threshold_delta: float = 0.15,
    critical_rate_threshold: float = 0.05,
) -> tuple[bool, str | None, float]:
    """Check whether 7-day rolling metrics trigger operational alerts.

    Triggers alert if:
    1. 7-day average HRS increases by more than `threshold_delta` (0.15).
    2. Proportion of critical tier samples (HRS > 0.80) exceeds `critical_rate_threshold` (5%).

    Returns:
        Tuple of (alert_triggered, alert_reason, delta_mean).
    """
    if not current_7d_samples:
        return False, None, 0.0

    curr_arr = np.asarray(current_7d_samples, dtype=float)
    curr_mean = float(np.mean(curr_arr))

    # Check critical tier rate (HRS > 0.80)
    critical_count = np.sum(curr_arr > 0.80)
    critical_rate = float(critical_count / len(curr_arr))
    if critical_rate > critical_rate_threshold:
        return (
            True,
            f"Critical tier rate ({critical_rate:.1%}) exceeded threshold ({critical_rate_threshold:.1%})",
            0.0,
        )

    if not prior_7d_samples:
        return False, None, 0.0

    prior_arr = np.asarray(prior_7d_samples, dtype=float)
    prior_mean = float(np.mean(prior_arr))
    delta = float(curr_mean - prior_mean)

    if delta > threshold_delta:
        return (
            True,
            f"7-day average HRS increased by {delta:.3f} (exceeds alert threshold {threshold_delta})",
            delta,
        )

    return False, None, delta


def evaluate_distribution_drift(
    baseline_samples: Sequence[float],
    current_samples: Sequence[float],
    prior_7d_samples: Sequence[float] | None = None,
    current_7d_samples: Sequence[float] | None = None,
    psi_num_bins: int = 10,
) -> DriftReport:
    """Evaluate comprehensive drift between baseline reference and active production samples.

    Evaluates:
    - Population Stability Index (PSI):
      - PSI < 0.10: Stable
      - 0.10 <= PSI < 0.20: Moderate Drift
      - PSI >= 0.20: Significant Drift
    - Kolmogorov-Smirnov (KS) two-sample test (p-value significance)
    - 7-day rolling window shift and critical hallucination spike alerts
    """
    psi_val, base_prop, curr_prop = calculate_psi(
        baseline_samples=baseline_samples,
        current_samples=current_samples,
        num_bins=psi_num_bins,
    )

    ks_stat, ks_pval = calculate_ks_test(baseline_samples, current_samples)

    if psi_val < 0.10:
        status = DriftStatus.STABLE
    elif psi_val < 0.20:
        status = DriftStatus.MODERATE_DRIFT
    else:
        status = DriftStatus.SIGNIFICANT_DRIFT

    base_mean = float(np.mean(baseline_samples)) if baseline_samples else 0.0
    curr_mean = float(np.mean(current_samples)) if current_samples else 0.0

    # Evaluate rolling spikes
    alert = False
    alert_reason = None
    delta_7d: float | None = None

    if current_7d_samples is not None:
        alert, alert_reason, delta_7d = check_rolling_spikes(
            prior_7d_samples=prior_7d_samples or [],
            current_7d_samples=current_7d_samples,
        )

    if not alert and status == DriftStatus.SIGNIFICANT_DRIFT:
        alert = True
        alert_reason = f"Significant distributional drift detected (PSI={psi_val:.4f} >= 0.20, KS p={ks_pval:.4e})"

    return DriftReport(
        psi=psi_val,
        ks_statistic=ks_stat,
        ks_pvalue=ks_pval,
        status=status,
        alert_triggered=alert,
        alert_reason=alert_reason,
        baseline_sample_count=len(baseline_samples),
        current_sample_count=len(current_samples),
        baseline_mean_hrs=round(base_mean, 4),
        current_mean_hrs=round(curr_mean, 4),
        rolling_7d_delta=round(delta_7d, 4) if delta_7d is not None else None,
        bin_proportions_baseline=[round(p, 4) for p in base_prop],
        bin_proportions_current=[round(p, 4) for p in curr_prop],
    )


class LongitudinalDriftTracker:
    """Sliding-window collector managing multi-tenant drift tracking and historical aggregations."""

    def __init__(self, baseline_size: int = 500) -> None:
        self.baseline_size = baseline_size
        self._samples: dict[str, list[float]] = {}
        self._baseline: dict[str, list[float]] = {}

    def record_score(self, tenant_id: str, hrs: float) -> None:
        """Record a newly evaluated HRS score for a tenant."""
        if tenant_id not in self._samples:
            self._samples[tenant_id] = []
            self._baseline[tenant_id] = []

        # If baseline is not filled, populate baseline first
        if len(self._baseline[tenant_id]) < self.baseline_size:
            self._baseline[tenant_id].append(hrs)

        self._samples[tenant_id].append(hrs)
        if len(self._samples[tenant_id]) > 5000:
            self._samples[tenant_id] = self._samples[tenant_id][-5000:]

    def get_drift_report(self, tenant_id: str) -> DriftReport:
        """Generate real-time drift report for a tenant against baseline."""
        baseline = self._baseline.get(tenant_id, [])
        current = self._samples.get(tenant_id, [])

        if not baseline:
            # Synthetic default baseline if none accumulated yet
            baseline = [0.15, 0.20, 0.25, 0.18, 0.30]

        if not current:
            current = baseline

        # If more than 50 samples, use last 25 as current_7d and prior 25 as prior_7d
        n = len(current)
        if n >= 20:
            mid = n // 2
            prior_7d = current[:mid]
            curr_7d = current[mid:]
        else:
            prior_7d = None
            curr_7d = current

        return evaluate_distribution_drift(
            baseline_samples=baseline,
            current_samples=current,
            prior_7d_samples=prior_7d,
            current_7d_samples=curr_7d,
        )
