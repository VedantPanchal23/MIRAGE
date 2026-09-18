"""Database models, persistence services, and session exports."""

from db.models import AuditLogRecord, ClaimRecord, Tenant, VerificationSession
from db.mongo import (
    MongoPersistenceError,
    MongoTraceService,
    default_mongo_trace_service,
    reset_default_mongo_service,
)
from db.persistence import (
    AmbiguousPostgresCommitError,
    DatabasePersistenceError,
    DefinitivePostgresPersistenceError,
    PostgresPersistenceService,
    default_persistence_service,
)
from db.redis import (
    RateLimitExceededError,
    RedisCacheService,
    RedisClientManager,
    RedisConnectionError,
    RedisOperationTimeoutError,
    RedisServiceError,
    TokenBucketRateLimiter,
    TokenBucketResult,
    default_redis_cache_service,
    default_redis_client_manager,
    default_token_bucket_rate_limiter,
    reset_default_redis_client,
)
from db.session import (
    AsyncSessionLocal,
    Base,
    create_app_engine,
    engine,
    get_db_session,
    get_tenant_session,
    reset_sessionmaker,
)

__all__ = [
    "AmbiguousPostgresCommitError",
    "AsyncSessionLocal",
    "AuditLogRecord",
    "Base",
    "ClaimRecord",
    "DatabasePersistenceError",
    "DefinitivePostgresPersistenceError",
    "MongoPersistenceError",
    "MongoTraceService",
    "PostgresPersistenceService",
    "RateLimitExceededError",
    "RedisCacheService",
    "RedisClientManager",
    "RedisConnectionError",
    "RedisOperationTimeoutError",
    "RedisServiceError",
    "Tenant",
    "TokenBucketRateLimiter",
    "TokenBucketResult",
    "VerificationSession",
    "create_app_engine",
    "default_mongo_trace_service",
    "default_persistence_service",
    "default_redis_cache_service",
    "default_redis_client_manager",
    "default_token_bucket_rate_limiter",
    "engine",
    "get_db_session",
    "get_tenant_session",
    "reset_default_mongo_service",
    "reset_default_redis_client",
    "reset_sessionmaker",
]
