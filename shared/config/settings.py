"""Application configuration management using pydantic-settings (12-Factor App)."""

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EnvironmentType(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --------------------------------------------------------------------------
    # General & Security
    # --------------------------------------------------------------------------
    environment: EnvironmentType = Field(default=EnvironmentType.DEVELOPMENT)
    debug: bool = Field(default=True)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")
    secret_key: str = Field(
        default="dev-insecure-secret-key-change-in-production-min32chars",
        min_length=32,
        description="HMAC secret key for JWT signing and cryptohash verification",
    )
    algorithm: str = Field(default="HS256")
    access_token_expire_minutes: int = Field(default=1440)

    # --------------------------------------------------------------------------
    # PostgreSQL Database
    # --------------------------------------------------------------------------
    postgres_user: str = Field(default="mirage")
    postgres_password: str = Field(default="mirage_dev_secret")
    postgres_db: str = Field(default="mirage_db")
    postgres_host: str = Field(default="localhost")
    postgres_port: int = Field(default=5432)
    database_url: str = Field(
        default="postgresql+asyncpg://mirage:mirage_dev_secret@localhost:5432/mirage_db",
        description="Async SQLAlchemy database connection URL",
    )
    database_sync_url: str = Field(
        default="postgresql://mirage:mirage_dev_secret@localhost:5432/mirage_db",
        description="Sync database connection URL for Alembic migrations",
    )

    # --------------------------------------------------------------------------
    # MongoDB Document Store
    # --------------------------------------------------------------------------
    mongo_uri: str = Field(default="mongodb://root:mirage_mongo_secret@localhost:27017")
    mongo_db: str = Field(default="mirage_traces")
    mongo_retention_days: int = Field(default=90)

    # --------------------------------------------------------------------------
    # Redis Cache & Rate Limiting (P0.4)
    # --------------------------------------------------------------------------
    redis_host: str = Field(default="localhost")
    redis_port: int = Field(default=6379)
    redis_username: str = Field(default="")
    redis_password: str = Field(default="mirage_redis_secret")
    redis_url: str = Field(default="redis://:mirage_redis_secret@localhost:6379/0")
    redis_max_connections: int = Field(default=50)
    redis_socket_timeout: float = Field(default=2.0)
    redis_socket_connect_timeout: float = Field(default=2.0)
    redis_rate_limit_fail_closed: bool = Field(default=True)

    # --------------------------------------------------------------------------
    # RabbitMQ & Celery (P0.5)
    # --------------------------------------------------------------------------
    rabbitmq_host: str = Field(default="localhost")
    rabbitmq_port: int = Field(default=5672)
    rabbitmq_user: str = Field(default="mirage")
    rabbitmq_password: str = Field(default="mirage_rabbit_secret")
    rabbitmq_vhost: str = Field(default="/")
    celery_broker_url: str = Field(default="amqp://mirage:mirage_rabbit_secret@localhost:5672//")
    celery_result_backend: str = Field(default="redis://mirage_celery:mirage_celery_secret@localhost:6379/1")
    celery_redis_username: str = Field(default="mirage_celery")
    celery_redis_password: str = Field(default="mirage_celery_secret")

    @field_validator("celery_broker_url")
    @classmethod
    def validate_broker_tls(cls, v: str, info: ValidationInfo) -> str:
        """Enforce AMQPS (TLS 1.2+) in production per Security_Access.md §4.1 and ADR 0003."""
        env = info.data.get("environment")
        if env == EnvironmentType.PRODUCTION and not v.startswith("amqps://"):
            raise ValueError(
                "Production security policy violation: CELERY_BROKER_URL must use AMQPS (TLS 1.2+) "
                f"in production mode. Plaintext amqp:// is strictly prohibited. Received: {v[:8]}***"
            )
        return v

    # --------------------------------------------------------------------------
    # Qdrant Vector Database
    # --------------------------------------------------------------------------
    qdrant_host: str = Field(default="localhost")
    qdrant_port: int = Field(default=6333)
    qdrant_api_key: str | None = Field(default=None)

    # --------------------------------------------------------------------------
    # OpenTelemetry Tracing
    # --------------------------------------------------------------------------
    otel_exporter_otlp_endpoint: str = Field(default="http://localhost:4317")
    otel_service_name: str = Field(default="mirage-gateway")

    # --------------------------------------------------------------------------
    # External LLM Providers (Zero-cost free tiers)
    # --------------------------------------------------------------------------
    groq_api_key: str = Field(default="")
    openrouter_api_key: str = Field(default="")
    huggingface_api_key: str = Field(default="")
    llm_upstream_url: str = Field(default="https://api.groq.com/openai/v1")

    # --------------------------------------------------------------------------
    # Model Thresholds & Parameters
    # --------------------------------------------------------------------------
    default_primary_model: str = Field(default="allam-2-7b")
    scs_sample_count: int = Field(default=5, ge=1, le=10)
    scs_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    clip_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    hrs_correction_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    max_correction_retries: int = Field(default=2, ge=1, le=5)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
