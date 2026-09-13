"""Rate limiting middleware with tiered sliding window tracking.

Implements Security & Access Document §7.2:
- Free tier: 60 req/min
- Pro tier: 300 req/min
- Enterprise tier: 1000 req/min
"""

import time
from collections import defaultdict

from fastapi import HTTPException, status

from shared.logging import get_logger

logger = get_logger("rate_limiter")

TIER_LIMITS: dict[str, int] = {
    "free": 60,
    "pro": 300,
    "enterprise": 1000,
}


class SlidingWindowRateLimiter:
    """Sliding-window rate limiter tracking requests per tenant with tier sensitivity."""

    def __init__(self, default_limit: int = 60, limit_per_minute: int | None = None) -> None:
        self.default_limit = default_limit
        self.limit_per_minute = limit_per_minute
        self.requests: dict[str, list[float]] = defaultdict(list)

    def check_rate_limit(self, tenant_id: str, tier: str = "free") -> None:
        now = time.time()
        window_start = now - 60.0

        # Purge timestamps outside the 1-minute window
        self.requests[tenant_id] = [t for t in self.requests[tenant_id] if t > window_start]

        if self.limit_per_minute is not None:
            limit = self.limit_per_minute
        else:
            limit = TIER_LIMITS.get(tier.lower(), self.default_limit)

        if len(self.requests[tenant_id]) >= limit:
            logger.warning("Rate limit exceeded for tenant", tenant_id=tenant_id, tier=tier, limit=limit)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for {tier} tier. Maximum {limit} requests per minute allowed.",
                headers={"Retry-After": "60"},
            )

        self.requests[tenant_id].append(now)


rate_limiter = SlidingWindowRateLimiter(default_limit=60)
