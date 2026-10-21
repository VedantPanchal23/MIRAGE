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


def is_insecure_placeholder(val: str | None) -> bool:
    """Check if value is empty, a known development default, or an unfilled placeholder."""
    if val is None or not str(val).strip():
        return True
    low = str(val).strip().lower()
    return (
        low.startswith("replace_with_")
        or low.startswith("your_")
        or "placeholder" in low
        or "changeme" in low
        or "example" in low
        or "min32chars" in low
        or "mirage_dev_secret" in low
        or "mirage_redis_secret" in low
        or "mirage_rabbit_secret" in low
        or "mirage_celery_secret" in low
        or "mirage_mongo_secret" in low
        or "mirage_qdrant_secret" in low
        or "mirage_grafana_secret" in low
    )


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
    cors_allowed_origins: list[str] = Field(
        default_factory=list,
        description="Explicit allowed CORS origins. If empty, falls back to environment defaults",
    )
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
    audit_anchor_dir: str = Field(
        default="data/audit_anchors",
        description="Filesystem directory for immutable external audit anchor storage",
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
    database_sync_url: str | None = Field(
        default=None,
        description="Sync database connection URL for Alembic migrations and CLI utilities (optional for runtime)",
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
    # Privacy Attestation & Notary Trust Anchor Configuration
    # --------------------------------------------------------------------------
    trusted_privacy_notary_public_keys: dict[str, str] = Field(
        default_factory=dict,
        description="Map of trusted notary issuer IDs to hex-encoded Ed25519 public keys",
    )

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

    def validate_production_configuration(self) -> list[str]:
        """Validate settings against production security hardening requirements.

        Returns a list of violation messages (empty list if configuration is compliant).
        Fails closed on any insecure development defaults or missing security credentials.
        """
        defects: list[str] = []

        if self.environment != EnvironmentType.PRODUCTION:
            return defects

        # 1. JWT & HMAC Secret Hardening
        if (
            self.secret_key == "dev-insecure-secret-key-change-in-production-min32chars"
            or is_insecure_placeholder(self.secret_key)
        ):
            defects.append("SECRET_KEY is using the default insecure development secret or unfilled placeholder")
        elif len(self.secret_key) < 48:
            defects.append(
                f"SECRET_KEY length ({len(self.secret_key)}) is less than 48 characters required for production"
            )

        # 2. Celery & RabbitMQ TLS Enforcement
        if not self.celery_broker_url.startswith("amqps://"):
            defects.append("CELERY_BROKER_URL must use AMQPS (TLS 1.2+) in production")

        # 3. Notary Keys for External Anchoring
        if not self.notary_keys_json or not self.notary_keys_json.strip():
            defects.append("NOTARY_KEYS_JSON must be configured with authorized notary signing keys in production")
        if self.allow_dev_notary_keys is True:
            defects.append("ALLOW_DEV_NOTARY_KEYS is strictly prohibited in production")

        # 4. Authentication & Mock Providers
        if self.demo_auth_enabled:
            defects.append("DEMO_AUTH_ENABLED is strictly prohibited in production")
        if self.allow_mock_providers is True:
            defects.append("ALLOW_MOCK_PROVIDERS is strictly prohibited in production")

        # 5. Database Credentials Hardening
        db_sync_insecure = (
            self.database_sync_url
            and ("mirage_dev_secret" in self.database_sync_url or is_insecure_placeholder(self.database_sync_url))
        )
        if "mirage_dev_secret" in self.database_url or is_insecure_placeholder(self.database_url) or db_sync_insecure:
            defects.append(
                "DATABASE_URL / DATABASE_SYNC_URL contains default development password "
                "'mirage_dev_secret' or placeholder"
            )

        # 6. Redis Credentials Hardening
        redis_insecure = (
            "mirage_redis_secret" in self.redis_url
            or self.redis_password == "mirage_redis_secret"
            or is_insecure_placeholder(self.redis_password)
        )
        if redis_insecure:
            defects.append(
                "REDIS_URL / REDIS_PASSWORD contains default development password 'mirage_redis_secret' or placeholder"
            )

        # 7. Provider Configuration Validation (if configured, must not be placeholder)
        for prov_name, key_val in [
            ("groq", self.groq_api_key),
            ("openrouter", self.openrouter_api_key),
            ("huggingface", self.huggingface_api_key),
            ("openai", self.openai_api_key),
            ("anthropic", self.anthropic_api_key),
            ("gemini", self.gemini_api_key),
        ]:
            if key_val and is_insecure_placeholder(key_val):
                defects.append(f"{prov_name.upper()}_API_KEY contains an unfilled placeholder value")

        return defects

        return defects

    def validate_staging_configuration(self) -> list[str]:
        """Validate settings against AWS private staging security requirements.

        Fails closed on default development secrets, unconfigured security settings,
        unfilled placeholders (REPLACE_WITH_*), or insecure fallback credentials.
        """
        defects: list[str] = []

        if self.environment != EnvironmentType.STAGING:
            return defects

        # 1. JWT & HMAC Secret Hardening (staging requires at least 32 characters, no dev default or placeholder)
        if (
            self.secret_key == "dev-insecure-secret-key-change-in-production-min32chars"
            or is_insecure_placeholder(self.secret_key)
        ):
            defects.append("SECRET_KEY is using the default insecure development secret or unfilled placeholder")
        elif len(self.secret_key) < 32:
            defects.append(
                f"SECRET_KEY length ({len(self.secret_key)}) is less than 32 characters required for staging"
            )

        # 2. Authentication & Mock Providers
        if self.demo_auth_enabled:
            defects.append("DEMO_AUTH_ENABLED is strictly prohibited in staging")
        if self.allow_mock_providers is True:
            defects.append("ALLOW_MOCK_PROVIDERS is strictly prohibited in staging mode")

        # 3. Debugging Mode
        if self.debug:
            defects.append("DEBUG mode must be set to false in staging")

        # 4. Database Credentials Hardening
        if is_insecure_placeholder(self.database_url) or "mirage_dev_secret" in self.database_url:
            defects.append(
                "DATABASE_URL / DATABASE_SYNC_URL contains default development password "
                "'mirage_dev_secret' or placeholder"
            )
        if self.database_sync_url and (
            is_insecure_placeholder(self.database_sync_url) or "mirage_dev_secret" in self.database_sync_url
        ):
            defects.append(
                "DATABASE_URL / DATABASE_SYNC_URL contains default development password "
                "'mirage_dev_secret' or placeholder"
            )

        # 5. Redis Credentials Hardening
        if is_insecure_placeholder(self.redis_password) or "mirage_redis_secret" in self.redis_url:
            defects.append(
                "REDIS_URL / REDIS_PASSWORD contains default development password 'mirage_redis_secret' or placeholder"
            )

        # 6. Broker & Message Queue Hardening
        if is_insecure_placeholder(self.rabbitmq_password) or "mirage_rabbit_secret" in self.celery_broker_url:
            defects.append(
                "CELERY_BROKER_URL / RABBITMQ_PASSWORD contains default password 'mirage_rabbit_secret' or placeholder"
            )
        if (
            is_insecure_placeholder(self.celery_redis_password)
            or "mirage_celery_secret" in self.celery_result_backend
        ):
            defects.append(
                "CELERY_RESULT_BACKEND / CELERY_REDIS_PASSWORD contains default password "
                "'mirage_celery_secret' or placeholder"
            )

        # 7. Document & Vector Store Hardening
        if is_insecure_placeholder(self.mongo_uri) or "mirage_mongo_secret" in self.mongo_uri:
            defects.append("MONGO_URI contains default development password 'mirage_mongo_secret' or placeholder")
        if is_insecure_placeholder(self.qdrant_api_key) or self.qdrant_api_key == "mirage_qdrant_secret":
            defects.append("QDRANT_API_KEY contains default development key 'mirage_qdrant_secret' or placeholder")

        # 8. Provider Configuration Validation
        for prov_name, key_val in [
            ("groq", self.groq_api_key),
            ("openrouter", self.openrouter_api_key),
            ("huggingface", self.huggingface_api_key),
            ("openai", self.openai_api_key),
            ("anthropic", self.anthropic_api_key),
            ("gemini", self.gemini_api_key),
        ]:
            if key_val and is_insecure_placeholder(key_val):
                defects.append(f"{prov_name.upper()}_API_KEY contains an unfilled placeholder value")

        return defects

    def validate_environment_configuration(self) -> list[str]:
        """Validate configuration based on active environment (staging, production)."""
        if self.environment == EnvironmentType.PRODUCTION:
            return self.validate_production_configuration()
        elif self.environment == EnvironmentType.STAGING:
            return self.validate_staging_configuration()
        return []

    def get_configured_providers(self) -> dict[str, bool]:
        """Return mapping of supported LLM provider names to whether their API key is configured.

        Security Invariant: Never reveals, formats, or logs secret key values.
        """
        return {
            "groq": bool(
                self.groq_api_key
                and self.groq_api_key.strip()
                and not self.groq_api_key.startswith("your_")
                and self.groq_api_key != "mock-groq-key"
            ),
            "openrouter": bool(
                self.openrouter_api_key
                and self.openrouter_api_key.strip()
                and not self.openrouter_api_key.startswith("your_")
            ),
            "huggingface": bool(
                self.huggingface_api_key
                and self.huggingface_api_key.strip()
                and not self.huggingface_api_key.startswith("your_")
            ),
            "openai": bool(
                self.openai_api_key
                and self.openai_api_key.strip()
                and not self.openai_api_key.startswith("your_")
            ),
            "anthropic": bool(
                self.anthropic_api_key
                and self.anthropic_api_key.strip()
                and not self.anthropic_api_key.startswith("your_")
            ),
            "gemini": bool(
                self.gemini_api_key
                and self.gemini_api_key.strip()
                and not self.gemini_api_key.startswith("your_")
            ),
            "ollama": bool(
                self.ollama_base_url
                and self.ollama_base_url.strip()
            ),
        }


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
