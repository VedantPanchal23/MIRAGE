"""Distributed rate limiting middleware using atomic Redis Token Bucket.

Adheres to:
- Security_Access.md §1.3 (Threat T-06), §7.2, §9.1
- Technical_Architecture.md §7.4, §8.2 (SERVICE_DEGRADED)
- ADR 0002: Atomic Token Bucket with Redis Server Time

Tier boundaries:
- Free tier: 60 req/min (refill: 1.0 tokens/sec)
- Pro tier: 300 req/min (refill: 5.0 tokens/sec)
- Enterprise tier: 1000 req/min (refill: 16.6667 tokens/sec)
"""

from fastapi import HTTPException, status

from db.redis import (
    RateLimitExceededError,
    RedisConnectionError,
    RedisOperationTimeoutError,
    RedisServiceError,
    TokenBucketRateLimiter,
    TokenBucketResult,
    default_token_bucket_rate_limiter,
)
from shared.logging import get_logger

logger = get_logger("rate_limiter")


class AsyncRateLimiter:
    """Production rate limiter backed exclusively by Redis atomic token bucket."""

    def __init__(self, backend: TokenBucketRateLimiter | None = None) -> None:
        self.backend = backend or default_token_bucket_rate_limiter

    async def check_rate_limit(
        self,
        tenant_id: str,
        tier: str = "free",
        cost: int = 1,
        scope: str = "verify",
    ) -> TokenBucketResult:
        """Evaluate rate limit atomically against Redis server clock.

        Raises:
            HTTPException(429): If capacity is exhausted, returning standard headers:
                - X-RateLimit-Limit
                - X-RateLimit-Remaining
                - X-RateLimit-Reset
                - Retry-After
            HTTPException(503): If Redis is unavailable, failing closed (SERVICE_DEGRADED).
        """
        try:
            res = await self.backend.check_rate_limit(
                tenant_id=tenant_id,
                tier=tier,
                cost=cost,
                scope=scope,
            )
            return res
        except RateLimitExceededError as rle:
            headers = {
                "X-RateLimit-Limit": str(rle.limit),
                "X-RateLimit-Remaining": str(rle.remaining),
                "X-RateLimit-Reset": str(rle.reset_time),
                "Retry-After": str(rle.retry_after),
            }
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(rle),
                headers=headers,
            ) from rle
        except (RedisConnectionError, RedisOperationTimeoutError) as redis_err:
            logger.error(
                "Redis rate limiting service unreachable; failing closed for security",
                tenant_id=tenant_id,
                error=str(redis_err),
            )
            raise
        except RedisServiceError as srv_err:
            logger.error(
                "Redis rate limiting service error",
                tenant_id=tenant_id,
                error=str(srv_err),
            )
            raise


# Global production singleton backed by Redis
rate_limiter = AsyncRateLimiter()
