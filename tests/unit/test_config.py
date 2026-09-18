"""Unit tests for configuration management (12-Factor App settings)."""

import pytest

from shared.config import EnvironmentType, Settings, get_settings


@pytest.mark.unit
class TestConfig:
    def test_default_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("REDIS_PORT", raising=False)
        monkeypatch.delenv("RABBITMQ_PORT", raising=False)
        monkeypatch.delenv("POSTGRES_PORT", raising=False)
        monkeypatch.delenv("QDRANT_PORT", raising=False)

        settings = Settings()
        assert settings.environment == EnvironmentType.DEVELOPMENT
        assert settings.debug is True
        assert settings.postgres_port == 5432
        assert settings.redis_port == 6379
        assert settings.rabbitmq_port == 5672
        assert settings.qdrant_port == 6333
        assert settings.scs_sample_count == 5
        assert settings.scs_temperature == 0.7
        assert settings.clip_threshold == 0.85
        assert settings.hrs_correction_threshold == 0.60
        assert settings.max_correction_retries == 2

    def test_settings_caching(self) -> None:
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("CELERY_BROKER_URL", "amqps://mirage:secret@rabbit.internal:5671//")
        monkeypatch.setenv("DEBUG", "false")
        monkeypatch.setenv("SCS_SAMPLE_COUNT", "7")
        monkeypatch.setenv("CLIP_THRESHOLD", "0.90")

        custom_settings = Settings()
        assert custom_settings.environment == EnvironmentType.PRODUCTION
        assert custom_settings.debug is False
        assert custom_settings.scs_sample_count == 7
        assert custom_settings.clip_threshold == 0.90
