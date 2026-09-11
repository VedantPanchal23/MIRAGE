"""Rate limiting middleware with in-memory sliding window and Redis support."""

import time
from collections import defaultdict

from fastapi import HTTPException, status

from shared.logging import get_logger

logger = get_logger("rate_limiter")


class SlidingWindowRateLimiter:
    """Sliding-window rate limiter tracking requests per tenant."""

    def __init__(self, limit_per_minute: int = 60) -> None:
        self.limit_per_minute = limit_per_minute
        self.requests: dict[str, list[float]] = defaultdict(list)

    def check_rate_limit(self, tenant_id: str) -> None:
        now = time.time()
        window_start = now - 60.0

        # Purge timestamps outside the 1-minute window
        self.requests[tenant_id] = [t for t in self.requests[tenant_id] if t > window_start]

        if len(self.requests[tenant_id]) >= self.limit_per_minute:
            logger.warning("Rate limit exceeded for tenant", tenant_id=tenant_id)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Maximum 60 requests per minute allowed.",
                headers={"Retry-After": "60"},
            )

        self.requests[tenant_id].append(now)


rate_limiter = SlidingWindowRateLimiter(limit_per_minute=60)
