"""Security and validation test suite for AWS Private Staging Configuration.

Validates:
1. Staging configuration validation and fail-closed security rules on Settings.
2. Unified environment configuration validation across environments.
3. Secure LLM provider key handling and provider status reporting.
4. OpenRouter and HuggingFace adapter resolution via ProviderFactory.
5. Custom CORS origins support in Gateway configuration.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from gateway.main import create_app
from services.providers.factory import ProviderConfigurationError, get_provider_adapter
from shared.config.settings import EnvironmentType, Settings


class TestStagingConfigurationHardening:
    """Validate Settings fail-closed enforcement under EnvironmentType.STAGING."""

    def test_default_dev_secret_rejected_in_staging(self) -> None:
        """In staging, default insecure secret key must be flagged as a defect."""
        s = Settings(
            environment=EnvironmentType.STAGING,
            debug=False,
            secret_key="dev-insecure-secret-key-change-in-production-min32chars",
        )
        defects = s.validate_staging_configuration()
        assert any("SECRET_KEY is using the default insecure development secret" in d for d in defects)

    def test_short_secret_key_rejected_in_staging(self) -> None:
        """Staging SECRET_KEY must be at least 32 characters (Pydantic ValidationError)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(
                environment=EnvironmentType.STAGING,
                debug=False,
                secret_key="short_key_16_ch",
            )

    def test_debug_mode_rejected_in_staging(self) -> None:
        """Staging must not have DEBUG=True."""
        s = Settings(
            environment=EnvironmentType.STAGING,
            debug=True,
            secret_key="a" * 32,
        )
        defects = s.validate_staging_configuration()
        assert any("DEBUG mode must be set to false in staging" in d for d in defects)

    def test_demo_auth_rejected_in_staging(self) -> None:
        """DEMO_AUTH_ENABLED is strictly prohibited in staging."""
        s = Settings(
            environment=EnvironmentType.STAGING,
            debug=False,
            secret_key="a" * 32,
            demo_auth_enabled=True,
        )
        defects = s.validate_staging_configuration()
        assert any("DEMO_AUTH_ENABLED is strictly prohibited in staging" in d for d in defects)

    def test_mock_providers_rejected_in_staging(self) -> None:
        """ALLOW_MOCK_PROVIDERS is strictly prohibited in staging."""
        s = Settings(
            environment=EnvironmentType.STAGING,
            debug=False,
            secret_key="a" * 32,
            allow_mock_providers=True,
        )
        defects = s.validate_staging_configuration()
        assert any("ALLOW_MOCK_PROVIDERS is strictly prohibited in staging" in d for d in defects)

    def test_default_passwords_rejected_in_staging(self) -> None:
        """All default dev passwords in DB, Redis, RabbitMQ, Mongo, Qdrant must be flagged."""
        s = Settings(
            environment=EnvironmentType.STAGING,
            debug=False,
            secret_key="a" * 32,
            demo_auth_enabled=False,
            allow_mock_providers=False,
            database_url="postgresql+asyncpg://mirage:mirage_dev_secret@staging-db:5432/mirage_db",
            redis_url="redis://:mirage_redis_secret@staging-redis:6379/0",
            celery_broker_url="amqp://mirage:mirage_rabbit_secret@staging-mq:5672//",
            celery_result_backend="redis://:mirage_celery_secret@staging-redis:6379/1",
            mongo_uri="mongodb://root:mirage_mongo_secret@staging-mongo:27017",
            qdrant_api_key="mirage_qdrant_secret",
        )
        defects = s.validate_staging_configuration()
        assert any("DATABASE_URL" in d and "mirage_dev_secret" in d for d in defects)
        assert any("REDIS_URL" in d and "mirage_redis_secret" in d for d in defects)
        assert any("CELERY_BROKER_URL" in d and "mirage_rabbit_secret" in d for d in defects)
        assert any("CELERY_RESULT_BACKEND" in d and "mirage_celery_secret" in d for d in defects)
        assert any("MONGO_URI" in d and "mirage_mongo_secret" in d for d in defects)
        assert any("QDRANT_API_KEY" in d and "mirage_qdrant_secret" in d for d in defects)

    def test_fully_hardened_staging_configuration_passes(self) -> None:
        """A properly configured staging environment produces zero configuration defects."""
        s = Settings(
            environment=EnvironmentType.STAGING,
            debug=False,
            secret_key="staging-strong-secret-key-at-least-32-chars",
            demo_auth_enabled=False,
            allow_mock_providers=False,
            postgres_password="strong_staging_db_password_987",
            database_url="postgresql+asyncpg://mirage_app:strong_staging_db_password_987@staging-db:5432/mirage_db",
            database_sync_url="postgresql://mirage:strong_staging_db_password_987@staging-db:5432/mirage_db",
            redis_password="strong_staging_redis_password_987",
            redis_url="redis://mirage_app:strong_staging_redis_password_987@staging-redis:6379/0",
            rabbitmq_password="strong_staging_rabbit_password_987",
            celery_broker_url="amqp://mirage:strong_staging_rabbit_password_987@staging-mq:5672//",
            celery_redis_password="strong_staging_celery_password_987",
            celery_result_backend="redis://mirage_celery:strong_staging_celery_password_987@staging-redis:6379/1",
            mongo_uri="mongodb://mirage_app:strong_staging_mongo_password_987@staging-mongo:27017/mirage_traces",
            qdrant_api_key="strong_staging_qdrant_key_987",
        )
        defects = s.validate_staging_configuration()
        assert defects == []
        assert s.validate_environment_configuration() == []


class TestProviderConfigurationAndAdapters:
    """Validate provider key status reporting and factory resolution for OpenRouter and HuggingFace."""

    def test_get_configured_providers_reports_accurately(self) -> None:
        """Provider status dict accurately reports configured providers without secret exposure."""
        s = Settings(
            groq_api_key="gsk_actual_live_groq_key_example",
            openrouter_api_key="sk-or-v1-actual_openrouter_key",
            huggingface_api_key="",  # unconfigured
            openai_api_key="sk-proj-actual_openai_key",
            anthropic_api_key="",  # unconfigured
            gemini_api_key="",  # unconfigured
        )
        status = s.get_configured_providers()
        assert status["groq"] is True
        assert status["openrouter"] is True
        assert status["huggingface"] is False
        assert status["openai"] is True
        assert status["anthropic"] is False
        assert status["gemini"] is False
        assert status["ollama"] is True  # default localhost URL

    def test_openrouter_adapter_resolution(self) -> None:
        """OpenRouter adapter resolves when OPENROUTER_API_KEY is configured."""
        with (
            patch("services.providers.factory.get_settings") as mock_settings,
            patch("services.providers.factory.validate_provider_base_url", return_value="https://openrouter.ai/api/v1"),
        ):
            mock_settings.return_value = Settings(
                openrouter_api_key="sk-or-v1-test-key-value",
                allow_mock_providers=False,
            )
            adapter = get_provider_adapter("openrouter")
            assert adapter.provider_name == "openai"  # OpenAI-compatible protocol
            assert adapter.base_url == "https://openrouter.ai/api/v1"

    def test_openrouter_adapter_fails_closed_when_key_missing(self) -> None:
        """OpenRouter adapter raises ProviderConfigurationError in staging when unconfigured."""
        with patch("services.providers.factory.get_settings") as mock_settings:
            mock_settings.return_value = Settings(
                environment=EnvironmentType.STAGING,
                openrouter_api_key="",
                allow_mock_providers=False,
            )
            with pytest.raises(ProviderConfigurationError, match="Missing required OPENROUTER_API_KEY"):
                get_provider_adapter("openrouter")

    def test_huggingface_adapter_resolution(self) -> None:
        """HuggingFace adapter resolves when HUGGINGFACE_API_KEY is configured."""
        with (
            patch("services.providers.factory.get_settings") as mock_settings,
            patch("services.providers.factory.validate_provider_base_url", return_value="https://api-inference.huggingface.co/models"),
        ):
            mock_settings.return_value = Settings(
                huggingface_api_key="hf_test_api_key_value",
                allow_mock_providers=False,
            )
            adapter = get_provider_adapter("huggingface")
            assert adapter.base_url == "https://api-inference.huggingface.co/models"


class TestCustomCORSConfiguration:
    """Validate configurable CORS allowed origins in Gateway."""

    def test_explicit_cors_origins_permitted(self) -> None:
        """Explicit cors_allowed_origins are permitted with credentials."""
        custom_origins = ["https://staging-dashboard.mirage-ai.internal", "https://admin.mirage.corp"]
        custom_settings = Settings(
            debug=False,
            cors_allowed_origins=custom_origins,
            secret_key="a" * 48,
        )
        with patch("gateway.main.get_settings", return_value=custom_settings):
            app = create_app()
            client = TestClient(app)

            for origin in custom_origins:
                resp = client.options(
                    "/v1/health",
                    headers={
                        "Origin": origin,
                        "Access-Control-Request-Method": "GET",
                    },
                )
                assert resp.status_code == 200
                assert resp.headers.get("access-control-allow-origin") == origin

            # Disallowed origin is rejected
            resp = client.options(
                "/v1/health",
                headers={
                    "Origin": "https://untrusted-external-site.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.headers.get("access-control-allow-origin") is None


class TestStagingBlockerRemediation:
    """Validate fixes for AWS pre-provisioning blockers."""

    def test_placeholder_secrets_rejected_in_staging(self) -> None:
        """Any REPLACE_WITH_* or placeholder values must be rejected in staging."""
        s = Settings(
            environment=EnvironmentType.STAGING,
            debug=False,
            secret_key="REPLACE_WITH_ACTUAL_SECRET_KEY_MIN32CHARS",
            postgres_password="strong_staging_db_password_987",
            database_url="postgresql+asyncpg://mirage_app:strong_staging_db_password_987@staging-db:5432/mirage_db",
            redis_password="strong_staging_redis_password_987",
            redis_url="redis://mirage_app:strong_staging_redis_password_987@staging-redis:6379/0",
            rabbitmq_password="strong_staging_rabbit_password_987",
            celery_broker_url="amqp://mirage:strong_staging_rabbit_password_987@staging-mq:5672//",
            celery_redis_password="strong_staging_celery_password_987",
            celery_result_backend="redis://mirage_celery:strong_staging_celery_password_987@staging-redis:6379/1",
            mongo_uri="mongodb://mirage_app:strong_staging_mongo_password_987@staging-mongo:27017/mirage_traces",
            qdrant_api_key="strong_staging_qdrant_key_987",
            groq_api_key="REPLACE_WITH_GROQ_API_KEY",
        )
        defects = s.validate_staging_configuration()
        assert any("SECRET_KEY" in d and "placeholder" in d for d in defects)
        assert any("GROQ_API_KEY" in d and "placeholder" in d for d in defects)

    def test_database_sync_url_optional_for_runtime(self) -> None:
        """database_sync_url is optional for application runtime and defaults to None."""
        s = Settings(
            environment=EnvironmentType.STAGING,
            debug=False,
            secret_key="staging-strong-secret-key-at-least-32-chars",
            demo_auth_enabled=False,
            allow_mock_providers=False,
            postgres_password="strong_staging_db_password_987",
            database_url="postgresql+asyncpg://mirage_app:strong_staging_db_password_987@staging-db:5432/mirage_db",
            database_sync_url=None,
            redis_password="strong_staging_redis_password_987",
            redis_url="redis://mirage_app:strong_staging_redis_password_987@staging-redis:6379/0",
            rabbitmq_password="strong_staging_rabbit_password_987",
            celery_broker_url="amqp://mirage:strong_staging_rabbit_password_987@staging-mq:5672//",
            celery_redis_password="strong_staging_celery_password_987",
            celery_result_backend="redis://mirage_celery:strong_staging_celery_password_987@staging-redis:6379/1",
            mongo_uri="mongodb://mirage_app:strong_staging_mongo_password_987@staging-mongo:27017/mirage_traces",
            qdrant_api_key="strong_staging_qdrant_key_987",
        )
        assert s.database_sync_url is None
        defects = s.validate_staging_configuration()
        assert defects == []

    def test_secret_serializer_handles_special_characters(self) -> None:
        """fetch_secrets serializer properly quotes strings with dollars, quotes, and backslashes."""
        from scripts.fetch_secrets import serialize_env_value, serialize_secrets_to_env

        # Test simple
        assert serialize_env_value("simple123") == "simple123"
        # Test dollars
        val_with_dollar = "pass$word"
        serialized = serialize_env_value(val_with_dollar)
        assert serialized == "'pass$word'"

        # Test single quote and backslash
        val_complex = "pass'word\"with\\backslash"
        serialized_complex = serialize_env_value(val_complex)
        assert serialized_complex.startswith('"')
        assert "\\\\" in serialized_complex

        # Test dictionary serialization with placeholder detection in staging
        secrets = {
            "SECRET_KEY": "valid-long-secret-key-at-least-48-chars-for-staging-environment",
            "POSTGRES_PASSWORD": "strong_db_password_123456",
            "POSTGRES_APP_PASSWORD": "strong_app_password_123456",
            "REDIS_PASSWORD": "strong_redis_password_123456",
            "RABBITMQ_PASSWORD": "strong_rabbit_password_123456",
            "CELERY_REDIS_PASSWORD": "strong_celery_password_123456",
            "MONGO_INITDB_ROOT_PASSWORD": "strong_mongo_root_123456",
            "MONGO_APP_PASSWORD": "strong_mongo_app_123456",
            "QDRANT_API_KEY": "strong_qdrant_key_123456",
            "GRAFANA_ADMIN_PASSWORD": "strong_grafana_password_123456",
            "PLACEHOLDER_KEY": "REPLACE_WITH_VALUE",
        }
        content, defects = serialize_secrets_to_env(secrets, environment="staging")
        assert len(defects) == 1
        assert "PLACEHOLDER_KEY" in defects[0]
        assert "SECRET_KEY=valid-long-secret-key-at-least-48-chars-for-staging-environment" in content

    def test_staging_compose_identity_and_credentials_hygiene(self) -> None:
        """Verify staging compose does not leak sync credentials to app services or miswire Mongo."""
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        staging_compose = repo_root / "docker-compose.staging.yml"
        assert staging_compose.exists()
        content = staging_compose.read_text(encoding="utf-8")

        # Gateway and worker must not have DATABASE_SYNC_URL
        gateway_block = content.split("gateway:")[1].split("\n\n")[0]
        assert "DATABASE_SYNC_URL" not in gateway_block
        assert "POSTGRES_PASSWORD" not in gateway_block

        worker_block = content.split("worker:")[1].split("\n\n")[0]
        assert "DATABASE_SYNC_URL" not in worker_block
        assert "POSTGRES_PASSWORD" not in worker_block

        # MongoDB must use MONGO_APP_USER, not POSTGRES_APP_USER
        mongo_block = content.split("mongodb:")[1].split("\n\n")[0]
        assert "POSTGRES_APP_USER" not in mongo_block
        assert "MONGO_APP_USER" in mongo_block
