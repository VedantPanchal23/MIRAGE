"""In-memory and persistent session store supporting dashboard queries, analytics, and drift tracking."""

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from analytics.drift import LongitudinalDriftTracker


@dataclass
class SessionRecord:
    """Stored representation of a completed verification session for dashboard analytics."""

    session_id: str
    tenant_id: str
    trace_id: str
    model_id: str
    prompt_hash: str
    response_hash: str
    hrs_score: float
    risk_tier: str
    ci_lower: float
    ci_upper: float
    correction_applied: bool
    claims_count: int
    contradicted_count: int
    created_at: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    signal_attribution: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert session record to JSON-serializable dictionary."""
        return asdict(self)


class SessionStore:
    """Central store for verification sessions and longitudinal drift analytics."""

    def __init__(self, drift_tracker: LongitudinalDriftTracker | None = None) -> None:
        self.sessions: list[SessionRecord] = []
        self.drift_tracker = drift_tracker or LongitudinalDriftTracker()

    def record_session(
        self,
        session_id: str,
        tenant_id: str,
        trace_id: str,
        model_id: str,
        prompt: str,
        response: str,
        hrs_score: float,
        risk_tier: str,
        ci_lower: float,
        ci_upper: float,
        correction_applied: bool,
        claims_count: int,
        contradicted_count: int,
        claims: list[dict[str, Any]] | None = None,
        signal_attribution: dict[str, float] | None = None,
        timestamp: datetime | None = None,
    ) -> SessionRecord:
        """Record and index a newly verified session."""
        created_dt = timestamp or datetime.now(UTC)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        response_hash = hashlib.sha256(response.encode("utf-8")).hexdigest()

        record = SessionRecord(
            session_id=session_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            model_id=model_id,
            prompt_hash=prompt_hash,
            response_hash=response_hash,
            hrs_score=hrs_score,
            risk_tier=risk_tier,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            correction_applied=correction_applied,
            claims_count=claims_count,
            contradicted_count=contradicted_count,
            created_at=created_dt.isoformat(),
            claims=claims or [],
            signal_attribution=signal_attribution or {},
        )

        self.sessions.append(record)
        self.drift_tracker.record_score(tenant_id, hrs_score)
        return record

    def list_sessions(
        self,
        tenant_id: str | None = None,
        risk_tier: str | None = None,
        min_hrs: float | None = None,
        max_hrs: float | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Query and paginate sessions with optional tenant and risk filters."""
        filtered = self.sessions

        if tenant_id:
            filtered = [s for s in filtered if s.tenant_id == tenant_id]
        if risk_tier:
            filtered = [s for s in filtered if s.risk_tier.upper() == risk_tier.upper()]
        if min_hrs is not None:
            filtered = [s for s in filtered if s.hrs_score >= min_hrs]
        if max_hrs is not None:
            filtered = [s for s in filtered if s.hrs_score <= max_hrs]

        total = len(filtered)
        start_idx = max(0, (page - 1) * page_size)
        end_idx = start_idx + page_size
        items = [s.to_dict() for s in reversed(filtered[start_idx:end_idx])]
        return total, items

    def get_stats(self, tenant_id: str | None = None) -> dict[str, Any]:
        """Aggregate summary metrics for the executive dashboard."""
        records = self.sessions
        if tenant_id:
            records = [s for s in records if s.tenant_id == tenant_id]

        total_requests = len(records)
        if total_requests == 0:
            return {
                "total_requests": 0,
                "average_hrs": 0.0,
                "tier_counts": {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0},
                "correction_rate": 0.0,
                "contradiction_rate": 0.0,
                "drift_report": asdict(self.drift_tracker.get_drift_report(tenant_id or "default")),
            }

        avg_hrs = float(sum(s.hrs_score for s in records) / total_requests)
        corrections = sum(1 for s in records if s.correction_applied)
        contradictions = sum(1 for s in records if s.contradicted_count > 0)

        tier_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        for s in records:
            tier_key = s.risk_tier.upper()
            if tier_key in tier_counts:
                tier_counts[tier_key] += 1
            else:
                tier_counts[tier_key] = 1

        drift_rep = self.drift_tracker.get_drift_report(tenant_id or "default")

        return {
            "total_requests": total_requests,
            "average_hrs": round(avg_hrs, 4),
            "tier_counts": tier_counts,
            "correction_rate": round(corrections / total_requests, 4),
            "contradiction_rate": round(contradictions / total_requests, 4),
            "drift_report": asdict(drift_rep),
        }

    def get_time_series(self, tenant_id: str, days: int = 30) -> list[dict[str, Any]]:
        """Compute daily time series aggregates for longitudinal charts."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        records = [
            s for s in self.sessions if s.tenant_id == tenant_id and datetime.fromisoformat(s.created_at) >= cutoff
        ]

        # Group by day YYYY-MM-DD
        daily_groups: dict[str, list[SessionRecord]] = {}
        for s in records:
            day_key = s.created_at[:10]
            if day_key not in daily_groups:
                daily_groups[day_key] = []
            daily_groups[day_key].append(s)

        time_series: list[dict[str, Any]] = []
        for day_str in sorted(daily_groups.keys()):
            group = daily_groups[day_str]
            avg_h = sum(x.hrs_score for x in group) / len(group)
            crit_count = sum(1 for x in group if x.risk_tier.upper() == "CRITICAL")
            time_series.append(
                {
                    "date": day_str,
                    "request_count": len(group),
                    "average_hrs": round(avg_h, 4),
                    "critical_count": crit_count,
                }
            )

        return time_series


# Global singleton instance for gateway and workers
default_session_store = SessionStore()
