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
    jwt_issuer: str = Field(default="mirage-control-plane")
    jwt_audience: str = Field(default="mirage-gateway")
    demo_auth_enabled: bool = Field(default=False)
    notary_keys_json: str | None = Field(
        default=None,
        description="JSON-serialized mapping of signer_identity to notary secret key for NotaryKeyRegistry",
    )
    allow_dev_notary_keys: bool | None = Field(
        default=None,
        description="Allow default dev notary key in non-production environments",
    )

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

    @field_validator("secret_key")
    @classmethod
    def validate_signing_secret(cls, v: str, info: ValidationInfo) -> str:
        """Reject known development signing material in production."""
        env = info.data.get("environment")
        if env == EnvironmentType.PRODUCTION and (
            v == "dev-insecure-secret-key-change-in-production-min32chars" or len(v) < 48
        ):
            raise ValueError("Production requires a unique JWT signing secret of at least 48 characters")
        return v

    @field_validator("demo_auth_enabled")
    @classmethod
    def reject_demo_auth_in_production(cls, v: bool, info: ValidationInfo) -> bool:
        """Prevent a demonstration issuer from being enabled in production."""
        if v and info.data.get("environment") == EnvironmentType.PRODUCTION:
            raise ValueError("DEMO_AUTH_ENABLED is prohibited in production")
        return v

    @field_validator("notary_keys_json")
    @classmethod
    def validate_notary_keys_json_format(cls, v: str | None, _info: ValidationInfo) -> str | None:
        """Validate notary keys JSON formatting and contents."""
        if v is None or not v.strip():
            return None
        import json

        try:
            parsed = json.loads(v)
        except Exception as exc:
            raise ValueError(f"Invalid NOTARY_KEYS_JSON format: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("NOTARY_KEYS_JSON must be a JSON object mapping signer_identity to secret key")
        for signer, key in parsed.items():
            if not isinstance(signer, str) or not signer.strip():
                raise ValueError("Signer identity in NOTARY_KEYS_JSON must be a non-empty string")
            if not isinstance(key, str) or len(key.strip()) < 32:
                raise ValueError(
                    f"Notary key for '{signer}' in NOTARY_KEYS_JSON must be at least 32 characters (256 bits)"
                )
        return v

    @field_validator("allow_dev_notary_keys")
    @classmethod
    def reject_dev_notary_keys_in_production(cls, v: bool | None, info: ValidationInfo) -> bool:
        """Prevent default development notary keys in production mode."""
        env = info.data.get("environment")
        if env == EnvironmentType.PRODUCTION:
            if v is True:
                raise ValueError("ALLOW_DEV_NOTARY_KEYS is prohibited in production")
            return False
        return True if v is None else v

    # --------------------------------------------------------------------------
    # Qdrant Vector Database
    # --------------------------------------------------------------------------
    qdrant_host: str = Field(default="localhost")
    qdrant_port: int = Field(default=6333)
    qdrant_api_key: str | None = Field(default=None)
    qdrant_https: bool = Field(default=False)

    # --------------------------------------------------------------------------
    # OpenTelemetry Tracing
    # --------------------------------------------------------------------------
    otel_exporter_otlp_endpoint: str = Field(default="http://localhost:4317")
    otel_service_name: str = Field(default="mirage-gateway")

    # --------------------------------------------------------------------------
    # External LLM Providers (Zero-cost free tiers & Enterprise endpoints)
    # --------------------------------------------------------------------------
    groq_api_key: str = Field(default="")
    openrouter_api_key: str = Field(default="")
    huggingface_api_key: str = Field(default="")
    llm_upstream_url: str = Field(default="https://api.groq.com/openai/v1")
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    anthropic_api_key: str = Field(default="")
    anthropic_base_url: str = Field(default="https://api.anthropic.com/v1")
    gemini_api_key: str = Field(default="")
    gemini_base_url: str = Field(default="https://generativelanguage.googleapis.com/v1beta")
    ollama_base_url: str = Field(default="http://localhost:11434")
    allow_mock_providers: bool | None = Field(default=None)

    @field_validator("allow_mock_providers")
    @classmethod
    def reject_mock_providers_in_production(cls, v: bool | None, info: ValidationInfo) -> bool:
        """Forbid mock providers in production environment; default to False in prod, True in dev/test."""
        env = info.data.get("environment")
        if env == EnvironmentType.PRODUCTION:
            if v is True:
                raise ValueError("ALLOW_MOCK_PROVIDERS is strictly prohibited in production mode")
            return False
        return True if v is None else v


    # --------------------------------------------------------------------------
    # Circuit Breaker & Routing Egress Controls
    # --------------------------------------------------------------------------
    circuit_breaker_fail_closed_on_redis: bool = Field(
        default=False,
        description="Fail closed when Redis is unreachable for distributed circuit breaker",
    )
    local_inference_allowlist: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"],
        description="Allowlisted hosts for local inference (Ollama)",
    )

    @field_validator("circuit_breaker_fail_closed_on_redis")
    @classmethod
    def enforce_circuit_breaker_fail_closed_in_production(cls, v: bool, info: ValidationInfo) -> bool:
        """In production, distributed circuit breaker must fail closed if Redis is unreachable."""
        env = info.data.get("environment")
        if env == EnvironmentType.PRODUCTION and not v:
            return True
        return v

    # --------------------------------------------------------------------------
    # Model Thresholds & Parameters
    # --------------------------------------------------------------------------
    default_primary_model: str = Field(default="allam-2-7b")
    scs_sample_count: int = Field(default=5, ge=1, le=10)
    scs_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    clip_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    hrs_correction_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    max_correction_retries: int = Field(default=2, ge=1, le=5)

    # --------------------------------------------------------------------------
    # Object Storage Configuration (ADR 0005)
    # --------------------------------------------------------------------------
    storage_driver: str = Field(default="local")  # "local" or "s3"
    storage_local_root: str = Field(default="tmp/storage")
    s3_bucket_name: str = Field(default="mirage-audit")
    s3_endpoint_url: str | None = Field(default=None)
    s3_region_name: str = Field(default="us-east-1")
    aws_access_key_id: str | None = Field(default=None)
    aws_secret_access_key: str | None = Field(default=None)


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
